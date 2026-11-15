"""Учёт стоимости: вызовы внешних моделей (точно, из ответа OpenRouter) и сессии
IDE-модели (оценка по токенам из транскрипта Claude Code или ручной ввод)."""
from __future__ import annotations

import json
from pathlib import Path

from .common import CONFIG, PROJECTS, ROOT, append_jsonl, now, read_jsonl, read_yaml, write_jsonl

GLOBAL_COSTS = ROOT / ".cache" / "costs_global.jsonl"

# Цены IDE-моделей за 1 млн токенов (USD) — для оценки; см. config/routing.yaml → ide_models
DEFAULT_IDE_PRICES = {
    "claude-opus": {"in": 5.0, "out": 25.0, "cache_read": 0.5, "cache_write": 6.25},
    "claude-sonnet": {"in": 3.0, "out": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku": {"in": 1.0, "out": 5.0, "cache_read": 0.1, "cache_write": 1.25},
}


def _path(pid: str | None) -> Path:
    return (PROJECTS / pid / "costs.jsonl") if pid else GLOBAL_COSTS


def log(rec: dict, pid: str | None) -> None:
    rec.setdefault("ts", now())
    append_jsonl(_path(pid), rec)


def ide_prices() -> dict:
    cfg = read_yaml(CONFIG / "routing.yaml", {}) or {}
    return cfg.get("ide_models", DEFAULT_IDE_PRICES)


def price_for_model(model: str) -> dict:
    prices = ide_prices()
    m = (model or "").lower()
    for key, p in prices.items():
        if key in m:
            return p
    return prices.get("claude-opus", DEFAULT_IDE_PRICES["claude-opus"])


def ide_usage_from_transcript(transcript_path: str, since: str = "") -> dict:
    """Суммирует usage сообщений ассистента в JSONL-транскрипте Claude Code (только после момента since, ISO)."""
    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0, "model": "", "messages": 0}
    seen = set()
    p = Path(transcript_path)
    if not p.exists():
        return tot
    with open(p, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            msg = r.get("message") or {}
            if since and r.get("timestamp") and str(r["timestamp"])[:19] < since[:19]:
                continue
            u = msg.get("usage")
            if not u or r.get("type") != "assistant":
                continue
            mid = msg.get("id") or r.get("uuid")
            if mid in seen:  # одно сообщение может быть разбито на несколько строк
                continue
            seen.add(mid)
            model = msg.get("model", "")
            pr = price_for_model(model)
            i, o = u.get("input_tokens", 0), u.get("output_tokens", 0)
            cr, cw = u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0)
            tot["input"] += i
            tot["output"] += o
            tot["cache_read"] += cr
            tot["cache_write"] += cw
            tot["usd"] += (i * pr["in"] + o * pr["out"] + cr * pr["cache_read"] + cw * pr["cache_write"]) / 1e6
            tot["model"] = model or tot["model"]
            tot["messages"] += 1
    tot["usd"] = round(tot["usd"], 4)
    return tot


def upsert_ide_session(pid: str, session_id: str, usage: dict, tool: str = "claude-code") -> None:
    """Одна запись на сессию IDE (обновляется при каждом Stop-хуке — без двойного счёта)."""
    path = _path(pid)
    recs = read_jsonl(path)
    recs = [r for r in recs if not (r.get("type") == "ide_session" and r.get("session_id") == session_id)]
    recs.append({"ts": now(), "type": "ide_session", "tool": tool, "session_id": session_id, **usage,
                 "estimate": True})
    write_jsonl(path, recs)


def summary(pid: str | None) -> dict:
    recs = read_jsonl(_path(pid))
    out = {"external_usd": 0.0, "external_calls": 0, "cached_calls": 0, "failed_calls": 0,
           "ide_usd": 0.0, "ide_tokens": 0, "subagent_tokens": 0, "by_task": {}, "by_model": {}, "by_stage": {}}
    for r in recs:
        t = r.get("type", "llm")
        if t == "llm":
            if r.get("cached"):
                out["cached_calls"] += 1
                continue
            if r.get("status") == "failed":
                out["failed_calls"] += 1
            usd = float(r.get("usd") or 0)
            out["external_usd"] += usd
            out["external_calls"] += 1
            for key, field in (("by_task", "task"), ("by_model", "model"), ("by_stage", "stage")):
                k = r.get(field) or "—"
                out[key][k] = round(out[key].get(k, 0) + usd, 6)
        elif t == "ide_session":
            out["ide_usd"] += float(r.get("usd") or 0)
            out["ide_tokens"] += int(r.get("input", 0)) + int(r.get("output", 0)) + int(r.get("cache_read", 0)) + int(r.get("cache_write", 0))
        elif t == "subagent":
            out["subagent_tokens"] += int(r.get("tokens", 0))
            out["ide_usd"] += float(r.get("usd") or 0)
            k = r.get("stage") or "—"
            out["by_stage"][k] = round(out["by_stage"].get(k, 0) + float(r.get("usd") or 0), 6)
        elif t == "manual":
            out["ide_usd"] += float(r.get("usd") or 0)
    out["external_usd"] = round(out["external_usd"], 6)
    out["ide_usd"] = round(out["ide_usd"], 4)
    return out


def add_manual(pid: str, usd: float, note: str, kind: str = "manual", tokens: int = 0, stage: str = "",
               model: str = "") -> None:
    log({"type": kind, "usd": usd, "note": note, "tokens": tokens, "stage": stage, "model": model}, pid)
