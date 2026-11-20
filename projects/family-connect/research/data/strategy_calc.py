"""Воспроизводимые расчёты пилота, воронки и экономики варианта B."""
import json
import math
from pathlib import Path

HERE = Path(__file__).parent

# Исходная таблица брифа C003–C007 и ставка C011.
BASELINE = {"profit": 279, "active": 5000, "connected": 8000, "owners": 1000, "activation": 45}
TARGET = {"profit": 285, "active": 8000, "connected": 12000, "owners": 2000, "activation": 60}
START_GROUPS = 6500
RATE = 500

# Допущения A1, A2, A4, A6–A11, A14–A16.
NUMBERS_PER_GROUP = 3
CHURN = 0.015
BASE_RESTRICT = (0.10, 0.12, 0.15)
MIN_EFFECTS = (0.03, 0.04, 0.05)
ELIGIBLE_PER_WEEK = (75, 150, 300)
CHANNELS = (
    ("Приложение", 5000, 0.024, 0.075),
    ("Продажи", 2500, 0.02, 0.05),
    ("Поддержка", 1500, 0.02, 0.05),
)
INVITE_ACCEPTANCE = 0.80
OTHER_GROUPS_CREATED = 1000
MONTHLY_COST = 20_000
SCENARIOS = {
    "основной": {"activity_pp": 4, "funnel_activation": 50, "rel_churn": 0.10, "coverage": (0.30, 0.40, 0.50)},
    "менее благоприятный": {"activity_pp": 0, "funnel_activation": 45, "rel_churn": 0.0, "coverage": (0.0, 0.0, 0.0)},
}
Z_ALPHA, Z_POWER = 1.959964, 0.841621


def n_per_arm(control_rate, signal_rate):
    pooled = (control_rate + signal_rate) / 2
    pooled_variance = 2 * pooled * (1 - pooled)
    paired_variance = control_rate * (1 - control_rate) + signal_rate * (1 - signal_rate)
    distance = Z_ALPHA * math.sqrt(pooled_variance) + Z_POWER * math.sqrt(paired_variance)
    return math.ceil((distance / (control_rate - signal_rate)) ** 2)


def extra_months(relative_change, months):
    return sum((1 - CHURN * (1 - relative_change)) ** t - (1 - CHURN) ** t for t in range(1, months + 1))


def rollout_contribution(coverage, relative_change, months):
    """Отдельные когорты номеров, впервые получивших доступ в октябре, ноябре и декабре."""
    covered = [round(START_GROUPS * share * NUMBERS_PER_GROUP) for share in coverage]
    new_numbers = [count - previous for previous, count in zip([0, *covered], covered)]
    paid_months = sum(count * extra_months(relative_change, months - index)
                      for index, count in enumerate(new_numbers))
    first_month = next((index for index, count in enumerate(new_numbers) if count), months)
    return {"new_numbers": new_numbers, "paid_months": round(paid_months, 1),
            "retention_rub": round(paid_months * RATE), "cost_rub": (months - first_month) * MONTHLY_COST}


def acquisition_funnel(scenario, activation):
    rows = []
    for channel, reached, control_rate, rollout_rate in CHANNELS:
        rate = rollout_rate if scenario == "основной" else control_rate
        groups = round(reached * rate)
        control_groups = round(reached * control_rate)
        rows.append({"channel": channel, "reached": reached, "conversion": rate,
                     "control_groups": control_groups, "control_accepted": round(control_groups * INVITE_ACCEPTANCE),
                     "created": groups,
                     "accepted": round(groups * INVITE_ACCEPTANCE), "activated": round(groups * activation / 100)})
    return rows


out = {"pilot": [], "funnel": {}, "forecast": {}, "investment": []}
for base in BASE_RESTRICT:
    for delta in MIN_EFFECTS:
        n = n_per_arm(base, base - delta)
        weeks = {w: math.ceil(2 * n / w) + 1 for w in ELIGIBLE_PER_WEEK}
        out["pilot"].append({"base": base, "mde_pp": delta, "relative": delta / base, "n_per_arm": n, "weeks": weeks})

for name, scenario in SCENARIOS.items():
    funnel = acquisition_funnel(name, scenario["funnel_activation"])
    out["funnel"][name] = funnel
    connected = BASELINE["connected"] + sum(row["accepted"] - row["control_accepted"] for row in funnel)
    quarter_created = OTHER_GROUPS_CREATED + sum(row["created"] for row in funnel)
    quarter_activated = OTHER_GROUPS_CREATED * BASELINE["activation"] / 100 + sum(row["activated"] for row in funnel)
    activation = round(100 * quarter_activated / quarter_created)
    active_share = BASELINE["active"] / BASELINE["connected"] + scenario["activity_pp"] / 100
    rollout = rollout_contribution(scenario["coverage"], scenario["rel_churn"], 3)
    profit = BASELINE["profit"] + (rollout["retention_rub"] - rollout["cost_rub"]) / 1e6
    out["forecast"][name] = {"profit": round(profit, 2), "active": round(connected * active_share),
                             "connected": connected, "owners": BASELINE["owners"], "activation": activation,
                             **rollout, "profit_gap_mln": round(TARGET["profit"] - profit, 2)}

