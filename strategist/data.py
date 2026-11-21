"""Анализ данных: профиль набора (единицы, периоды, пропуски, выбросы, дубли) и
воспроизводимый запуск аналитических скриптов с фиксацией хэшей входов и выходов."""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

from .common import StrategistError, native_file_path, now, sha256_bytes
from .project import journal, project_dir


def read_delimited_table(path: Path):
    """Ограниченный набор разделителей сохраняет CSV из одного столбца."""
    import pandas as pd
    delimiter = "\t"
    if path.suffix.lower() != ".tsv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(16384)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    return pd.read_csv(path, sep=delimiter)


def _read(path: Path):
    if path.suffix.lower() in (".xlsx", ".xls"):
        import pandas as pd
        return pd.read_excel(path)
    return read_delimited_table(path)


def _resolve(path: str, pid, what: str) -> Path:
    """Путь от текущей папки или от папки проекта (`research/data/x.py` работает из корня репозитория)."""
    p = native_file_path(Path(path))
    if p.exists():
        return p
    q = native_file_path(project_dir(pid) / path)
    if q.exists():
        return q
    raise StrategistError(f"Нет {what} {path} (искали от текущей папки и от папки проекта {project_dir(pid).name})")


def profile(file: str, pid=None) -> dict:
    import numpy as np
    import pandas as pd
    p = _resolve(file, pid, "файла")
    df = _read(p)
    issues, cols = [], []
    dups = int(df.duplicated().sum())
    if dups:
        issues.append(f"Полных дублей строк: {dups}")
    for c in df.columns:
        s = df[c]
        info = {"col": str(c), "dtype": str(s.dtype), "missing_pct": round(100 * s.isna().mean(), 1),
                "unique": int(s.nunique())}
        if info["missing_pct"] > 0:
            issues.append(f"«{c}»: пропусков {info['missing_pct']}%")
        name = str(c).lower()
        # даты и периоды
        if s.dtype == object or "date" in name or "дата" in name or "период" in name or "month" in name:
            dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
            if dt.notna().mean() > 0.8:
                info["date_min"], info["date_max"] = str(dt.min().date()), str(dt.max().date())
                diffs = dt.dropna().sort_values().diff().dropna().dt.days
                if len(diffs):
                    step = int(diffs.mode().iloc[0])
                    info["period_step_days"] = step
                    gaps = int((diffs > step * 1.5).sum()) if step else 0
                    if gaps:
                        issues.append(f"«{c}»: пропущенных периодов ≈{gaps} (шаг {step} дн.)")
        if pd.api.types.is_numeric_dtype(s):
            v = s.dropna()
            if len(v):
                info.update({"min": float(v.min()), "max": float(v.max()), "mean": round(float(v.mean()), 3)})
                q1, q3 = np.percentile(v, [25, 75])
                iqr = q3 - q1
                out = int(((v < q1 - 3 * iqr) | (v > q3 + 3 * iqr)).sum()) if iqr > 0 else 0
                if out:
                    issues.append(f"«{c}»: сильных выбросов (3×IQR): {out}")
                if (v < 0).any() and not re.search(r"(измен|delta|дельта|разниц|прирост|growth)", name):
                    issues.append(f"«{c}»: есть отрицательные значения")
                nz = v[v != 0].abs().sort_values()
                if len(nz) > 4 and nz.iloc[-1] / max(nz.iloc[len(nz) // 2], 1e-9) > 500:
                    issues.append(f"«{c}»: разброс масштаба >500× — проверить единицы (тыс./млн, руб./коп.)")
                if re.search(r"(доля|share|pct|процент|%)", name) and v.max() > 1.5 and v.max() <= 100:
                    info["unit_hint"] = "проценты 0–100"
                elif re.search(r"(доля|share|pct|процент|%)", name) and v.max() <= 1:
                    info["unit_hint"] = "доли 0–1"
        cols.append(info)
    unit_cols = [c for c in df.columns if not re.search(r"(руб|₽|тыс|млн|млрд|шт|%|доля|usd|\$|кол|count|num|n_)", str(c), re.I)
                 and pd.api.types.is_numeric_dtype(df[c])]
    if unit_cols:
        issues.append(f"Не указаны единицы в названиях числовых столбцов: {', '.join(map(str, unit_cols[:6]))}")
    d = project_dir(pid)
    out = d / "research" / "data" / f"profile-{p.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Профиль данных: {p.name}", f"_Сформировано {now()} · sha256 {sha256_bytes(p.read_bytes())[:16]}_", "",
             f"Строк: {len(df)} · Столбцов: {df.shape[1]}", "", "## Столбцы", "",
             "| Столбец | Тип | Пропуски % | Уникальных | Диапазон / период | Единицы |", "|---|---|---|---|---|---|"]
    for c in cols:
        rng = (f"{c.get('date_min')} … {c.get('date_max')} (шаг {c.get('period_step_days')} дн.)" if "date_min" in c
               else (f"{c.get('min')} … {c.get('max')}" if "min" in c else ""))
        lines.append(f"| {c['col']} | {c['dtype']} | {c['missing_pct']} | {c['unique']} | {rng} | {c.get('unit_hint', '')} |")
    lines += ["", "## Что проверить перед выводами", ""] + [f"- {i}" for i in issues or ["Явных проблем не найдено"]]
    native_file_path(out).write_text("\n".join(lines), encoding="utf-8")
    journal("data_profiled", f"{p.name}: {len(df)}×{df.shape[1]}, замечаний {len(issues)}", pid=pid, actor="tool")
    return {"file": out.relative_to(d).as_posix(), "rows": len(df), "cols": df.shape[1], "issues": issues}


def run_script(script: str, pid=None) -> dict:
    """Запуск аналитического скрипта проекта с фиксацией хэшей (воспроизводимость).
    В шапке скрипта: `# inputs: a.csv, b.csv` и `# outputs: out.csv, chart.png` (пути от папки скрипта)."""
    d = project_dir(pid)
    sp = _resolve(script, pid, "скрипта").resolve()
    head = sp.read_text(encoding="utf-8")[:2000]
    ins = [x.strip() for m in re.findall(r"#\s*inputs?:\s*(.+)", head) for x in m.split(",") if x.strip()]
    outs = [x.strip() for m in re.findall(r"#\s*outputs?:\s*(.+)", head) for x in m.split(",") if x.strip()]
    h_in = {i: sha256_bytes((sp.parent / i).read_bytes())[:16] for i in ins if (sp.parent / i).exists()}
    r = subprocess.run([sys.executable, str(sp)], cwd=sp.parent, capture_output=True, timeout=900,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    stdout = r.stdout.decode("utf-8", "replace")
    stderr = r.stderr.decode("utf-8", "replace")
    h_out = {o: sha256_bytes((sp.parent / o).read_bytes())[:16] for o in outs if (sp.parent / o).exists()}
    log = sp.with_suffix(".log")
    log.write_text(f"# запуск {now()} · код возврата {r.returncode}\n# script sha256 {sha256_bytes(sp.read_bytes())[:16]}\n"
                   f"# inputs {h_in}\n# outputs {h_out}\n\n{stdout}\n{stderr}", encoding="utf-8")
    status = "ok" if r.returncode == 0 else "failed"
    journal("analysis_run", f"{sp.name}: код {r.returncode}, входы {h_in}, выходы {h_out}", pid=pid, actor="tool",
            status=status)
    return {"returncode": r.returncode, "stdout": stdout[-4000:], "stderr": stderr[-2000:], "inputs": h_in,
            "outputs": h_out, "log": log.relative_to(d).as_posix() if str(log).startswith(str(d)) else str(log)}
