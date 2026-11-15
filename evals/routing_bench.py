"""Замер выбора модели для маршрутизации (задача classify): точность × цена × время на размеченных запросах.

Запуск: python evals/routing_bench.py [модель1,модель2,...]
Зачем: модели выбираются не «по новизне», а по качеству и стоимости на нашей задаче. Результат — evals/results/routing_bench.json.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from strategist.llm import ask  # noqa: E402
from strategist.router import SKILLS  # noqa: E402

CASES = [
    ("Почему у нас падает удержание в приложении и что делать в следующем квартале?", "intake"),
    ("Собери открытые материалы по рынку eSIM: страницы операторов, новости, статистику", "source-collection"),
    ("Сравни, как МТС и Билайн продают защиту от спама, и что про это пишут аналитики", "research"),
    ("Подготовь вопросы для разговоров с родителями-пенсионерами о звонках мошенников", "interviews"),
    ("Посмотри скриншоты нашего онбординга и скажи, где пользователи теряются", "ux-review"),
    ("Вот выгрузка подписок за 2025 год в csv — посчитай отток по месяцам подключения", "data-analysis"),
    ("Какие у нас есть пути: оставить подписку, сделать бесплатно или свернуть?", "options"),
    ("Опиши аудиторию, альтернативы и от чего мы сознательно отказываемся в продукте", "product-strategy"),
    ("Что сказать людям в рекламе, чтобы они поверили и подключили услугу?", "comms-strategy"),
    ("Как нам понять через три месяца, что новая цена сработала?", "validation-plan"),
    ("Кто отвечает за запуск пилота и какие сроки мы обещали?", "decision-support"),
    ("ЦБ опубликовал новые данные за квартал — что из наших выводов теперь неверно?", "revisit"),
    ("Собери итог для CPO на одну страницу и PDF", "report"),
    ("Хочу понять, что думают родители-пенсионеры о том, что мы им предлагаем", "interviews"),
    ("Конкуренты снизили цену — нужно ли нам пересматривать решение?", "revisit"),
    ("Сделай таблицу вариантов с возражениями финансистов и юристов", "options"),
]
DEFAULT = ["qwen/qwen3.7-flash", "z-ai/glm-5.3-flash", "z-ai/glm-5.3", "deepseek/deepseek-v4-flash", "moonshotai/kimi-k3.1-pro"]
catalog = "\n".join(f"- {k}: {v[0]}" for k, v in SKILLS.items())


def main():
    models = sys.argv[1].split(",") if len(sys.argv) > 1 else DEFAULT
    out = []
    for m in models:
        ok = cost = 0.0
        errs, t0 = [], time.time()
        for req, gold in CASES:
            prompt = (f"Выбери один навык агента для запроса руководителя продукта.\nНавыки:\n{catalog}\n"
                      f"Запрос: «{req}»\nОтветь JSON: {{\"skill\": \"<имя>\", \"confidence\": 0..1}}")
            try:
                r = ask("classify", prompt, model=m, pid="antifraud-family", stage="eval", label=f"routing-bench:{m}", cache=False)
                got = (r["json"] or {}).get("skill")
                ok += got == gold
                cost += r["usd"]
                if got != gold:
                    errs.append(f"{req[:40]}… → {got} (нужно {gold})")
            except Exception as e:  # модель не справилась — тоже результат замера
                errs.append(f"{req[:40]}… → ошибка: {str(e)[:120]}")
        dt = time.time() - t0
        row = {"model": m, "accuracy_pct": round(100 * ok / len(CASES), 1), "usd_total": round(cost, 6),
               "usd_per_1000_calls": round(1000 * cost / len(CASES), 3), "sec_per_call": round(dt / len(CASES), 2),
               "errors": errs}
        out.append(row)
        print(f"{m:<32} точность {row['accuracy_pct']:>5}% · ${row['usd_per_1000_calls']:>7} за 1000 вызовов · {row['sec_per_call']} с/вызов")
    f = ROOT / "evals" / "results" / "routing_bench.json"
    prev = {r["model"]: r for r in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else {}
    prev.update({r["model"]: r for r in out})  # объединяем с прошлыми замерами других моделей
    f.write_text(json.dumps(list(prev.values()), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
