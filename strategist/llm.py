"""Клиент OpenRouter: маршрутизация по задачам, кэш (без повторной оплаты), ретраи,
эскалация на следующую модель при сбое или провале проверки, учёт стоимости.

Режимы:
- нет OPENROUTER_API_KEY → NoKeyError с подсказкой выполнить шаг силами IDE-модели/субагента;
- STRATEGIST_REPLAY=1 → только ответы из кэша (воспроизведение демо без ключа и без затрат).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import requests

from .common import CACHE, CONFIG, PROJECTS, StrategistError, load_env, now, read_yaml, sha256_text
from . import costs as _costs


class NoKeyError(StrategistError):
    pass


class LLMError(StrategistError):
    pass


def routing() -> dict:
    return read_yaml(CONFIG / "routing.yaml", {}) or {}


def task_cfg(task: str) -> dict:
    r = routing()
    if task not in r.get("tasks", {}):
        raise StrategistError(f"Задача '{task}' не описана в config/routing.yaml")
    cfg = dict(r.get("defaults", {}))
    cfg.update(r["tasks"][task])
    return cfg


def model_prices() -> dict:
    p = CONFIG / "models_prices.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _cache_dir(pid: str | None) -> Path:
    return (PROJECTS / pid / ".llm_cache") if pid else (CACHE / "llm")


def _extract_json(text: str):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("ответ не содержит корректного JSON")


def has_key() -> bool:
    load_env()
    key_env = routing().get("provider", {}).get("key_env", "OPENROUTER_API_KEY")
    return bool(os.environ.get(key_env))


def ask(task: str, prompt: str | None = None, *, messages: list | None = None, system: str | None = None,
        pid: str | None = None, stage: str | None = None, model: str | None = None,
        json_mode: bool | None = None, max_tokens: int | None = None, temperature: float | None = None,
        validate: Callable[[dict], str | None] | None = None, cache: bool = True, models: list[str] | None = None,
        label: str = "") -> dict:
    """Вызвать модель для задачи `task`. Возвращает {text, json, model, usage, usd, cached, attempts}."""
    load_env()
    cfg = task_cfg(task)
    chain = [model] if model else (models or list(cfg.get("models", [])))
    if not chain:
        raise StrategistError(f"Для задачи {task} не указаны модели")
    json_mode = cfg.get("json", False) if json_mode is None else json_mode
    max_tokens = max_tokens or cfg.get("max_tokens", 2000)
    temperature = cfg.get("temperature", 0.3) if temperature is None else temperature
    if messages is None:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt or ""})
    replay = os.environ.get("STRATEGIST_REPLAY") == "1"
    key_env = routing().get("provider", {}).get("key_env", "OPENROUTER_API_KEY")
    key = os.environ.get(key_env, "")
    base = routing().get("provider", {}).get("base_url", "https://openrouter.ai/api/v1")
    attempts = []
    cdir = _cache_dir(pid)

    for m in chain:
        payload = {"model": m, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        ckey = sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + f"|json={json_mode}")
        cfile = cdir / f"{ckey[:32]}.json"
        # 1. кэш: повторный запуск не платит за уже выполненный вызов
        if cache and cfile.exists():
            res = json.loads(cfile.read_text(encoding="utf-8"))
            res["cached"] = True
            _costs.log({"type": "llm", "task": task, "model": m, "cached": True, "usd": 0, "stage": stage,
                        "label": label}, pid)
            if validate:
                err = validate(res)
                if err:
                    attempts.append({"model": m, "error": f"кэш не прошёл проверку: {err}"})
                    continue
            res["attempts"] = attempts + [{"model": m, "cached": True}]
            return res
        if replay:
            attempts.append({"model": m, "error": "нет в кэше (режим REPLAY)"})
            continue
        if not key:
            raise NoKeyError(
                f"Нет ключа {key_env} (.env). Задача '{task}' не выполнена внешней моделью. Варианты: "
                f"1) добавить ключ в .env; 2) выполнить шаг силами IDE-модели/субагента (см. AGENTS.md → «Без ключа»).")
        body = dict(payload)
        body["usage"] = {"include": True}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                   "X-Title": "Strategist Agent (hackathon)"}
        last_err = ""
        for retry in range(int(cfg.get("max_retries", 2)) + 1):
            t0 = time.time()
            try:
                r = requests.post(f"{base}/chat/completions", headers=headers, json=body,
                                  timeout=cfg.get("timeout_s", 120))
                if r.status_code == 400 and "response_format" in body:
                    body.pop("response_format")  # модель не умеет json_object — просим JSON текстом
                    raise LLMError("400: response_format не поддержан, повтор без него")
                if r.status_code in (408, 429) or r.status_code >= 500:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}: {r.text[:300]}"
                    break  # 4xx (кроме 408/429) — не повторяем на той же модели
                data = r.json()
                if "error" in data:
                    raise LLMError(str(data["error"])[:300])
                msg = data["choices"][0]["message"]
                text = msg.get("content") or ""
                if isinstance(text, list):
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                usage = data.get("usage", {}) or {}
                usd = usage.get("cost")
                if usd is None:
                    pr = model_prices().get(m, {})
                    usd = (usage.get("prompt_tokens", 0) * pr.get("prompt", 0) +
                           usage.get("completion_tokens", 0) * pr.get("completion", 0))
                res = {"text": text, "json": None, "model": data.get("model", m), "usage": usage,
                       "usd": float(usd or 0), "cached": False, "ts": now(), "duration_s": round(time.time() - t0, 2)}
                if json_mode:
                    try:
                        res["json"] = _extract_json(text)
                    except ValueError as e:
                        _costs.log({"type": "llm", "task": task, "model": m, "usd": res["usd"], "status": "failed",
                                    "error": "invalid_json", "stage": stage, "label": label,
                                    "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens")}, pid)
                        last_err = f"невалидный JSON: {e}"
                        break  # эскалация на следующую модель
                if validate:
                    err = validate(res)
                    if err:
                        _costs.log({"type": "llm", "task": task, "model": m, "usd": res["usd"], "status": "failed",
                                    "error": f"validate: {err}", "stage": stage, "label": label}, pid)
                        last_err = f"проверка качества не пройдена: {err}"
                        break
                _costs.log({"type": "llm", "task": task, "model": m, "usd": res["usd"], "status": "ok",
                            "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
                            "duration_s": res["duration_s"], "stage": stage, "label": label}, pid)
                if cache:
                    cdir.mkdir(parents=True, exist_ok=True)
                    cfile.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                res["attempts"] = attempts + [{"model": m, "ok": True, "retries": retry}]
                if attempts and pid:
                    from .project import journal
                    journal("model_escalation", f"{task}: {' → '.join(a['model'] for a in attempts)} → {m}",
                            pid=pid, actor="tool", reasons=[a.get("error") for a in attempts])
                return res
            except (requests.RequestException, LLMError) as e:
                last_err = str(e)
                time.sleep(min(2 ** retry, 8))
        attempts.append({"model": m, "error": last_err})
        _costs.log({"type": "llm", "task": task, "model": m, "usd": 0, "status": "failed", "error": last_err[:200],
                    "stage": stage, "label": label}, pid)
    if pid:
        from .project import journal
        journal("llm_failed", f"{task}: все модели цепочки не сработали", pid=pid, status="failed", actor="tool",
                attempts=attempts)
    raise LLMError(f"Задача '{task}': ни одна модель не дала годный ответ: {attempts}")


def image_part(path: str | Path) -> dict:
    p = Path(path)
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
            "gif": "image/gif"}.get(p.suffix.lower().lstrip("."), "image/png")
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def audio_part(path: str | Path) -> dict:
    p = Path(path)
    fmt = p.suffix.lower().lstrip(".")
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(p.read_bytes()).decode(),
                                                   "format": "mp3" if fmt == "mp3" else "wav"}}


def sync_models() -> dict:
    """Скачать публичный список моделей OpenRouter (без ключа) и сохранить цены за токен."""
    r = requests.get("https://openrouter.ai/api/v1/models", timeout=60)
    r.raise_for_status()
    out = {}
    for m in r.json().get("data", []):
        p = m.get("pricing", {})
        try:
            out[m["id"]] = {"prompt": float(p.get("prompt", 0)), "completion": float(p.get("completion", 0)),
                            "context": m.get("context_length"),
                            "input": m.get("architecture", {}).get("input_modalities", [])}
        except (TypeError, ValueError):
            continue
    (CONFIG / "models_prices.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    return out


def check_routing_models() -> list[str]:
    prices = model_prices()
    if not prices:
        return ["config/models_prices.json нет — выполните `python sf.py models sync`"]
    problems = []
    for task, cfg in routing().get("tasks", {}).items():
        for m in cfg.get("models", []) + cfg.get("rotate_pool", []):
            if m not in prices:
                problems.append(f"{task}: модели {m} нет в OpenRouter")
    return problems
