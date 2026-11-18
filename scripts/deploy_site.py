"""Выкладка сайта на свой сервер: python scripts/deploy_site.py

Собирает папку dist (site/index.html + PDF: описание работы и отчёты проектов) и копирует её по SSH
в каталог, который раздаёт контейнер `strategist-site` (nginx), стоящий за Caddy.
Адрес сервера и ключ не хранятся в репозитории — задаются переменными окружения:
  STRATEGIST_DEPLOY_HOST  например root@example.com
  STRATEGIST_DEPLOY_KEY   путь к приватному SSH-ключу (необязательно)
  STRATEGIST_DEPLOY_DIR   каталог на сервере (по умолчанию /opt/strategist-site/html)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "files/description.pdf": ROOT / "docs" / "report" / "description.pdf",
    "files/antifraud-family.pdf": ROOT / "projects" / "antifraud-family" / "report" / "index.pdf",
    "files/esim-travel.pdf": ROOT / "projects" / "esim-travel" / "report" / "index.pdf",
}
# Видео: имя на сайте → локальные файлы по приоритету (версия с голосом из scripts/voiceover.py, если собрана).
VIDEO = {
    "demo.mp4": ["demo-voice.mp4", "demo.mp4"],
    "demo.vtt": ["demo-voice.vtt", "demo.vtt"],
    "demo-poster.jpg": ["demo-poster.jpg"],
}


def has_audio(path: Path) -> bool:
    """Есть ли в видео звуковая дорожка (ffmpeg из imageio-ffmpeg)."""
    try:
        import imageio_ffmpeg
    except ImportError:
        return True  # проверить нечем — не блокируем
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return "Audio:" in r.stderr


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    host = os.environ.get("STRATEGIST_DEPLOY_HOST")
    if not host:
        sys.exit("Задайте STRATEGIST_DEPLOY_HOST, например: set STRATEGIST_DEPLOY_HOST=root@example.com")
    remote = os.environ.get("STRATEGIST_DEPLOY_DIR", "/opt/strategist-site/html")
    key = os.environ.get("STRATEGIST_DEPLOY_KEY")
    ssh_opts = ["-o", "IdentitiesOnly=yes", "-i", key] if key else []
    dist = ROOT / ".cache" / "site-dist"
    shutil.rmtree(dist, ignore_errors=True)
    (dist / "files").mkdir(parents=True)
    shutil.copy2(ROOT / "site" / "index.html", dist / "index.html")
    for rel, src in FILES.items():
        if not src.exists():
            sys.exit(f"Нет файла {src} — соберите отчёты: python sf.py render --pdf; python scripts/build_description.py")
        shutil.copy2(src, dist / rel)
    subprocess.run(["ssh", *ssh_opts, host, f"mkdir -p {remote}/files"], check=True)
    subprocess.run(["scp", *ssh_opts, "-q", str(dist / "index.html"), f"{host}:{remote}/index.html"], check=True)
    subprocess.run(["scp", *ssh_opts, "-q", *[str(dist / r) for r in FILES], f"{host}:{remote}/files/"], check=True)
    # Видео демо (scripts/record_video.py): большой файл не хранится в git, выкладывается, если записан локально.
    media = 0
    for name, candidates in VIDEO.items():
        src = next((ROOT / "docs" / "video" / c for c in candidates if (ROOT / "docs" / "video" / c).exists()), None)
        if src and name.endswith(".mp4") and not has_audio(src):
            # 18.11: озвученный файл переименовали, и на сайт ушла немая версия под заголовком «Видео с голосом»
            print(f"⚠ {src.name} без звуковой дорожки — видео не выложено. Соберите голос: python scripts/voiceover.py")
            continue
        if src:
            subprocess.run(["scp", *ssh_opts, "-q", str(src), f"{host}:{remote}/files/{name}"], check=True)
            media += 1
    print(f"Выложено: index.html, {len(FILES)} PDF и {media} файлов видео → {host}:{remote}")


if __name__ == "__main__":
    main()
