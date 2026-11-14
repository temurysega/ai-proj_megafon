"""База знаний и память между сеансами.

Поиск: по формулировке (BM25 со стеммингом), по смыслу (опциональный LLM-реранк
дешёвой моделью), по связям (frontmatter `links:` и [[wiki-ссылки]] → соседи).

Память: memory/entries.jsonl. У каждой записи — происхождение (кто/откуда), тип,
срок годности и статус. Выводы агента (`agent_conclusion`) хранятся, но НЕ могут
быть основанием факта: это гипотезы до подтверждения источником.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

import yaml

from .common import KNOWLEDGE, MEMORY, PROJECTS, StrategistError, next_id, now, read_jsonl, today, write_jsonl

MEM_FILE = MEMORY / "entries.jsonl"
MEM_KINDS = {
    "user_preference": "предпочтение пользователя (со слов человека)",
    "lesson": "урок процесса (что сработало/не сработало)",
    "source_pointer": "указатель на проверенный источник (сам факт — в источнике)",
    "agent_conclusion": "вывод агента — НЕ факт, требует подтверждения",
    "decision_ref": "ссылка на принятое решение в проекте",
}

try:
    import snowballstemmer
    _stem = snowballstemmer.stemmer("russian").stemWord
    _stem_en = snowballstemmer.stemmer("english").stemWord
except Exception:  # грубый фолбэк: усечение окончаний
    _stem = _stem_en = lambda w: w[:6] if len(w) > 6 else w

_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower().replace("ё", "е")):
        if len(w) < 2:
            continue
        out.append(_stem(w) if re.match(r"[а-я]", w) else _stem_en(w))
    return out


def _frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                return yaml.safe_load(parts[1]) or {}, parts[2]
            except yaml.YAMLError:
                pass
    return {}, text


def _chunks(path: Path, base: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = _frontmatter(text)
    rel = path.relative_to(base).as_posix()
    doc_id = fm.get("id") or path.stem
    links = list(fm.get("links", []) or []) + re.findall(r"\[\[([^\]]+)\]\]", body)
    out, head, buf = [], fm.get("title") or path.stem, []

    def flush():
        t = "\n".join(buf).strip()
        if t:
            out.append({"doc": doc_id, "file": rel, "section": head, "text": t, "links": links,
                        "tags": fm.get("tags", [])})
    for line in body.splitlines():
        if re.match(r"^#{1,3}\s", line):
            flush()
            head, buf = line.lstrip("#").strip(), []
        else:
            buf.append(line)
    flush()
    return out


def build_index(scope: str = "knowledge", pid: str | None = None) -> list[dict]:
    docs: list[dict] = []
    if scope in ("knowledge", "all"):
        for p in sorted(KNOWLEDGE.rglob("*.md")):
            docs += _chunks(p, KNOWLEDGE.parent)
    if scope in ("memory", "all"):
        for m in load_memory():
            if m.get("status") == "active":
                docs.append({"doc": m["id"], "file": "memory/entries.jsonl", "section": MEM_KINDS.get(m["kind"], m["kind"]),
                             "text": m["text"], "links": m.get("links", []), "tags": [m["kind"]], "memory": m})
    if scope in ("project", "all") and pid:
        base = PROJECTS / pid
        for p in sorted(base.rglob("*.md")):
            if "sources/raw" in p.as_posix() or "/report/" in p.as_posix():
                continue
            docs += _chunks(p, PROJECTS.parent)
        from .evidence import load_claims
        for c in load_claims(pid):
            docs.append({"doc": c["id"], "file": f"projects/{pid}/evidence/claims.jsonl", "section": c["kind"],
                         "text": c["text"], "links": c.get("depends_on", []), "tags": c.get("tags", []),
                         "claim_status": c.get("status")})
    return docs


def bm25(query: str, docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[tuple[float, dict]]:
    toks = [tokens(d["section"] + " " + d["text"]) for d in docs]
    if not docs:
        return []
    avgdl = sum(len(t) for t in toks) / len(toks)
    df = Counter()
    for t in toks:
        df.update(set(t))
    n = len(docs)
    q = tokens(query)
    scored = []
    for d, t in zip(docs, toks):
        tf = Counter(t)
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avgdl))
        if s > 0:
            scored.append((s, d))
    return sorted(scored, key=lambda x: -x[0])


def search(query: str, scope: str = "knowledge", pid: str | None = None, k: int = 6, rerank: bool = False,
           with_links: bool = True) -> list[dict]:
    docs = build_index(scope, pid)
    hits = bm25(query, docs)[: max(k * 2, 12)]
    results = [{"score": round(s, 2), **{kk: v for kk, v in d.items() if kk != "memory"},
                "warning": ("вывод агента — не факт" if d.get("memory", {}).get("kind") == "agent_conclusion" else "")}
               for s, d in hits]
    if rerank and results:
        from .llm import ask
        listing = "\n".join(f"{i}. [{r['doc']} / {r['section']}] {r['text'][:300]}" for i, r in enumerate(results))
        prompt = (f"Запрос: «{query}»\nУпорядочь фрагменты по смысловой релевантности запросу (не по совпадению слов). "
                  f"Верни JSON {{\"order\": [индексы от лучшего к худшему], \"irrelevant\": [индексы]}}.\n{listing}")
        try:
            res = ask("rerank", prompt, pid=pid, label="kb-rerank")
            order = [i for i in res["json"].get("order", []) if isinstance(i, int) and 0 <= i < len(results)]
            bad = set(res["json"].get("irrelevant", []))
            seen = set(order)
            order += [i for i in range(len(results)) if i not in seen]
            results = [dict(results[i], reranked=True) for i in order if i not in bad]
        except Exception as e:
            results = [dict(r, rerank_error=str(e)[:80]) for r in results]
    results = results[:k]
    if with_links:
        all_docs = {d["doc"]: d for d in docs}
        for r in results:
            r["related"] = [f"{l}: {all_docs[l]['section']}" for l in r.get("links", []) if l in all_docs][:5]
    return results


# ---------- память ----------
def load_memory() -> list[dict]:
    return [m for m in read_jsonl(MEM_FILE) if "id" in m]


def memory_add(text: str, kind: str, provenance: str, project: str = "", valid_until: str = "",
               links: list[str] | None = None) -> dict:
    if kind not in MEM_KINDS:
        raise StrategistError(f"Тип памяти: {list(MEM_KINDS)}")
    if not provenance:
        raise StrategistError("Укажите происхождение записи (--prov): кто сказал / какой источник / какой проект")
    mem = load_memory()
    for m in mem:
        if m["text"].strip() == text.strip() and m.get("status") == "active":
            return m
    rec = {"id": next_id("M", [m["id"] for m in mem]), "text": text, "kind": kind, "provenance": provenance,
           "project": project, "created": now(), "valid_until": valid_until, "links": links or [],
           "status": "active", "can_cite_as_fact": kind == "source_pointer"}
    mem.append(rec)
    write_jsonl(MEM_FILE, mem)
    return rec


def memory_retract(mid: str, reason: str, superseded_by: str = "") -> dict:
    mem = load_memory()
    for m in mem:
        if m["id"] == mid:
            m.update({"status": "superseded" if superseded_by else "retracted", "retracted_reason": reason,
                      "superseded_by": superseded_by, "retracted_at": now()})
            write_jsonl(MEM_FILE, mem)
            return m
    raise StrategistError(f"Запись памяти {mid} не найдена")


def memory_review() -> list[dict]:
    """Записи, которые пора проверить: истёк срок годности или это выводы агента старше 60 дней."""
    import datetime as dt
    out = []
    for m in load_memory():
        if m.get("status") != "active":
            continue
        vu = m.get("valid_until")
        if vu and str(vu) < today():
            out.append({**m, "why": f"истёк срок годности {vu}"})
        elif m["kind"] == "agent_conclusion":
            try:
                age = (dt.date.today() - dt.date.fromisoformat(m["created"][:10])).days
                if age > 60:
                    out.append({**m, "why": f"вывод агента без подтверждения {age} дней"})
            except Exception:
                pass
    return out
