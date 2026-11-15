"""Слепое жюри из моделей другого семейства (DeepSeek, Qwen через OpenRouter): рубрика K1–K8 + 12 решающих фактов.

Запуск: python evals/run_openrouter_jury.py
Сравнения: агент против обычного чата на Sonnet и против обычного чата на DeepSeek. Порядок документов случайный
(фиксированное зерно), названия скрыты; соответствие раскрывается только в файле результата.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import yaml  # noqa: E402

from strategist.llm import ask  # noqa: E402

RUBRIC = yaml.safe_load((ROOT / "evals" / "rubric.yaml").read_text(encoding="utf-8"))
FACTS = yaml.safe_load((ROOT / "evals" / "decision_facts.yaml").read_text(encoding="utf-8"))
JUDGES = ["deepseek/deepseek-v4-pro", "qwen/qwen3.7-plus"]
DOCS = {
    "agent": (ROOT / "evals" / "results" / "blind" / "doc_Y.md").read_text(encoding="utf-8"),
    "chat_sonnet": (ROOT / "evals" / "results" / "blind" / "doc_X.md").read_text(encoding="utf-8"),
    "chat_deepseek": (ROOT / "evals" / "baseline" / "deepseek-chat.md").read_text(encoding="utf-8").split("-->", 1)[-1],
}
crit = "\n".join(f"- {c['id']} {c['name']}: {c['what']}" for c in RUBRIC["criteria"])
facts = "\n".join(f"- {f['id']}: {f['fact']}" for f in FACTS["facts"])


def judge(model: str, a_name: str, b_name: str, rnd: random.Random) -> dict:
    swap = rnd.random() < 0.5
    first, second = (b_name, a_name) if swap else (a_name, b_name)
    prompt = (
        "Ты — независимый эксперт по продуктовой стратегии в жюри. Задача обоих документов: что делать МегаФону с семейной "
        "защитой от мошенников (платно / бесплатно / закрыть) и что говорить людям; цель — удержание и доверие при окупаемости. "
        "Авторы скрыты. Объём сам по себе не достоинство; проверяемость, разделение фактов и гипотез, конкретность и "
        "пригодность для решения оценивай строго.\n\n"
        f"Критерии (0–10):\n{crit}\n\nРешающие факты (для каждого документа: present_correct / present_wrong / absent):\n{facts}\n\n"
        "Верни ТОЛЬКО JSON: {\"X\": {\"K1\":..,\"K8\":..}, \"Y\": {...}, \"facts_X\": {\"F1\":\"...\",...}, "
        "\"facts_Y\": {...}, \"better\": \"X|Y|tie\", \"why\": \"3-5 предложений\"}\n\n"
        f"=== ДОКУМЕНТ X ===\n{DOCS[first]}\n\n=== ДОКУМЕНТ Y ===\n{DOCS[second]}")

    def valid(r):
        j = r.get("json") or {}
        return None if all(k in j for k in ("X", "Y", "better")) else "нет полей X/Y/better"
    res = ask("judge", prompt, model=model, pid="antifraud-family", stage="eval", label=f"jury:{model}:{a_name}-vs-{b_name}",
              validate=valid)
    j = res["json"]
    m = {"X": first, "Y": second}
    better = j.get("better")
    return {"judge": model, "pair": f"{a_name} vs {b_name}", "order": [first, second], "usd": res["usd"],
            "scores": {m["X"]: j["X"], m["Y"]: j["Y"]},
            "facts": {m["X"]: j.get("facts_X", {}), m["Y"]: j.get("facts_Y", {})},
            "better": m.get(better, "tie"), "why": j.get("why", "")}


def main():
    rnd = random.Random(20261115)
    out = []
    for model in JUDGES:
        for base in ("chat_sonnet", "chat_deepseek"):
            r = judge(model, "agent", base, rnd)
            out.append(r)
            avg = {k: round(sum(v.values()) / len(v), 2) for k, v in r["scores"].items()}
            fc = {k: sum(1 for x in v.values() if str(x).startswith("present_correct")) for k, v in r["facts"].items()}
            print(f"{model} | {r['pair']} | порядок {r['order']} | средние {avg} | факты верно {fc} | лучше: {r['better']} | ${r['usd']:.4f}")
    (ROOT / "evals" / "results" / "jury-openrouter.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
