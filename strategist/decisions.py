"""Поддержка решений после выбора: журнал решений, обязательства, условия пересмотра.

decisions.yaml — список решений. У каждого: основания (claims), допущения,
владельцы (роли), метрики, обязательства с датами и триггеры пересмотра.
`due_items` отвечает на вопрос «что решать сейчас и какие основания устарели».
"""
from __future__ import annotations

import datetime as _dt

from .common import StrategistError, now, read_yaml, write_yaml
from .project import journal, project_dir

TEMPLATE_DECISION = {
    "id": "D1",
    "title": "",
    "date": "",
    "question": "",
    "options_considered": [],
    "chosen": "",
    "decided_by": "руководитель продукта (роль)",
    "rationale_claims": [],
    "assumptions": [],
    "owners": {},
    "metrics": [],
    "commitments": [],
    "review_triggers": [],
    "status": "active",
}


def _path(pid=None):
    return project_dir(pid) / "decisions.yaml"


def load_decisions(pid=None) -> list[dict]:
    return read_yaml(_path(pid), []) or []


def save_decisions(decs: list[dict], pid=None) -> None:
    write_yaml(_path(pid), decs)


def validate(pid=None) -> list[str]:
    from .evidence import load_claims
    claims = {c["id"]: c for c in load_claims(pid)}
    errs = []
    for d in load_decisions(pid):
        did = d.get("id", "?")
        for k in ("title", "chosen", "rationale_claims", "metrics", "review_triggers"):
            if not d.get(k):
                errs.append(f"{did}: не заполнено поле {k}")
        for c in d.get("rationale_claims", []) + d.get("assumptions", []):
            if c not in claims:
                errs.append(f"{did}: нет утверждения {c}")
        for m in d.get("metrics", []):
            for k in ("name", "baseline", "target", "by"):
                if k not in m:
                    errs.append(f"{did}: у метрики {m.get('name', '?')} нет поля {k}")
        ids = {k.get("id") for k in d.get("commitments", [])}
        for k in d.get("commitments", []):
            for f in ("id", "what", "owner", "due"):
                if f not in k:
                    errs.append(f"{did}: у обязательства {k.get('id', '?')} нет поля {f}")
            for dep in k.get("depends_on", []):
                if dep not in ids:
                    errs.append(f"{did}: обязательство {k.get('id')} зависит от несуществующего {dep}")
            deps_due = [_date(x.get("due")) for x in d.get("commitments", []) if x.get("id") in k.get("depends_on", [])]
            if deps_due and _date(k.get("due")) and any(dd and dd > _date(k.get("due")) for dd in deps_due):
                errs.append(f"{did}: срок {k['id']} раньше срока его зависимостей {k.get('depends_on')}")
    return errs


def _date(s) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def due_items(pid=None, today: _dt.date | None = None, horizon_days: int = 14) -> list[str]:
    """Что требует внимания: просроченные/близкие обязательства, сработавшие триггеры,
    устаревшие допущения."""
    from .evidence import load_claims
    today = today or _dt.date.today()
    claims = {c["id"]: c for c in load_claims(pid)}
    out = []
    for d in load_decisions(pid):
        if d.get("status") not in ("active", "under_review"):
            continue
        did = d["id"]
        status_by_id = {k["id"]: k.get("status", "open") for k in d.get("commitments", [])}
        for k in d.get("commitments", []):
            if k.get("status", "open") == "done":
                continue
            blockers = [b for b in k.get("depends_on", []) if status_by_id.get(b) != "done"]
            if blockers:
                out.append(f"⏸ {did}/{k['id']} заблокировано до выполнения {', '.join(blockers)}: {k['what']}")
            due = _date(k.get("due"))
            if due and due < today:
                out.append(f"⛔ {did}/{k['id']} просрочено с {due}: {k['what']} (ответственный: {k['owner']})")
            elif due and (due - today).days <= horizon_days:
                out.append(f"⏰ {did}/{k['id']} срок {due}: {k['what']} (ответственный: {k['owner']})")
        for t in d.get("review_triggers", []):
            typ = t.get("type")
            if typ == "date":
                dt = _date(t.get("value"))
                if dt and dt <= today:
                    out.append(f"🔁 {did}: наступила дата пересмотра {dt} — {t.get('note', '')}")
            elif typ == "claim_status":
                c = claims.get(t.get("claim"))
                if c and c.get("status") in t.get("when", ["retracted", "disputed", "superseded"]):
                    out.append(f"🔁 {did}: основание {c['id']} стало «{c['status']}» — пересмотреть решение "
                               f"({t.get('note', '')})")
            elif typ == "metric":
                obs = t.get("observed")
                if obs is not None and t.get("threshold") is not None:
                    op = t.get("op", "<")
                    fired = (obs < t["threshold"]) if op == "<" else (obs > t["threshold"])
                    if fired:
                        out.append(f"🔁 {did}: метрика {t.get('metric')}={obs} {op} {t['threshold']} — "
                                   f"условие пересмотра выполнено")
        for a in d.get("assumptions", []):
            c = claims.get(a)
            if c and c.get("status") == "active":
                created = _date(c.get("created"))
                if created and (today - created).days > 90:
                    out.append(f"⚠ {did}: допущение {a} не проверялось >90 дней: {c['text'][:80]}")
    return out


def record_observation(decision_id: str, metric: str, value: float, pid=None) -> list[str]:
    decs = load_decisions(pid)
    for d in decs:
        if d["id"] == decision_id:
            for t in d.get("review_triggers", []):
                if t.get("type") == "metric" and t.get("metric") == metric:
                    t["observed"], t["observed_at"] = value, now()
            d.setdefault("observations", []).append({"metric": metric, "value": value, "ts": now()})
            save_decisions(decs, pid)
            journal("metric_observed", f"{decision_id}: {metric}={value}", pid=pid, actor="human")
            return due_items(pid)
    raise StrategistError(f"Решение {decision_id} не найдено")


def set_commitment(decision_id: str, commitment_id: str, status: str, pid=None) -> None:
    decs = load_decisions(pid)
    for d in decs:
        if d["id"] == decision_id:
            for k in d.get("commitments", []):
                if k["id"] == commitment_id:
                    k["status"] = status
                    k["status_at"] = now()
                    save_decisions(decs, pid)
                    journal("commitment", f"{decision_id}/{commitment_id} → {status}", pid=pid, actor="human")
                    return
    raise StrategistError(f"Обязательство {decision_id}/{commitment_id} не найдено")
