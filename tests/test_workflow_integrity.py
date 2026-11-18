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


def test_late_stage_checks_all_earlier_gates(workspace):
    with pytest.raises(StrategistError, match="G1_brief"):
        project.set_stage("review")
    assert project.load_state()["stage"] == "intake"
    project.gate("G1", "pass")
    with pytest.raises(StrategistError, match="G2_option"):
        project.set_stage("review")
    project.gate("G2", "pass")
    project.set_stage("review")
    with pytest.raises(StrategistError, match="G3_strategy"):
        project.set_stage("support")


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
