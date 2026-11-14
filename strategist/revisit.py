"""Пересмотр при новых данных: какие утверждения затрагивает новый источник.

1) Кандидаты — по лексической близости (BM25) фрагментов нового источника к активным утверждениям
   и по совпадению чисел/сущностей (бесплатно).
2) Опционально `--llm`: судья другого семейства классифицирует пару (подтверждает / противоречит /
   уточняет / не относится) с дословной цитатой из нового источника.
3) Агент обновляет утверждения (`claim update/retract`), затем `impact --mark-stale` помечает
   затронутые разделы и решения, а `due` показывает сработавшие триггеры пересмотра.
"""
from __future__ import annotations

import re

from .evidence import get_source, load_claims
from .kb import bm25
from .llm import ask
from .project import journal, project_dir
from .safety import quarantine

NUM = re.compile(r"\d+[.,]?\d*")


def candidates(source_id: str, top: int = 8, use_llm: bool = False, pid=None) -> list[dict]:
    d = project_dir(pid)
    src = get_source(source_id, pid)
    p = d / (src.get("text_path") or src.get("path") or f"sources/raw/{source_id}.md")
    if not p.exists() or p.suffix not in (".md", ".txt"):
        p = d / "sources" / "raw" / f"{source_id}.md"
    text = p.read_text(encoding="utf-8")
    paras = [x.strip() for x in re.split(r"\n\s*\n|\n(?=#)", text) if len(x.strip()) > 60]
    claims = [c for c in load_claims(pid) if c.get("status") == "active" and source_id not in c.get("sources", [])]
    out = []
    for c in claims:
        scored = bm25(c["text"], [{"section": "", "text": para} for para in paras])
        if not scored:
            continue
        s, best = scored[0]
        nums_c = set(NUM.findall(c["text"]))
        nums_p = set(NUM.findall(best["text"]))
        bonus = 1.0 if nums_c & nums_p else 0.0
        out.append({"claim": c["id"], "claim_text": c["text"], "score": round(s + bonus, 2),
                    "evidence": best["text"][:600]})
    out = sorted(out, key=lambda x: -x["score"])[:top]
    if use_llm:
        for o in out:
            prompt = (f"Утверждение из базы проекта: «{o['claim_text']}»\n\nФрагмент нового источника {source_id}:\n"
                      f"{quarantine(o['evidence'], source_id)}\n\nКак фрагмент относится к утверждению? "
                      f"JSON: {{\"relation\": \"supports|contradicts|refines|unrelated\", \"quote\": \"дословная цитата\", "
                      f"\"why\": \"кратко\"}}")
            try:
                res = ask("judge", prompt, pid=pid, stage="revisit", label=f"revisit:{o['claim']}", max_tokens=400)
                o.update(res["json"] or {})
            except Exception as e:
                o["relation"] = f"не оценено ({str(e)[:60]})"
    journal("revisit_candidates", f"{source_id}: кандидатов {len(out)}", pid=pid, actor="tool")
    return out
