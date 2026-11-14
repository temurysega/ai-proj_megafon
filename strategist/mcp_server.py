"""MCP-сервер «strategist»: те же функции, что и CLI, но как типизированные инструменты.

Зачем, если есть CLI: типизированные параметры (меньше ошибок экранирования кириллицы
в PowerShell/bash), одинаковое подключение в Claude Code, Cursor, Claude Desktop и других
MCP-клиентах. Запуск: python -m strategist.mcp_server (stdio).
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .common import load_env, setup_console

mcp = FastMCP("strategist")


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, indent=1, default=str)


@mcp.tool()
def project_status(project: str = "") -> str:
    """Статус активного (или указанного) проекта: стадия, следующий шаг, вопросы, стоимость, последние действия."""
    from .project import status_text
    return status_text(project or None)


@mcp.tool()
def checkpoint(note: str, next_action: str, waiting_human: bool = False, project: str = "") -> str:
    """Сохранить чекпойнт: что сделано и конкретный следующий шаг (для продолжения в новом чате)."""
    from .project import checkpoint as cp
    return _j(cp(note, next_action, waiting_human, project or None).get("next_action"))


@mcp.tool()
def add_source(title: str, kind: str = "web", url: str = "", path: str = "", publisher: str = "",
               published: str = "", reliability: str = "B", notes: str = "", project: str = "") -> str:
    """Зарегистрировать источник (kind: web/pdf/document/table/dataset/image/audio/video/interview/synthetic/user_material/analysis; reliability A–D)."""
    from .evidence import add_source as f
    return _j(f(title, kind, url, path, publisher, published, reliability, notes, pid=project or None))


@mcp.tool()
def fetch_url(url: str, title: str = "", publisher: str = "", published: str = "", reliability: str = "B",
              render: bool = False, project: str = "") -> str:
    """Загрузить страницу/PDF из allowlist в снимок-источник (с проверкой на инъекции). Возвращает id и путь к тексту."""
    from .web import fetch
    r = fetch(url, title, publisher, published, reliability, render, False, "", pid=project or None)
    return _j({k: r.get(k) for k in ("id", "title", "path", "chars", "injection_flags", "_note")})


@mcp.tool()
def add_claim(text: str, kind: str, sources: list[str] | None = None, quote: str = "", locator: str = "",
              confidence: str = "medium", tags: list[str] | None = None, depends_on: list[str] | None = None,
              method: str = "", project: str = "") -> str:
    """Добавить утверждение (kind: fact/estimate/hypothesis/forecast/assumption/synthetic/opinion). Факт требует источник и цитату."""
    from .evidence import add_claim as f
    return _j(f(text, kind, sources or [], quote, locator, confidence, tags or [], depends_on or [], method,
                pid=project or None))


@mcp.tool()
def update_claim(claim_id: str, status: str = "", note: str = "", superseded_by: str = "", project: str = "") -> str:
    """Изменить статус утверждения (active/disputed/retracted/superseded) с пояснением."""
    from .evidence import retract_claim, update_claim as f
    if status in ("retracted", "superseded"):
        return _j(retract_claim(claim_id, note, superseded_by, pid=project or None))
    return _j(f(claim_id, pid=project or None, status=status or None, note=note or None))


@mcp.tool()
def check_project(strict: bool = False, project: str = "") -> str:
    """Проверить доказательную базу и обязательные разделы документов. Возвращает ошибки, предупреждения, метрики."""
    from .evidence import check
    return _j(check(project or None, strict))


@mcp.tool()
def impact(claim_id: str, mark_stale: bool = False, project: str = "") -> str:
    """Какие разделы и решения зависят от утверждения (для пересмотра при новых данных)."""
    from .evidence import impact as f
    return _j(f(claim_id, project or None, mark_stale))


@mcp.tool()
def revisit_candidates(source_id: str, use_llm: bool = False, project: str = "") -> str:
    """Какие утверждения проекта затрагивает новый источник (кандидаты на пересмотр)."""
    from .revisit import candidates
    return _j(candidates(source_id, 8, use_llm, pid=project or None))


@mcp.tool()
def decisions_due(project: str = "") -> str:
    """Что требует внимания по принятым решениям: сроки обязательств, сработавшие триггеры, старые допущения."""
    from .decisions import due_items
    return _j(due_items(project or None))


@mcp.tool()
def kb_search(query: str, scope: str = "knowledge", rerank: bool = False, project: str = "") -> str:
    """Поиск по базе знаний (методы, шаблоны), памяти или материалам проекта. scope: knowledge/memory/project/all."""
    from .kb import search
    from .project import active_project
    return _j(search(query, scope, project or active_project(), 6, rerank))


@mcp.tool()
def memory_add(text: str, kind: str, provenance: str, project: str = "") -> str:
    """Запомнить между сеансами (kind: user_preference/lesson/source_pointer/agent_conclusion/decision_ref). Обязательно происхождение."""
    from .kb import memory_add as f
    return _j(f(text, kind, provenance, project))


@mcp.tool()
def memory_retract(memory_id: str, reason: str) -> str:
    """Отозвать устаревшую или ошибочную запись памяти."""
    from .kb import memory_retract as f
    return _j(f(memory_id, reason))


@mcp.tool()
def route_request(request: str) -> str:
    """Выбрать навык/процесс для запроса (правила → дешёвый классификатор → вопрос человеку)."""
    from .router import route
    from .project import active_project
    return _j(route(request, True, active_project()))


@mcp.tool()
def ask_model(task: str, prompt: str, project: str = "") -> str:
    """Вызвать внешнюю модель по задаче из config/routing.yaml (classify/extract/summarize/judge/critic/...). Стоимость учитывается."""
    from .llm import ask
    r = ask(task, prompt, pid=project or None)
    return _j({"model": r["model"], "usd": r["usd"], "cached": r["cached"], "text": r["text"]})


@mcp.tool()
def cost_report(project: str = "") -> str:
    """Стоимость проекта: внешние модели (точно) и IDE-модель (оценка)."""
    from .costs import summary
    from .project import project_dir
    return _j(summary(project_dir(project or None).name))


def main():
    setup_console()
    load_env()
    mcp.run()


if __name__ == "__main__":
    main()
