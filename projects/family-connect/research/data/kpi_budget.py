"""Условная цена устранения годовых разрывов после варианта B."""

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET = {"connected": 12_000, "active": 8_000, "owners": 2_000, "activation": 0.60}
BASE_PROFIT_RUB = 279_000_000
TARGET_PROFIT_RUB = 285_000_000
RUB_PER_PAID_MONTH = 500
FAMILY_REACHABLE = 100_000
OWNER_REACHABLE = 40_000
OTHER_Q4_CREATED, OTHER_Q4_ACTIVATED = 1_000, 450
INVITE_ACCEPTANCE = 0.80
ROLLOUT_WEEKS = 13


@dataclass(frozen=True)
class BudgetInputs:
    family_incremental_conversion: float
    family_survival_to_december: float
    activation_without_changes: float
    new_group_december_activity: float
    existing_group_activity_lift: float
    owner_incremental_conversion: float
    cost_per_family_reached: int
    cost_per_owner_reached: int
    cost_per_created_group: int
    cost_per_existing_group_reached: int
    cost_per_person_month: int
    family_person_months: float
    onboarding_person_months: float
    activity_person_months: float
    owner_person_months: float


SCENARIOS = {
    "высокий отклик": BudgetInputs(
        family_incremental_conversion=0.05,
        family_survival_to_december=0.98,
        activation_without_changes=0.55,
        new_group_december_activity=0.665,
        existing_group_activity_lift=0.12,
        owner_incremental_conversion=0.06,
        cost_per_family_reached=10,
        cost_per_owner_reached=10,
        cost_per_created_group=5,
        cost_per_existing_group_reached=5,
        cost_per_person_month=200_000,
        family_person_months=1.5,
        onboarding_person_months=2,
        activity_person_months=0.5,
        owner_person_months=2,
    ),
    "опорный": BudgetInputs(
        family_incremental_conversion=300 / 9_000,
        family_survival_to_december=0.95,
        activation_without_changes=0.50,
        new_group_december_activity=0.625,
        existing_group_activity_lift=0.08,
        owner_incremental_conversion=0.04,
        cost_per_family_reached=15,
        cost_per_owner_reached=15,
        cost_per_created_group=10,
        cost_per_existing_group_reached=10,
        cost_per_person_month=275_000,
        family_person_months=2,
        onboarding_person_months=3,
        activity_person_months=1,
        owner_person_months=2.5,
    ),
    "низкий отклик": BudgetInputs(
        family_incremental_conversion=0.02,
        family_survival_to_december=0.90,
        activation_without_changes=0.45,
        new_group_december_activity=0.55,
        existing_group_activity_lift=0.04,
        owner_incremental_conversion=0.02,
        cost_per_family_reached=25,
        cost_per_owner_reached=25,
        cost_per_created_group=20,
        cost_per_existing_group_reached=20,
        cost_per_person_month=350_000,
        family_person_months=3,
        onboarding_person_months=4,
        activity_person_months=1.5,
        owner_person_months=3,
    ),
}


def cost(volume, per_unit, person_months, cost_per_person_month):
    return {
        "direct_rub": volume * per_unit,
        "people_rub": round(person_months * cost_per_person_month),
        "person_months": person_months,
    }


