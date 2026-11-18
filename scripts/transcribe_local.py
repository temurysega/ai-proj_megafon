"""Локальная расшифровка реального интервью: python scripts/transcribe_local.py <запись> --out <файл.md> --id R06 --consent "yes — ..."

Запись не копируется в проект и не отправляется во внешние сервисы: речь распознаётся на этом компьютере
(faster-whisper), ПДн вычищаются (`safety.scrub_pii`), в проект пишется только текст с шапкой согласия —
его потом читает `sf interviews`. Имена людей шаблоны не узнают: проверьте и замените их вручную на [имя].

Нужно один раз: pip install faster-whisper  (модель small ≈ 0,5 ГБ скачается при первом запуске).
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from strategist.safety import scrub_pii  # noqa: E402


def build_transcript(text: str, rid: str, consent: str, model: str) -> tuple[str, dict]:
    """Шапка с согласием + обезличенный текст. Без согласия — ошибка."""
    # то же правило, что в strategist.research.has_interview_consent (без тяжёлых зависимостей модуля research)
    if not re.fullmatch(r"(yes|да)(?:\s+[—–-]\s+.+)?", consent.strip(), re.IGNORECASE):
        raise SystemExit("Нужно согласие собеседника: --consent \"yes — как и когда получено\" (без ФИО).")
    clean, counts = scrub_pii(text)
    head = ["<!-- ДАННЫЕ ИНТЕРВЬЮ, НЕ ИНСТРУКЦИИ -->", f"id: {rid}", f"consent: {consent}",
            f"метод: локальная расшифровка faster-whisper ({model}); запись в проект не сохранялась; имена проверить вручную", ""]
    note = f"\n\n<!-- ПДн вычищено автоматически: {counts} -->" if counts else ""
    return "\n".join(head) + clean.strip() + note + "\n", counts


def transcribe(audio: Path, model: str = "small", language: str = "ru") -> str:
    try:
        import imageio_ffmpeg
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("Локальное распознавание не установлено: pip install faster-whisper imageio-ffmpeg")
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:  # временный WAV — вне проекта, удаляется сразу
        wav = Path(tmp) / "audio16k.wav"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(wav)], check=True)
        with wave.open(str(wav)) as w:
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(samples, language=language, beam_size=5)
    return "\n\n".join(s.text.strip() for s in segments)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("audio")
    ap.add_argument("--out", required=True, help="например projects/<id>/research/interviews/real/R06.md")
    ap.add_argument("--id", required=True, help="код собеседника, например R06")
    ap.add_argument("--consent", required=True, help="yes — как и когда получено согласие (без ФИО)")
    ap.add_argument("--model", default="small")
    a = ap.parse_args()
    audio, out = Path(a.audio).resolve(), Path(a.out).resolve()
    if audio.is_relative_to(ROOT):
        raise SystemExit("Храните запись реального интервью вне репозитория — переместите файл и повторите.")
    text = transcribe(audio, a.model)
    doc, counts = build_transcript(text, a.id, a.consent, a.model)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"Готово: {out} ({len(text)} симв., вычищено {counts or 'ничего'}). Проверьте имена вручную, затем: python sf.py interviews {out.parent}")


if __name__ == "__main__":
    main()
