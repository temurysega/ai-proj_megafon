"""Общие утилиты: пути, чтение/запись YAML/JSONL, время, идентификаторы."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
CONFIG = ROOT / "config"
KNOWLEDGE = ROOT / "knowledge"
MEMORY = ROOT / "memory"
CACHE = ROOT / ".cache"
ACTIVE_FILE = PROJECTS / ".active"

STAGES = ["intake", "materials", "research", "options", "strategy", "review", "support"]
STAGE_TITLES = {
    "intake": "0. Постановка задачи",
    "materials": "1. Сбор материалов",
    "research": "2. Исследование",
    "options": "3. Варианты и выбор",
    "strategy": "4. Стратегия",
    "review": "5. Проверка качества",
    "support": "6. Сопровождение решения",
}
CLAIM_KINDS = ["fact", "estimate", "hypothesis", "forecast", "assumption", "synthetic", "opinion"]
CLAIM_KIND_RU = {
    "fact": "факт", "estimate": "расчёт", "hypothesis": "гипотеза", "forecast": "прогноз",
    "assumption": "допущение", "synthetic": "синтетика", "opinion": "мнение",
}
CLAIM_STATUSES = ["active", "disputed", "retracted", "superseded"]


def setup_console() -> None:
    """UTF-8 вывод в консоль Windows (кириллица)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return _dt.date.today().isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=110)
    os.replace(tmp, path)  # атомарная запись: обрыв не портит файл


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"_broken_line": i, "raw": line[:200]})
    return out


def append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, recs: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def next_id(prefix: str, existing: Iterable[str], width: int = 3) -> str:
    n = 0
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for e in existing:
        m = pat.match(str(e))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:0{width}d}"


def slugify(s: str, maxlen: int = 40) -> str:
    tr = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    })
    s = s.lower().translate(tr)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen] or "item"


class StrategistError(Exception):
    """Ошибка, понятная пользователю (без трейсбэка)."""
