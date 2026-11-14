"""Маршрутизация запроса к процессу (навыку) и модели.

1) Правила по ключевым словам — бесплатно и мгновенно.
2) Если правила неуверенны — дешёвый классификатор (config/routing.yaml → classify).
3) Если и он неуверен — вопрос человеку.
Исправления человека (`sf route --correct`) сохраняются и используются как примеры
и точные переопределения: ошибочный выбор не повторяется.
"""
from __future__ import annotations

import re

from .common import MEMORY, append_jsonl, now, read_jsonl
from .llm import NoKeyError, LLMError, ask

SKILLS = {
    "intake": ("Постановка задачи: уточнить вопрос, цель, получателя, ограничения, данные",
               r"(новая задача|нужно понять|разобраться|помоги|что делать|постав|бриф|запрос)"),
    "source-collection": ("Сбор материалов: документы, таблицы, сайты, реестр источников",
                          r"(собери|материал|источник|ссылк|документ|pdf|таблиц|сайт|загрузи)"),
    "research": ("Исследование: план от решающих вопросов, сопоставление источников, пробелы",
                 r"(исследуй|исследован|рынок|конкурент|почему|причин|анализ рынка|сопостав)"),
    "interviews": ("Интервью: гайд, анализ транскриптов, модельные респонденты",
                   r"(интервью|респондент|опрос|гайд|расшифровк|custdev|кастдев)"),
    "ux-review": ("Анализ UX: интерфейсы, пути, скриншоты",
                  r"(интерфейс|ux|ui|экран|скриншот|лендинг|путь пользоват|онбординг)"),
    "data-analysis": ("Анализ данных: метрики, когорты, проверка единиц и периодов",
                      r"(данные|метрик|когорт|удержани|retention|конверси|csv|xlsx|выгрузк|дашборд)"),
    "options": ("Варианты решения с возражениями, включая «оставить как есть» и «закрыть»",
                r"(вариант|альтернатив|сценари|что выбрать|сравни варианты)"),
    "product-strategy": ("Продуктовая стратегия", r"(продуктов\w* стратег|позиционир|монетизац|ценообраз|тариф)"),
    "comms-strategy": ("Коммуникационная стратегия", r"(коммуникац|сообщени|месседж|реклам|канал|как говорить|бренд)"),
    "validation-plan": ("План проверки: метрика, сравнение, срок, побочные эффекты",
                        r"(провер|эксперимент|a/b|аб-тест|пилот|метрика успеха)"),
    "decision-support": ("Сопровождение решения: обязательства, владельцы, условия пересмотра",
                         r"(решени|обязательств|дедлайн|ответственн|что решать сейчас|контрол)"),
    "revisit": ("Пересмотр выводов при новых данных", r"(новые данные|появил|обнови|пересмотр|изменилось|свежие)"),
    "report": ("Сборка отчёта для руководителя", r"(отчёт|отчет|итог|презентац|pdf|one-pager|резюме)"),
}
CORRECTIONS = MEMORY / "routing_corrections.jsonl"


def rule_scores(text: str) -> dict[str, int]:
    t = text.lower()
    return {k: len(re.findall(rx, t)) for k, (_, rx) in SKILLS.items()}


def route(request: str, use_llm: bool = True, pid: str | None = None) -> dict:
    # 0. точные исправления человека
    for c in reversed(read_jsonl(CORRECTIONS)):
        if c.get("request", "").strip().lower() == request.strip().lower():
            return {"skill": c["correct"], "confidence": 1.0, "method": "correction",
                    "reason": "ранее исправлено человеком"}
    scores = rule_scores(request)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (top, s1), (_, s2) = ranked[0], ranked[1]
    if s1 >= 2 and s1 - s2 >= 1:
        return {"skill": top, "confidence": min(0.6 + 0.1 * s1, 0.95), "method": "rules",
                "reason": f"ключевые слова ({s1} совпад.)", "scores": dict(ranked[:4])}
    if use_llm:
        examples = read_jsonl(CORRECTIONS)[-8:]
        ex = "\n".join(f"- «{e['request']}» → {e['correct']}" for e in examples)
        catalog = "\n".join(f"- {k}: {v[0]}" for k, v in SKILLS.items())
        prompt = (f"Выбери один навык агента для запроса руководителя продукта.\nНавыки:\n{catalog}\n"
                  f"{'Исправления прошлых ошибок:' + chr(10) + ex if ex else ''}\n"
                  f"Запрос: «{request}»\nОтветь JSON: {{\"skill\": \"<имя>\", \"confidence\": 0..1, "
                  f"\"reason\": \"кратко\", \"clarify\": \"вопрос человеку, если неясно, иначе пусто\"}}")

        def _valid(res):
            j = res.get("json") or {}
            return None if j.get("skill") in SKILLS else f"неизвестный навык {j.get('skill')}"
        try:
            res = ask("classify", prompt, pid=pid, validate=_valid, label="route")
            j = res["json"]
            out = {"skill": j["skill"], "confidence": float(j.get("confidence", 0.5)), "method": "llm",
                   "model": res["model"], "reason": j.get("reason", ""), "clarify": j.get("clarify", ""),
                   "usd": res["usd"]}
            if out["confidence"] < 0.55:
                out["ask_human"] = out.get("clarify") or "Уточните, какой результат нужен."
            return out
        except (NoKeyError, LLMError) as e:
            fallback_note = f"классификатор недоступен ({str(e)[:80]})"
        else:
            fallback_note = ""
    else:
        fallback_note = "LLM отключён"
    return {"skill": top if s1 else "intake", "confidence": 0.4 if s1 else 0.2, "method": "rules-weak",
            "reason": fallback_note, "ask_human": "Уточните задачу: какой результат и для кого нужен?",
            "scores": dict(ranked[:4])}


def correct(request: str, wrong: str, correct_skill: str) -> None:
    if correct_skill not in SKILLS:
        raise ValueError(f"Неизвестный навык {correct_skill}")
    append_jsonl(CORRECTIONS, {"ts": now(), "request": request, "wrong": wrong, "correct": correct_skill})


def routing_stats() -> dict:
    corr = read_jsonl(CORRECTIONS)
    by = {}
    for c in corr:
        k = f"{c.get('wrong')}→{c.get('correct')}"
        by[k] = by.get(k, 0) + 1
    return {"corrections": len(corr), "pairs": by}
