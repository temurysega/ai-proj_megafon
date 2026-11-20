"""Расчёт по brief.md. Флаг --replay заново создаёт изолированную запись CLI."""

import argparse
import io
import json
import math
import os
from pathlib import Path
import re
from statistics import NormalDist
import subprocess
import sys
import tempfile
import zipfile


CASE = Path(__file__).resolve().parent
REPO = CASE.parent.parent
REVISION = "6143ef4bfb78f4606554c3c8644bc6913c703307"
SEGMENTS = ("Малые", "Средние", "Крупные")


def sources(brief):
    parts = re.split(r"(?m)(?=^## S0[1-4] · )", brief)
    return {part[3:6]: part.strip() for part in parts[1:]}


def row(source, segment):
    line, = (line for line in source.splitlines() if line.startswith(f"| {segment} |"))
    # Между разрядами в брифе стоят пробелы, а между ветками — косая черта.
    return [int(n) for n in re.findall(r"\d+", line.replace(" ", ""))]


def calculate(sections):
    fixed, contact_price, send_price = 70_000, 250, 8
    z = NormalDist().inv_cdf(0.95)
    z_power = NormalDist().inv_cdf(0.90)
    raw_total = [0, 0]
    clean_total = [0, 0]
    total_n = 0
    variable_total = 0
    for segment in SEGMENTS:
        n, rc, rt, sc, st, cc, ct = row(sections["S02"], segment)
        dc, dt = row(sections["S03"], segment)
        monthly_n, renewal_value = row(sections["S04"], segment)
        uc, ut = rc - dc, rt - dt
        effect, support, complaint = (ut - uc) / n, (st - sc) / n, (ct - cc) / n
        value = monthly_n * effect * renewal_value
        support_cost = monthly_n * support * contact_price
        send_cost = monthly_n * send_price
        variable_net = value - support_cost - send_cost
        variable_total += variable_net
        raw_total[0] += rc
        raw_total[1] += rt
        clean_total[0] += uc
        clean_total[1] += ut
        total_n += n
        print(f"{segment}: уникальные {uc}/{ut}, доли {uc/n:.2%}/{ut/n:.2%}; "
              f"Δ записей {100*(rt-rc)/n:+.2f}, Δ продлений {100*effect:+.2f}, "
              f"Δ обращений {100*support:+.2f}, Δ жалоб {100*complaint:+.2f} п.п.; "
              f"продления {monthly_n*effect:+g}, обращения {monthly_n*support:+g}; "
              f"вклад {value:,.0f}, поддержка {support_cost:,.0f}, отправка {send_cost:,.0f}, "
              f"до фикс. {variable_net:+,.0f}, запуск отдельно {variable_net-fixed:+,.0f} ₽")
        if segment == "Малые":
            break_even = (support_cost + send_cost + fixed) / (monthly_n * renewal_value)
            variance = (uc/n) * (1-uc/n) + (ut/n) * (1-ut/n)
            complaint_variance = (cc/n) * (1-cc/n) + (ct/n) * (1-ct/n)
            lower = effect - z * math.sqrt(variance/n)
            upper = complaint + z * math.sqrt(complaint_variance/n)
            renew_per_arm = math.ceil((z+z_power)**2 * variance / (effect-break_even)**2)
            complaints_per_arm = math.ceil((z+z_power)**2 * complaint_variance / (0.01-complaint)**2)
            print(f"  Половина эффекта {50*effect:.2f} п.п.: {variable_net-value/2-fixed:+,.0f} ₽; "
                  f"порог {100*break_even:.6f} п.п.; нижняя 95% граница эффекта {100*lower:.3f} п.п.; "
                  f"верхняя 95% граница жалоб {100*upper:.3f} п.п.; план на ветку "
                  f"{renew_per_arm:,} по продлениям, {complaints_per_arm:,} по жалобам")
    for label, (control, test) in (("Сырые", raw_total), ("Сверенные", clean_total)):
        print(f"{label}: {control}/{total_n} и {test}/{total_n}; {control/total_n:.2%} → "
              f"{test/total_n:.2%}, Δ {100*(test-control)/total_n:+.2f} п.п.")
    print(f"Все без учёта запрета {variable_total-fixed:+,.0f} ₽; текущий процесс 0 ₽")


def write_decisions(project, decisions):
    (project / "decisions.yaml").write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")


