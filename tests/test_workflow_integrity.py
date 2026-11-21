"""Регрессии проверки стратегии, версий входных файлов и восстановления источников."""
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from strategist import evidence, ingest, project
from strategist.common import StrategistError, native_file_path, sha256_bytes
from strategist.data import profile


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(project, "PROJECTS", projects)
    monkeypatch.setattr(project, "ACTIVE_FILE", projects / ".active")
    return project.new_project("fixture", "Новый проект")


def test_versions_and_retries_keep_independent_portable_sources(workspace, tmp_path):
    upload = tmp_path / "Показатели.csv"
    versions = []
    for value in [20, 80]:
        upload.write_text(f"total\n{value}\n", encoding="utf-8")
        source = ingest.ingest(str(upload))
        assert ingest.ingest(str(upload)) == source
        versions.append(source)
    assert [s["id"] for s in evidence.load_sources()] == ["S001", "S002"]
    moved = tmp_path / "Копия проекта"
    shutil.copytree(workspace, moved)
    for source, value in zip(versions, [20, 80]):
        stored = Path(source["path"])
        assert not stored.is_absolute()
        data = (moved / stored).read_bytes()
        assert sha256_bytes(data) == source["sha256"]
        assert data.decode().splitlines() == ["total", str(value)]
        snapshot = evidence.snapshot_text(source, moved)
        assert "1 строк × 1 столбцов" in snapshot and str(value) in snapshot
        assert profile(str(workspace / stored))["cols"] == 1


def test_imported_table_in_deep_checkout(tmp_path, monkeypatch):
    projects = tmp_path / ("p" * max(1, 190 - len(str(tmp_path)))) / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(project, "PROJECTS", projects)
    monkeypatch.setattr(project, "ACTIVE_FILE", projects / ".active")
    workspace = project.new_project("fixture", "Длинный путь")
    upload = tmp_path / "Показатели.csv"
    data = b"total\n20\n"
    upload.write_bytes(data)
    digest = sha256_bytes(data)
    stored = workspace / "sources" / "raw" / "originals" / f"{digest}.csv"
    profile_path = workspace / "research" / "data" / f"profile-{digest}.md"
    assert len(str(stored)) > 260
    try:
        source = ingest.ingest(str(upload))
        assert ingest.ingest(str(upload)) == source
        assert workspace / source["path"] == stored
        assert native_file_path(stored).read_bytes() == data
        assert profile(source["path"])["cols"] == 1
        assert native_file_path(profile_path).is_file()
    finally:
        # Старые функции очистки Windows не видят имена длиной >260 без префикса.
        native_file_path(profile_path).unlink(missing_ok=True)
        native_file_path(stored).unlink(missing_ok=True)


def test_internal_file_named_like_snapshot_is_archived(workspace):
    note = workspace / "sources/raw/S001.md"
    note.write_text("до правки", encoding="utf-8")
    first = ingest.ingest(str(note))
    note.write_text("после правки", encoding="utf-8")
    second = ingest.ingest(str(note))
    assert first["id"] != second["id"]
    assert (workspace / first["path"]).read_text(encoding="utf-8") == "до правки"
    assert "до правки" in evidence.snapshot_text(first, workspace)
    assert "после правки" in evidence.snapshot_text(second, workspace)


def test_identical_media_can_be_enriched_once(workspace, tmp_path, monkeypatch):
    clip = tmp_path / "demo.mp4"
    clip.write_bytes(b"fixture")
    modes = []

    def analyze(path, *, transcribe, describe, pid):
        modes.append((describe, transcribe))
        body = "\nкадр с ценой" if describe else ""
        if transcribe:
            body += "\nрасшифровка"
        return "[видео] кадров: 1" + body, 0.0

    monkeypatch.setattr(ingest, "process_video", analyze)
    args = dict(file=str(clip), public_media=True)
    first = ingest.ingest(**args)
    ingest.ingest(**args, describe=True)
    result = ingest.ingest(**args, describe=True, transcribe=True)
    assert result["id"] == first["id"]
    assert result == ingest.ingest(**args, describe=True, transcribe=True) == ingest.ingest(**args)
    assert modes == [(False, False), (True, False), (False, True)]
    text = evidence.snapshot_text(result, workspace)
    assert "кадр с ценой" in text and "расшифровка" in text


BRIEF = ("# Бриф\n## Решаемый вопрос\nПочему падает удержание\n## Цель\nВернуть удержание\n## Получатель\nCPO\n"
         "## Ограничения\nТолько открытые данные\n## Доступные данные\nОтчёты\n")


