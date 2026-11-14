# inputs: cbr_quarterly.csv
# outputs: cbr_quarterly_summary.csv, cbr_quarterly.png, cbr_quarterly_findings.json
"""Динамика хищений со счетов клиентов банков (Банк России), 2024–2026.

Вопрос DQ2: растёт или сокращается проблема. Проверки качества данных:
- смена методики с III кв. 2024 (6 признаков вместо 3) → сравнения год к году только внутри новой методики;
- IV кварталы и I кв. 2026 не опубликованы отдельно → восстанавливаются вычитанием (помечены derived);
- единицы: млрд руб., номинал (без поправки на инфляцию).
Запуск: python sf.py data run research/data/cbr_quarterly.py
"""
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).parent
df = pd.read_csv(HERE / "cbr_quarterly.csv", dtype={"quarter": str})
v = dict(zip(df.quarter, df.theft_bn_rub))

# 1. Восстановление непубликуемых кварталов (расчёт, а не факт)
v["2024Q4"] = round(27.5 - (v["2024Q1"] + v["2024Q2"] + v["2024Q3"]), 2)
v["2025Q4"] = round(29.3 - (v["2025Q1"] + v["2025Q2"] + v["2025Q3"]), 2)
v["2026Q1"] = round(v["2026Q2"] / (1 - 0.006), 2)
df["theft_bn_rub"] = df.quarter.map(v)

# 2. Сопоставимые сравнения (только новая методика)
new = df[df.methodology == "new_6_signs"].set_index("quarter").theft_bn_rub
res = {
    "q4_2024_derived": v["2024Q4"],
    "q4_2025_derived": v["2025Q4"],
    "q1_2026_derived": v["2026Q1"],
    "h2_2025_vs_h2_2024_pct": round(100 * ((new["2025Q3"] + new["2025Q4"]) / (new["2024Q3"] + new["2024Q4"]) - 1), 1),
    "h1_2026_vs_h1_2025_pct": round(100 * ((new["2026Q1"] + new["2026Q2"]) / (new["2025Q1"] + new["2025Q2"]) - 1), 1),
    "q2_2026_vs_q2_2025_pct": round(100 * (new["2026Q2"] / new["2025Q2"] - 1), 1),
    "range_since_new_method_bn": [float(new.min()), float(new.max())],
    "mean_since_new_method_bn": round(float(new.mean()), 2),
    "annual_2025_vs_2024_pct_reported": round(100 * (29.3 / 27.5 - 1), 1),
    "note": "Годовой рост 2025/2024 (+6,5% по расчёту, ЦБ: +6,4%) несопоставим: I–II кв. 2024 считались по старой методике (3 признака).",
}
pd.DataFrame([{"metric": k, "value": json.dumps(val, ensure_ascii=False)} for k, val in res.items()]).to_csv(
    HERE / "cbr_quarterly_summary.csv", index=False, encoding="utf-8")
(HERE / "cbr_quarterly_findings.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

# 3. График: показатель, единица, период, источник — в подписи
fig, ax = plt.subplots(figsize=(9, 4.2), dpi=130)
colors = ["#9aa3ad" if m == "old_3_signs" else "#00a650" for m in df.methodology]
bars = ax.bar(df.quarter, df.theft_bn_rub, color=colors)
for b, d, val in zip(bars, df.derived, df.theft_bn_rub):
    if d:
        b.set_hatch("///")
        b.set_alpha(0.7)
    ax.text(b.get_x() + b.get_width() / 2, val + 0.15, f"{val:.1f}", ha="center", fontsize=8)
ax.axvline(1.5, color="#731982", ls="--", lw=1)
ax.text(1.55, 9.6, "смена методики ЦБ\n(6 признаков вместо 3)", fontsize=7.5, color="#731982", va="top")
ax.set_ylabel("млрд руб. за квартал (номинал)")
ax.set_ylim(0, 10.5)
ax.set_title("Хищения со счетов клиентов банков, Банк России, 2024–2026", fontsize=10)
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.01, 0.01, "Штриховка — восстановлено вычитанием из годовых итогов. Источники: утверждения C013, C039–C045.",
         fontsize=7, color="#555")
fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(HERE / "cbr_quarterly.png")
print(json.dumps(res, ensure_ascii=False, indent=1))
