# inputs: economics_assumptions.yaml
# outputs: experiment_design.md, experiment_design.json
"""Дизайн эксперимента с учётом доли принявших предложение (uptake) — версия 2 после красной команды стратегии.

Рандомизируется ПРЕДЛОЖЕНИЕ (encouragement design): тесту предлагают бесплатную семейную защиту, контролю — нет.
Анализ ITT разбавляет эффект: ITT-эффект = uptake × эффект на защищённое домохозяйство (CACE).
Нужный размер группы растёт примерно как 1/uptake². Затраты несут только принявшие предложение.
Квартальный отток p0 = 1 − (1 − c_month)^3; α = 0,05 (двусторонний), мощность 80%.
"""
import json
import math
from pathlib import Path

import yaml

HERE = Path(__file__).parent
A = yaml.safe_load((HERE / "economics_assumptions.yaml").read_text(encoding="utf-8"))
Z = 1.959964 + 0.841621
c = A["base"]["monthly_churn"]
p0 = 1 - (1 - c) ** 3
COST = A["marginal_cost_per_family_rub"]


def n_per_group(itt_rel):
    p1 = p0 * (1 - itt_rel)
    return math.ceil(Z ** 2 * (p0 * (1 - p0) + p1 * (1 - p1)) / (p0 - p1) ** 2)


rows = []
for u in (0.1, 0.2, 0.5):
    for r in (0.04, 0.08, 0.15, 0.25):
        n = n_per_group(u * r)
        rows.append({"uptake_pct": int(u * 100), "cace_effect_pct": int(r * 100), "itt_effect_pct": round(u * r * 100, 1),
                     "n_per_group": n, "direct_cost_mln_rub": round(n * u * COST * 3 / 1e6, 2)})
def group_size_at_half_uptake(effect_pct):
    row = next(row for row in rows if row["uptake_pct"] == 50 and row["cace_effect_pct"] == effect_pct)
    return f"{row['n_per_group']:,}".replace(",", " ")


res = {
    "quarterly_churn_pct": round(p0 * 100, 2),
    "rows": rows,
    "reading": (
        f"При принятии 50% эффект 4% требует {group_size_at_half_uptake(4)} домохозяйств на группу. "
        f"Для эффекта 15% нужно {group_size_at_half_uptake(15)} на группу. "
        "Если интервал эффекта пересекает порог окупаемости C, сохраняем A+. "
        "Решение для всей базы требует отдельной оценки удержания и потери маржи у платящих."
    ),
}
(HERE / "experiment_design.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
md = ["# Дизайн эксперимента с учётом доли принявших (v2)", "",
      f"_Квартальный отток контроля {p0 * 100:.2f}% (допущение C056). α=0,05, мощность 80%. Затраты — только на принявших "
      f"({COST} ₽/мес × 3 мес.)._", "",
      "| Доля принявших, % | Эффект на защищённое домохозяйство, % | ITT-эффект, % | Домохозяйств на группу | Прямые затраты, млн ₽ |",
      "|---|---|---|---|---|"]
md += [f"| {x['uptake_pct']} | {x['cace_effect_pct']} | {x['itt_effect_pct']} | {x['n_per_group']:,} | {x['direct_cost_mln_rub']} |".replace(",", " ")
       for x in rows]
md += ["", "**Как читать:** " + res["reading"]]
(HERE / "experiment_design.md").write_text("\n".join(md), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
