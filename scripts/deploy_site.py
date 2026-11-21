"""Выкладка сайта на свой сервер: python scripts/deploy_site.py

Собирает папку dist (site/index.html + PDF: описание работы и отчёты проектов) и копирует её по SSH
в каталог, который раздаёт контейнер `strategist-site` (nginx), стоящий за Caddy.
Адрес сервера и ключ не хранятся в репозитории — задаются переменными окружения:
  STRATEGIST_DEPLOY_HOST  например root@example.com
  STRATEGIST_DEPLOY_KEY   путь к приватному SSH-ключу (необязательно)
  STRATEGIST_DEPLOY_DIR   каталог на сервере (по умолчанию /opt/strategist-site/html)
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "files/description.pdf": ROOT / "docs" / "report" / "description.pdf",
    "files/family-connect.pdf": ROOT / "projects" / "family-connect" / "report" / "index.pdf",
    "files/antifraud-family.pdf": ROOT / "projects" / "antifraud-family" / "report" / "index.pdf",
    "files/esim-travel.pdf": ROOT / "projects" / "esim-travel" / "report" / "index.pdf",
    "files/family-connect.mp4": ROOT / "docs" / "video" / "Стратег Фабрики продуктов — демо «Связь для близких и собственных устройств».mp4",
}
FILES.update({
    f"files/{name}": ROOT / "docs" / "video" / name
    for name in ("family-connect.vtt", "family-connect-poster.jpg")
})
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


def build_site():
    dist = ROOT / ".cache" / "site-dist"
    (dist / "files").mkdir(parents=True, exist_ok=True)
    for rel, src in FILES.items():
        if not src.is_file():
            sys.exit(f"Нет файла из комплекта сайта: {src.relative_to(ROOT)}")
        shutil.copy2(src, dist / rel)
    optional = []
    for name, candidates in VIDEO.items():
        src = next((ROOT / "docs" / "video" / c for c in candidates if (ROOT / "docs" / "video" / c).exists()), None)
        if src and name.endswith(".mp4") and not has_audio(src):
            # 18.11: озвученный файл переименовали, и на сайт ушла немая версия под заголовком «Видео с голосом»
            print(f"⚠ {src.name} без звуковой дорожки — не выложено. Соберите голос: python scripts/voiceover.py")
            continue
        if src:
            dest = dist / "files" / name
            shutil.copy2(src, dest)
            optional.append(dest)
    shutil.copy2(ROOT / "site" / "index.html", dist / "index.html")
    return dist, [*(dist / rel for rel in FILES), *optional]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Собрать и выложить сайт агента")
    parser.add_argument("--build-only", action="store_true", help="собрать локально, без SSH")
    args = parser.parse_args()
    host = os.environ.get("STRATEGIST_DEPLOY_HOST")
    if not args.build_only and not host:
        sys.exit("Задайте STRATEGIST_DEPLOY_HOST или запустите с --build-only")
    dist, files = build_site()
    if args.build_only:
        print(f"Собрано: {dist.relative_to(ROOT)}")
        return
    remote = os.environ.get("STRATEGIST_DEPLOY_DIR", "/opt/strategist-site/html")
    key = os.environ.get("STRATEGIST_DEPLOY_KEY")
    ssh_opts = ["-o", "IdentitiesOnly=yes", "-i", key] if key else []
    subprocess.run(["ssh", *ssh_opts, host, f"mkdir -p {remote}/files"], check=True)
    subprocess.run(["scp", *ssh_opts, "-q", *map(str, files), f"{host}:{remote}/files/"], check=True)
    subprocess.run(["scp", *ssh_opts, "-q", str(dist / "index.html"), f"{host}:{remote}/index.html"], check=True)
    print(f"Выложено: index.html и {len(files)} файлов → {host}:{remote}")


if __name__ == "__main__":
    main()