def replay(brief, sections):
    cache = REPO / ".cache"
    cache.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="source-revision-", dir=cache))
    archive = subprocess.check_output(
        ["git", "archive", "--format=zip", REVISION, "sf.py", "strategist", "config", "projects/_template"], cwd=REPO
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        bundle.extractall(scratch)
    print(f"Изолированная копия: {scratch}", flush=True)
    for label, source in sections.items():
        (scratch / f"{label}.md").write_text(source + "\n", encoding="utf-8")

    env = os.environ.copy()
    env.pop("OPENROUTER_API_KEY", None)
    env["PYTHONUTF8"] = "1"

    def sf(*args):
        print("\n$ python sf.py " + subprocess.list2cmdline(args), flush=True)
        result = subprocess.run([sys.executable, "sf.py", *args], cwd=scratch, env=env,
                                text=True, encoding="utf-8", capture_output=True)
        print(result.stdout.rstrip(), flush=True)
        if result.returncode:
            print(result.stderr.rstrip(), file=sys.stderr, flush=True)
            result.check_returncode()
        return result.stdout

    def ingest(label):
        title = sections[label].splitlines()[0].removeprefix("## ")
        sf("ingest", f"{label}.md", "--title", title, "--notes", "Вымышленный учебный кейс")

    def fact(text, sid, quote, locator):
        sf("claim", "add", "--text", text, "--kind", "fact", "--src", sid,
           "--quote", quote, "--locator", locator, "--conf", "high")

    def claim(text, kind, dependencies=(), method=""):
        sf("claim", "add", "--text", text, "--kind", kind, "--depends", ",".join(dependencies),
           "--method", method)

    request = brief.split("\n\n", 2)[1]
    sf("new", "zz-smoke-source-revision", "--title", "Напоминание о продлении (учебный кейс)",
       "--request", request)
    project = scratch / "projects" / "zz-smoke-source-revision"
    (project / "brief.md").write_text(
        "# Напоминание о продлении\n\n"
        f"## Исходный запрос\n\n{request}\n\n"
        "## Решаемый вопрос\n\nОставить текущий процесс, отправить всем или выбрать более узкий шаг?\n\n"
        "## Цель\n\nСравнить месячный чистый вклад и соблюсти политику жалоб.\n\n"
        "## Получатель\n\nРуководитель сервиса подписок. Записка с расчётом, письмом, проверкой и записью решения.\n\n"
        "## Ограничения\n\nТолько условия и данные вымышленного кейса.\n\n"
        "## Доступные данные\n\nЗаписка команды, выгрузка пилота, акт сверки и условия решения.\n",
        encoding="utf-8",
    )
    ingest("S01")
    ingest("S02")
    fact("До сверки команда предварительно одобрила отправку всем; рассылку не начали. Внутри сегментов было случайное назначение, 30 дней наблюдения, сегменты адресуются отдельно.",
         "S001", sections["S01"].split("\n\n")[1], "S01, абзац под заголовком")
    fact("Выгрузка по трём сегментам содержит назначения, числители журнала платежей, обращения, жалобы.",
         "S002", sections["S02"].split("\n\n")[-1], "S02, таблица пилота")
    claim("По журналу платежей доля записей о продлении выросла с 61,60% до 68,24% (+6,64 п.п.).",
          "estimate", ("C002",), "Контроль (330+260+180)/1250, тест (372+288+193)/1250")
    claim("Записи о продлении по журналу платежей дают оценку прироста уникальных продлений +6,64 п.п.",
          "estimate", ("C003",), "До сверки одна запись условно принята за один уникальный аккаунт")
    (project / "decision.md").write_text(
        "# Решение до сверки\n\n## Основание предварительного решения\n\n"
        "Команда предварительно одобрила рассылку всем [C001]. Оценочный прирост уникальных продлений +6,64 п.п. [C004].\n",
        encoding="utf-8",
    )
    old = {
        "id": "D1", "title": "Предварительно отправить всем", "chosen": "отправка всем",
        "rationale_claims": ["C001", "C004"], "status": "active",
        "metrics": [{"name": "прирост по журналу, п.п.", "baseline": 6.64, "target": "рост",
                     "by": "сверка до рассылки"}],
        "review_triggers": [{"type": "claim_status", "claim": "C004", "note": "сверка уникальных платежей"}],
    }
    write_decisions(project, [old])
    sf("decisions", "check")
    sf("checkpoint", "Записано предварительное решение команды по S01/S02.", "--next",
       "Принять акт сверки и проверить прежнее основание рассылки.")

    ingest("S03")
    candidates = sf("revisit", "S003")
    assert "C004 (score" in candidates
    fact("Сверка выделила повторные записи по трём сегментам, остальные метрики и знаменатели прежние.",
         "S003", sections["S03"].partition("\n\n")[2], "S03, абзац и таблица повторов")
    claim("После удаления повторов прирост уникальных продлений: малые +5,50 п.п., средние +0,50 п.п., крупные −1,20 п.п., всего +2,56 п.п.",
          "estimate", ("C002", "C005"), "Вычесть повторы из числителя каждой ветки и разделить на назначения; agent_calc.py")
    sf("claim", "retract", "C004", "--reason", "S03 выявил повторную обработку успешных платежей.", "--by", "C006")
    impact = json.loads(sf("impact", "C004"))
    assert [item["file"] for item in impact["sections"]] == ["decision.md"]
    assert [item["decision"] for item in impact["decisions"]] == ["D1"]
    sf("decisions", "due")
    sf("checkpoint", "C004 заменено C006 после S03, раздел и D1 требуют пересмотра.", "--next",
       "Восстановить пересмотр: пересчитать экономику по S04, заменить рекомендацию и закрыть пометки.")
    reopened = json.loads(sf("status", "--json"))
    assert reopened["next_action"].startswith("Восстановить пересмотр")
    assert {item["file"] for item in reopened["stale"]} == {"decision.md", "decisions.yaml"}

    ingest("S04")
    fact("Условия задают масштаб, маржу продления, стоимость обращения, отправки и фиксированные расходы.",
         "S004", sections["S04"].split("\n\n", 1)[1].split("\n\nПолитика", 1)[0], "S04, таблица и абзац расходов")
    claim("Чистый вклад: малые +65 200 ₽, средние −79 000 ₽, крупные −152 000 ₽, все −25 800 ₽. Для малых порог +3,2361 п.п., при половине эффекта −14 000 ₽.",
          "estimate", ("C002", "C006", "C007"), "Масштабирование разниц на сегменты следующего месяца; agent_calc.py")
    fact("Политика запрещает отправку выше +1 п.п. жалоб, перед полной отправкой нужно подтвердить окупаемость, письмо можно отключить в настройках.",
         "S004", "Политика безопасности: " + sections["S04"].split("Политика безопасности: ")[1],
         "S04, политика безопасности и доступные параметры письма")
    claim("Перенос эффекта продлений, обращений и жалоб на будущую аудиторию требует проверки.",
          "assumption", ("C006", "C007"))
    claim("В малых нижняя односторонняя граница эффекта +0,81 п.п., верхняя по жалобам +1,55 п.п.; для проверки ориентир 8 453 на ветку.",
          "estimate", ("C002", "C006", "C008", "C009"), "Нормальное приближение для разницы двух независимых долей; agent_calc.py")
    claim("Полную рассылку не запускать. Малые допускают отдельную проверку после оценки набора и бюджета.",
          "hypothesis", ("C008", "C009", "C011"))

    (project / "decision.md").write_text((CASE / "agent.md").read_text(encoding="utf-8"), encoding="utf-8")
    write_decisions(project, [dict(old, status="reversed"), {
        "id": "D2", "title": "Оставить текущий процесс, подготовить проверку в малых",
        "chosen": "Кандидат на проверку: малые аккаунты, после проверки набора и бюджета",
        "rationale_claims": ["C006", "C008", "C009", "C011", "C012"], "assumptions": ["C010"],
        "owners": {"product": "руководитель продукта", "analytics": "аналитик", "payments": "платёжная команда"},
        "metrics": [{"name": "эффект уникальных продлений, п.п.", "baseline": 5.50, "target": "нижняя граница > порога окупаемости", "by": "после набора и 30 дней наблюдения"},
                    {"name": "прирост жалоб, п.п.", "baseline": 0.50, "target": "верхняя граница ≤ 1 п.п.", "by": "после набора и 30 дней наблюдения"}],
        "commitments": [{"id": "K1", "owner": "аналитик", "what": "Подтвердить набор и полную стоимость до выделения бюджета", "due": "до решения о пилоте", "status": "open"}],
        "review_triggers": [{"type": "claim_status", "claim": "C006", "note": "новая сверка платежей"},
                            {"type": "metric", "metric": "прирост жалоб, п.п.", "op": ">", "threshold": 1}],
        "status": "active",
    }])
    sf("stale", "--file", "decision.md")
    sf("stale", "--file", "decisions.yaml")
    sf("check", "--strict", "--json")
    sf("decisions", "check")
    sf("decisions", "due")
    sf("cost", "--add", "0", "--note", "Без ключа в экспериментальной копии, без внешних моделей")
    sf("checkpoint", "Сверка завершена, D1 заменено D2, пометки сняты.", "--next",
       "Подтвердить темп набора и бюджет проверки в малых перед одобрением пилота.")
    final = json.loads(sf("status", "--json"))
    assert not final["stale"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true", help="дополнительно воспроизвести пересмотр в CLI")
    args = parser.parse_args()
    brief = (CASE / "brief.md").read_text(encoding="utf-8")
    sections = sources(brief)
    calculate(sections)
    if args.replay:
        replay(brief, sections)


if __name__ == "__main__":
    main()
