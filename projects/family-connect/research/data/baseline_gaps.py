"""Разрывы, охват и граница прибыли по числам брифа организаторов (S001; утверждения C001–C015).
# inputs: (числа брифа — константы ниже, источник S001)
# outputs: baseline_gaps.md, baseline_gaps.json

Все числа брифа учебные. Допущения (A…) вынесены в константы и в реестр утверждений; их диапазоны — не данные кейса.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
# --- числа брифа (S001) ---
ACCESSIBLE_HH, ACCESSIBLE_OWNERS = 100_000, 40_000                     # C002
ACTIVE = {"plan_base": 5000, "est_base": 4000, "no_change": 5000, "target": 8000}      # C004
CONNECTED = {"plan_base": 7500, "est_base": 6500, "no_change": 8000, "target": 12000}  # C005
OWNERS = {"plan_base": 1000, "est_base": 800, "no_change": 1000, "target": 2000}       # C006
ACTIVATION = {"plan_base": 50, "est_base": 42, "no_change": 45, "target": 60}         # C007, %
PROFIT = {"plan_base": 282, "est_base": 275, "no_change": 279, "target": 285}          # C003, млн руб.
RATE = 500                                                                              # C011, руб. за доп. оплаченный месяц номера
GAP_MONTHS = (PROFIT["target"] - PROFIT["no_change"]) * 1_000_000 / RATE               # C012 → 12 000

# --- допущения (не данные кейса; диапазоны для проверки) ---
NUMBERS_PER_GROUP = (2.5, 3.5)     # A1: номеров в подключённой семейной группе
MONTHLY_CHURN = (0.010, 0.020)     # A2: месячный отток номера при обычном обслуживании
LIVE_MONTHS = 6                    # A3: месяцев работы услуги в плановом году (пилот во II кв., запуск с III кв.)
REL_REDUCTION = (0.05, 0.10, 0.20) # A4: относительное снижение месячного оттока у охваченных номеров


def sp(n):
    return f"{n:,}".replace(",", " ")


def share(a, c):
    return 100 * a / c


out = {"active_share_pct": {k: round(share(ACTIVE[k], CONNECTED[k]), 1) for k in ACTIVE}}
# Разложение отставания активных групп в базовом году (оценка против плана): эффект числа групп и эффект доли активных,
# усреднение двух порядков (не зависит от порядка разложения).
dA = ACTIVE["est_base"] - ACTIVE["plan_base"]
s_plan, s_est = ACTIVE["plan_base"] / CONNECTED["plan_base"], ACTIVE["est_base"] / CONNECTED["est_base"]
dC = CONNECTED["est_base"] - CONNECTED["plan_base"]
vol = 0.5 * (dC * s_plan + dC * s_est)
mix = 0.5 * (CONNECTED["plan_base"] * (s_est - s_plan) + CONNECTED["est_base"] * (s_est - s_plan))
out["active_gap_base"] = {"total": dA, "fewer_connected": round(vol), "lower_active_share": round(mix)}
out["penetration_pct"] = {
    "groups_est_base": round(share(CONNECTED["est_base"], ACCESSIBLE_HH), 1), "groups_target": round(share(CONNECTED["target"], ACCESSIBLE_HH), 1),
    "owners_est_base": round(share(OWNERS["est_base"], ACCESSIBLE_OWNERS), 1), "owners_no_change": round(share(OWNERS["no_change"], ACCESSIBLE_OWNERS), 1),
    "owners_target": round(share(OWNERS["target"], ACCESSIBLE_OWNERS), 1)}
out["target_vs_no_change"] = {"connected": CONNECTED["target"] - CONNECTED["no_change"], "active": ACTIVE["target"] - ACTIVE["no_change"],
                              "owners": OWNERS["target"] - OWNERS["no_change"], "activation_pp": ACTIVATION["target"] - ACTIVATION["no_change"],
                              "profit_mln": PROFIT["target"] - PROFIT["no_change"], "net_connected_vs_start": CONNECTED["target"] - CONNECTED["est_base"]}
out["gap_extra_paid_months"] = int(GAP_MONTHS)

# Граница прибыли через удержание: дополнительные оплаченные месяцы на один охваченный номер за LIVE_MONTHS месяцев
def extra_months_per_number(p, r, months=LIVE_MONTHS):
    return sum((1 - p * (1 - r)) ** t - (1 - p) ** t for t in range(1, months + 1))


grid = []
for p in MONTHLY_CHURN:
    for r in REL_REDUCTION:
        per = extra_months_per_number(p, r)
        grid.append({"monthly_churn": p, "rel_reduction": r, "extra_months_per_number": round(per, 4),
                     "numbers_needed": round(GAP_MONTHS / per)})
numbers_target = [round(CONNECTED["target"] * n) for n in NUMBERS_PER_GROUP]
out["retention_boundary"] = {"live_months": LIVE_MONTHS, "numbers_in_target_groups": numbers_target, "grid": grid}

md = ["# Разрывы, охват и граница прибыли (по числам брифа)", "",
      "_Числа брифа — S001 (C001–C015); допущения A1–A4 — диапазоны для проверки, не данные кейса._", "",
      "## Доля активных среди подключённых групп",
      f"- План базового года: {out['active_share_pct']['plan_base']}%; оценка: {out['active_share_pct']['est_base']}%; "
      f"без изменений в плановом году: {out['active_share_pct']['no_change']}%; цель: {out['active_share_pct']['target']}%.", "",
      "## Почему активных групп меньше плана (базовый год: 4 000 против 5 000)",
      f"- Меньше подключённых групп (6 500 вместо 7 500): {out['active_gap_base']['fewer_connected']} групп.",
      f"- Ниже доля активных (61,5% вместо 66,7%): {out['active_gap_base']['lower_active_share']} групп.",
      "- Разложение усреднено по двум порядкам; примерно две трети отставания — от числа групп, треть — от активности.", "",
      "## Охват доступной базы",
      f"- Семейные группы: {out['penetration_pct']['groups_est_base']}% от 100 тыс. домохозяйств сейчас, цель — {out['penetration_pct']['groups_target']}%.",
      f"- Владельцы нескольких номеров: {out['penetration_pct']['owners_est_base']}% от 40 тыс. сейчас, без изменений — "
      f"{out['penetration_pct']['owners_no_change']}%, цель — {out['penetration_pct']['owners_target']}%.", "",
      "## Цели против «без изменений»",
      f"- Подключённых групп +{out['target_vs_no_change']['connected']} (чистый прирост к началу года +{out['target_vs_no_change']['net_connected_vs_start']}); "
      f"активных +{out['target_vs_no_change']['active']}; владельцев +{out['target_vs_no_change']['owners']}; активация +{out['target_vs_no_change']['activation_pp']} п.п.; "
      f"прибыль +{out['target_vs_no_change']['profit_mln']} млн руб. = {out['gap_extra_paid_months']} доп. оплаченных месяцев по {RATE} руб.", "",
      f"## Граница прибыли через удержание (услуга работает {LIVE_MONTHS} мес. планового года)",
      f"В целевых 12 000 группах — {sp(numbers_target[0])}–{sp(numbers_target[1])} номеров (A1). Сколько охваченных номеров нужно, чтобы удержание дало "
      f"{sp(out['gap_extra_paid_months'])} доп. месяцев:", "",
      "| Месячный отток номера (A2) | Снижение оттока у охваченных (A4) | Доп. месяцев на номер | Нужно охваченных номеров |", "|---|---|---|---|"]
for g in grid:
    md.append(f"| {100 * g['monthly_churn']:.1f}% | {100 * g['rel_reduction']:.0f}% | {g['extra_months_per_number']:.3f} | {sp(g['numbers_needed'])} |")
md += ["", "**Вывод расчёта:** даже при снижении оттока на 20% за полгода нужно в несколько раз больше охваченных номеров, чем есть во всех "
       "целевых группах, — удержание само по себе не закрывает 6 млн руб. в плановом году. Его эффект копится в следующих годах; для планового "
       "года нужны другие вклады (платная опция, экономия поддержки) или честно названный разрыв."]
(HERE / "baseline_gaps.md").write_text("\n".join(md) + "\n", encoding="utf-8")
(HERE / "baseline_gaps.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n".join(md))
