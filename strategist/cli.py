"""CLI `sf` — команды для человека и для агента (в любой IDE).

python sf.py <команда> …     (или `sf …` после `pip install -e .`)
Справка: python sf.py -h ; по команде: python sf.py <команда> -h
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import CLAIM_KIND_RU, ROOT, STAGE_TITLES, STAGES, StrategistError, load_env, setup_console


def _print(obj):
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _console():
    try:
        from rich.console import Console
        return Console(soft_wrap=False)
    except Exception:
        return None


def _split(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").replace(";", ",").split(",") if x.strip()]


# ---------------- обработчики ----------------
def cmd_new(a):
    from .project import new_project
    d = new_project(a.id, a.title, a.request or "", a.mode)
    _print(f"Создан проект {a.id} ({d}). Он активен. Следующий шаг — постановка задачи (навык intake): "
           f"заполнить {a.id}/brief.md по шаблону knowledge/templates/brief.md.")


def cmd_use(a):
    from .project import set_active
    set_active(a.id)
    _print(f"Активный проект: {a.id}")


def cmd_list(a):
    from .project import list_projects
    for p in list_projects():
        print(f"{'*' if p['active'] else ' '} {p['id']:<28} {STAGE_TITLES.get(p['stage'], p['stage']):<28} {p['title']}")


def cmd_status(a):
    from .project import load_state, status_text
    if a.json:
        _print(load_state(a.project))
        return
    txt = status_text(a.project, brief=a.brief)
    con = _console()
    if con and not a.plain:
        from rich.panel import Panel
        con.print(Panel(txt, title="Стратег · статус проекта", border_style="green"))
    else:
        print(txt)


def cmd_stage(a):
    from .project import set_stage
    st = set_stage(a.stage, a.status, a.project, a.note or "")
    _print(f"Стадия: {STAGE_TITLES[st['stage']]} ({st['stage_status']})")


def cmd_gate(a):
    from .project import gate
    st = gate(a.gate, a.decision, a.note or "", a.by, a.project)
    _print({g: v.get("status") for g, v in st["gates"].items()})


def cmd_checkpoint(a):
    from .project import checkpoint
    st = checkpoint(a.note, a.next, a.waiting, a.project)
    _print(f"Чекпойнт сохранён. Следующее действие: {st.get('next_action')}")


def cmd_deliverable(a):
    from .project import set_deliverable
    _print(set_deliverable(a.file, a.template or "", _split_semicolon(a.sections), a.project))


def _split_semicolon(s):
    return [x for x in (s or "").split(";") if x.strip()]


def cmd_ask(a):
    from .project import add_question, answer_question
    if a.action == "add":
        _print(add_question(a.text, a.why or "", a.default or "", a.project))
    else:
        answer_question(a.qid, a.text, a.project)
        _print("Ответ записан")


def cmd_source(a):
    from .evidence import add_source, load_sources
    if a.action == "add":
        _print(add_source(a.title, a.kind, a.url or "", a.path or "", a.publisher or "", a.published or "",
                          a.reliability, a.notes or "", pid=a.project))
    else:
        for s in load_sources(a.project):
            flag = f" ⚠инъекции:{len(s['injection_flags'])}" if s.get("injection_flags") else ""
            print(f"{s['id']} [{s['kind']}/{s['reliability']}] {s['title'][:70]} {s.get('url') or s.get('path')}{flag}")


def cmd_fetch(a):
    from .web import fetch
    r = fetch(a.url, a.title or "", a.publisher or "", a.published or "", a.reliability, a.render, a.refresh,
              a.notes or "", pid=a.project)
    _print({k: r.get(k) for k in ("id", "title", "path", "chars", "injection_flags", "_note")})


def cmd_capture(a):
    from .web import capture
    _print(capture(a.url, a.name or "", a.mobile, not a.viewport_only, pid=a.project))


def cmd_ingest(a):
    from .ingest import ingest
    r = ingest(a.file, a.title or "", a.kind or "", a.reliability, a.publisher or "", a.published or "",
               a.describe, a.transcribe, a.notes or "", pid=a.project, public_media=a.public_media)
    _print({k: r.get(k) for k in ("id", "title", "kind", "text_path", "chars", "injection_flags")})


def cmd_claim(a):
    from .evidence import add_claim, retract_claim, update_claim
    if a.action == "add":
        _print(add_claim(a.text, a.kind, _split(a.src), a.quote or "", a.locator or "", a.conf, _split(a.tags),
                         _split(a.depends), a.method or "", a.note or "", pid=a.project,
                         unverified_quote=a.unverified_quote))
    elif a.action == "update":
        fields = {k: v for k, v in {"status": a.status, "kind": a.kind_new, "confidence": a.conf_new,
                                    "note": a.note, "text": a.text_new, "quote": a.quote}.items() if v}
        if a.src:
            fields["sources"] = _split(a.src)
        _print(update_claim(a.cid, pid=a.project, **fields))
    elif a.action == "retract":
        _print(retract_claim(a.cid, a.reason, a.by or "", pid=a.project))


def cmd_claims(a):
    from .evidence import load_claims
    for c in load_claims(a.project):
        if a.kind and c["kind"] != a.kind or a.status and c.get("status") != a.status:
            continue
        if a.tag and a.tag not in c.get("tags", []):
            continue
        base = ",".join(c.get("sources", [])) or ("←" + ",".join(c.get("depends_on", [])))
        print(f"{c['id']} [{CLAIM_KIND_RU[c['kind']]}/{c.get('confidence')}/{c.get('status')}] {c['text'][:110]} ({base})")


def cmd_check(a):
    from .evidence import check
    res = check(a.project, strict=a.strict)
    if a.json:
        _print(res)
    else:
        con = _console()
        if con and not a.plain:
            from rich.table import Table
            con.print(f"[bold]{'❌ ОШИБКИ' if res['errors'] else '✅ Ошибок нет'}[/bold] · ошибок {len(res['errors'])} · "
                      f"предупреждений {len(res['warnings'])}")
            for e in res["errors"]:
                con.print(f"  [red]✗[/red] {e}", highlight=False)
            for w in res["warnings"][: a.max_warnings]:
                con.print(f"  [yellow]![/yellow] {w}", highlight=False)
            if len(res["warnings"]) > a.max_warnings:
                con.print(f"  … ещё {len(res['warnings']) - a.max_warnings} предупреждений (--max-warnings)")
            t = Table(title="Метрики доказательной базы", show_header=True)
            t.add_column("Метрика")
            t.add_column("Значение")
            for k, v in res["metrics"].items():
                t.add_row(k, json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v))
            con.print(t)
        else:
            _print(res)
    if res["errors"]:
        sys.exit(2)


def cmd_impact(a):
    from .evidence import impact
    _print(impact(a.cid, a.project, a.mark_stale))


def cmd_stale(a):
    from .evidence import clear_stale
    _print(f"Снято пометок: {clear_stale(a.file or '', a.project)}")


def cmd_revisit(a):
    from .revisit import candidates
    for c in candidates(a.source, a.top, a.llm, pid=a.project):
        rel = f" → {c.get('relation')}" if c.get("relation") else ""
        print(f"{c['claim']} (score {c['score']}){rel}: {c['claim_text'][:100]}\n   фрагмент: {c['evidence'][:200]}\n")


def cmd_decisions(a):
    from .decisions import due_items, record_observation, set_commitment, validate
    if a.action == "check":
        errs = validate(a.project)
        _print(errs or "Журнал решений заполнен корректно")
        if errs:
            sys.exit(2)
    elif a.action == "due":
        items = due_items(a.project)
        _print("\n".join(items) if items else "Нет просроченных обязательств и сработавших триггеров")
    elif a.action == "observe":
        items = record_observation(a.decision, a.metric, float(a.value), a.project)
        _print("\n".join(items) if items else "Наблюдение записано; триггеры не сработали")
    elif a.action == "commitment":
        set_commitment(a.decision, a.commitment, a.status, a.project)
        _print("Статус обязательства обновлён")


def cmd_kb(a):
    from .kb import search
    from .project import active_project
    for r in search(a.query, a.scope, a.project_opt or a.project or active_project(), a.k, a.rerank):
        w = f" ⚠ {r['warning']}" if r.get("warning") else ""
        print(f"[{r['score']}] {r['doc']} › {r['section']} ({r['file']}){w}\n    {r['text'][:220].replace(chr(10), ' ')}")
        if r.get("related"):
            print(f"    связи: {'; '.join(r['related'])}")


def cmd_memory(a):
    from .kb import load_memory, memory_add, memory_retract, memory_review
    if a.action == "add":
        _print(memory_add(a.text, a.kind, a.prov, a.project_name or "", a.valid_until or "", _split(a.links)))
    elif a.action == "list":
        for m in load_memory():
            if a.all or m.get("status") == "active":
                print(f"{m['id']} [{m['kind']}/{m['status']}] {m['text'][:110]} (откуда: {m['provenance'][:60]})")
    elif a.action == "retract":
        _print(memory_retract(a.mid, a.reason, a.by or ""))
    elif a.action == "review":
        _print(memory_review() or "Нечего пересматривать")


def cmd_route(a):
    from .router import correct, route, routing_stats
    if a.correct:
        correct(a.request, a.wrong or "", a.correct)
        _print("Исправление сохранено: в следующий раз этот запрос пойдёт в " + a.correct)
    elif a.stats:
        _print(routing_stats())
    else:
        _print(route(a.request, not a.no_llm, a.project))


def cmd_llm(a):
    from .llm import ask
    prompt = Path(a.prompt_file).read_text(encoding="utf-8") if a.prompt_file else a.prompt
    res = ask(a.task, prompt, system=a.system, pid=a.project, model=a.model, stage=a.stage, label=a.label or "",
              models=_split(a.chain) or None, cache=not a.no_cache)
    if a.out:
        Path(a.out).write_text(res["text"], encoding="utf-8")
    _print({"model": res["model"], "usd": res["usd"], "cached": res["cached"], "attempts": res.get("attempts"),
            "text": res["text"] if not a.out else f"→ {a.out}"})


def cmd_models(a):
    from .llm import check_routing_models, routing, sync_models
    if a.action == "sync":
        m = sync_models()
        probs = check_routing_models()
        _print(f"Моделей в OpenRouter: {len(m)}. Проблем в config/routing.yaml: {probs or 'нет'}")
    else:
        from .llm import model_prices
        pr = model_prices()
        for task, cfg in routing().get("tasks", {}).items():
            ms = ", ".join(f"{m} (${pr.get(m, {}).get('prompt', 0) * 1e6:.3f}/${pr.get(m, {}).get('completion', 0) * 1e6:.3f})"
                           for m in cfg.get("models", []))
            print(f"{task:<15} {ms}\n{'':<15} зачем: {cfg.get('why', '')}")


def cmd_research_import(a):
    from .importer import import_research
    _print(import_research(a.file, not a.no_fetch, pid=a.project))


def cmd_respondents(a):
    from .research import run_synthetic
    _print(run_synthetic(a.personas, a.guide, a.followups, a.rotate, _split(a.only), pid=a.project, out_subdir=a.out_dir))


def cmd_interviews(a):
    from .research import analyze_interviews
    _print(analyze_interviews(a.folder, a.synthetic, pid=a.project))


def cmd_data(a):
    from .data import profile, run_script
    if a.action == "profile":
        r = profile(a.file, pid=a.project)
        _print(r)
    else:
        r = run_script(a.file, pid=a.project)
        print(r["stdout"])
        if r["returncode"]:
            print(r["stderr"], file=sys.stderr)
            sys.exit(r["returncode"])


def cmd_render(a):
    from .render import build
    _print(build(a.project, a.pdf, link_base=a.link_base))


def cmd_cost(a):
    from .costs import add_manual, summary
    from .project import project_dir
    if a.add is not None:
        add_manual(project_dir(a.project).name, a.add, a.note or "", a.kind, a.tokens or 0, a.stage or "", a.model or "")
        _print("Записано")
        return
    pid = project_dir(a.project).name
    s = summary(pid)
    con = _console()
    if con and not a.plain:
        from rich.table import Table
        t = Table(title=f"Стоимость проекта {pid}")
        t.add_column("Статья")
        t.add_column("Значение", justify="right")
        t.add_row("Внешние модели (OpenRouter), USD", f"{s['external_usd']:.4f}")
        t.add_row("  вызовов / из кэша / неудачных", f"{s['external_calls']} / {s['cached_calls']} / {s['failed_calls']}")
        t.add_row("Субагенты и ручные записи, USD (оценка)", f"{s['subagent_usd']:.2f}")
        t.add_row("Основной чат IDE, USD (оценка по транскрипту)", f"{s['session_usd']:.2f}")
        if s["session_mixed"]:
            t.add_row(f"  [dim]не входит в проект: {s['session_note'][:60]}[/dim]", "")
        t.add_row("  токенов основного чата / субагентов", f"{s['ide_tokens']:,} / {s['subagent_tokens']:,}".replace(",", " "))
        for k, v in sorted(s["by_task"].items(), key=lambda x: -x[1]):
            t.add_row(f"  задача: {k}", f"{v:.4f}")
        for k, v in sorted(s["by_model"].items(), key=lambda x: -x[1]):
            t.add_row(f"  модель: {k}", f"{v:.4f}")
        demo = s.get("demo_runs")
        cost_label = "Учтённые расходы" if demo else "Стоимость проекта"
        t.add_row(f"[bold]{cost_label}, USD[/bold]", f"[bold]{s['project_usd']:.2f}[/bold]")
        if demo:
            t.add_row("Тестовых демопрогонов", str(demo["test_runs"]))
            t.add_row("Верхняя оценка одного демопрогона, USD", f"{demo['max_usd_per_run']:.2f}")
        con.print(t)
    else:
        _print(s)


def cmd_eval(a):
    from . import evals
    if a.action == "metrics":
        text = Path(a.file).read_text(encoding="utf-8") if a.file else evals.project_text(a.project_name)
        _print(evals.text_metrics(text))
    else:
        A = Path(a.a).read_text(encoding="utf-8") if Path(a.a).exists() else evals.project_text(a.a)
        B = Path(a.b).read_text(encoding="utf-8") if Path(a.b).exists() else evals.project_text(a.b)
        res = evals.judge(A, B, a.rubric, _split(a.models) or None, pid=a.project)
        if a.out:
            evals.save(res, a.out)
        _print(res)


def cmd_doctor(a):
    import importlib
    import platform
    from .llm import check_routing_models, has_key
    from .safety import scan_repo_secrets
    ok = True
    rows = [f"Python {platform.python_version()} ({sys.executable})"]
    for mod in ["yaml", "requests", "bs4", "pypdf", "docx", "openpyxl", "xlrd", "pandas", "markdown", "rich", "dotenv"]:
        try:
            importlib.import_module(mod)
            rows.append(f"✅ {mod}")
        except ImportError:
            rows.append(f"❌ {mod} — pip install -r requirements.txt")
            ok = False
    for mod, why in [("mcp", "MCP-сервер"), ("playwright", "скриншоты/PDF"), ("snowballstemmer", "стемминг поиска"),
                     ("matplotlib", "графики в скриптах анализа данных"), ("imageio_ffmpeg", "видео")]:
        try:
            importlib.import_module(mod)
            rows.append(f"✅ {mod} ({why})")
        except ImportError:
            rows.append(f"➖ {mod} не установлен — {why} недоступно (опционально)")
    rows.append("✅ OPENROUTER_API_KEY задан (значение не показывается)" if has_key() else
                "➖ OPENROUTER_API_KEY не задан → внешние модели недоступны; агент работает на IDE-модели (см. AGENTS.md «Без ключа»)")
    probs = check_routing_models()
    rows.append("✅ все модели из config/routing.yaml есть в локальном каталоге OpenRouter" if not probs else
                "⚠ " + "; ".join(probs[:5]))
    sec = scan_repo_secrets()
    rows.append("✅ секретов в файлах репозитория не найдено" if not sec else "❌ найдены секреты: " + "; ".join(sec[:5]))
    ok = ok and not sec
    if (ROOT / ".git").exists():
        installed, hook_report = _doctor_git_hook(a.install_git_hook)
        rows.append(hook_report)
        ok = ok and (installed or not a.install_git_hook)
    elif a.install_git_hook:
        rows.append("⚠ Для установки pre-commit хука нужна копия с Git.")
        ok = False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        rows.append("✅ Chromium для Playwright доступен")
    except Exception:
        rows.append("➖ Chromium не установлен: python -m playwright install chromium (нужно для скриншотов и PDF)")
    print("\n".join(rows))
    print("\nИтог: " + ("готово к работе ✅" if ok else "есть проблемы ❌"))
    if not ok:
        sys.exit(1)


def _doctor_git_hook(install: bool) -> tuple[bool, str]:
    import os
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "--git-path", "hooks/pre-commit"], cwd=ROOT,
                                capture_output=True, check=True, timeout=10)
        hook = ROOT / result.stdout.decode("utf-8").strip()
        hook_source = (ROOT / "scripts" / "pre-commit").read_bytes()
        other_hook = "➖ Уже есть другой git pre-commit хук. Для проверки секретов подключите к нему scripts/pre-commit."
        if hook.is_symlink():
            return False, other_hook
        previous = hook.read_bytes() if hook.exists() else None
        if previous is not None and previous.replace(b"\r\n", b"\n") != hook_source:
            return False, other_hook
        if install:
            hook.parent.mkdir(parents=True, exist_ok=True)
            if previous is None:
                with hook.open("xb") as f:
                    f.write(hook_source)
            elif previous != hook_source:
                hook.write_bytes(hook_source)
            hook.chmod(hook.stat().st_mode | 0o111)
        if (previous == hook_source or install) and (os.name == "nt" or hook.stat().st_mode & 0o111):
            return True, "✅ git pre-commit хук на секреты установлен"
        return False, "➖ git pre-commit хук не установлен: python sf.py doctor --install-git-hook"
    except (OSError, UnicodeError, subprocess.SubprocessError) as e:
        return False, f"⚠ Не удалось проверить или установить git pre-commit хук: {e}"


def cmd_export(a):
    import shutil
    from .project import project_dir
    d = project_dir(a.project)
    out = shutil.make_archive(str(ROOT / f"{d.name}-export"), "zip", d.parent, d.name)
    _print(f"Проект упакован: {out}. В другой копии выполните `python sf.py import \"{out}\"`, "
           f"затем `python sf.py use {d.name}`.")


def cmd_import(a):
    from pathlib import PurePosixPath
    from tempfile import TemporaryDirectory
    import zipfile

    from .common import PROJECTS

    try:
        with zipfile.ZipFile(a.zip) as archive:
            roots = set()
            for name in archive.namelist():
                path = PurePosixPath(name)
                if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                    raise StrategistError(f"Недопустимый путь в архиве: {name}")
                roots.add(path.parts[0])
            if len(roots) != 1:
                raise StrategistError("Архив должен содержать одну папку проекта.")
            project = roots.pop()
            destination = PROJECTS / project
            if destination.exists():
                raise StrategistError(f"Проект '{project}' уже существует. Для импорта выберите копию репозитория без него.")
            with TemporaryDirectory(prefix=".import-", dir=PROJECTS) as temporary:
                archive.extractall(temporary)
                incoming = Path(temporary) / project
                if not (incoming / "state.yaml").is_file():
                    raise StrategistError("В архиве проекта отсутствует state.yaml.")
                incoming.rename(destination)
    except (OSError, zipfile.BadZipFile) as e:
        raise StrategistError(f"Не удалось импортировать проект: {e}") from e
    _print(f"Импортировано: {project}. Для продолжения выполните `python sf.py use {project}`.")


# ---------------- парсер ----------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sf", description="Стратег Фабрики продуктов — инструменты агента")
    p.add_argument("-p", "--project", help="id проекта (по умолчанию — активный)")
    sp = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sp.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        # -p можно писать и после подкоманды: `sf check -p esim-travel` (замечание агента второго проекта)
        s.add_argument("-p", "--project", dest="project_sub", default=None, help=argparse.SUPPRESS)
        return s

    s = add("new", cmd_new, "создать проект")
    s.add_argument("id")
    s.add_argument("--title", required=True)
    s.add_argument("--request", help="исходный запрос человека дословно")
    s.add_argument("--mode", choices=["checkpoints", "autopilot"], default="checkpoints")
    s = add("use", cmd_use, "сделать проект активным")
    s.add_argument("id")
    add("list", cmd_list, "список проектов")
    s = add("status", cmd_status, "статус: стадия, следующий шаг, вопросы, стоимость")
    s.add_argument("--brief", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--plain", action="store_true")
    s = add("stage", cmd_stage, "перейти на стадию")
    s.add_argument("stage", choices=STAGES)
    s.add_argument("--status", default="in_progress", choices=["in_progress", "waiting_human", "done"])
    s.add_argument("--note")
    s = add("gate", cmd_gate, "ворота: решение человека G1/G2/G3")
    s.add_argument("gate")
    s.add_argument("decision", choices=["pass", "reject", "assume"])
    s.add_argument("--note")
    s.add_argument("--by", default="human")
    s = add("checkpoint", cmd_checkpoint, "сохранить чекпойнт и следующий шаг")
    s.add_argument("note")
    s.add_argument("--next")
    s.add_argument("--waiting", action="store_true", help="ждём ответа человека")
    s = add("deliverable", cmd_deliverable, "структура итогового документа, которую требует бриф (проверяет sf check)")
    s.add_argument("--file", default="strategy/document.md")
    s.add_argument("--template", help="шаблон из knowledge/templates, например strategy-document-5parts")
    s.add_argument("--sections", help="или список частей через «;»")
    s = add("ask", cmd_ask, "вопросы человеку")
    s.add_argument("action", choices=["add", "answer"])
    s.add_argument("qid", nargs="?")
    s.add_argument("--text", required=True)
    s.add_argument("--why")
    s.add_argument("--default")

    s = add("source", cmd_source, "реестр источников")
    s.add_argument("action", choices=["add", "list"])
    s.add_argument("--title", default="")
    s.add_argument("--kind", default="web")
    s.add_argument("--url")
    s.add_argument("--path")
    s.add_argument("--publisher")
    s.add_argument("--published")
    s.add_argument("--reliability", default="B", choices=list("ABCD"))
    s.add_argument("--notes")
    s = add("fetch", cmd_fetch, "загрузить страницу/PDF из разрешённого источника")
    s.add_argument("url")
    s.add_argument("--title")
    s.add_argument("--publisher")
    s.add_argument("--published")
    s.add_argument("--reliability", default="B", choices=list("ABCD"))
    s.add_argument("--render", action="store_true", help="рендер в браузере (JS-сайты)")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--notes")
    s = add("capture", cmd_capture, "скриншот страницы для UX-анализа")
    s.add_argument("url")
    s.add_argument("--name")
    s.add_argument("--mobile", action="store_true")
    s.add_argument("--viewport-only", action="store_true")
    s = add("ingest", cmd_ingest, "принять файл: pdf/docx/xlsx/csv/html/изображение/аудио/видео")
    s.add_argument("file")
    s.add_argument("--title")
    s.add_argument("--kind")
    s.add_argument("--reliability", default="A", choices=list("ABCD"))
    s.add_argument("--publisher")
    s.add_argument("--published")
    s.add_argument("--describe", action="store_true", help="описать изображение/кадры vision-моделью")
    s.add_argument("--transcribe", action="store_true", help="расшифровать аудио")
    s.add_argument("--public-media", action="store_true",
                   help="подтверждаю: медиа открытое или синтетическое, без ПДн, пригодно для хранения "
                        "в проекте и передачи модели при --describe/--transcribe")
    s.add_argument("--notes")

    s = add("claim", cmd_claim, "реестр утверждений: add/update/retract")
    s.add_argument("action", choices=["add", "update", "retract"])
    s.add_argument("cid", nargs="?")
    s.add_argument("--text", default="")
    s.add_argument("--kind", default="fact")
    s.add_argument("--src", help="S001,S002")
    s.add_argument("--quote")
    s.add_argument("--locator")
    s.add_argument("--conf", default="medium", choices=["high", "medium", "low"])
    s.add_argument("--tags")
    s.add_argument("--depends")
    s.add_argument("--method")
    s.add_argument("--note")
    s.add_argument("--status")
    s.add_argument("--kind-new")
    s.add_argument("--conf-new")
    s.add_argument("--text-new")
    s.add_argument("--unverified-quote", action="store_true",
                   help="факт со сканом/изображением: цитату нельзя сверить по тексту — нужен --locator")
    s.add_argument("--reason", default="")
    s.add_argument("--by", help="id утверждения-замены (superseded)")
    s = add("claims", cmd_claims, "список утверждений")
    s.add_argument("--kind")
    s.add_argument("--status")
    s.add_argument("--tag")
    s = add("check", cmd_check, "проверка доказательной базы и структуры документов")
    s.add_argument("--strict", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--plain", action="store_true")
    s.add_argument("--max-warnings", type=int, default=15)
    s = add("impact", cmd_impact, "что затронет изменение утверждения")
    s.add_argument("cid")
    s.add_argument("--mark-stale", action="store_true")
    s = add("stale", cmd_stale, "снять пометку «требует пересмотра» после обновления")
    s.add_argument("--file")
    s = add("revisit", cmd_revisit, "какие утверждения затрагивает новый источник")
    s.add_argument("source")
    s.add_argument("--top", type=int, default=8)
    s.add_argument("--llm", action="store_true")
    s = add("decisions", cmd_decisions, "журнал решений: check/due/observe/commitment")
    s.add_argument("action", choices=["check", "due", "observe", "commitment"])
    s.add_argument("--decision")
    s.add_argument("--metric")
    s.add_argument("--value")
    s.add_argument("--commitment")
    s.add_argument("--status", default="done")

    s = add("kb", cmd_kb, "поиск по базе знаний / памяти / проекту")
    s.add_argument("query")
    s.add_argument("--scope", default="knowledge", choices=["knowledge", "memory", "project", "all"])
    s.add_argument("--project-opt", dest="project_opt")
    s.add_argument("-k", type=int, default=6)
    s.add_argument("--rerank", action="store_true", help="переупорядочить по смыслу дешёвой моделью")
    s = add("memory", cmd_memory, "память между сеансами")
    s.add_argument("action", choices=["add", "list", "retract", "review"])
    s.add_argument("mid", nargs="?")
    s.add_argument("--text", default="")
    s.add_argument("--kind", default="lesson")
    s.add_argument("--prov", default="")
    s.add_argument("--project-name")
    s.add_argument("--valid-until")
    s.add_argument("--links")
    s.add_argument("--reason", default="")
    s.add_argument("--by")
    s.add_argument("--all", action="store_true")
    s = add("route", cmd_route, "выбрать навык/процесс для запроса")
    s.add_argument("request", nargs="?", default="")
    s.add_argument("--no-llm", action="store_true")
    s.add_argument("--correct", help="правильный навык (исправление ошибочного выбора)")
    s.add_argument("--wrong")
    s.add_argument("--stats", action="store_true")
    s = add("llm", cmd_llm, "вызов внешней модели по задаче из routing.yaml")
    s.add_argument("task")
    s.add_argument("--prompt", default="")
    s.add_argument("--prompt-file")
    s.add_argument("--system")
    s.add_argument("--model")
    s.add_argument("--stage")
    s.add_argument("--label")
    s.add_argument("--out")
    s.add_argument("--chain", help="своя цепочка моделей через запятую (эскалация слева направо)")
    s.add_argument("--no-cache", action="store_true")
    s = add("models", cmd_models, "модели: sync (цены OpenRouter) / list (маршруты)")
    s.add_argument("action", choices=["sync", "list"])
    s = add("research-import", cmd_research_import, "импорт JSON субагента researcher: снимки + сверка цитат")
    s.add_argument("file")
    s.add_argument("--no-fetch", action="store_true")
    s = add("respondents", cmd_respondents, "синтетические интервью с модельными респондентами")
    s.add_argument("--personas", required=True)
    s.add_argument("--guide", required=True)
    s.add_argument("--followups", type=int, default=1)
    s.add_argument("--rotate", action="store_true")
    s.add_argument("--only")
    s.add_argument("--out-dir", default="synthetic", help="подпапка research/interviews/ для транскриптов")
    s = add("interviews", cmd_interviews, "анализ транскриптов интервью")
    s.add_argument("folder")
    s.add_argument("--synthetic", action="store_true")
    s = add("data", cmd_data, "данные: profile <файл> / run <скрипт>")
    s.add_argument("action", choices=["profile", "run"])
    s.add_argument("file")
    s = add("render", cmd_render, "собрать отчёт HTML (и PDF)")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--link-base", help="публичный URL папки проекта для локальных ссылок в PDF")
    s = add("cost", cmd_cost, "стоимость проекта")
    s.add_argument("--add", type=float, help="добавить ручную запись (USD)")
    s.add_argument("--kind", default="manual", choices=["manual", "subagent"])
    s.add_argument("--tokens", type=int)
    s.add_argument("--stage")
    s.add_argument("--model")
    s.add_argument("--note")
    s.add_argument("--plain", action="store_true")
    s = add("eval", cmd_eval, "сравнение с исходным способом")
    s.add_argument("action", choices=["metrics", "judge"])
    s.add_argument("--file")
    s.add_argument("--project-name")
    s.add_argument("--a")
    s.add_argument("--b")
    s.add_argument("--rubric", default=str(ROOT / "evals" / "rubric.yaml"))
    s.add_argument("--models")
    s.add_argument("--out")
    s = add("doctor", cmd_doctor, "проверка окружения, ключей (без показа), моделей, секретов")
    s.add_argument("--install-git-hook", action="store_true")
    add("export", cmd_export, "упаковать проект в zip (перенос в другую среду)")
    s = add("import", cmd_import, "распаковать проект из zip")
    s.add_argument("zip")
    return p


def main(argv=None):
    setup_console()
    load_env()
    args = build_parser().parse_args(argv)
    if getattr(args, "project_sub", None):
        args.project = args.project_sub
    try:
        args.fn(args)
    except StrategistError as e:
        print(f"⚠ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
