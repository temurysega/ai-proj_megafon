"""Интервью: гайды, модельные (синтетические) респонденты, анализ транскриптов.

Принципы:
- синтетические интервью помечаются как СИНТЕТИКА на каждом шаге (файл, источник, утверждения);
  они ищут гипотезы и формулировки, но не доказывают спрос и распространённость;
- реальные интервью принимаются только с метаданными consent: yes; ПДн вычищаются
  ДО отправки любой модели и до записи в репозиторий.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .common import StrategistError, now, read_yaml, sha256_text, slugify
from .evidence import add_claim, add_source
from .llm import ask, task_cfg
from .project import journal, project_dir
from .safety import scrub_pii

SYNTH_BANNER = ("> ⚠ СИНТЕТИЧЕСКОЕ ИНТЕРВЬЮ. Ответы сгенерированы моделью {model} в роли персонажа. "
                "Используется только для поиска гипотез и формулировок. НЕ доказывает спрос, долю или "
                "распространённость потребности.\n")

RESPONDENT_SYSTEM = """Ты играешь роль респондента в исследовательском интервью. Это модельный (синтетический) респондент.
Персонаж:
{persona}

Правила:
- Отвечай от первого лица, разговорно, 2–6 предложений, как реальный человек с этим опытом и ограничениями.
- Не будь услужливым: сомневайся, возражай, признавайся, когда не знаешь или не помнишь.
- Не придумывай статистику и не ссылайся на исследования — ты обычный человек.
- Если вопрос наводящий, отвечай честно с позиции персонажа, а не так, как «хочет» интервьюер.
- Конкретика из жизни (ситуации, слова, действия) важнее оценок."""

PROBE_PROMPT = """Ты интервьюер в JTBD-интервью. Вопрос: «{q}». Ответ респондента: «{a}».
Если ответ общий или содержит интересную деталь — задай ОДИН короткий открытый уточняющий вопрос (о конкретной ситуации, \
действиях, причинах; без подсказки ответа). Если уточнять нечего — ответь ровно: НЕТ."""


def load_guide(path: Path) -> list[str]:
    qs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(\d+)[.)]\s+(.+)", line)
        if m:
            qs.append(m.group(2).strip())
    if not qs:
        raise StrategistError(f"В гайде {path} нет нумерованных вопросов («1. …»)")
    return qs


def run_synthetic(personas_file: str, guide_file: str, max_followups: int = 1, rotate: bool = False,
                  only: list[str] | None = None, pid=None, out_subdir: str = "synthetic") -> list[dict]:
    d = project_dir(pid)
    personas = read_yaml(Path(personas_file), [])
    guide = load_guide(Path(guide_file))
    cfg = task_cfg("respondent")
    pool = cfg.get("rotate_pool", cfg["models"]) if rotate else cfg["models"]
    out_dir = d / "research" / "interviews" / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, p in enumerate(personas):
        if only and p["id"] not in only:
            continue
        key = f"synthetic:{out_subdir}:{p['id']}:{sha256_text(yaml.safe_dump(p, allow_unicode=True) + '|'.join(guide))[:12]}"
        from .project import already_done
        done = already_done(key, pid)
        if done:  # устойчивость: уже проведённое интервью не повторяется (и не оплачивается)
            results.append({"persona": p["id"], "file": done.get("file"), "skipped": True})
            continue
        model_chain = [pool[i % len(pool)]] + [m for m in cfg["models"] if m != pool[i % len(pool)]]
        persona_txt = yaml.safe_dump({k: v for k, v in p.items() if k != "id"}, allow_unicode=True)
        msgs = [{"role": "system", "content": RESPONDENT_SYSTEM.format(persona=persona_txt)}]
        transcript, usd, used_model = [], 0.0, model_chain[0]
        for qi, q in enumerate(guide, 1):
            asks = [q]
            n_follow = 0
            while asks:
                cur = asks.pop(0)
                msgs.append({"role": "user", "content": cur})
                res = ask("respondent", messages=msgs, models=model_chain, pid=pid, stage="research",
                          label=f"respondent:{p['id']}:q{qi}")
                used_model, usd = res["model"], usd + res["usd"]
                ans = res["text"].strip()
                msgs.append({"role": "assistant", "content": ans})
                transcript.append(("И", cur))
                transcript.append(("Р", ans))
                if n_follow < max_followups:
                    pr = ask("interviewer", PROBE_PROMPT.format(q=cur, a=ans), pid=pid, stage="research",
                             label=f"probe:{p['id']}:q{qi}")
                    usd += pr["usd"]
                    probe = pr["text"].strip().strip("«»\"")
                    if probe and not probe.upper().startswith("НЕТ"):
                        asks.append(probe)
                        n_follow += 1
        fname = out_dir / f"{p['id']}.md"
        body = [f"# Синтетическое интервью: {p.get('label', p['id'])}", "",
                SYNTH_BANNER.format(model=used_model), "", "## Персонаж", "```yaml", persona_txt.strip(), "```", "",
                "## Транскрипт"]
        body += [f"**{'Интервьюер' if who == 'И' else 'Респондент (синт.)'}:** {txt}\n" for who, txt in transcript]
        fname.write_text("\n".join(body), encoding="utf-8")
        src = add_source(f"Синтетическое интервью ({used_model}): {p.get('label', p['id'])}", kind="synthetic",
                         path=fname.relative_to(d).as_posix(), reliability="D",
                         notes=f"модель {used_model}; стоимость ${usd:.4f}; не доказывает спрос", pid=pid)
        journal("synthetic_interview", f"{p['id']} → {fname.name} ({used_model}, ${usd:.4f})", pid=pid,
                actor="tool", key=key, file=fname.relative_to(d).as_posix(), usd=round(usd, 5))
        results.append({"persona": p["id"], "file": fname.relative_to(d).as_posix(), "source": src["id"],
                        "model": used_model, "usd": round(usd, 5)})
    return results


CODE_PROMPT = """Закодируй транскрипт интервью для продуктового исследования. Верни JSON:
{{"jobs": [{{"text": "...", "quote": "дословная цитата"}}],
 "pains": [{{"text": "...", "quote": "..."}}],
 "current_solutions": [{{"text": "...", "quote": "..."}}],
 "barriers": [{{"text": "барьер понимания/выбора/оплаты", "quote": "..."}}],
 "triggers": [{{"text": "что заставило искать решение", "quote": "..."}}],
 "words": ["характерные слова и формулировки респондента"],
 "surprises": ["что противоречит ожиданиям"]}}