def budget_case(forecast, funnel, assumptions):
    a = assumptions
    net_families = TARGET["connected"] - forecast["connected"]
    net_owners = TARGET["owners"] - forecast["owners"]
    prior_family_reach = sum(row["reached"] for row in funnel)
    family_reach_limit = FAMILY_REACHABLE - forecast["connected"] - prior_family_reach
    owner_reach_limit = OWNER_REACHABLE - forecast["owners"]
    family_reach = math.ceil(net_families / a.family_incremental_conversion)
    owner_reach = math.ceil(net_owners / a.owner_incremental_conversion)

    created = math.ceil(net_families / (INVITE_ACCEPTANCE * a.family_survival_to_december))
    activation_base = OTHER_Q4_ACTIVATED + sum(row["activated"] for row in funnel)
    q4_created = OTHER_Q4_CREATED + sum(row["created"] for row in funnel) + created
    activated_without_onboarding = activation_base + math.floor(created * a.activation_without_changes)
    extra_activations = math.ceil(q4_created * TARGET["activation"]) - activated_without_onboarding

    active_from_new = math.floor(net_families * a.new_group_december_activity)
    active_gap = TARGET["active"] - forecast["active"]
    extra_active = max(0, active_gap - active_from_new)
    audience_existing = forecast["connected"] - forecast["active"]
    activity_reach = math.ceil(extra_active / a.existing_group_activity_lift)

    work = {
        "connected": cost(family_reach, a.cost_per_family_reached, a.family_person_months, a.cost_per_person_month),
        "activation": cost(q4_created, a.cost_per_created_group, a.onboarding_person_months, a.cost_per_person_month),
        "active": cost(activity_reach, a.cost_per_existing_group_reached, a.activity_person_months, a.cost_per_person_month),
        "owners": cost(owner_reach, a.cost_per_owner_reached, a.owner_person_months, a.cost_per_person_month),
    }
    direct = sum(row["direct_rub"] for row in work.values())
    people = sum(row["people_rub"] for row in work.values())
    fits_available_audiences = (
        family_reach <= family_reach_limit
        and activity_reach <= audience_existing
        and owner_reach <= owner_reach_limit
    )
    profit_before_pilot = BASE_PROFIT_RUB + forecast["retention_rub"] - forecast["cost_rub"]
    profit_shortfall = TARGET_PROFIT_RUB - profit_before_pilot
    # Мощность финансового сценария при одной дополнительной причинной линии на подключение.
    # Если подключения равномерны в октябре–декабре, остаются в среднем два оплачиваемых месяца.
    illustrative_paid_months = 2 * (net_families + net_owners)

    return {
        "connected": {
            "gap": net_families,
            "new_groups_created_vs_control": created,
            "reach": family_reach,
            "unique_contacts_per_week": math.ceil(family_reach / ROLLOUT_WEEKS),
            "reach_limit_before_actual_targeting": family_reach_limit,
            "minimum_incremental_conversion_at_limit": net_families / family_reach_limit,
        },
        "activation": {
            "created_q4": q4_created,
            "activated_without_onboarding": activated_without_onboarding,
            "extra_first_actions_needed": extra_activations,
            "incremental_lift_needed": extra_activations / q4_created,
        },
        "active": {
            "gap": active_gap,
            "net_active_from_new_groups": active_from_new,
            "extra_active_needed_among_existing": extra_active,
            "reach": activity_reach,
            "reach_limit_before_deduplication": audience_existing,
        },
        "owners": {
            "gap": net_owners,
            "reach": owner_reach,
            "reach_limit_before_actual_targeting": owner_reach_limit,
            "minimum_incremental_conversion_at_limit": net_owners / owner_reach_limit,
        },
        "work": work,
        "direct_rub": direct,
        "people_rub": people,
        "person_months": sum(row["person_months"] for row in work.values()),
        "package_budget_rub": direct + people,
        "package_budget_using_full_remaining_family_reach_rub": (
            direct + people + (family_reach_limit - family_reach) * a.cost_per_family_reached
            if fits_available_audiences else None
        ),
        "reach_passes_upper_bound_check": fits_available_audiences,
        "finance": {
            "profit_shortfall_before_pilot_rub": profit_shortfall,
            "gross_contribution_to_hit_target_before_pilot_rub": profit_shortfall + direct,
            "gross_contribution_to_hit_target_and_repay_people_before_pilot_rub": profit_shortfall + direct + people,
            "paid_months_to_hit_target_before_pilot": math.ceil((profit_shortfall + direct) / RUB_PER_PAID_MONTH),
            "one_causal_paid_line_per_new_connection_example_paid_months": illustrative_paid_months,
            "one_causal_paid_line_per_new_connection_example_rub": illustrative_paid_months * RUB_PER_PAID_MONTH,
            "still_needed_in_one_line_example_before_pilot_rub": profit_shortfall + direct - illustrative_paid_months * RUB_PER_PAID_MONTH,
        },
    }


def integer(number):
    return f"{number:,}".replace(",", " ")


def decimal(number, digits=1):
    return f"{number:.{digits}f}".replace(".", ",")


def millions(rubles):
    return decimal(rubles / 1_000_000, 2)


