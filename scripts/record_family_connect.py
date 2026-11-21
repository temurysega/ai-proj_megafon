"""Собрать демо Family Connect из архива проекта и свежих запусков CLI.

Подготовка для записи: requirements.txt, Chromium для Playwright и imageio-ffmpeg.
Запуск: python scripts/record_family_connect.py
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import yaml
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path("projects") / "family-connect"
OUT = ROOT / "docs" / "video"
INTAKE = "65c29ba"
PAUSED = "7fb6003"
REVIEW = "57ce7f7"
WIDTH, HEIGHT = 1280, 720
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"}
ESC = html.escape


@dataclass
class Shot:
    chapter: str
    origin: str
    title: str
    content: str
    caption: str
    seconds: int


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in read(path).splitlines() if line]


def state(root: Path) -> dict:
    return yaml.safe_load(read(root / PROJECT / "state.yaml"))


def capture(root: Path, script: str, *arguments: str, stdin: str = "") -> str:
    proc = subprocess.run(
        [sys.executable, script, *arguments], cwd=root, input=stdin,
        env=ENV, capture_output=True, text=True, encoding="utf-8", timeout=40,
    )
    if proc.returncode:
        raise RuntimeError(f"{script} {arguments}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def sf(root: Path, *args: str) -> str:
    return capture(root, "sf.py", "-p", "family-connect", *args)


def snapshot(root: Path, revision: str) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=zip", revision, PROJECT.as_posix()],
        cwd=ROOT, check=True, capture_output=True,
    )
    with zipfile.ZipFile(io.BytesIO(archive.stdout)) as saved:
        saved.extractall(root)


def copy_runtime(root: Path) -> None:
    root.mkdir()
    for dirname in ("strategist", "knowledge", "config"):
        shutil.copytree(ROOT / dirname, root / dirname, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "sf.py", root)
    (root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "hook.py", root / "scripts")


def rows(entries: list[tuple[str, str]]) -> str:
    return "".join(f'<div class="row"><b>{ESC(key)}</b><span>{ESC(value)}</span></div>'
                   for key, value in entries)


def terminal(command: str, output: str, description: str = "") -> str:
    label = f'<div class="terminal-label">{ESC(description)}</div>' if description else ""
    return (f'{label}<div class="terminal"><div class="prompt"><b>PS&gt;</b> {ESC(command)}</div>'
            f'<pre>{ESC(output)}</pre></div>')


def excerpt(label: str, quote: str) -> str:
    return f'<div class="label">{ESC(label)}</div><blockquote>{ESC(quote)}</blockquote>'


def gate_detail(run: list[dict], gate: str) -> str:
    return next(row["detail"] for row in run if row["action"] == "gate" and row["detail"].startswith(gate))


def collect_shots(temp: Path) -> list[Shot]:
    early, paused, review, current = [temp / x for x in ("intake", "paused", "review", "current")]
    snapshot(early, INTAKE)
    snapshot(review, REVIEW)
    copy_runtime(paused)
    snapshot(paused, PAUSED)
    copy_runtime(current)
    shutil.copytree(ROOT / PROJECT, current / PROJECT)

    original_state = state(paused)
    record = records(current / PROJECT / "journal.jsonl")
    first_status = sf(paused, "status", "--plain", "--brief")
    source_list = sf(paused, "source", "list")
    sf(paused, "use", "family-connect")
    hook_raw = capture(paused, "scripts/hook.py", "session_start", stdin="{}")
    hook = json.loads(hook_raw)["hookSpecificOutput"]["additionalContext"]
    head = first_status.splitlines()[:4]
    if "G2_option=pending" not in head[2] or any(line not in hook for line in head):
        raise RuntimeError("Хук не восстановил ожидающее состояние G2 из снимка.")
    hook_head = "\n".join(hook.splitlines()[:5])
    recorded_choice = state(review)["gates"]["G2_option"]["note"]
    passed_gate = sf(paused, "gate", "G2", "pass", "--note", recorded_choice)
    advanced = sf(paused, "stage", "strategy")
    resumed_state = state(paused)
    if resumed_state["stage"] != "strategy" or resumed_state["gates"]["G2_option"]["status"] != "passed":
        raise RuntimeError("После выбора не удалось продолжить на стадии стратегии.")

    strict = sf(current, "check", "--strict", "--json")
    result = json.loads(strict)
    if result["errors"] or result["warnings"]:
        raise RuntimeError(f"Строгая проверка вернула замечания:\n{strict}")
    decisions_check = sf(current, "decisions", "check")
    due = sf(current, "decisions", "due")
    due_lines = due.splitlines()
    next_status = sf(current, "status", "--plain", "--brief").splitlines()[:4]
    g1 = gate_detail(record, "G1_brief")
    g2 = gate_detail(record, "G2_option")
    g3 = gate_detail(record, "G3_strategy")
    request = state(early)["request"].split(" (бриф организаторов", 1)[0]
    archived_questions = state(early)["open_questions"]
    claims = {c["id"]: c for c in records(current / PROJECT / "evidence" / "claims.jsonl")}
    key_fact = claims["C016"]
    rejoin = "Тексты и решения исходной сессии воспроизводятся по файлам и журналу. Команды, помеченные «Новый запуск», выполнены в этой записи."
    baseline_script = (PROJECT / "research" / "data" / "baseline_gaps.py").as_posix()
    baseline_output = capture(current, baseline_script)
    baseline_lines = baseline_output.splitlines()
    baseline_start = next(i for i, line in enumerate(baseline_lines) if line.startswith("## Почему активных"))
    baseline_excerpt = "\n".join(baseline_lines[baseline_start:baseline_start + 3])
    forecast = json.loads(read(current / PROJECT / "research" / "data" / "strategy_calc.json"))["forecast"]["основной"]
    profit = f'{forecast["profit"]:.2f}'.replace(".", ",")
    gap = f'{forecast["profit_gap_mln"]:.2f}'.replace(".", ",")
    budget_script = (PROJECT / "research" / "data" / "kpi_budget.py").as_posix()
    capture(current, budget_script)
    budget = json.loads(read(current / PROJECT / "research" / "data" / "kpi_budget.json"))
    high_response = budget["cases"]["основной"]["высокий отклик"]
    package_floor = f'{high_response["package_budget_rub"] / 1_000_000:.2f}'.replace(".", ",")
    profit_needed = high_response["finance"]["gross_contribution_to_hit_target_before_pilot_rub"]
    profit_floor = f'{profit_needed / 1_000_000:.2f}'.replace(".", ",")
    report_path = current / PROJECT / "report" / "index.pdf"
    if not report_path.read_bytes().startswith(b"%PDF"):
        raise RuntimeError("Итоговый PDF отсутствует или повреждён.")
    report = read(current / PROJECT / "strategy" / "document.md")
    parts = re.findall(r"^## ([1-5]\. .+)$", report, flags=re.MULTILINE)
    if len(parts) != 5:
        raise RuntimeError("Для демонстрации нужны пять частей стратегии.")
    compared = read(current / PROJECT / "options.md")
    option_ids = re.findall(r"^## Вариант ([A-F]) —", compared, flags=re.MULTILINE)
    if option_ids != list("ABCDEF"):
        raise RuntimeError("Ожидалось шесть вариантов от A до F.")

    archive = "Материалы исходной сессии"
    fresh = "Новый запуск · копия проекта"
    strategy = "Актуальная версия стратегии"
    status_command = "python sf.py -p family-connect status --plain --brief"
    return [
        Shot("Запрос", "Демонстрация по брифу организаторов", "Связь для близких\nи собственных устройств",
             '<div class="subtitle">Стратег Фабрики продуктов</div>'
             + excerpt("Запрос руководителя · учебный оператор", request),
             rejoin, 15),
        Shot("Запрос", archive, "Два уточнения до старта",
             rows([("Q1 · Данные", archived_questions[0]["question"]),
                   ("Q2 · Режим", archived_questions[1]["question"])])
             + excerpt("Журнал · подтверждение G1", g1),
             "Руководитель утвердил работу по учебным данным PDF и подтвердил контрольные точки принятия решений.", 14),
        Shot("Источники", fresh, "Оригинал PDF в реестре",
             terminal("python sf.py -p family-connect source list", source_list)
             + excerpt(f'{key_fact["id"]} · источник {key_fact["sources"][0]} · {key_fact["locator"]}',
                       f'«{key_fact["quote"]}»'),
             "Снимок PDF имеет идентификатор S001. Факт о запоздалой помощи можно проверить по дословной цитате.", 13),
        Shot("Исследование", archive, "Что меняет решение",
             rows([("Факт · C016", "Организатор уже может передать интернет из свободного остатка. О перебое порой узнаёт из просьбы о помощи."),
                   ("Расчёт · C025", claims["C025"]["text"]),
                   ("Допущение · C030", "Базовые 10–15% участников с ограничением предстоит проверить по выгрузке."),
                   ("Пробел · DQ5", "Как часто одновременно есть низкий остаток у близкого и свободный объём в группе?")]),
             "Сигнал имеет смысл, если организатор сумеет помочь до ограничения. Частоту подходящих случаев бриф не сообщает.", 17),
        Shot("Исследование", fresh, "Расчёт можно повторить",
             terminal(f"python {baseline_script}", baseline_excerpt, "Фрагмент фактического вывода"),
             "Расчёт показывает вклад подключений и активности в отставание. Он использует числа из таблицы учебного брифа.", 14),
        Shot("Варианты", archive, "Шесть способов действовать",
             rows([("A · Оставить как есть", "Сохраняет текущий сервис. Цели года остаются недостижимыми."),
                   ("B · Сигнал", "Предупредить организатора и открыть существующую передачу. Нужен свободный остаток."),
                   ("C · Общий кабинет", "Собрать остатки, списания и передачу в одном месте. Дольше и дороже."),
                   ("D · Автоматика тарифа", "Перераспределять остаток. Изменение менее обратимо."),
                   ("E · Собственные номера", "Сначала напоминания для владельцев роутеров. У семей остаётся текущий путь."),
                   ("F · Закрыть", "Высвободить ресурсы. Семейное направление потеряет год развития.")]),
             "Файл options.md содержит сравнение, возражения и условия смены рекомендации по каждому варианту.", 18),
        Shot("Возобновление", fresh, "Чекпойнт перед выбором G2",
             terminal(status_command, "\n".join(head),
                      f'Архивный снимок {PAUSED} · сохранён {original_state["last_checkpoint"]["ts"][11:19]}'),
             "Первая команда прочитала сохранённый проект: варианты готовы, G2 ждёт решения человека.", 12),
        Shot("Возобновление", fresh, "Новый процесс читает файлы",
             terminal("python scripts/hook.py session_start", hook_head,
                      "Фрагмент поля additionalContext из ответа хука"),
             "Запущен отдельный процесс с реальным хуком SessionStart. Он получил тот же статус и следующий шаг без истории чата.", 15),
        Shot("Варианты", "Архивное решение · новый запуск в копии", "Выбор человека возвращает ход работе",
             excerpt("Записанное решение G2", g2)
             + terminal("python sf.py -p family-connect gate G2 pass --note …", passed_gate)
             + terminal("python sf.py -p family-connect stage strategy", advanced),
             "Команда использует сохранённый текст выбора B. Временная копия проекта переходит к стратегии.", 16),
        Shot("Стратегия", strategy, "Документ из пяти частей",
             rows([(heading.split(". ", 1)[0], heading.split(". ", 1)[1]) for heading in parts])
             + '<div class="path">projects/family-connect/strategy/document.md</div>',
             "Руководитель получает один документ по структуре брифа, стратегии и план проверки доступны отдельно.", 12),
        Shot("Стратегия", strategy, "Одна помощь и ясное обещание",
             rows([("Продукт", "Организатор семейной группы получает сигнал при низком остатке у близкого и может добавить интернет из свободного остатка."),
                   ("Разрешение", "Участник сам разрешает показ остатка и может отозвать доступ."),
                   ("Канал", "Уведомление ведёт к передаче. Приглашение на экране группы объясняет, что увидит организатор."),
                   ("Проверка", "Случайное распределение целыми семьями: обычное обслуживание против сигнала.")]),
             "Механика продукта и коммуникация согласованы: сообщение обещает возможность помочь заранее при наличии разрешения и свободного остатка.", 16),
        Shot("Стратегия", strategy, "Когда расширять пилот",
             rows([("Плановый год", f"≈{profit} млн ₽ при цели 285 млн ₽. Разрыв ≈{gap} млн ₽ до оценки прямых затрат пилота [C010, C038]."),
                   ("Эффект пилота", "Порог — снижение доли ограничений на 3 п.п. Подходящая выборка и неопределённость учитываются до решения [C031, C037, C040]."),
                   ("Условия остановки", "Повторный вычет или видимость остатка после отзыва согласия."),
                   ("Третий год", "10 000 активных групп — условный ориентир, пересматриваемый по данным пилота [C041].")]),
             "В II квартале проверяют исполнение и понятность. Решение по ограничениям принимают по достаточному набору и правилу интервала.", 18),
        Shot("Стратегия", strategy, "Два отдельных решения о вложениях",
             rows([("Годовые цели", f"Условная смета четырёх показателей использования начинается с {package_floor} млн ₽ при высоком отклике. Сверяем охват, конверсию и затраты [C054]."),
                   ("Годовая прибыль", f"При нижней смете нужен новый валовой вклад ≈{profit_floor} млн ₽ плюс прямые расходы пилота [C055]."),
                   ("Полный кабинет", "Прототип начислений и истории, затем сравнение с B при одинаковом сигнале. Решающие условия: польза, безопасность и добавочная окупаемость [C048, C049].")]),
             "Смету можно повторить. Для финансирования кабинета проверяют пользу начислений и истории сверх простого сигнала.", 15),
        Shot("Проверка", fresh, "Строгая проверка перед сдачей",
             terminal("python sf.py -p family-connect check --strict --json",
                      json.dumps({"errors": result["errors"], "warnings": result["warnings"]}, ensure_ascii=False, indent=2),
                      "Поля errors и warnings из фактического ответа")
             + rows([("Активных утверждений", str(result["metrics"]["claims_active"])),
                     ("Дословных совпадений", str(result["metrics"]["quote_matches_in_current_snapshots"].get("verbatim", 0)))]),
             "Проверка запущена на готовой копии. Она сверяет цитаты со снимком и проверяет полноту стратегии.", 12),
        Shot("Сопровождение", "Архивная приёмка · новый запуск в копии", "Что контролировать после решения",
             excerpt("Журнал · исходное подтверждение G3", g3)
             + terminal("python sf.py -p family-connect decisions check", decisions_check)
             + terminal("python sf.py -p family-connect decisions due",
                        "\n".join(due_lines[:2]), "Первые две строки фактического вывода"),
             "По журналу исходной приёмки видны владельцы, сроки и зависимости. Выгрузка ждёт выделения людей.", 17),
        Shot("Сопровождение", fresh, "С чего продолжить теперь",
             terminal(status_command, "\n".join(next_status))
             + '<div class="path">projects/family-connect/report/index.pdf</div>',
             "Итог проекта доступен в PDF. Следующая проверка — частота подходящих случаев, причины ограничений и наличие свободного остатка.", 13),
    ]


CSS = """
:root{font-family:"Segoe UI",Arial,sans-serif;color:#eef6f1;background:#0a191a}
*{box-sizing:border-box} html,body{margin:0;width:1280px;height:720px;overflow:hidden}
body{background:radial-gradient(ellipse at 105% 3%,#193f35 0,#0a191a 58%);padding:34px 58px 0}
header{display:flex;align-items:center;justify-content:space-between;padding-bottom:17px;border-bottom:1px solid #41635a}
.wordmark{font-size:17px;font-weight:750;letter-spacing:.065em;text-transform:uppercase;display:flex;align-items:center;gap:11px}
.mark{display:inline-block;width:13px;height:13px;background:#9bffc4;border-radius:4px;transform:rotate(12deg)}
.chapter{font-size:18px;color:#c2d2c9}
.origin{font-size:16px;letter-spacing:.035em;color:#9bffc4;margin-top:24px;font-weight:650}
h1{margin:6px 0 20px;font-size:49px;line-height:1.02;font-weight:700;letter-spacing:-.035em;white-space:pre-line}
.content{font-size:22px;line-height:1.35;color:#e1ece5}
.subtitle{font-size:32px;margin-bottom:22px;color:#9ab2a6}
.row{display:grid;grid-template-columns:280px 1fr;gap:23px;padding:9px 16px;background:#162b2a;border-bottom:1px solid #334f49}
.row:nth-child(even){background:#102523}
.row b{color:#a3f8c1;font-size:21px}.row span{font-size:21px}
.label,.terminal-label{color:#a6c3b6;font-size:15px;line-height:1.25;margin:0 0 4px}
blockquote{margin:0 0 13px;border-left:3px solid #9bffc4;background:#18312c;padding:10px 18px;font-size:23px}
.path{margin-top:18px;color:#a6c3b6;font:17px Consolas,"DejaVu Sans Mono",monospace}
.terminal{padding:10px 15px;background:#071111;border:1px solid #34534b;border-radius:8px;margin-bottom:13px}
.prompt{color:#eef9f3;font:20px/1.2 Consolas,"DejaVu Sans Mono",monospace;margin-bottom:6px}
.prompt b{color:#9bffc4}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:19px/1.26 Consolas,"DejaVu Sans Mono",monospace;margin:0;color:#cfdfd7}
.footer{position:absolute;width:1164px;bottom:25px}
.caption{font-size:20px;font-weight:520;line-height:1.3;padding:11px 13px;color:#f4fbf7;background:#18322e;min-height:74px;
display:flex;align-items:center;border-radius:7px}
.progress{height:3px;background:#24453e;margin-top:11px}.fill{height:3px;background:#9bffc4}
"""


def frame(shot: Shot, index: int, count: int) -> str:
    pct = 100 * index / count
    return (f'<!doctype html><html lang="ru"><meta charset="utf-8"><style>{CSS}</style><body>'
            f'<header><div class="wordmark"><i class="mark"></i>Стратег Фабрики продуктов</div>'
            f'<div class="chapter">{ESC(shot.chapter)} · {index:02d}/{count:02d}</div></header>'
            f'<div class="origin">{ESC(shot.origin)}</div><h1>{ESC(shot.title)}</h1>'
            f'<div class="content">{shot.content}</div><div class="footer">'
            f'<div class="caption">{ESC(shot.caption)}</div>'
            f'<div class="progress"><div class="fill" style="width:{pct:.2f}%"></div></div></div></body></html>')


def stamp(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"00:{minutes:02d}:{seconds:02d}.000"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="strategist-family-video-") as work:
        temp = Path(work)
        shots = collect_shots(temp)
        total = sum(shot.seconds for shot in shots)
        if total > 600:
            raise RuntimeError("Запись превысила ограничение в 10 минут.")
        manifest, vtt = [], ["WEBVTT\n"]
        cursor = 0
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            for i, shot in enumerate(shots, 1):
                page.set_content(frame(shot, i, len(shots)))
                fits = page.evaluate(
                    "() => document.querySelector('.content').getBoundingClientRect().bottom + 10"
                    " <= document.querySelector('.footer').getBoundingClientRect().top"
                )
                if not fits:
                    raise RuntimeError(f"Кадр {i} выходит за область содержимого: {shot.title}")
                image = f"frame-{i:02d}.jpg"
                page.screenshot(path=temp / image, type="jpeg", quality=95)
                manifest += [f"file '{image}'", f"duration {shot.seconds}"]
                end = cursor + shot.seconds
                vtt.append(f"{stamp(cursor)} --> {stamp(end)}\n{shot.caption}\n")
                cursor = end
            browser.close()
        manifest.append(f"file 'frame-{len(shots):02d}.jpg'")
        manifest_path = temp / "frames.txt"
        manifest_path.write_text("\n".join(manifest) + "\n", encoding="utf-8")
        video = temp / "family-connect.mp4"
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "1", "-i", str(manifest_path),
            "-vf", "fps=24,format=yuv420p", "-t", str(total), "-c:v", "libx264",
            "-crf", "21", "-preset", "fast", "-movflags", "+faststart", str(video),
        ], check=True, timeout=160)
        shutil.copy2(temp / "frame-01.jpg", OUT / "family-connect-poster.jpg")
        shutil.copy2(video, OUT / video.name)
        (OUT / "family-connect.vtt").write_text("\n".join(vtt), encoding="utf-8")
    print(f"{video.name} | {WIDTH}x{HEIGHT} | {total // 60}:{total % 60:02d}")


if __name__ == "__main__":
    main()
