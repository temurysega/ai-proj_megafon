import pytest

from strategist import research


@pytest.mark.parametrize("header", [
    "---\nid: R1\nconsent: yes\n---",
    "<!-- Данные интервью -->\nid: R1\nconsent: yes — согласие на использование ответов\nроль: покупатель",
    "consent: да",
])
def test_explicit_consent_headers(header):
    assert research.has_interview_consent(header + "\n\nРеспондент: отвечаю.")


def test_interview_report_requires_consent_in_header_and_verifies_whole_quote(tmp_path, monkeypatch):
    real = tmp_path / "research" / "interviews" / "real"
    real.mkdir(parents=True)
    prefix = "Когда у меня не получается найти нужный учебный материал, я обычно спрашиваю "
    original = prefix + "знакомого преподавателя."
    forged = prefix + "сотрудника службы продаж."
    (real / "R01.md").write_text("consent: yes\n\n" + original, encoding="utf-8")
    (real / "R02.md").write_text("---\nconsent: no\n---\nВ черновике упомянуто consent: yes.", encoding="utf-8")
    (real / "R03.md").write_text("id: R03\n\nВопрос о согласии:\nconsent: yes", encoding="utf-8")

    def ask(task, prompt, **kwargs):
        assert kwargs["label"] == "code:R01"
        return {"json": {"pains": [
            {"text": "Поиск учебных материалов", "quote": original},
            {"text": "Подтверждение покупки", "quote": forged},
        ]}, "usd": 0}

    monkeypatch.setattr(research, "project_dir", lambda pid: tmp_path)
    monkeypatch.setattr(research, "ask", ask)
    monkeypatch.setattr(research, "journal", lambda *args, **kwargs: None)
    result = research.analyze_interviews(str(real))
    report = (tmp_path / result["file"]).read_text(encoding="utf-8")
    assert result["n"] == 1
    assert result["unverified_quotes"] == 1
    assert original in report
    assert forged not in report
    assert "Подтверждение покупки" not in report


def test_local_transcript_has_consent_and_no_pii():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("transcribe_local", root / "scripts" / "transcribe_local.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    doc, counts = mod.build_transcript("Мой телефон +7 916 123-45-67, звонили из банка.", "R06", "yes — устно перед записью", "small")
    assert research.has_interview_consent(doc) and "+7 916" not in doc and counts
    with pytest.raises(SystemExit):
        mod.build_transcript("текст", "R07", "нет", "small")
