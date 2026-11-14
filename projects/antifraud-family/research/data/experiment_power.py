# inputs: economics_assumptions.yaml
# outputs: experiment_power.md, experiment_power.json
"""Размер выборки для эксперимента «бесплатная семейная база → отток домохозяйства».

Двухвыборочный тест долей (α=0,05 двусторонний, мощность 80%), окно наблюдения — квартал.
Квартальный отток p0 = 1 − (1 − c_month)^3. Эффект — относительное снижение оттока r: p1 = p0·(1 − r).
n на группу = (z_α/2 + z_β)² · [p0(1−p0) + p1(1−p1)] / (p0 − p1)².
"""
import json
import math
from pathlib import Path

import yaml

HERE = Path(__file__).parent
A = yaml.safe_load((HERE / "economics_assumptions.yaml").read_text(encoding="utf-8"))
Z = 1.959964 + 0.841621
c_month = A["base"]["monthly_churn"]
p0 = 1 - (1 - c_month) ** 3
out = []
for r in [0.03, 0.05, 0.08, 0.10, 0.15, 0.25]:
    p1 = p0 * (1 - r)
    n = Z ** 2 * (p0 * (1 - p0) + p1 * (1 - p1)) / (p0 - p1) ** 2
    out.append({"relative_reduction_pct": round(r * 100), "quarterly_churn_control_pct": round(p0 * 100, 2),
                "quarterly_churn_test_pct": round(p1 * 100, 2), "n_per_group": int(math.ceil(n))})
res = {"base_monthly_churn": c_month, "window": "квартал", "alpha": 0.05, "power": 0.8, "grid": out}
(HERE / "experiment_power.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
md = ["# Размер выборки эксперимента (отток домохозяйства за квартал)", "",
      f"_Базовый месячный отток {c_month * 100:.1f}% (допущение C056) → квартальный {p0 * 100:.2f}%. α=0,05, мощность 80%._", "",
      "| Снижение оттока (отн.), % | Отток контроль, % | Отток тест, % | Домохозяйств на группу |", "|---|---|---|---|"]
md += [f"| {o['relative_reduction_pct']} | {o['quarterly_churn_control_pct']} | {o['quarterly_churn_test_pct']} | {o['n_per_group']:,} |".replace(",", " ")
       for o in out]
md += ["", "**Как читать:** эффекты порядка порогов C и «расширения» (≈3–5%) требуют сотен тысяч домохозяйств на группу — "
       "проверять их напрямую дорого; эффект ≈8–10% (порог B при части допущений) различим на десятках тысяч. "
       "Поэтому в плане проверки: прямое измерение оттока на крупной выборке + опережающие индикаторы."]
(HERE / "experiment_power.md").write_text("\n".join(md), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