def test_late_stage_checks_all_earlier_gates(workspace):
    with pytest.raises(StrategistError, match="G1_brief"):
        project.set_stage("review")
    assert project.load_state()["stage"] == "intake"
    # ворота нельзя пройти, пока нечего подтверждать (ревью 18.11: пустой проект проходил G1 и G2)
    with pytest.raises(StrategistError, match="brief.md"):
        project.gate("G1", "pass")
    (workspace / "brief.md").write_text(BRIEF, encoding="utf-8")
    project.gate("G1", "pass")
    with pytest.raises(StrategistError, match="options.md"):
        project.gate("G2", "pass")
    (workspace / "options.md").write_text("".join(f"## Вариант {x}\nтекст\n" for x in "ABC"), encoding="utf-8")
    (workspace / "research" / "findings.md").write_text("# Картина\nизвестно\n", encoding="utf-8")
    project.gate("G2", "pass")
    # ворота пройдены, но результатов стадий материалов и исследования нет — перепрыгнуть нельзя
    with pytest.raises(StrategistError, match="результаты предыдущих стадий"):
        project.set_stage("review")
    with pytest.raises(StrategistError, match="G3_strategy|результаты"):
        project.set_stage("support")


def test_gates_go_in_order(workspace):
    (workspace / "brief.md").write_text(BRIEF, encoding="utf-8")
    with pytest.raises(StrategistError, match="по порядку"):
        project.gate("G2", "pass")
    with pytest.raises(StrategistError, match="по порядку"):
        project.gate("G3", "pass")


def test_check_requires_previous_stages_and_strict_requires_current_output(workspace):
    assert not evidence.check()["errors"]
    assert any("brief.md" in e for e in evidence.check(strict=True)["errors"])
    # Сохранённое состояние старой версии могло пропустить ворота.
    state = project.load_state()
    state["stage"] = "review"
    project.save_state(state)
    ordinary = evidence.check()["errors"]
    assert any("G2_option" in e for e in ordinary)
    assert any("communication.md" in e for e in ordinary)
    assert any("validation.md" in e for e in ordinary)
    assert any("one-pager.md" in e for e in evidence.check(strict=True)["errors"])


def test_strict_rechecks_quotes_after_source_changes(workspace, tmp_path):
    note = tmp_path / "note.txt"
    first = "Пользователи подтвердили получение уведомления о звонке."
    second = "Выбор тарифа обсуждался в конце интервью."
    note.write_text(first + "\n" + second, encoding="utf-8")
    source = ingest.ingest(str(note))
    evidence.add_claim("Оповещение получено", "fact", [source["id"]], quote=first)
    evidence.add_claim("Обсуждали оповещение и тариф", "fact", [source["id"]], quote=first + " … " + second)
    result = evidence.check(strict=True)
    assert result["metrics"]["quote_matches_in_current_snapshots"] == {"verbatim": 1, "partial": 1}
    assert any("C002" in warning for warning in result["warnings"])
    (workspace / source["text_path"]).write_text("Обновлённый текст.", encoding="utf-8")
    failed = evidence.check(strict=True)
    assert failed["metrics"]["quote_matches_in_current_snapshots"] == {"not_found": 2}
    assert any("C001" in error for error in failed["errors"])


def test_fact_with_invented_quote_is_refused(workspace, tmp_path):
    # ревью 18.11: `claim add --kind fact --quote "выдуманная цитата"` проходил с кодом 0
    note = tmp_path / "отчёт.md"
    note.write_text("Выручка выросла на 12% в 2025 году.", encoding="utf-8")
    src = ingest.ingest(str(note))
    with pytest.raises(StrategistError, match="не найдена"):
        evidence.add_claim("Выручка выросла", "fact", [src["id"]], quote="выдуманная цитата")
    ok = evidence.add_claim("Выручка выросла на 12%", "fact", [src["id"]], quote="Выручка выросла на 12% в 2025 году")
    assert ok["quote_status"] == "verbatim"
    scan = evidence.add_claim("Цифра со скана", "fact", [src["id"]], quote="3,999", locator="стр. 4, таблица 2",
                              unverified_quote=True)
    assert "не сверена" in scan["note"]


def test_one_pager_cost_must_match_ledger(workspace):
    (workspace / "strategy" / "one-pager.md").write_text("# Резюме\n## Решение\nx\n## Стоимость\n**Стоимость проекта ≈ $9,99**\n",
                                                          encoding="utf-8")
    (workspace / "costs.jsonl").write_text('{"type": "subagent", "usd": 1.0, "tokens": 1000}\n', encoding="utf-8")
    assert any("расходится с журналом" in e for e in evidence.check()["errors"])
    (workspace / "strategy" / "one-pager.md").write_text("# Резюме\n**Стоимость проекта ≈ $1,00**\n", encoding="utf-8")
    assert not any("расходится" in e for e in evidence.check()["errors"])


def test_fact_without_quote_is_refused_and_flagged(workspace, tmp_path):
    # ревью 18.11: `claim add` сохранял активный факт с источником и пустой цитатой, обычный check давал только предупреждение
    note = tmp_path / "заметка.md"
    note.write_text("Абонентов стало больше.", encoding="utf-8")
    src = ingest.ingest(str(note))
    with pytest.raises(StrategistError, match="цитат"):
        evidence.add_claim("Абонентов стало больше", "fact", [src["id"]])
    claims = evidence.load_claims()
    claims.append({"id": "C900", "text": "старый факт без цитаты", "kind": "fact", "sources": [src["id"]], "quote": "",
                   "locator": "", "status": "active"})
    evidence.write_jsonl(evidence._claims_path(None), claims)
    assert any("C900" in e and "без дословной цитаты" in e for e in evidence.check()["errors"])


