"""Проект: состояние задачи, журнал действий, стадии, ворота, вопросы человеку.

Состояние хранится в projects/<id>/state.yaml — это единственное, что нужно
новому чату (или другой IDE), чтобы продолжить работу с сохранённого места.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .common import (ACTIVE_FILE, PROJECTS, STAGE_TITLES, STAGES, StrategistError, append_jsonl,
                     next_id, now, read_jsonl, read_yaml, sha256_text, write_yaml)

TEMPLATE = PROJECTS / "_template"
GATES = {
    "G1_brief": "Бриф подтверждён человеком",
    "G2_option": "Вариант выбран человеком",
    "G3_strategy": "Стратегия принята человеком",
}
GATE_ALIASES = {"G1": "G1_brief", "G2": "G2_option", "G3": "G3_strategy"}
GATE_STAGES = {"materials": "G1_brief", "strategy": "G2_option", "support": "G3_strategy"}
DEFAULT_NEXT = {
    "materials": "Собрать материалы по навыку source-collection; параллельно составить research/plan.md",
    "research": "Ответить на решающие вопросы из research/plan.md (навык research) и написать research/findings.md",
    "options": "Составить options.md по навыку options и провести красную команду",
    "strategy": "Написать strategy/product.md, communication.md, validation.md по выбранному варианту",
    "review": "Ворота качества и отчёт (навык report): one-pager, check, fact-checker, render --pdf",
    "support": "Заполнить decisions.yaml и регулярно проверять `sf decisions due` (навык decision-support)",
}


# ---------- пути ----------
def project_dir(pid: str | None = None) -> Path:
    pid = pid or active_project()
    if not pid:
        existing = sorted(p.parent.name for p in PROJECTS.glob("*/state.yaml") if not p.parent.name.startswith("zz-"))
        hint = (f" Есть проекты: {', '.join(existing)} — например, `python sf.py use {existing[0]}`, затем `python sf.py status`."
                if existing else "")
        raise StrategistError("Нет активного проекта (на свежем клоне он не выбран)." + hint +
                              " Новая задача: `python sf.py new <id> --title \"...\"` или просто напишите её агенту в IDE.")
    d = PROJECTS / pid
    if not (d / "state.yaml").exists():
        raise StrategistError(f"Проект '{pid}' не найден ({d}).")
    return d


def active_project() -> str | None:
    if ACTIVE_FILE.exists():
        pid = ACTIVE_FILE.read_text(encoding="utf-8").strip()
        if pid and (PROJECTS / pid / "state.yaml").exists():
            return pid
    return None


def set_active(pid: str) -> None:
    if not (PROJECTS / pid / "state.yaml").exists():
        raise StrategistError(f"Проект '{pid}' не найден.")
    ACTIVE_FILE.write_text(pid, encoding="utf-8")


def list_projects() -> list[dict]:
    out = []
    for d in sorted(PROJECTS.iterdir()):
        if d.is_dir() and not d.name.startswith("_") and (d / "state.yaml").exists():
            st = read_yaml(d / "state.yaml", {})
            out.append({"id": d.name, "title": st.get("title", ""), "stage": st.get("stage"),
                        "updated": st.get("updated"), "active": d.name == active_project()})
    return out


# ---------- состояние ----------
def load_state(pid: str | None = None) -> dict:
    return read_yaml(project_dir(pid) / "state.yaml", {})


def save_state(state: dict, pid: str | None = None) -> None:
    state["updated"] = now()
    write_yaml(project_dir(pid) / "state.yaml", state)


def journal(action: str, detail: str = "", *, pid: str | None = None, actor: str = "agent",
            status: str = "ok", key: str | None = None, **extra) -> dict:
    """Записать действие в журнал. `key` — ключ идемпотентности."""
    rec = {"ts": now(), "actor": actor, "action": action, "detail": detail, "status": status}
    if key:
        rec["key"] = key
    rec.update({k: v for k, v in extra.items() if v is not None})
    append_jsonl(project_dir(pid) / "journal.jsonl", rec)
    return rec


def already_done(key: str, pid: str | None = None) -> dict | None:
    """Идемпотентность: было ли действие с этим ключом успешно выполнено."""
    for rec in reversed(read_jsonl(project_dir(pid) / "journal.jsonl")):
        if rec.get("key") == key and rec.get("status") == "ok":
            return rec
    return None


def new_project(pid: str, title: str, request: str = "", mode: str = "checkpoints") -> Path:
    d = PROJECTS / pid
    if d.exists():
        raise StrategistError(f"Проект '{pid}' уже существует.")
    if TEMPLATE.exists():
        shutil.copytree(TEMPLATE, d)
    else:
        d.mkdir(parents=True)
    for sub in ["sources/raw", "evidence", "research/interviews", "research/ux", "research/data",
                "strategy", "report"]:
        (d / sub).mkdir(parents=True, exist_ok=True)
    state = {
        "project": pid,
        "title": title,
        "request": request,
        "created": now(),
        "updated": now(),
        "mode": mode,
        "stage": "intake",
        "stage_status": "in_progress",
        "gates": {g: {"status": "pending"} for g in GATES},
        "next_action": "Прочитать запрос, провести постановку задачи по навыку intake и заполнить brief.md",
        "open_questions": [],
        "stale": [],
        "history": [{"ts": now(), "event": "created", "stage": "intake"}],
    }
    write_yaml(d / "state.yaml", state)
    ACTIVE_FILE.write_text(pid, encoding="utf-8")
    journal("project_created", f"{title} | запрос: {request[:300]}", pid=pid, actor="human")
    return d


def missing_gates(state: dict, stage: str) -> list[str]:
    gates = state.get("gates", {})
    return [GATE_STAGES[s] for s in STAGES[:STAGES.index(stage) + 1]
            if s in GATE_STAGES and gates.get(GATE_STAGES[s], {}).get("status") != "passed"]


def set_stage(stage: str, status: str = "in_progress", pid: str | None = None, note: str = "") -> dict:
    if stage not in STAGES:
        raise StrategistError(f"Неизвестная стадия '{stage}'. Допустимо: {', '.join(STAGES)}")
    st = load_state(pid)
    pending = missing_gates(st, stage)
    if pending:
        gate_id = pending[0]
        if st.get("mode") == "autopilot":
            action, decision = "запишите основание допущения", "assume"
        else:
            action, decision = "получите и запишите решение человека", "pass"
        raise StrategistError(f"Для стадии {stage} нужны ворота {gate_id} ({GATES[gate_id]}). "
                              f"Сначала {action}: python sf.py gate {gate_id[:2]} {decision} --note \"...\"")
    # результаты всех предыдущих стадий должны существовать: нельзя «перепрыгнуть» исследование и варианты
    from .evidence import STAGE_OUTPUTS  # отложенный импорт: evidence импортирует project
    d = project_dir(pid)
    missing = [rel for s in STAGES[:STAGES.index(stage)] for rel in STAGE_OUTPUTS[s]
               if not (d / rel).is_file() or not (d / rel).stat().st_size]
    if missing:
        raise StrategistError(f"Для стадии {stage} не готовы результаты предыдущих стадий: {', '.join(missing)}")
    prev = st.get("stage")
    st["stage"], st["stage_status"] = stage, status
    if prev != stage:
        st["next_action"] = DEFAULT_NEXT.get(stage, st.get("next_action", ""))
    st.setdefault("history", []).append({"ts": now(), "event": "stage", "from": prev, "to": stage,
                                         "status": status, "note": note})
    save_state(st, pid)
    journal("stage", f"{prev} → {stage} ({status}) {note}".strip(), pid=pid)
    return st


GATE_ORDER = {"G2_option": "G1_brief", "G3_strategy": "G2_option"}


def gate_prerequisites(gate_id: str, d: Path) -> list[str]:
    """Что должно быть готово, чтобы показывать человеку решение на воротах (иначе подтверждать нечего)."""
    from .evidence import STRUCTURE, sections  # отложенный импорт: evidence импортирует project

    def text(rel: str) -> str:
        p = d / rel
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    problems: list[str] = []
    if gate_id == "G1_brief":
        brief = text("brief.md")
        if not brief.strip():
            return ["brief.md отсутствует или пуст — сначала постановка задачи (навык intake)"]
        filled = [(h.lower(), b.strip()) for h, b in sections(brief)]
        for kw in STRUCTURE["brief.md"]:
            if not any(kw in h and b for h, b in filled):
                problems.append(f"brief.md: раздел «{kw}…» отсутствует или не заполнен")
    elif gate_id == "G2_option":
        n = len(re.findall(r"^##\s+Вариант", text("options.md"), re.M))
        if n < 3:
            problems.append(f"options.md: вариантов {n}, нужно не меньше 3")
        if not text("research/findings.md").strip():
            problems.append("research/findings.md отсутствует или пуст — варианты должны опираться на картину ситуации")
    elif gate_id == "G3_strategy":
        for rel in ("strategy/product.md", "strategy/communication.md", "strategy/validation.md", "strategy/one-pager.md"):
            if not text(rel).strip():
                problems.append(f"{rel} отсутствует или пуст")
    return problems


def gate(gate_id: str, decision: str, note: str = "", by: str = "human", pid: str | None = None) -> dict:
    gate_id = GATE_ALIASES.get(gate_id, gate_id)
    if gate_id not in GATES:
        raise StrategistError(f"Неизвестные ворота '{gate_id}'. Допустимо: G1, G2, G3")
    if decision not in ("pass", "reject", "assume"):
        raise StrategistError("Решение: pass | reject | assume (assume — только в режиме autopilot)")
    st = load_state(pid)
    if decision == "assume" and st.get("mode") != "autopilot":
        raise StrategistError("assume разрешён только в режиме autopilot; в checkpoints решает человек.")
    if decision in ("pass", "assume"):
        before = GATE_ORDER.get(gate_id)
        if before and st["gates"].get(before, {}).get("status") != "passed":
            raise StrategistError(f"Сначала ворота {before} ({GATES[before]}): ворота проходятся по порядку G1 → G2 → G3.")
        problems = gate_prerequisites(gate_id, project_dir(pid))
        if problems:
            raise StrategistError(f"Ворота {gate_id} нельзя пройти — не готово то, что человек должен подтвердить: "
                                  + "; ".join(problems))
    st["gates"][gate_id] = {"status": {"pass": "passed", "reject": "rejected", "assume": "passed"}[decision],
                            "at": now(), "by": "assumed" if decision == "assume" else by, "note": note}
    if decision != "reject" and st.get("stage_status") == "waiting_human":
        st["stage_status"] = "in_progress"
    save_state(st, pid)
    journal("gate", f"{gate_id}: {decision} — {note}", pid=pid, actor=by if decision != "assume" else "agent")
    return st


def set_deliverable(file: str, template: str = "", sections: list[str] | None = None, pid: str | None = None) -> dict:
    """Требуемая структура итогового документа (например, бриф организаторов «пять частей»): её проверяет `sf check`."""
    from .common import ROOT
    sections = [s.strip() for s in (sections or []) if s.strip()]
    if template:
        tpl = ROOT / "knowledge" / "templates" / f"{template}.md"
        if not tpl.is_file():
            raise StrategistError(f"Нет шаблона {tpl.relative_to(ROOT)}")
        sections = [m.group(1).strip() for m in re.finditer(r"^##\s+\d+\.\s+(.+)$", tpl.read_text(encoding="utf-8"), re.M)]
    if not sections:
        raise StrategistError("Укажите --template или --sections \"Часть 1;Часть 2;...\"")
    st = load_state(pid)
    st["deliverable"] = {"file": file, "template": template, "sections": sections}
    save_state(st, pid)
    journal("deliverable_set", f"{file}: {len(sections)} обязательных частей" + (f" ({template})" if template else ""), pid=pid)
    return st["deliverable"]


def checkpoint(note: str = "", next_action: str | None = None, waiting_human: bool = False,
               pid: str | None = None) -> dict:
    st = load_state(pid)
    if next_action:
        st["next_action"] = next_action
    if waiting_human:
        st["stage_status"] = "waiting_human"
    st["last_checkpoint"] = {"ts": now(), "note": note}
    save_state(st, pid)
    journal("checkpoint", note, pid=pid, next_action=next_action)
    return st


def add_question(question: str, why: str, default: str = "", pid: str | None = None) -> str:
    st = load_state(pid)
    qs = st.setdefault("open_questions", [])
    qid = next_id("Q", [q["id"] for q in qs], width=1)
    qs.append({"id": qid, "question": question, "why": why, "default": default, "status": "open",
               "asked": now()})
    save_state(st, pid)
    journal("question_asked", f"{qid}: {question}", pid=pid)
    return qid


def answer_question(qid: str, answer: str, pid: str | None = None) -> None:
    st = load_state(pid)
    for q in st.get("open_questions", []):
        if q["id"] == qid:
            q.update({"status": "answered", "answer": answer, "answered": now()})
            save_state(st, pid)
            journal("question_answered", f"{qid}: {answer}", pid=pid, actor="human")
            return
    raise StrategistError(f"Вопрос {qid} не найден")


def status_text(pid: str | None = None, brief: bool = False) -> str:
    """Человекочитаемый статус — его же SessionStart-хук подаёт в контекст нового чата."""
    from . import costs as _costs
    from . import decisions as _dec
    from . import evidence as _ev
    d = project_dir(pid)
    st = load_state(pid)
    claims = _ev.load_claims(d.name)
    srcs = _ev.load_sources(d.name)
    lines = [
        f"Проект: {st['project']} — {st.get('title', '')}",
        f"Режим: {st.get('mode')} · Стадия: {STAGE_TITLES.get(st['stage'], st['stage'])} ({st.get('stage_status')})",
        "Ворота: " + ", ".join(f"{g}={v.get('status')}" for g, v in st.get("gates", {}).items()),
        f"Следующее действие: {st.get('next_action', '—')}",
    ]
    oq = [q for q in st.get("open_questions", []) if q.get("status") == "open"]
    if oq:
        lines.append("Открытые вопросы человеку:")
        lines += [f"  {q['id']}: {q['question']} (зачем: {q['why']}; по умолчанию: {q.get('default') or '—'})"
                  for q in oq]
    if st.get("stale"):
        lines.append("Требуют пересмотра (устаревшие основания):")
        lines += [f"  {s.get('file')}: {s.get('reason')}" for s in st["stale"]]
    by_kind: dict[str, int] = {}
    for c in claims:
        if c.get("status") == "active":
            by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    lines.append(f"Доказательная база: источников {len(srcs)}, утверждений {len(claims)} "
                 f"(активных по типам: {by_kind or '—'})")
    try:
        due = _dec.due_items(d.name)
        if due:
            lines.append("Решения/обязательства, требующие внимания:")
            lines += [f"  {x}" for x in due[:8]]
    except Exception:
        pass
    tot = _costs.summary(d.name)
    lines.append(f"Стоимость проекта ≈${tot['project_usd']:.2f}: внешние модели ${tot['external_usd']:.4f} "
                 f"({tot['external_calls']} вызовов), субагенты ≈${tot['subagent_usd']:.2f}"
                 + (f"; основной чат ≈${tot['session_usd']:.2f} — отдельно ({tot['session_note']})" if tot["session_mixed"]
                    else (f", основной чат ≈${tot['session_usd']:.2f}" if tot["session_usd"] else "")))
    if not brief:
        tail = read_jsonl(d / "journal.jsonl")[-8:]
        if tail:
            lines.append("Последние действия:")
            lines += [f"  {r['ts'][:16]} [{r.get('actor')}] {r.get('action')}: {str(r.get('detail', ''))[:110]}"
                      f"{'' if r.get('status') == 'ok' else ' — ' + r.get('status', '')}" for r in tail]
        failed = [r for r in read_jsonl(d / "journal.jsonl") if r.get("status") == "failed"]
        if failed:
            lines.append(f"Сбоев в журнале: {len(failed)} (последний: {failed[-1].get('action')} — "
                         f"{str(failed[-1].get('detail'))[:100]})")
    return "\n".join(lines)


def file_fingerprint(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8")) if path.exists() else ""