def render(cases, scenarios):
    lines = [
        "# Условный бюджет на сокращение годовых разрывов",
        "",
        "Для пересчёта запустите `python projects/family-connect/research/data/kpi_budget.py`. На входе `strategy_calc.json` с прогнозами B, цели и базы брифа [C002–C008, C011, C038, C043].",
        "",
        "Допущения для проверки чувствительности [C052, C053]. Финансовая команда и операционный пилот должны подтвердить ставки и отклик. Опорный семейный отклик взят из исходного сценария B. Крайние значения показывают результат при более низком и более высоком отклике. Привлечение семей, улучшение приглашения, помощь существующим группам и запуск для владельцев относятся к дополнительному пакету сверх B.",
        "",
        "| Параметр | Высокий отклик | Опорный | Низкий отклик |",
        "|---|---:|---:|---:|",
    ]
    for label, values in (
        ("Прирост доли подключённых семей после контакта к контролю", [f"{decimal(a.family_incremental_conversion * 100, 2)}%" for a in scenarios.values()]),
        ("Новые семьи остаются подключёнными к декабрю", [f"{decimal(a.family_survival_to_december * 100, 0)}%" for a in scenarios.values()]),
        ("Активация дополнительных созданных групп без доработки приглашений", [f"{decimal(a.activation_without_changes * 100, 0)}%" for a in scenarios.values()]),
        ("Доля дополнительных подключённых групп, активных в декабре", [f"{decimal(a.new_group_december_activity * 100)}%" for a in scenarios.values()]),
        ("Прирост декабрьской активности неактивных групп после контакта", [f"{decimal(a.existing_group_activity_lift * 100, 0)} п.п." for a in scenarios.values()]),
        ("Прирост доли владельцев с двумя объединёнными номерами после контакта к контролю", [f"{decimal(a.owner_incremental_conversion * 100, 0)}%" for a in scenarios.values()]),
        ("Прямые расходы на один контакт с семьёй / владельцем, руб.", [f"{a.cost_per_family_reached} / {a.cost_per_owner_reached}" for a in scenarios.values()]),
        ("Прямые расходы на группу в приглашениях / контакт с неактивной группой, руб.", [f"{a.cost_per_created_group} / {a.cost_per_existing_group_reached}" for a in scenarios.values()]),
        ("Полная ставка человеко-месяца, руб.", [integer(a.cost_per_person_month) for a in scenarios.values()]),
        ("Человеко-месяцы на семейное привлечение / приглашения / активность / владельцев", [" / ".join(decimal(v) for v in (a.family_person_months, a.onboarding_person_months, a.activity_person_months, a.owner_person_months)) for a in scenarios.values()]),
    ):
        lines.append(f"| {label} | {' | '.join(values)} |")

    lines += [
        "",
        "Для новых семей используем 80% принятия приглашений, как в исходной воронке [C042]. Ставка человеко-месяца включает труд настройки, разработки, тестирования и анализа. Прямые расходы покрывают дополнительные показы, сообщения и сопровождение. Расходы, уже учтённые в B и пилоте B, исключаем из сметы пакета.",
        "",
        "Продажи и поддержка присваивают семье первое касание по идентификатору домохозяйства. Остаток рынка вычисляем после вычитания подключённых и ранее охваченных из воронки B. Если эти две группы пересекаются, такое вычитание уменьшает расчётную базу. Перед закупкой нужно снять пересечение и проверить пригодность тарифов и достижимый квартальный охват. Владельцы нескольких номеров идут отдельной аудиторией с исключением совпадений с семейным рынком [C002].",
        "",
        "Разрыв по активности считаем после учёта новых групп. Для остатка бюджетуем контакт с ранее подключёнными неактивными группами, у которых измеряем прирост к контролю. Он не может начисляться на группы, уже учтённые в декабрьской активности. Если первое действие из воронки активации уже выполнило декабрьский критерий, оно считается в обоих показателях по их определениям [C008], а отдельный контакт с такой группой не закупаем. Показатели активации считаем по всем созданным в IV квартале группам после выдержки 14 дней для последней когорты.",
        "",
        "Для отдельной сметы числитель активации до доработки равен исходным активациям плюс активации дополнительных групп при обычном пути. Знаменатель включает исходные и дополнительные создания. Дополнительные создания считаем из числа недостающих декабрьских подключений, принятий приглашения и сохранения группы к декабрю. Приросты и бюджеты ниже относятся к разнице с прогнозом B, поэтому подключение, которое произошло бы без пакета, из эффекта кампании исключаем.",
    ]
    for forecast_name, budget_cases in cases.items():
        lines += [
            "",
            f"## Прогноз B — {forecast_name}",
            "",
            "| Отклик и расходы | Семейные показы / расчётный остаток базы | Первые действия сверх обычного пути / создано групп в IV квартале | Активность новых + нужный прирост прежних | Контакты с прежними / верхняя граница | Показы владельцам / остаток базы | Прямые расходы, млн руб. | Труд, млн руб. | Сумма, млн руб. |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for scenario, case in budget_cases.items():
            family, activation, active, owners = (case[key] for key in ("connected", "activation", "active", "owners"))
            lines.append(
                f"| {scenario} | {integer(family['reach'])} / {integer(family['reach_limit_before_actual_targeting'])} "
                f"| {integer(activation['extra_first_actions_needed'])} / {integer(activation['created_q4'])} "
                f"| {integer(active['net_active_from_new_groups'])} + {integer(active['extra_active_needed_among_existing'])} "
                f"| {integer(active['reach'])} / {integer(active['reach_limit_before_deduplication'])} "
                f"| {integer(owners['reach'])} / {integer(owners['reach_limit_before_actual_targeting'])} "
                f"| {millions(case['direct_rub'])} | {millions(case['people_rub'])} | {millions(case['package_budget_rub'])} |"
            )
        lines += [
            "",
            "| Отклик и расходы | Семейное привлечение, млн руб. | Приглашения и активация, млн руб. | Декабрьская активность, млн руб. | Владельцы, млн руб. | Проверка доступной базы |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for scenario, case in budget_cases.items():
            row = [millions(work["direct_rub"] + work["people_rub"]) for work in case["work"].values()]
            eligible = "Объём помещается в расчётную базу. Проверить фактическую доступность" if case["reach_passes_upper_bound_check"] else "Нужен больший отклик, охват или срок"
            lines.append(f"| {scenario} | {' | '.join(row)} | {eligible} |")
        for scenario, case in budget_cases.items():
            if case["reach_passes_upper_bound_check"]:
                family = case["connected"]
                lines += [
                    "",
                    f"Сценарий «{scenario}» требует около {integer(family['unique_contacts_per_week'])} уникальных семейных контактов в неделю на протяжении квартала. "
                    f"Если семейный отклик приблизится к {decimal(family['minimum_incremental_conversion_at_limit'] * 100, 2)}%, "
                    f"понадобится весь расчётный семейный остаток. При неизменных остальных ставках и результатах пакет потребует "
                    f"{millions(case['package_budget_rub'])}–{millions(case['package_budget_using_full_remaining_family_reach_rub'])} млн руб. "
                    "При меньшем отклике сначала меняем календарь, предложение или целевой объём.",
                ]

    lines += [
        "",
        "## Граница по прибыли",
        "",
        "Пусть P — прямые расходы пилота B, D — прямые дополнительные расходы пакета, I — стоимость труда пакета. Для валовой прибыли 285 млн руб. требуется новый валовой вклад сверх результата B до пилота на сумму годового разрыва до пилота + P + D. Чтобы одновременно окупить труд пакета к тому же сроку, добавляем I. Труд программы показан отдельно как бюджет запуска. Сумму разовых вложений в сам B также сверяем отдельно с финансовой командой [C003, C011, C038, C045].",
        "",
        "Прирост подключённых групп и объединённых номеров сам по себе не показывает рост оплаты. Учебная проверка границы предполагает, что каждое дополнительное подключение причинно даёт ровно один оплачиваемый номер, а подключения равномерно распределены в октябре, ноябре и декабре. Это в среднем два дополнительных оплаченных месяца на подключение. Новые платящие номера и удержанные номера нужно разнести по идентификаторам, исключить месяцы, уже засчитанные в удержании B, и сравнить с контролем. Платные услуги и фактически предотвращённые расходы можно прибавить после подтверждения. Они в расчёт не заложены.",
        "",
        "| Прогноз B | Отклик и расходы | Новый вклад до P, млн руб. | При 500 руб. на месяц, до P | Новый вклад до P с окупаемостью труда, млн руб. | Остаток разрыва в примере с одной линией, млн руб. до P |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for forecast_name, budget_cases in cases.items():
        for scenario, case in budget_cases.items():
            f = case["finance"]
            lines.append(
                f"| {forecast_name} | {scenario} | {millions(f['gross_contribution_to_hit_target_before_pilot_rub'])} "
                f"| {integer(f['paid_months_to_hit_target_before_pilot'])} "
                f"| {millions(f['gross_contribution_to_hit_target_and_repay_people_before_pilot_rub'])} "
                f"| {millions(f['still_needed_in_one_line_example_before_pilot_rub'])} |"
            )
    lines += [
        "",
        "Перед финансированием владелец каналов проверяет чистый прирост относительно контроля, уникальный охват, фактические расходы и недельную пропускную способность каждого канала. Дизайнер и аналитик проверяют первое действие после приглашения. Руководители продукта измеряют декабрьскую реактивацию прежних групп и объединение двух собственных номеров. Финансовая команда проверяет сроки работ, оплаченные месяцы и дополнительные прямые расходы. Если отклик ниже требуемого или вклад не покрывает расходы, руководитель переносит часть годовой цели, меняет предложение или прекращает закупку охвата. Ставки и объёмы над границей базы служат оценкой чувствительности.",
    ]
    return "\n".join(lines) + "\n"


def main():
    forecasts = json.loads((HERE / "strategy_calc.json").read_text(encoding="utf-8"))
    reference_funnel = forecasts["funnel"]["основной"]
    reference_uplift = sum(row["accepted"] - row["control_accepted"] for row in reference_funnel)
    reference_reach = sum(row["reached"] for row in reference_funnel)
    scenarios = {**SCENARIOS, "опорный": replace(SCENARIOS["опорный"], family_incremental_conversion=reference_uplift / reference_reach)}
    cases = {
        name: {s: budget_case(forecast, forecasts["funnel"][name], a) for s, a in scenarios.items()}
        for name, forecast in forecasts["forecast"].items()
    }
    result = {"assumptions": {name: asdict(a) for name, a in scenarios.items()}, "cases": cases}
    (HERE / "kpi_budget.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (HERE / "kpi_budget.md").write_text(render(cases, scenarios), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
