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
VIDEO = [ROOT / "docs" / "video" / n for n in ("demo.mp4", "demo.vtt", "demo-poster.jpg")]


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
    media = [p for p in VIDEO if p.exists()]
    if media:
        subprocess.run(["scp", *ssh_opts, "-q", *[str(p) for p in media], f"{host}:{remote}/files/"], check=True)
    print(f"Выложено: index.html, {len(FILES)} PDF и {len(media)} файлов видео → {host}:{remote}")


if __name__ == "__main__":
    main()
