"""Проверка рабочего маршрутизатора. Без сети: python evals/routing_offline.py [--save].
С дешёвым классификатором OpenRouter (нужен ключ): python evals/routing_offline.py --llm [--save]."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategist.router import SKILLS, route  # noqa: E402


def evaluate(cases: list[dict], use_llm: bool = False) -> dict:
    results = []
    outcomes = Counter()
    for case in cases:
        if case["skill"] not in SKILLS:
            raise ValueError(f"Неизвестная метка: {case['skill']}")
        result = route(case["request"], use_llm=use_llm)
        correct = result["skill"] == case["skill"]
        if result.get("ask_human"):
            outcome = "clarify"
        else:
            outcome = "correct" if correct else "wrong"
        outcomes[outcome] += 1
        results.append({**case, "proposed_skill": result["skill"], "method": result["method"], "outcome": outcome})

    # Та же подсказка навыка, если бы система принимала решение без уточнений.
    forced_correct = sum(row["proposed_skill"] == row["skill"] for row in results)
    return {
        "cases": len(cases),
        "use_llm": use_llm,
        "topics": sorted({case["topic"] for case in cases}),
        "routes": dict(sorted(Counter(row["method"] for row in results).items())),
        "correct_without_question": outcomes["correct"],
        "wrong_without_question": outcomes["wrong"],
        "questions": outcomes["clarify"],
        "forced_choice_correct": forced_correct,
        "forced_choice_wrong": len(cases) - forced_correct,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Обновить сохранённый JSON с ответом на каждый запрос")
    parser.add_argument("--llm", action="store_true", help="Правила → дешёвый классификатор → вопрос (как в рабочем режиме с ключом)")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    cases = yaml.safe_load((folder / "routing_requests.yaml").read_text(encoding="utf-8"))
    report = evaluate(cases, use_llm=args.llm)
    if args.save:
        name = "routing_llm.json" if args.llm else "routing_offline.json"
        (folder / "results" / name).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
