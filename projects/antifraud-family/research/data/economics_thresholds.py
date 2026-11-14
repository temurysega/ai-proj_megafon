# inputs: economics_assumptions.yaml
# outputs: economics_thresholds.csv, economics_thresholds.md, economics_findings.json
"""Пороги безубыточности вариантов «семейной защиты» без внутренних данных компании (C001).

Идея: вместо выдуманной выручки — «что должно быть правдой». Для каждого сочетания допущений
считаем, на сколько процентных пунктов в месяц бесплатная семейная защита должна снизить отток
домохозяйства, чтобы окупить:
  (а) потерю 249 ₽/мес с семьи, которая сейчас платит (каннибализация, вариант B),
  (б) предельные затраты на защиту семьи, которая не платила (расширение охвата, варианты B/C).
Модель: LTV домохозяйства = выручка_дом × маржа / отток. Снижение оттока с c0 до c1 даёт
ΔLTV = R·m·(1/c1 − 1/c0). Ищем минимальное Δc = c0 − c1, при котором ΔLTV ≥ потерянная маржа
подписки за срок жизни (R_sub·m_sub/c1) — для (а), или ≥ предельные затраты за срок жизни — для (б).
Все входы — допущения (assumption) с диапазонами; результат — расчёт (estimate), не прогноз.
"""
import itertools
import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
A = yaml.safe_load((HERE / "economics_assumptions.yaml").read_text(encoding="utf-8"))


def min_delta_c(R_h, m, c0, cost_month, m_cost=1.0, step=0.00001):
    """Минимальное снижение месячного оттока (в долях), окупающее cost_month×m_cost в месяц за срок жизни."""
    c1 = c0
    while c1 > 0.0005:
        c1 -= step
        gain = R_h * m * (1 / c1 - 1 / c0)
        loss = cost_month * m_cost / c1
        if gain >= loss:
            return c0 - c1
    return None


rows = []
for arpu, lines, m, c0 in itertools.product(A["arpu_rub"], A["lines_per_household"], A["margin"], A["monthly_churn"]):
    R_h = arpu * lines
    dc_cannibal = min_delta_c(R_h, m, c0, A["family_price_rub"], A["subscription_margin"])
    dc_expand = min_delta_c(R_h, m, c0, A["marginal_cost_per_family_rub"])
    rows.append({"arpu_rub": arpu, "lines": lines, "margin": m, "churn_month_pct": round(c0 * 100, 2),
                 "household_revenue_rub": R_h,
                 "need_dc_pp_cannibal": round(dc_cannibal * 100, 3) if dc_cannibal else None,
                 "need_rel_cannibal_pct": round(100 * dc_cannibal / c0, 1) if dc_cannibal else None,
                 "need_dc_pp_expand": round(dc_expand * 100, 3) if dc_expand else None,
                 "need_rel_expand_pct": round(100 * dc_expand / c0, 1) if dc_expand else None})

import csv  # noqa: E402

with open(HERE / "economics_thresholds.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

base = [r for r in rows if r["arpu_rub"] == A["base"]["arpu_rub"] and r["lines"] == A["base"]["lines_per_household"]
        and r["margin"] == A["base"]["margin"] and abs(r["churn_month_pct"] - A["base"]["monthly_churn"] * 100) < 1e-9][0]
cann = [r["need_rel_cannibal_pct"] for r in rows if r["need_rel_cannibal_pct"] is not None]
expd = [r["need_rel_expand_pct"] for r in rows if r["need_rel_expand_pct"] is not None]
res = {
    "base_case": base,
    "cannibal_rel_reduction_range_pct": [min(cann), max(cann)],
    "expand_rel_reduction_range_pct": [min(expd), max(expd)],
    "reading": ("Перевод платящей семьи на бесплатную защиту окупается, только если отток её домохозяйства падает "
                "на {0}–{1}% относительно (в базовом сценарии {2}%). Защита семьи, которая не платила, окупается уже "
                "при снижении оттока на {3}–{4}% (базовый {5}%). Вывод: бесплатное расширение охвата дёшево, "
                "каннибализация платящих — дорого; это аргумент за модель «бесплатная семейная база + платная "
                "отдельная ценность», а не за полную бесплатность.").format(
        min(cann), max(cann), base["need_rel_cannibal_pct"], min(expd), max(expd), base["need_rel_expand_pct"]),
}
(HERE / "economics_findings.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
md = ["# Пороги безубыточности (расчёт по допущениям)", "",
      "_Входы — допущения из `economics_assumptions.yaml` (не данные компании). Требуемое снижение месячного оттока "
      "домохозяйства: абсолютное (п. п.) и относительное (%)._", "",
      "| ARPU, ₽ | Линий | Маржа | Отток/мес, % | Δ отток для окупаемости 249 ₽ (п.п. / %) | Δ отток для окупаемости затрат на неплатящую семью (п.п. / %) |",
      "|---|---|---|---|---|---|"]
for r in rows:
    if r["lines"] == A["base"]["lines_per_household"] and r["margin"] == A["base"]["margin"]:
        md.append(f"| {r['arpu_rub']} | {r['lines']} | {r['margin']} | {r['churn_month_pct']} | "
                  f"{r['need_dc_pp_cannibal']} / {r['need_rel_cannibal_pct']}% | {r['need_dc_pp_expand']} / {r['need_rel_expand_pct']}% |")
md += ["", "**Как читать:** " + res["reading"]]
(HERE / "economics_thresholds.md").write_text("\n".join(md), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
