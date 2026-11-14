# inputs: economics_assumptions.yaml
# outputs: economics_thresholds.csv, economics_thresholds.md, economics_findings.json
"""Пороги безубыточности вариантов «семейной защиты» без внутренних данных компании (C001). Версия 2.

Изменения после красной команды (research/quality/red-team-options.md):
- потеря от перевода платящей семьи в бесплатные считается на срок жизни ПОДПИСКИ (1/c_sub), а не домохозяйства;
- линии домохозяйства — только номера МегаФона (защита работает только в сети, C050);
- добавлен порог для варианта C (смесь: доля d платящих уходит на бесплатную базу, k новых семей на одну платящую);
- полный разрез таблицы в .md, чтобы заявленные диапазоны можно было сверить.
Модель: LTV домохозяйства = R·m/c. Снижение оттока с c0 до c1 = c0·(1−r) даёт прирост R·m·(1/c1 − 1/c0).
Ищем минимальное относительное снижение r, при котором прирост покрывает потери/затраты.
Не учтено (ограничения): привлечение новых абонентов, переход семей к конкурентам, NPS/доверие, затраты на
разработку и юристов, страховая премия; самоотбор (подключают и так лояльные) — эффект доказывается только A/B.
"""
import csv
import itertools
import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
A = yaml.safe_load((HERE / "economics_assumptions.yaml").read_text(encoding="utf-8"))
P, MS, CM = A["family_price_rub"], A["subscription_margin"], A["marginal_cost_per_family_rub"]


def gain(R, m, c0, r):
    """Прирост LTV домохозяйства при относительном снижении оттока r."""
    return R * m * (1 / (c0 * (1 - r)) - 1 / c0)


def solve_r(fn_gain, fn_loss):
    """Минимальное r (0..0.95), при котором fn_gain(r) >= fn_loss(r)."""
    for i in range(1, 951):
        r = i / 1000
        if fn_gain(r) >= fn_loss(r):
            return r
    return None


rows = []
for arpu, lines, m, c0, csub in itertools.product(A["arpu_rub"], A["lines_per_household"], A["margin"],
                                                   A["monthly_churn"], A["subscription_churn"]):
    R = arpu * lines
    # (а) B: платящая семья становится бесплатной — теряем маржу подписки на срок её жизни
    r_b = solve_r(lambda r: gain(R, m, c0, r), lambda r: P * MS / csub + CM / (c0 * (1 - r)))
    # (б) расширение: неплатящая семья получает бесплатную защиту — несём только предельные затраты
    r_e = solve_r(lambda r: gain(R, m, c0, r), lambda r: CM / (c0 * (1 - r)))
    rows.append({"arpu_rub": arpu, "lines": lines, "margin": m, "churn_month_pct": round(c0 * 100, 2),
                 "sub_churn_month_pct": round(csub * 100, 1),
                 "B_need_rel_pct": round(r_b * 100, 1) if r_b else None,
                 "expand_need_rel_pct": round(r_e * 100, 1) if r_e else None})

# (в) C: на одну платящую семью — d уходят в бесплатную базу (теряем подписку), k новых бесплатных семей
c_rows = []
b = A["base"]
for d, k in itertools.product(A["c_downgrade_share"], A["c_new_free_per_payer"]):
    R = b["arpu_rub"] * b["lines_per_household"]
    m, c0, csub = b["margin"], b["monthly_churn"], b["subscription_churn"]
    protected = d + k  # сколько домохозяйств получают бесплатную базу на 1 платящую
    r_c = solve_r(lambda r: protected * gain(R, m, c0, r),
                  lambda r: d * P * MS / csub + protected * CM / (c0 * (1 - r)))
    c_rows.append({"downgrade_share": d, "new_free_per_payer": k, "C_need_rel_pct": round(r_c * 100, 1) if r_c else None})

