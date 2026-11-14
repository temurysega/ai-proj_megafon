"""Импорт результата субагента-исследователя в реестры с проверкой цитат.

Конвейер для каждого утверждения: загрузка источника в снимок (allowlist, инъекции) →
сверка цитаты со снимком (дословно / частично / не найдена) → если не найдена, поиск в снимке
предложения с теми же числами (автолокализация дословной цитаты) → регистрация утверждения
с уверенностью по надёжности источника и статусу цитаты. Пересказ не выдаётся за цитату.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import StrategistError
from .evidence import add_claim, add_source, load_sources, update_claim
from .project import journal, project_dir

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»“”„\"'`]", "", s)
    s = re.sub(r"[‐-‒–—−]", "-", s)
    s = s.replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, text: str) -> str:
    if not text:
        return "no_snapshot"
    q, t = norm(quote), norm(text)
    if not q:
        return "no_quote"
    if q in t:
        return "verbatim"
    segs = [x.strip(" .,;:") for x in re.split(r"…|\.\.\.|;|\(|\)", q) if len(x.strip()) >= 20]
    if segs:
        found = sum(1 for x in segs if x in t)
        if found and found / len(segs) >= 0.5:
            return "partial"
    return "not_found"


def locate_quote(claim_text: str, quote: str, text: str) -> str:
    """Найти в снимке предложение, где встречаются те же числа, что в утверждении/цитате."""
    nums = {n.replace(",", ".") for n in _NUM.findall(claim_text + " " + quote) if len(n) >= 2 or "," in n or "." in n}
    if not nums or not text:
        return ""
    from .kb import tokens
    def _words(x):  # только слова (без чисел и коротких аббревиатур), иначе даты дают ложное совпадение
        return {t for t in tokens(x) if t.isalpha() and len(t) >= 3}
    ctoks = _words(claim_text)
    best, best_score = "", 0
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        s = sent.strip()
        if not (30 <= len(s) <= 600) or s.startswith("<!--"):
            continue
        if len(ctoks & _words(s)) < 3:  # числа совпали случайно (даты, номера законов) — не та фраза
            continue
        sn = {n.replace(",", ".") for n in _NUM.findall(s)}
        score = len(nums & sn)
        if score > best_score:
            best, best_score = s, score
    need = 2 if len(nums) >= 3 else 1
    return best if best_score >= need else ""


def _load(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    raw = m.group(1) if m else raw
    return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])


def import_research(json_file: str, fetch_sources: bool = True, pid=None) -> dict:
    from .web import fetch
    d = project_dir(pid)
    data = _load(Path(json_file))
    dq = data.get("dq", "")
    out = {"dq": dq, "claims": [], "stats": {}}
    for c in data.get("claims", []):
        url, rel = c.get("url", ""), (c.get("reliability") or "B").upper()[:1]
        src, snap = None, ""
        from .safety import domain_allowed
        allowed = domain_allowed(url)[0] if url else True
        if url and not allowed:  # домен вне allowlist: не загружаем; утверждение — только гипотеза
            src = next((s for s in load_sources(pid) if s.get("url") == url), None) or add_source(
                c.get("title", url), "web", url, publisher=c.get("publisher", ""), published=c.get("published", ""),
                reliability="D", notes="домен вне allowlist — не загружен; нужно разрешение человека", pid=pid)
        elif url and fetch_sources:
            try:
                src = fetch(url, c.get("title", ""), c.get("publisher", ""), c.get("published", ""), rel, pid=pid)
            except StrategistError as e:
                note = f"снимок не получен: {str(e)[:120]}"
                try:
                    src = fetch(url, c.get("title", ""), c.get("publisher", ""), c.get("published", ""), rel,
                                render=True, pid=pid)
                except StrategistError:
                    src = add_source(c.get("title", url), "web", url, publisher=c.get("publisher", ""),
                                     published=c.get("published", ""), reliability=rel, notes=note, pid=pid)
        elif url:
            src = next((s for s in load_sources(pid) if s.get("url") == url), None) or add_source(
                c.get("title", url), "web", url, publisher=c.get("publisher", ""), published=c.get("published", ""),
                reliability=rel, notes="без снимка (--no-fetch)", pid=pid)
        if src and src.get("path") and (d / src["path"]).exists() and src["path"].endswith(".md"):
            snap = (d / src["path"]).read_text(encoding="utf-8")
        quote = c.get("quote", "")
        status = verify_quote(quote, snap)
        located = ""
        if status in ("not_found", "no_quote"):
            located = locate_quote(c.get("text", ""), quote, snap)
            if located:
                quote, status = located, "auto_located"
        conf = {"A": "high", "B": "medium", "C": "low", "D": "low"}.get(rel, "medium")
        if status in ("not_found", "no_snapshot", "no_quote"):
            conf = "low" if conf != "high" else "medium"
        kind = c.get("kind", "fact")
        if kind not in ("fact", "opinion", "forecast", "hypothesis", "estimate", "assumption"):
            kind = "fact"
        if not allowed:
            kind, conf, status = "hypothesis", "low", "outside_allowlist"
        note = f"quote_status={status}; от субагента researcher ({dq})"
        if status == "not_found":
            note += "; цитата исследователя не найдена дословно в снимке — проверить вручную"
        claim = add_claim(c["text"], kind, [src["id"]] if src else [], quote,
                          c.get("locator", ""), conf, [dq, "researcher"], pid=pid, note=note)
        update_claim(claim["id"], pid=pid, quote_status=status)
        out["claims"].append({"id": claim["id"], "source": src["id"] if src else None, "quote_status": status,
                              "confidence": conf})
    for k in ("verbatim", "partial", "auto_located", "not_found", "no_snapshot", "no_quote", "outside_allowlist"):
        out["stats"][k] = sum(1 for x in out["claims"] if x["quote_status"] == k)
    # противоречия и пробелы — в сводку исследователя
    md = [f"# Результат субагента researcher: {dq}", "", f"_Импортировано: {len(out['claims'])} утверждений; "
          f"сверка цитат со снимками: {out['stats']}_", "", "## Краткий ответ", data.get("answer_summary", ""), "",
          "## Противоречия"] + [f"- {x}" for x in data.get("contradictions", [])] + ["", "## Пробелы"] + \
         [f"- {x}" for x in data.get("gaps", [])] + ["", "## Утверждения"] + \
         [f"- [{x['id']}] источник {x['source']} · цитата: {x['quote_status']} · уверенность: {x['confidence']}"
          for x in out["claims"]]
    if data.get("injection_notes"):
        md += ["", "## Признаки инъекций в источниках"] + [f"- {x}" for x in data["injection_notes"]]
    summary = d / "research" / "researchers" / f"{dq or Path(json_file).stem}.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("\n".join(md), encoding="utf-8")
    journal("research_imported", f"{dq}: {len(out['claims'])} утв., цитаты {out['stats']}", pid=pid, actor="tool")
    out["summary"] = summary.relative_to(d).as_posix()
    return out
