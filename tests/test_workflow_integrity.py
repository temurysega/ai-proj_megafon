"""Регрессии проверки стратегии, версий входных файлов и восстановления источников."""
import shutil
from pathlib import Path

import pytest

from strategist import evidence, ingest, project
from strategist.common import StrategistError, sha256_bytes
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