def test_deliverable_structure_from_brief_is_checked(workspace):
    # бриф организаторов задаёт «один документ из пяти частей» — sf check требует все части
    deliv = project.set_deliverable("strategy/document.md", template="strategy-document-5parts")
    assert len(deliv["sections"]) == 5 and deliv["sections"][0] == "Клиент и его проблема"
    state = project.load_state()
    state["stage"] = "review"
    project.save_state(state)
    (workspace / "strategy" / "document.md").write_text("# Стратегия\n## 1. Клиент и его проблема\nтекст\n", encoding="utf-8")
    errors = evidence.check()["errors"]
    assert any("Ресурсы, риски и решение руководителя" in e for e in errors)
    assert not any("«Клиент и его проблема»" in e for e in errors)


def test_report_includes_brief_required_document(workspace):
    # документ, которого требует бриф, попадает в отчёт сразу после резюме
    from strategist import render
    project.set_deliverable("strategy/document.md", template="strategy-document-5parts")
    (workspace / "strategy" / "one-pager.md").write_text("# Резюме\n## Решение\nПилот\n", encoding="utf-8")
    (workspace / "strategy" / "document.md").write_text("# Стратегия\n## 1. Клиент и его проблема\nтекст\n", encoding="utf-8")
    out = render.build(pdf=False)
    html_text = (workspace / out["html"]).read_text(encoding="utf-8")
    assert "Стратегия в формате брифа" in html_text and "Клиент и его проблема" in html_text
    assert html_text.index("Резюме для руководителя") < html_text.index("Стратегия в формате брифа")


def test_report_links_keep_project_paths_and_internal_anchors(workspace):
    from strategist import render

    (workspace / "strategy" / "one-pager.md").write_text(
        "# Резюме\n[План](validation.md) · [Бриф](../brief.md#goal) · "
        "[Цитата](#C001) · [Источник](https://example.org/page)\n",
        encoding="utf-8",
    )
    out = render.build()
    text = (workspace / out["html"]).read_text(encoding="utf-8")
    assert 'href="../strategy/validation.md"' in text
    assert 'href="../brief.md#goal"' in text
    assert 'href="#C001"' in text
    assert 'href="https://example.org/page"' in text


def test_import_preserves_checkpoint_and_refuses_to_overwrite(workspace, tmp_path, monkeypatch):
    from strategist import cli, common

    project.checkpoint("Выбран следующий шаг", "Собрать материалы", waiting_human=True)
    archive_root = tmp_path / "archives"
    archive_root.mkdir()
    monkeypatch.setattr(cli, "ROOT", archive_root)
    cli.cmd_export(SimpleNamespace(project=workspace.name))

    projects_copy = tmp_path / "Копия репозитория" / "projects"
    projects_copy.mkdir(parents=True)
    monkeypatch.setattr(common, "PROJECTS", projects_copy)
    args = SimpleNamespace(zip=archive_root / f"{workspace.name}-export.zip")
    cli.cmd_import(args)
    state = projects_copy / workspace.name / "state.yaml"
    assert common.read_yaml(state)["next_action"] == "Собрать материалы"
    state.write_text("stage: materials\n", encoding="utf-8")
    with pytest.raises(StrategistError, match="уже существует"):
        cli.cmd_import(args)
    assert common.read_yaml(state)["stage"] == "materials"


def test_scan_secrets_in_unpacked_repository(tmp_path):
    from strategist.safety import scan_repo_secrets

    (tmp_path / "notes.txt").write_text("sk-or-v1-" + "a1" * 16, encoding="utf-8")
    assert scan_repo_secrets(tmp_path) == ["notes.txt: OpenRouter key: sk-or-v1-a…"]


def test_download_checks_each_redirect_before_request(monkeypatch):
    from strategist import web

    source_url = "https://www.cbr.ru/start"
    intermediate_url = "https://www.cbr.ru/next"
    session = MagicMock(max_redirects=5, headers={})
    session.__enter__.return_value = session
    session.get.side_effect = [SimpleNamespace(url=source_url), SimpleNamespace(url=intermediate_url)]
    session.get_redirect_target.side_effect = ["/next", "https://outside.invalid/doc"]
    monkeypatch.setattr(web.requests, "Session", lambda: session)

    with pytest.raises(StrategistError, match="Переадресация запрещена"):
        web._download(source_url)
    assert [call.args[0] for call in session.get.call_args_list] == [source_url, intermediate_url]
    assert all(call.kwargs["allow_redirects"] is False for call in session.get.call_args_list)