with open(HERE / "economics_thresholds.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)


def pick(rows_, **kw):
    return [r for r in rows_ if all(abs(r[k] - v) < 1e-9 if isinstance(v, float) else r[k] == v for k, v in kw.items())][0]


base_row = pick(rows, arpu_rub=b["arpu_rub"], lines=b["lines_per_household"], margin=b["margin"],
                churn_month_pct=round(b["monthly_churn"] * 100, 2), sub_churn_month_pct=round(b["subscription_churn"] * 100, 1)) \
    if any(r["sub_churn_month_pct"] == round(b["subscription_churn"] * 100, 1) for r in rows) else None
B = [r["B_need_rel_pct"] for r in rows if r["B_need_rel_pct"]]
E = [r["expand_need_rel_pct"] for r in rows if r["expand_need_rel_pct"]]
Cn = [r["C_need_rel_pct"] for r in c_rows if r["C_need_rel_pct"]]
c_base = pick(c_rows, downgrade_share=b["c_downgrade_share"], new_free_per_payer=b["c_new_free_per_payer"]) \
    if any(r["downgrade_share"] == b["c_downgrade_share"] and r["new_free_per_payer"] == b["c_new_free_per_payer"] for r in c_rows) else None
res = {
    "version": 2,
    "B_need_rel_reduction_range_pct": [min(B), max(B)],
    "expand_need_rel_reduction_range_pct": [min(E), max(E)],
    "C_need_rel_reduction_range_pct": [min(Cn), max(Cn)],
    "C_grid": c_rows,
    "C_base_case": c_base,
    "reading": (f"B (всем бесплатно): нужно снизить отток домохозяйства на {min(B)}–{max(B)}% относительно. "
                f"Расширение на неплатящих: {min(E)}–{max(E)}%. C (смесь, база: 30% платящих уходят в бесплатное, "
                f"5 новых семей на платящую): {min(Cn)}–{max(Cn)}% по сетке сценариев. Чем больше новых бесплатных семей "
                f"на одну платящую и меньше каннибализация, тем ниже порог C. Пороги зависят от допущений — "
                f"их нужно заменить внутренними данными; эффект на отток доказывается только экспериментом."),
}
(HERE / "economics_findings.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

md = ["# Пороги безубыточности (расчёт по допущениям, версия 2)", "",
      "_Входы — допущения из `economics_assumptions.yaml` (не данные компании, C001). Показано, на сколько процентов "
      "**относительно** должен снизиться месячный отток домохозяйства, чтобы вариант окупился. Ограничения модели — в "
      "шапке скрипта._", "",
      "## Варианты B и «расширение охвата» (отток подписки — сетка 5% и 10% в месяц)", "",
      "| ARPU, ₽ | Линий МегаФона | Маржа | Отток дом./мес, % | Отток подписки/мес, % | B: нужно снизить отток, % | Расширение: нужно снизить отток, % |",
      "|---|---|---|---|---|---|---|"]
for r in rows:
    if r["churn_month_pct"] == 1.5:
        md.append(f"| {r['arpu_rub']} | {r['lines']} | {r['margin']} | {r['churn_month_pct']} | {r['sub_churn_month_pct']} | "
                  f"{r['B_need_rel_pct']} | {r['expand_need_rel_pct']} |")
md += ["", "_Порог «расширения» не зависит от базового оттока домохозяйства (сокращается в формуле); порог B — зависит "
       "(потеря подписки не масштабируется оттоком домохозяйства), поэтому здесь показан отток 1,5%, полная сетка "
       "(1–2,5%) — в `economics_thresholds.csv`._", "",
       "## Вариант C — смесь (база: ARPU 550 ₽, 2 линии, маржа 0,55, отток 1,5%, отток подписки 7%)", "",
       "| Доля платящих, ушедших в бесплатное | Новых бесплатных семей на 1 платящую | C: нужно снизить отток, % |", "|---|---|---|"]
for r in c_rows:
    md.append(f"| {r['downgrade_share']} | {r['new_free_per_payer']} | {r['C_need_rel_pct']} |")
md += ["", "**Как читать:** " + res["reading"]]
(HERE / "economics_thresholds.md").write_text("\n".join(md), encoding="utf-8")
print(json.dumps({k: v for k, v in res.items() if k != "C_grid"}, ensure_ascii=False, indent=1))
