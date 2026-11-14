"""Доказательная база: реестр источников, реестр утверждений, проверка, граф влияния.

Каждое существенное утверждение в документах проекта ссылается на запись
[C001] в evidence/claims.jsonl, а та — на источник [S001] из sources/registry.yaml.
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import (CLAIM_KINDS, CLAIM_STATUSES, StrategistError, next_id, now, read_jsonl, read_yaml,
                     today, write_jsonl, write_yaml)
from .project import journal, load_state, project_dir, save_state

REF_BLOCK = re.compile(r"\[([^\[\]]{2,200})\]")
CLAIM_TOKEN = re.compile(r"\bC\d{3,}\b")
SOURCE_TOKEN = re.compile(r"\bS\d{3,}\b")
SOURCE_KINDS = ["web", "pdf", "document", "table", "dataset", "image", "audio", "video", "interview",
                "synthetic", "user_material", "analysis"]
RELIABILITY = {"A": "первичный/официальный", "B": "авторитетный вторичный (СМИ, аналитики)",
               "C": "вторичный/блог/агрегатор", "D": "непроверенный"}
DEMAND_WORDS = re.compile(r"(спрос|доля|распростран|большинств|\d+\s?%|процент|рын(ок|ка)|готов[аы]? платить)",
                          re.I)
NUMBER_PAT = re.compile(r"(\d[\d\s,.]*\s?(%|млн|млрд|тыс|руб|₽|\$|раз[а]?\b|п\.\s?п\.))", re.I)


# ---------- источники ----------
def _reg_path(pid=None) -> Path:
    return project_dir(pid) / "sources" / "registry.yaml"


def load_sources(pid=None) -> list[dict]:
    return read_yaml(_reg_path(pid), []) or []


def update_source(sid: str, pid=None, **fields) -> dict:
    srcs = load_sources(pid)
    for s in srcs:
        if s["id"] == sid:
            s.update({k: v for k, v in fields.items() if v is not None})
            write_yaml(_reg_path(pid), srcs)
            return s
    raise StrategistError(f"Источник {sid} не найден")


def get_source(sid: str, pid=None) -> dict:
    for s in load_sources(pid):
        if s["id"] == sid:
            return s
    raise StrategistError(f"Источник {sid} не найден")


def add_source(title: str, kind: str = "web", url: str = "", path: str = "", publisher: str = "",
               published: str = "", reliability: str = "B", notes: str = "", sha256: str = "",
               injection_flags: list | None = None, pid=None, **extra) -> dict:
    if kind not in SOURCE_KINDS:
        raise StrategistError(f"Тип источника '{kind}' неизвестен: {SOURCE_KINDS}")
    if reliability not in RELIABILITY:
        raise StrategistError(f"Надёжность: {list(RELIABILITY)}")
    srcs = load_sources(pid)
    if url:
        for s in srcs:  # идемпотентность: тот же URL того же типа не регистрируется дважды
            if s.get("url") == url and s.get("kind") == kind and (not path or s.get("path") == path):
                return s
    sid = next_id("S", [s["id"] for s in srcs])
    rec = {"id": sid, "title": title, "kind": kind, "url": url, "path": path, "publisher": publisher,
           "published": str(published), "retrieved": today(), "reliability": reliability,
           "sha256": sha256, "injection_flags": injection_flags or [], "notes": notes}
    rec.update({k: v for k, v in extra.items() if v})
    srcs.append(rec)
    write_yaml(_reg_path(pid), srcs)
    journal("source_added", f"{sid}: {title} ({url or path})", pid=pid)
    return rec


# ---------- утверждения ----------
def _claims_path(pid=None) -> Path:
    return project_dir(pid) / "evidence" / "claims.jsonl"


def load_claims(pid=None) -> list[dict]:
    return [c for c in read_jsonl(_claims_path(pid)) if "id" in c]


def get_claim(cid: str, pid=None) -> dict:
    for c in load_claims(pid):
        if c["id"] == cid:
            return c
    raise StrategistError(f"Утверждение {cid} не найдено")


def add_claim(text: str, kind: str, sources: list[str] | None = None, quote: str = "", locator: str = "",
              confidence: str = "medium", tags: list[str] | None = None, depends_on: list[str] | None = None,
              method: str = "", note: str = "", pid=None) -> dict:
    if kind not in CLAIM_KINDS:
        raise StrategistError(f"Тип утверждения '{kind}' неизвестен: {CLAIM_KINDS}")
    sources = [s.strip() for s in (sources or []) if s.strip()]
    depends_on = [d.strip() for d in (depends_on or []) if d.strip()]
    known_s = {s["id"]: s for s in load_sources(pid)}
    for s in sources:
        if s not in known_s:
            raise StrategistError(f"Источник {s} не зарегистрирован (python sf.py source add / fetch)")
    claims = load_claims(pid)
    known_c = {c["id"] for c in claims}
    for d in depends_on:
        if d not in known_c:
            raise StrategistError(f"Зависимость {d} не найдена")
    if kind in ("fact", "opinion") and not sources:
        raise StrategistError(f"Тип '{kind}' требует источник (--src S001). Нет источника → это hypothesis.")
    if kind == "estimate" and not (depends_on or sources) :
        raise StrategistError("Расчёт (estimate) требует входные данные: --depends C001,... или --src")
    if sources and all(known_s[s]["kind"] == "synthetic" for s in sources) and kind not in ("synthetic", "hypothesis"):
        raise StrategistError("Источник синтетический (модельные респонденты) → тип только synthetic/hypothesis. "
                              "Синтетика не доказывает спрос и распространённость.")
    for c in claims:  # идемпотентность по тексту
        if c["text"].strip() == text.strip() and c.get("status") == "active":
            return c
    cid = next_id("C", known_c)
    rec = {"id": cid, "text": text.strip(), "kind": kind, "sources": sources, "quote": quote.strip(),
           "locator": locator, "confidence": confidence, "tags": tags or [], "depends_on": depends_on,
           "method": method, "status": "active", "created": now(), "updated": now(), "note": note}
    claims.append(rec)
    write_jsonl(_claims_path(pid), claims)
    journal("claim_added", f"{cid} [{kind}] {text[:120]}", pid=pid)
    return rec


def update_claim(cid: str, pid=None, **fields) -> dict:
    claims = load_claims(pid)
    for c in claims:
        if c["id"] == cid:
            if "status" in fields and fields["status"] not in CLAIM_STATUSES:
                raise StrategistError(f"Статус: {CLAIM_STATUSES}")
            if "kind" in fields and fields["kind"] not in CLAIM_KINDS:
                raise StrategistError(f"Тип: {CLAIM_KINDS}")
            old = {k: c.get(k) for k in fields}
            for k, v in fields.items():
                if v is not None:
                    c[k] = v
            c["updated"] = now()
            c.setdefault("history", []).append({"ts": now(), "changed": old})
            write_jsonl(_claims_path(pid), claims)
            journal("claim_updated", f"{cid}: {fields}", pid=pid)
            return c
    raise StrategistError(f"Утверждение {cid} не найдено")


def retract_claim(cid: str, reason: str, superseded_by: str = "", pid=None) -> dict:
    status = "superseded" if superseded_by else "retracted"
    return update_claim(cid, status=status, note=reason, superseded_by=superseded_by or None, pid=pid)


# ---------- ссылки в документах ----------
def doc_files(pid=None) -> list[Path]:
    d = project_dir(pid)
    out = []
    for p in d.rglob("*.md"):
        rel = p.relative_to(d).as_posix()
        if rel.startswith(("sources/raw", "report/", "research/interviews/synthetic")):
            continue
        out.append(p)
    return sorted(out)


def refs_in_text(text: str) -> tuple[set[str], set[str]]:
    cs, ss = set(), set()
    for m in REF_BLOCK.finditer(text):
        inner = m.group(1)
        cs |= set(CLAIM_TOKEN.findall(inner))
        ss |= set(SOURCE_TOKEN.findall(inner))
    return cs, ss


def sections(text: str) -> list[tuple[str, str]]:
    """[(заголовок, текст секции)] по заголовкам markdown."""
    out, head, buf = [], "(начало)", []
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s", line):
            out.append((head, "\n".join(buf)))
            head, buf = line.lstrip("#").strip(), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf)))
    return out


# ---------- структура документов (обязательные разделы шаблонов) ----------
STRUCTURE = {
    "brief.md": ["вопрос", "цель", "получатель", "ограничени", "данные"],
    "research/plan.md": ["решающие вопросы"],
    "research/findings.md": ["известно", "не знаем"],
    "options.md": ["оставить как есть", "закрыть", "сравнение", "рекомендац"],
    "strategy/product.md": ["аудитория", "альтернатив", "направление", "отказ", "затрат"],
    "strategy/communication.md": ["аудитория", "барьер", "ключевое сообщение", "подтвержд", "канал", "обещани"],
    "strategy/validation.md": ["ожидаемое изменение", "с чем сравниваем", "срок", "нежелательн"],
    "strategy/one-pager.md": ["решение", "риск", "проверить"],
}
STAGE_REQUIRES = {
    "materials": ["brief.md"],
    "research": ["brief.md", "research/plan.md"],
    "options": ["brief.md", "research/plan.md", "research/findings.md"],
    "strategy": ["options.md"],
    "review": ["strategy/product.md", "strategy/communication.md", "strategy/validation.md"],
    "support": ["strategy/product.md", "strategy/communication.md", "strategy/validation.md",
                "strategy/one-pager.md", "decisions.yaml"],
}


def check(pid=None, strict: bool = False) -> dict:
    """Проверка целостности. Возвращает {errors, warnings, metrics}."""
    d = project_dir(pid)
    st = load_state(pid)
    claims = {c["id"]: c for c in load_claims(pid)}
    srcs = {s["id"]: s for s in load_sources(pid)}
    errors, warnings = [], []

    # 1. утверждения
    for c in claims.values():
        for s in c.get("sources", []):
            if s not in srcs:
                errors.append(f"{c['id']}: ссылка на несуществующий источник {s}")
        if c["kind"] in ("fact", "opinion") and not c.get("sources"):
            errors.append(f"{c['id']}: {c['kind']} без источника")
        if c["kind"] == "fact" and c.get("status") == "active" and not (c.get("quote") or c.get("locator")):
            warnings.append(f"{c['id']}: факт без цитаты/локатора — сложно проверить")
        if c["kind"] == "fact" and c.get("status") == "active" and c.get("quote_status") in ("not_found", "no_snapshot"):
            warnings.append(f"{c['id']}: цитата не подтверждена снимком источника ({c.get('quote_status')}) — сверить")
        if c["kind"] == "estimate" and not c.get("method"):
            warnings.append(f"{c['id']}: расчёт без указания метода/скрипта (--method)")
        src_kinds = {srcs[s]["kind"] for s in c.get("sources", []) if s in srcs}
        if src_kinds == {"synthetic"} and c["kind"] not in ("synthetic", "hypothesis"):
            errors.append(f"{c['id']}: синтетический источник используется как {c['kind']}")
        for s in c.get("sources", []):
            if s in srcs and srcs[s].get("injection_flags") and c.get("status") == "active":
                warnings.append(f"{c['id']}: опирается на источник {s} с признаками инъекции — перепроверить")
    # 2. ссылки в документах
    used: set[str] = set()
    unsourced_numbers = 0
    covered, total_paras = 0, 0
    for f in doc_files(pid):
        rel = f.relative_to(d).as_posix()
        text = f.read_text(encoding="utf-8")
        is_decision_doc = rel.startswith(("strategy/", "options.md", "decision", "research/findings.md"))
        for ln_no, line in enumerate(text.splitlines(), 1):
            cs, ss = refs_in_text(line)
            used |= cs
            for cid in cs:
                if cid not in claims:
                    errors.append(f"{rel}:{ln_no}: ссылка на несуществующее утверждение {cid}")
                    continue
                c = claims[cid]
                if is_decision_doc and c.get("status") in ("retracted", "superseded"):
                    errors.append(f"{rel}:{ln_no}: опора на отозванное утверждение {cid} ({c.get('note', '')[:80]})")
                elif is_decision_doc and c.get("status") == "disputed":
                    warnings.append(f"{rel}:{ln_no}: опора на оспоренное утверждение {cid}")
                if c["kind"] == "synthetic" and DEMAND_WORDS.search(line):
                    errors.append(f"{rel}:{ln_no}: синтетика {cid} используется как довод о спросе/доле")
            for sid in ss:
                if sid not in srcs:
                    errors.append(f"{rel}:{ln_no}: ссылка на несуществующий источник {sid}")
            if is_decision_doc:
                body = line.strip()
                if body and not body.startswith(("#", "|---", "<!--", ">")) and len(body) > 40:
                    total_paras += 1
                    if cs or ss:
                        covered += 1
                    elif NUMBER_PAT.search(body) and not re.search(r"(цель|целев|порог|target|бюджет|срок)", body, re.I):
                        unsourced_numbers += 1
                        warnings.append(f"{rel}:{ln_no}: число без ссылки на утверждение: «{body[:90]}»")
    # 3. структура
    for rel, req in STRUCTURE.items():
        f = d / rel
        if not f.exists():
            continue
        heads = " | ".join(h.lower() for h, _ in sections(f.read_text(encoding="utf-8")))
        for kw in req:
            if kw not in heads:
                errors.append(f"{rel}: нет обязательного раздела «{kw}…» (см. knowledge/templates)")
    opt = d / "options.md"
    if opt.exists():
        n_opts = len(re.findall(r"^##\s+Вариант", opt.read_text(encoding="utf-8"), re.M))
        if n_opts < 3:
            errors.append(f"options.md: вариантов {n_opts} < 3")
        for head, body in sections(opt.read_text(encoding="utf-8")):
            if head.lower().startswith("вариант ") and "возражени" not in body.lower():
                errors.append(f"options.md: у «{head[:50]}» нет сильных возражений")
    order = ["intake", "materials", "research", "options", "strategy", "review", "support"]
    stage_idx = order.index(st["stage"])
    for stage, files in STAGE_REQUIRES.items():
        if order.index(stage) <= stage_idx:
            for rel in files:
                if not (d / rel).exists():
                    warnings.append(f"стадия {st['stage']}: ожидался файл {rel}")
    # 4. метрики
    active = [c for c in claims.values() if c.get("status") == "active"]
    facts = [c for c in active if c["kind"] == "fact"]
    metrics = {
        "sources": len(srcs),
        "claims_total": len(claims),
        "claims_active": len(active),
        "by_kind": {k: sum(1 for c in active if c["kind"] == k) for k in CLAIM_KINDS},
        "facts_with_quote_pct": round(100 * sum(1 for c in facts if c.get("quote")) / len(facts), 1) if facts else 0,
        "claims_used_in_docs": len(used & set(claims)),
        "decision_paragraph_coverage_pct": round(100 * covered / total_paras, 1) if total_paras else 0,
        "unsourced_numbers": unsourced_numbers,
        "reliability_mix": {r: sum(1 for s in srcs.values() if s.get("reliability") == r) for r in RELIABILITY},
    }
    if strict:
        errors += [f"[strict] {w}" for w in warnings if "число без ссылки" in w]
    res = {"errors": sorted(set(errors)), "warnings": sorted(set(warnings)), "metrics": metrics}
    journal("check", f"ошибок {len(res['errors'])}, предупреждений {len(res['warnings'])}", pid=pid,
            status="ok" if not res["errors"] else "failed")
    return res


def lint_file(path: Path, pid=None) -> list[str]:
    """Быстрая проверка одного файла (для PostToolUse-хука)."""
    claims = {c["id"]: c for c in load_claims(pid)}
    srcs = {s["id"] for s in load_sources(pid)}
    problems = []
    for ln_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        cs, ss = refs_in_text(line)
        for cid in cs:
            if cid not in claims:
                problems.append(f"строка {ln_no}: нет утверждения {cid} — добавьте `sf claim add` или исправьте ссылку")
            elif claims[cid].get("status") in ("retracted", "superseded"):
                problems.append(f"строка {ln_no}: {cid} отозвано ({claims[cid].get('note', '')[:60]})")
            elif claims[cid]["kind"] == "synthetic" and DEMAND_WORDS.search(line):
                problems.append(f"строка {ln_no}: синтетика {cid} как довод о спросе — недопустимо")
        for sid in ss:
            if sid not in srcs:
                problems.append(f"строка {ln_no}: нет источника {sid}")
    return problems


# ---------- граф влияния ----------
def dependents(cid: str, pid=None) -> list[str]:
    claims = load_claims(pid)
    out, frontier = [], [cid]
    while frontier:
        cur = frontier.pop()
        for c in claims:
            if cur in c.get("depends_on", []) and c["id"] not in out:
                out.append(c["id"])
                frontier.append(c["id"])
    return out


def impact(cid: str, pid=None, mark_stale: bool = False) -> dict:
    from .decisions import load_decisions
    get_claim(cid, pid)
    d = project_dir(pid)
    deps = dependents(cid, pid)
    targets = {cid, *deps}
    hits = []
    for f in doc_files(pid):
        rel = f.relative_to(d).as_posix()
        for head, body in sections(f.read_text(encoding="utf-8")):
            cs, _ = refs_in_text(body + " " + head)
            inter = cs & targets
            if inter:
                hits.append({"file": rel, "section": head, "via": sorted(inter)})
    dec_hits = []
    for dec in load_decisions(pid):
        refs = set(dec.get("rationale_claims", [])) | set(dec.get("assumptions", []))
        refs |= {t.get("claim") for t in dec.get("review_triggers", []) if t.get("claim")}
        if refs & targets:
            dec_hits.append({"decision": dec["id"], "title": dec.get("title", ""), "via": sorted(refs & targets)})
    res = {"claim": cid, "dependent_claims": deps, "sections": hits, "decisions": dec_hits}
    if mark_stale and (hits or dec_hits):
        st = load_state(pid)
        stale = st.setdefault("stale", [])
        for h in hits:
            item = {"file": h["file"], "section": h["section"], "reason": f"изменилось основание {cid}",
                    "claims": h["via"], "ts": now()}
            if not any(s.get("file") == h["file"] and s.get("section") == h["section"] for s in stale):
                stale.append(item)
        for dh in dec_hits:
            stale.append({"file": "decisions.yaml", "section": dh["decision"],
                          "reason": f"изменилось основание {cid}", "claims": dh["via"], "ts": now()})
        save_state(st, pid)
        journal("impact_marked_stale", f"{cid}: разделов {len(hits)}, решений {len(dec_hits)}", pid=pid)
    return res


def clear_stale(file: str = "", pid=None) -> int:
    st = load_state(pid)
    before = len(st.get("stale", []))
    st["stale"] = [s for s in st.get("stale", []) if file and s.get("file") != file]
    save_state(st, pid)
    n = before - len(st["stale"])
    journal("stale_cleared", f"{file or 'все'}: {n}", pid=pid)
    return n
