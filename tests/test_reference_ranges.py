"""Проверка согласованного разбора диапазонов в документах и отчёте."""

from bs4 import BeautifulSoup

from strategist import evidence, project, render
from strategist.common import write_jsonl


def test_reference_ranges_include_each_claim_and_source():
    claims, sources = evidence.refs_in_text("[C998–C1001, C005; S002 - S004]")
    assert claims == {"C998", "C999", "C1000", "C1001", "C005"}
    assert sources == {"S002", "S003", "S004"}


def test_report_links_range_members_in_order():
    claims = {
        cid: {"kind": "hypothesis", "text": cid, "status": "active"}
        for cid in ("C001", "C002", "C003")
    }
    source = {"S001": {"title": "Исходный документ"}}
    text = "Вывод [C001—C003, S001]. [C003](notes.md). [C001, пояснение]."
    html = render._claim_links(text, claims, source)
    links = BeautifulSoup(html, "html.parser").find_all("a")
    assert [link["href"] for link in links] == ["#C001", "#C002", "#C003", "#S001"]
    assert "[C003](notes.md)" in html
    assert "[C001, пояснение]" in html


def test_missing_and_retracted_range_members_are_found(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(project, "PROJECTS", projects)
    monkeypatch.setattr(project, "ACTIVE_FILE", projects / ".active")
    workspace = project.new_project("ranges", "Диапазоны ссылок")
    findings = workspace / "research/findings.md"
    findings.write_text("## Результат\nВывод опирается на [C001–C003].\n", encoding="utf-8")
    claims = [evidence.add_claim(f"Гипотеза {n}", "hypothesis") for n in range(3)]
    retracted = evidence.retract_claim("C002", "Новая выгрузка изменила основание")
    assert retracted["impact"]["sections"] == [
        {"file": "research/findings.md", "section": "Результат", "via": ["C002"]}
    ]
    assert project.load_state()["stale"][0]["claims"] == ["C002"]
    assert any("отозванное утверждение C002" in msg for msg in evidence.check(strict=True)["errors"])
    assert any("C002 отозвано" in msg for msg in evidence.lint_file(findings))

    write_jsonl(workspace / "evidence/claims.jsonl", [claims[0], claims[2]])
    assert any("несуществующее утверждение C002" in msg for msg in evidence.check(strict=True)["errors"])
    assert any("нет утверждения C002" in msg for msg in evidence.lint_file(findings))


def test_invalid_and_excessive_ranges_remain_bounded():
    invalid = []
    text = "[C005–C003] [S001–C004] [C001–C1000000000]"
    claims, sources = evidence.refs_in_text(text, invalid_ranges=invalid)
    assert claims == {"C001", "C003", "C004", "C005", "C1000000000"}
    assert sources == {"S001"}
    assert invalid == ["C005–C003", "S001–C004", "C001–C1000000000"]
    assert render._claim_links(text, {}, {}) == text
