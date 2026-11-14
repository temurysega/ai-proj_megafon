"""Сравнение с исходным способом: объективные метрики + слепая оценка судьями другого семейства.

Ограничения (заявлены в отчёте): n=1 задача; ИИ-судьи; рубрика написана авторами агента.
Поэтому основной вес — у проверяемых метрик (доля утверждений с источником, точность
выборочной проверки фактов), а оценки судей — вспомогательные.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from .common import ROOT, now, read_yaml
from .llm import ask

URL = re.compile(r"https?://[^\s)\]>\"']+")


def text_metrics(text: str) -> dict:
    """Метрики для любого текста стратегии (в т.ч. ответа обычного чата)."""
    low = text.lower()
    options = len(re.findall(r"^#{1,4}\s*(вариант|опция|сценарий)\b", text, re.I | re.M))
    return {
        "chars": len(text),
        "distinct_urls": len(set(URL.findall(text))),
        "claim_refs": len(set(re.findall(r"\bC\d{3,}\b", text))),
        "numbers": len(re.findall(r"\d+[.,]?\d*\s?(%|млн|млрд|тыс|руб|₽)", text)),
        "options": options,
        "has_status_quo": bool(re.search(r"оставить как есть|статус[- ]кво|ничего не (менять|делать)", low)),
        "has_close": bool(re.search(r"закрыть|свернуть|прекратить|выйти из", low)),
        "objections": len(re.findall(r"возражени|контраргумент|риск", low)),
        "marks_hypotheses": bool(re.search(r"гипотез", low)),
        "marks_unknowns": bool(re.search(r"не знаем|неизвестн|пробел|нет данных", low)),
        "validation_plan": all(k in low for k in ("метрик", "срок")) and bool(re.search(r"сравн|контрольн", low)),
    }


def project_text(pid: str) -> str:
    base = ROOT / "projects" / pid
    parts = []
    for rel in ["strategy/one-pager.md", "research/findings.md", "options.md", "strategy/product.md",
                "strategy/communication.md", "strategy/validation.md"]:
        f = base / rel
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def judge(a_text: str, b_text: str, rubric_file: str, models: list[str] | None = None, pid: str | None = None,
          seed: int = 7) -> dict:
    """Слепое сравнение: порядок A/B случайный, названия скрыты; несколько судей."""
    rubric = read_yaml(Path(rubric_file), {})
    crit = "\n".join(f"- {c['id']}: {c['name']} — {c['what']}" for c in rubric.get("criteria", []))
    models = models or ["deepseek/deepseek-v4-pro", "qwen/qwen3.7-plus"]
    rnd = random.Random(seed)
    results = []
    for m in models:
        swap = rnd.random() < 0.5
        x, y = (b_text, a_text) if swap else (a_text, b_text)
        prompt = (f"Ты — независимый эксперт по продуктовой стратегии. Оцени два документа по критериям (0–10 каждый). "
                  f"Проверяемость (ссылки, разделение фактов и гипотез) оценивай строго; объём сам по себе не достоинство.\n"
                  f"Критерии:\n{crit}\n\nВерни JSON: {{\"X\": {{\"<id>\": балл, ...}}, \"Y\": {{...}}, "
                  f"\"better\": \"X|Y|tie\", \"why\": \"3-5 предложений\"}}\n\n"
                  f"=== ДОКУМЕНТ X ===\n{x[:60000]}\n\n=== ДОКУМЕНТ Y ===\n{y[:60000]}")
        res = ask("judge", prompt, model=m, pid=pid, stage="eval", label=f"judge:{m}", max_tokens=2500)
        j = res["json"] or {}
        a_sc, b_sc = (j.get("Y"), j.get("X")) if swap else (j.get("X"), j.get("Y"))
        better = j.get("better")
        if swap and better in ("X", "Y"):
            better = "Y" if better == "X" else "X"
        results.append({"judge": m, "A": a_sc, "B": b_sc, "better": {"X": "A", "Y": "B"}.get(better, "tie"),
                        "why": j.get("why", ""), "usd": res["usd"], "order_swapped": swap})
    return {"ts": now(), "rubric": rubric_file, "results": results}


def save(result: dict, path: str) -> None:
    Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