for coverage in ((0.30, 0.30, 0.30), SCENARIOS["основной"]["coverage"]):
    for relative_change in (0.05, 0.10, 0.20):
        rollout = rollout_contribution(coverage, relative_change, 27)
        remaining = (rollout["retention_rub"] - rollout["cost_rub"]) / 1e6
        out["investment"].append({"coverage": coverage[-1], "rel_churn": relative_change,
                                  "covered_numbers": sum(rollout["new_numbers"]),
                                  "max_invest_mln_to_y3": round(max(0, remaining), 2)})

n = n_per_arm(0.12, 0.09)
half_width = 100 * Z_ALPHA * math.sqrt((0.12 * 0.88 + 0.09 * 0.91) / n)
out["ci_half_width_pp"] = round(half_width, 1)
md = ["# Пилот B, воронка, прибыль и вложения", "",
      "Числа брифа [C003–C012]. Сценарии опираются на проверяемые допущения [C020–C023, C030–C036, C042, C044, C045].", "",
      "## Пилот", "",
      "Одна группа — один первый подходящий случай у участника. Исход — ограничение интернета этого участника за 7 дней. "
      "Двусторонний тест с уровнем 5% и мощностью 80% рассчитан для отличия эффекта от нуля [C037, C040].", "",
      "| База | Важное улучшение | Относительно | Групп на ветку | Недель при 75 / 150 / 300 группах в неделю |",
      "|---|---|---|---|---|"]
for row in out["pilot"]:
    weeks = row["weeks"]
    md.append(f"| {row['base']:.0%} | {100 * row['mde_pp']:.0f} п.п. | {row['relative']:.0%} | {row['n_per_arm']} | {weeks[75]} / {weeks[150]} / {weeks[300]} |")
md += ["", f"Основной расчёт для базы 12% и порога 3 п.п. — {n} групп на ветку. "
       f"Половина ширины 95% интервала ≈{half_width:.1f} п.п. [C037, C040].", "",
       "Набор и наблюдение при базе 12% занимают 12–45 недель. Дата решения зависит от фактического набора. "
       "Расчёты для 4 и 5 п.п. показывают чувствительность до запуска [C031, C037].", "",
       "## Воронка привлечения за IV квартал [C042, C043]", ""]
for name, rows in out["funnel"].items():
    md += [f"### {name.capitalize()} ход", "",
           "| Канал первого касания | Уникальный охват | Конверсия в создание | Создано в контроле | Создано | Приглашение принято | Активировано |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        md.append(f"| {row['channel']} | {row['reached']} | {row['conversion']:.1%} | {row['control_groups']} | {row['created']} | {row['accepted']} | {row['activated']} |")
    totals = [sum(row[key] for row in rows) for key in ("reached", "control_groups", "created", "accepted", "activated")]
    md += [f"| Итого | {totals[0]} | — | {totals[1]} | {totals[2]} | {totals[3]} | {totals[4]} |", ""]

md += ["## Прогноз по пяти строкам брифа [C038]", "",
       "| Показатель | Без изменений | Основной | Менее благоприятный | Цель |",
       "|---|---:|---:|---:|---:|"]
labels = {"profit": "Валовая прибыль, млн руб., до вычета расходов пилота",
          "active": "Активные группы за последний месяц", "connected": "Подключённые группы на конец года",
          "owners": "Владельцы нескольких номеров на конец года", "activation": "Активированные за 14 дней, %"}
main = out["forecast"]["основной"]
adverse = out["forecast"]["менее благоприятный"]
out["cost_sensitivity"] = [
    {"monthly_cost_rub": cost, "annual_increment_rub_before_pilot": main["retention_rub"] - 3 * cost}
    for cost in (10_000, 20_000, 30_000)
]
for key, label in labels.items():
    md.append(f"| {label} | {BASELINE[key]} | {main[key]} | {adverse[key]} | {TARGET[key]} |")
md += ["", f"Октябрьская, ноябрьская и декабрьская когорты в основном ходе дают около {main['paid_months']:.0f} доп. оплаченных месяцев. "
       f"Вклад удержания ≈{main['retention_rub']} руб., прямые расходы после расширения — {main['cost_rub']} руб. "
       "Из обоих сценарных прогнозов финансовая команда вычитает подтверждённые расходы пилота [C038, C044, C045].", "",
       "## Предельные вложения до конца третьего года [C039]", "",
       "Помесячная прибыль когорт IV квартала после прямых расходов до конца третьего года, без следующих когорт. "
       "Из предельного бюджета разработки вычитаются расходы пилота [C039, C044, C045].", "",
       "| Охват к декабрю | Снижение оттока охваченных | Охваченные номера | Максимум вложений, млн руб. |",
       "|---|---|---|---|"]
for row in out["investment"]:
    md.append(f"| {row['coverage']:.0%} | {row['rel_churn']:.0%} | {row['covered_numbers']} | {row['max_invest_mln_to_y3']:.2f} |")
md += ["", "По каждой месячной когорте суммируем разницу числа продолжающих оплату номеров между двумя сценариями, умножаем на ставку брифа, "
       "вычитаем прямые расходы. Для срока окупаемости финансовая команда сравнивает накопленный результат на конец каждого квартала с вложениями к этому сроку [C039, C045]."]

(HERE / "strategy_calc.md").write_text("\n".join(md) + "\n", encoding="utf-8")
(HERE / "strategy_calc.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("\n".join(md))
