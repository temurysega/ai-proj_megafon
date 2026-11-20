"""Пилот варианта B, прогноз по пяти строкам таблицы брифа, прибыль и предельные вложения.
# inputs: (числа брифа S001 — константы; допущения A1–A12 — константы, все в реестре утверждений)
# outputs: strategy_calc.md, strategy_calc.json
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
# --- бриф (S001) ---
NO_CHANGE = {"profit": 279, "active": 5000, "connected": 8000, "owners": 1000, "activation": 45}   # C003–C007
TARGET = {"profit": 285, "active": 8000, "connected": 12000, "owners": 2000, "activation": 60}
RATE = 500                       # C011
GAP_MONTHS = 12000               # C012
# --- допущения ---
NUMBERS_PER_GROUP = 3.0          # A1 (середина 2,5–3,5)
CHURN = 0.015                    # A2 (середина 1–2%)
LIVE = 6                         # A3: месяцев работы в плановом году
BASE_RESTRICT = (0.10, 0.12, 0.15)   # A6: доля ограничений за 7 дней после первого низкого остатка, обычное обслуживание
MDE_PP = (0.03, 0.04, 0.05)          # A7: минимальное важное улучшение, п.п.
ELIGIBLE_PER_WEEK = (75, 150, 300)   # A8: групп в неделю впервые с подходящим низким остатком
SCEN = {  # A9–A12 и эффект удержания (A4)
    "основной": {"share_pp": 4, "coverage": 0.5, "activation_pp": 2, "connected_add": 300, "rel_churn": 0.10},
    "менее благоприятный": {"share_pp": 1, "coverage": 0.3, "activation_pp": 0, "connected_add": 0, "rel_churn": 0.0},
}
Z_A, Z_B = 1.959964, 0.841621    # α = 0,05 двусторонний, мощность 80%


def n_per_arm(p1, p2):
    pb = (p1 + p2) / 2
    return math.ceil((Z_A * math.sqrt(2 * pb * (1 - pb)) + Z_B * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p1 - p2) ** 2)


def extra_months(p, r, months):
    return sum((1 - p * (1 - r)) ** t - (1 - p) ** t for t in range(1, months + 1))


out = {"pilot": [], "forecast": {}, "investment": []}
for p1 in BASE_RESTRICT:
    for d in MDE_PP:
        n = n_per_arm(p1, p1 - d)
        weeks = {w: math.ceil(2 * n / w) + 1 for w in ELIGIBLE_PER_WEEK}   # набор обеих групп + 1 неделя наблюдения (7 дней)
        out["pilot"].append({"base": p1, "mde_pp": d, "relative": round(d / p1, 3), "n_per_arm": n, "weeks": weeks})

share_nc = NO_CHANGE["active"] / NO_CHANGE["connected"]
for name, s in SCEN.items():
    connected = NO_CHANGE["connected"] + s["connected_add"]
    active = round(connected * (share_nc + s["share_pp"] / 100))
    covered_numbers = round(connected * s["coverage"] * NUMBERS_PER_GROUP)
    months = covered_numbers * extra_months(CHURN, s["rel_churn"], LIVE)
    profit = NO_CHANGE["profit"] + months * RATE / 1e6
    out["forecast"][name] = {"profit": round(profit, 2), "active": active, "connected": connected, "owners": NO_CHANGE["owners"],
                             "activation": NO_CHANGE["activation"] + s["activation_pp"], "covered_numbers": covered_numbers,
                             "extra_paid_months": round(months), "profit_gap_mln": round(TARGET["profit"] - profit, 2)}
# предельные вложения: доп. прибыль охваченной когорты с III кв. планового года до конца третьего года (30 месяцев), без новых охватов
for cov in (0.3, 0.5):
    for r in (0.05, 0.10, 0.20):
        n = NO_CHANGE["connected"] * cov * NUMBERS_PER_GROUP
        val = n * extra_months(CHURN, r, 30) * RATE / 1e6
        out["investment"].append({"coverage": cov, "rel_churn": r, "covered_numbers": round(n), "max_invest_mln_to_y3": round(val, 2)})

f = out["forecast"]
md = ["# Пилот B, прогноз по пяти строкам, прибыль и вложения", "",
      "_Числа брифа — S001 (C003–C012); допущения A1–A12 — диапазоны для проверки, не данные кейса._", "",
      "## Пилот: сколько групп нужно и сколько недель набирать",
      "Единица — семейная группа с первым подходящим случаем низкого остатка у участника; исход — ограничение интернета у этого участника за 7 дней. "
      "α = 0,05 (двусторонний), мощность 80%, распределение 50/50 по группам целиком.", "",
      "| Доля ограничений без сигнала (A6) | Важное улучшение (A7) | Относительно | Групп на ветку | Недель при 75 / 150 / 300 подходящих в неделю (A8) |",
      "|---|---|---|---|---|"]
for row in out["pilot"]:
    w = row["weeks"]
    md.append(f"| {100 * row['base']:.0f}% | {100 * row['mde_pp']:.0f} п.п. | {100 * row['relative']:.0f}% | {row['n_per_arm']} | {w[75]} / {w[150]} / {w[300]} |")
# разброс оценки при расчётном размере: половина ширины 95% интервала разницы долей (база 12%, улучшение 3 п.п.)
n_main = n_per_arm(0.12, 0.09)
half_width = Z_A * math.sqrt(0.12 * 0.88 / n_main + 0.09 * 0.91 / n_main)
out["ci_half_width_pp"] = round(100 * half_width, 1)
md += ["", f"Разброс: при {n_main} группах на ветку половина ширины 95% интервала разницы ≈{100 * half_width:.1f} п.п. Правило решения: интервал "
       "целиком выше нуля и оценка не меньше порога — запуск; интервал целиком ниже порога — масштабирование не оправдано; интервал включает "
       "и ноль, и порог — продлить набор."]
md += ["", "**Вывод:** при базе 12% и улучшении на 3 п.п. нужно ≈1,6 тыс. групп на ветку; даже при 300 подходящих группах в неделю это ≈12 недель — "
       "больше, чем остаётся во II квартале после разработки. К концу II квартала надёжно проверяются понятность сигнала и исполнение передачи, "
       "а эффект на ограничения — к концу III квартала (или при улучшении от 5 п.п.).", "",
       "## Прогноз по пяти строкам таблицы брифа (плановый год)",
       "| Показатель | Без изменений | Основной | Менее благоприятный | Цель | Разрыв основного до цели |", "|---|---|---|---|---|---|",
       f"| Валовая прибыль, млн руб. | {NO_CHANGE['profit']} | {f['основной']['profit']} | {f['менее благоприятный']['profit']} | {TARGET['profit']} | {f['основной']['profit_gap_mln']} |",
       f"| Активные группы за последний месяц | {NO_CHANGE['active']} | {f['основной']['active']} | {f['менее благоприятный']['active']} | {TARGET['active']} | {TARGET['active'] - f['основной']['active']} |",
       f"| Подключённые группы на конец года | {NO_CHANGE['connected']} | {f['основной']['connected']} | {f['менее благоприятный']['connected']} | {TARGET['connected']} | {TARGET['connected'] - f['основной']['connected']} |",
       f"| Подключённые владельцы нескольких номеров | {NO_CHANGE['owners']} | {f['основной']['owners']} | {f['менее благоприятный']['owners']} | {TARGET['owners']} | {TARGET['owners'] - f['основной']['owners']} |",
       f"| Активированные за 14 дней, % | {NO_CHANGE['activation']} | {f['основной']['activation']} | {f['менее благоприятный']['activation']} | {TARGET['activation']} | {TARGET['activation'] - f['основной']['activation']} п.п. |",
       "", f"Основной ход: охват {f['основной']['covered_numbers']} номеров с III квартала даёт ≈{f['основной']['extra_paid_months']} доп. оплаченных месяцев "
       f"из {GAP_MONTHS} нужных — удержание в плановом году почти не меняет прибыль.", "",
       "## Предельные вложения, которые вернутся к концу третьего года",
       "Доп. прибыль когорты, охваченной с III квартала планового года, за 30 месяцев (без новых охватов во 2–3 году — осторожная оценка):", "",
       "| Охват групп (A10) | Снижение оттока охваченных (A4) | Охваченных номеров | Предельные вложения, млн руб. |", "|---|---|---|---|"]
for row in out["investment"]:
    md.append(f"| {100 * row['coverage']:.0f}% | {100 * row['rel_churn']:.0f}% | {row['covered_numbers']} | {row['max_invest_mln_to_y3']} |")
md += ["", "Формула: N охваченных номеров × Σ по месяцам [(1 − p(1 − r))^t − (1 − p)^t] × 500 руб.; p — месячный отток (A2), r — снижение оттока, "
       "которое должен показать пилот. Если разработка дороже предельной суммы, вариант B окупается только через экономию поддержки или "
       "рост подключений."]
(HERE / "strategy_calc.md").write_text("\n".join(md) + "\n", encoding="utf-8")
(HERE / "strategy_calc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n".join(md))
