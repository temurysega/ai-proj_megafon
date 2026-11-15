"""Наложение закадрового голоса на демо-видео по таймингам: python scripts/voiceover.py --voice <запись диктора>

Вход: docs/video/demo.mp4 (без звука, scripts/record_video.py), docs/video/timeline.json (подписи в кадре),
docs/video/voice_anchors.json (опорные точки: начало фразы в записи → подпись видео, к которой она относится).
Каждый кусок голоса ставится на момент своей подписи. Если фраза длиннее сцены, последний кадр сцены удерживается,
пока фраза не закончится. Субтитры и главы сдвигаются на те же удержания.
Выход: docs/video/demo-voice.mp4, demo-voice.vtt, subtitles-voice.srt, timeline-voice.json.
Сама запись голоса в репозитории не хранится.
"""
import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
VID = ROOT / "docs" / "video"
SR = 48000
FPS = 25           # запись Playwright — постоянные 25 кадров/с
LEAD = 0.25        # голос начинается чуть позже появления подписи
GAP = 0.35         # минимальная пауза между кусками голоса
SWITCH_PAD = 1.0   # кадр удерживаем за секунду до смены сцены (страница могла уже начать переход)
PRE, TAIL = 0.12, 0.25


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def video_duration(ff, path):
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next(x for x in r.stderr.splitlines() if "Duration" in x)
    h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def load_voice(ff, src):
    tmp = ROOT / ".cache" / "voice" / "voice48k.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(tmp)], check=True)
    with wave.open(str(tmp)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=str(ROOT / ".cache" / "voice" / "voice.ogg"))
    args = ap.parse_args()
    ff = ffmpeg()
    tl = json.loads((VID / "timeline.json").read_text(encoding="utf-8"))
    anchors = json.loads((VID / "voice_anchors.json").read_text(encoding="utf-8"))["anchors"]
    src_mp4 = VID / "demo.mp4"
    dur = video_duration(ff, src_mp4)

    def vtime(cap):  # момент появления подписи (для финальной заставки — момент её показа)
        if cap == "end":
            return tl[-1]["end"] - 0.4
        return 0.5 if cap == 0 else tl[cap]["start"]

    # куски голоса: [начало фразы − PRE, конец последнего слова + TAIL], без наложения на соседей
    pieces = []
    for k, a in enumerate(anchors):
        nxt = anchors[k + 1]["audio_start"] if k + 1 < len(anchors) else a["audio_end"] + 1
        prev_end = pieces[-1]["a1"] if pieces else 0.0
        a0 = max(a["audio_start"] - PRE, prev_end, 0.0)
        a1 = min(a["audio_end"] + TAIL, nxt - 0.02) if k + 1 < len(anchors) else a["audio_end"] + TAIL
        pieces.append({"cap": a["caption"], "v": vtime(a["caption"]), "a0": a0, "a1": max(a1, a0 + 0.1)})

    holds = []  # (время в исходном видео, длительность удержания)

    def new(t):
        return t + sum(d for th, d in holds if th < t)

    for k, p in enumerate(pieces):
        p["start"] = new(p["v"]) + LEAD
        end = p["start"] + (p["a1"] - p["a0"])
        if k + 1 < len(pieces):
            nv = pieces[k + 1]["v"]
            short = end + GAP - (new(nv) + LEAD)
            if short > 0:
                holds.append((nv - SWITCH_PAD, round(short + 0.05, 2)))
        else:
            short = end + 1.2 - new(dur)
            if short > 0:
                holds.append((dur - 0.05, round(short, 2)))
    total = new(dur)  # удержание в самом конце (th = dur − 0.05) уже учтено

    # --- видео: удерживаем кадр повтором (loop) в точках удержания; индексы сдвигаются на уже вставленные кадры ---
    loops, inserted = [], 0
    for th, d in sorted(holds):
        n = max(1, round(d * FPS))
        loops.append(f"loop=loop={n}:size=1:start={round(th * FPS) + inserted}")
        inserted += n
    filt = ["[0:v]" + ",".join(loops + [f"setpts=N/{FPS}/TB"]) + "[vout]"]

    # --- звук: собираем дорожку из кусков голоса с короткими затуханиями на краях ---
    voice = load_voice(ff, args.voice)
    track = np.zeros(int((total + 1) * SR), dtype=np.float32)
    fade = int(0.015 * SR)
    for p in pieces:
        seg = voice[int(p["a0"] * SR):int(p["a1"] * SR)].copy()
        if len(seg) > 2 * fade:
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        i0 = int(p["start"] * SR)
        track[i0:i0 + len(seg)] += seg[:max(0, len(track) - i0)]
    wav = ROOT / ".cache" / "voice" / "track.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())

    out = VID / "demo-voice.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src_mp4), "-i", str(wav),
                    "-filter_complex", ";".join(filt) + ";[1:a]highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]",
                    "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-shortest", "-movflags", "+faststart", str(out)], check=True)

    # --- субтитры и разметка, сдвинутые на удержания ---
    tl2 = [{"start": round(new(c["start"]), 3), "end": round(new(c["end"]), 3), "text": c["text"]} for c in tl]
    for i in range(len(tl2) - 1):  # подпись перед удержанием остаётся на экране, пока кадр удерживается
        tl2[i]["end"] = tl2[i + 1]["start"]
    (VID / "timeline-voice.json").write_text(json.dumps({"holds": holds, "captions": tl2}, ensure_ascii=False, indent=1), encoding="utf-8")

    def ts(x, sep):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", sep)
    (VID / "demo-voice.vtt").write_text("WEBVTT\n\n" + "\n".join(f"{ts(c['start'], '.')} --> {ts(c['end'], '.')}\n{c['text']}\n" for c in tl2),
                                        encoding="utf-8")
    (VID / "subtitles-voice.srt").write_text("\n".join(f"{i}\n{ts(c['start'], ',')} --> {ts(c['end'], ',')}\n{c['text']}\n"
                                                       for i, c in enumerate(tl2, 1)), encoding="utf-8")
    print(f"Готово: {out} ({out.stat().st_size // 1024 // 1024} МБ), длительность {video_duration(ff, out):.1f} с "
          f"(было {dur:.1f}); удержаний кадра: {len(holds)} = {', '.join(f'{th:.1f} с +{d:.1f}' for th, d in holds)}")
    for p in pieces:
        print(f"  подпись {p['cap']!s:>4}: голос {p['a0']:6.2f}–{p['a1']:6.2f} → {p['start']:6.2f}")


if __name__ == "__main__":
    main()
