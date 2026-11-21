"""Регрессии строгой проверки перед приёмкой стратегии."""

import pytest

from strategist import evidence, project
from strategist.common import StrategistError, read_jsonl


@pytest.fixture
def review_project(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(project, "PROJECTS", projects)
    monkeypatch.setattr(project, "ACTIVE_FILE", projects / ".active")
    path = project.new_project("library", "Поиск книг")
    for name, headings in evidence.STRUCTURE.items():
        (path / name).write_text("".join(f"## {heading}\nОписание.\n" for heading in headings), encoding="utf-8")
    with (path / "options.md").open("a", encoding="utf-8") as options:
        options.write("".join(f"## Вариант {option}\nВозражения учтены.\n" for option in "ABC"))
    snapshot = path / "sources/raw/S001.md"
    quote = "Все экземпляры видны на странице книги."
    snapshot.write_text(quote, encoding="utf-8")
    source = evidence.add_source("Учебный каталог", "document", path="sources/raw/S001.md")
    evidence.add_claim(quote, "fact", sources=[source["id"]], quote=quote)
    project.gate("G1", "pass")
    project.gate("G2", "pass")
    project.set_stage("review", status="waiting_human")
    return path, snapshot, quote


@pytest.mark.parametrize("decision", ["pass", "assume"])
def test_g3_validates_latest_snapshot_before_recording_acceptance(review_project, decision):
    path, snapshot, quote = review_project
    if decision == "assume":
        state = project.load_state()
        state["mode"] = "autopilot"
        project.save_state(state)

    snapshot.write_text("Остатки скрыты в каталоге.", encoding="utf-8")
    state_before = project.load_state()
    with pytest.raises(StrategistError, match=r"G3_strategy требуют строгой проверки[\s\S]*C001: цитата не подтверждена"):
        project.gate("G3", decision)
    assert project.load_state() == state_before
    assert read_jsonl(path / "journal.jsonl")[-1]["status"] == "failed"

    snapshot.write_text(quote, encoding="utf-8")
    state = project.gate("G3", decision, note="Условия проверки согласованы")
    assert state["gates"]["G3_strategy"]["status"] == "passed"
    assert state["stage_status"] == "in_progress"


def test_g3_validates_prior_outputs_even_when_stage_is_earlier(review_project):
    path, _, _ = review_project
    project.set_stage("options")
    (path / "research/plan.md").unlink()

    with pytest.raises(StrategistError, match=r"G3_strategy[\s\S]*research/plan.md"):
        project.gate("G3", "pass")
    assert project.load_state()["gates"]["G3_strategy"]["status"] == "pending"


def test_g3_can_record_rejection_and_reapprove_during_support(review_project):
    _, snapshot, quote = review_project
    project.gate("G3", "pass")
    project.set_stage("support")
    snapshot.write_text("Снимок обновлён.", encoding="utf-8")

    declined = project.gate("G3", "reject", note="Перед согласованием нужна новая сверка")
    assert declined["gates"]["G3_strategy"]["status"] == "rejected"

    snapshot.write_text(quote, encoding="utf-8")
    approved = project.gate("G3", "pass")
    assert approved["stage"] == "support"
    assert approved["gates"]["G3_strategy"]["status"] == "passed"