Цитаты — ТОЛЬКО дословно из транскрипта. Не обобщай за пределы сказанного.
{data}"""


def analyze_interviews(folder: str, synthetic: bool = False, pid=None) -> dict:
    d = project_dir(pid)
    files = sorted(Path(folder).glob("*.md"))
    if not files:
        raise StrategistError(f"В {folder} нет транскриптов .md")
    coded, total_usd = [], 0.0
    from .safety import quarantine
    for f in files:
        text = f.read_text(encoding="utf-8")
        if not synthetic:
            meta = re.search(r"consent:\s*(yes|да)", text, re.I)
            if not meta:
                journal("interview_rejected", f"{f.name}: нет отметки согласия consent: yes", pid=pid, status="skipped")
                continue
        text, pii = scrub_pii(text)
        res = ask("code_interview", CODE_PROMPT.format(data=quarantine(text, f.stem)), pid=pid, stage="research",
                  label=f"code:{f.stem}",
                  validate=lambda r: None if isinstance(r.get("json"), dict) and "pains" in r["json"] else "нет поля pains")
        total_usd += res["usd"]
        # проверка дословности цитат (защита от выдуманных цитат)
        j = res["json"]
        bad = 0
        for cat in ("jobs", "pains", "current_solutions", "barriers", "triggers"):
            for it in j.get(cat, []):
                qt = (it.get("quote") or "").strip(" .«»\"")
                it["quote_verified"] = bool(qt) and qt[:60].lower() in text.lower()
                bad += 0 if it["quote_verified"] else 1
        coded.append({"file": f.name, "coded": j, "pii_removed": pii, "unverified_quotes": bad})
    # агрегация: тема → сколько интервью
    themes: dict[str, dict] = {}
    for c in coded:
        for cat in ("pains", "barriers", "jobs", "triggers"):
            for it in c["coded"].get(cat, []):
                k = f"{cat}: {it['text'][:90]}"
                t = themes.setdefault(k, {"cat": cat, "text": it["text"], "files": set(), "quotes": []})
                t["files"].add(c["file"])
                if it.get("quote_verified"):
                    t["quotes"].append(f"«{it['quote']}» ({c['file']})")
    label = "синтетических" if synthetic else "реальных"
    lines = [f"# Анализ {label} интервью ({len(coded)} шт.)", ""]
    if synthetic:
        lines.append("> ⚠ Синтетика: частоты ниже показывают совпадения между персонажами, а не распространённость "
                     "в реальной аудитории. Все выводы — гипотезы для проверки на реальных людях.\n")
    for cat, title in (("jobs", "Задачи (jobs)"), ("pains", "Боли"), ("barriers", "Барьеры"), ("triggers", "Триггеры")):
        lines.append(f"## {title}")
        items = sorted([t for t in themes.values() if t["cat"] == cat], key=lambda t: -len(t["files"]))
        for t in items[:12]:
            lines.append(f"- **{t['text']}** — {len(t['files'])}/{len(coded)} интервью")
            for q in t["quotes"][:2]:
                lines.append(f"  - {q}")
        lines.append("")
    unv = sum(c["unverified_quotes"] for c in coded)
    lines.append(f"_Неподтверждённых (не найденных дословно) цитат отброшено: {unv}. Стоимость кодирования: ${total_usd:.4f}._")
    out = d / "research" / "interviews" / f"analysis-{Path(folder).name}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    journal("interviews_analyzed", f"{len(coded)} {label} → {out.name}", pid=pid, actor="tool", usd=round(total_usd, 5))
    return {"file": out.relative_to(d).as_posix(), "n": len(coded), "themes": len(themes), "usd": total_usd,
            "unverified_quotes": unv}
