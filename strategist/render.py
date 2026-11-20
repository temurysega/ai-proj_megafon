"""Сборка читаемого отчёта для руководителя: HTML (и PDF через Chromium).

Каждая ссылка [C012] превращается в сноску с текстом утверждения, типом и источником;
в конце — реестр утверждений, источников, журнал и стоимость. Отчёт = прозрачность.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import markdown as md

from .common import CLAIM_KIND_RU, STAGE_TITLES, now
from .costs import summary as cost_summary
from .decisions import load_decisions
from .evidence import load_claims, load_sources
from .project import journal, load_state, project_dir
from .common import read_jsonl

ORDER = [
    ("strategy/one-pager.md", "Резюме для руководителя"),
    ("brief.md", "Постановка задачи"),
    ("research/plan.md", "План исследования"),
    ("research/findings.md", "Картина ситуации"),
    ("options.md", "Варианты"),
    ("strategy/product.md", "Продуктовая стратегия"),
    ("strategy/communication.md", "Коммуникационная стратегия"),
    ("strategy/validation.md", "План проверки"),
    ("decision.md", "Решение и сопровождение"),
]

CSS = """
:root{--bg:#fff;--fg:#1c1d21;--muted:#5d6270;--line:#e3e5ea;--accent:#00a650;--accent2:#731982;--warn:#b54708;--chip:#f3f4f6}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#15161a;--fg:#ececf1;--muted:#a0a4b0;--line:#2c2e35;--chip:#22242b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:28px;margin:0 0 6px}h2{font-size:22px;margin:34px 0 10px;padding-top:10px;border-top:2px solid var(--line)}
h3{font-size:17px;margin:22px 0 8px}h4{font-size:15px;margin:16px 0 6px}
.meta{color:var(--muted);font-size:13px}.chips span{display:inline-block;background:var(--chip);border-radius:12px;padding:2px 10px;margin:2px 4px 2px 0;font-size:12px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}th{background:var(--chip)}
a.c{font-size:11px;font-weight:600;color:var(--accent2);text-decoration:none;border:1px solid var(--accent2);border-radius:8px;padding:0 4px;margin:0 1px;white-space:nowrap}
a.c.k-hypothesis,a.c.k-forecast,a.c.k-assumption{color:var(--warn);border-color:var(--warn);border-style:dashed}
a.c.k-synthetic{color:#888;border-color:#888;border-style:dotted}
a.c.st-retracted,a.c.st-superseded{text-decoration:line-through;color:#c00;border-color:#c00}
.legend span{margin-right:12px;font-size:12px}
blockquote{margin:10px 0;padding:6px 12px;border-left:4px solid var(--accent);background:var(--chip)}
code{background:var(--chip);padding:1px 4px;border-radius:4px;font-size:90%}
section.doc{page-break-before:always}nav ol{columns:2;font-size:14px}
.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.kpi div{border:1px solid var(--line);border-radius:10px;padding:8px 12px;min-width:140px}
.kpi b{display:block;font-size:20px}
.print-only{display:none}
@media print{a.c{border:none;padding:0}nav,.screen-only{display:none}.print-only{display:inline}table{display:table;overflow:visible;font-size:11.5px}th,td{padding:4px 5px;overflow-wrap:break-word}}
"""


def _claim_links(text: str, claims: dict, srcs: dict) -> str:
    def rep_block(m):
        inner = m.group(1)
        toks = re.findall(r"\b([CS]\d{3,})\b", inner)
        if not toks or re.sub(r"[\sCS\d,;]", "", inner):
            return m.group(0)
        parts = []
        for t in toks:
            if t.startswith("C") and t in claims:
                c = claims[t]
                src = ", ".join(c.get("sources", [])) or "—"
                title = f"{CLAIM_KIND_RU.get(c['kind'], c['kind'])}: {c['text']} · источники: {src}"
                parts.append(f'<a class="c k-{c["kind"]} st-{c.get("status")}" href="#{t}" title="{html.escape(title)}">{t}</a>')
            elif t.startswith("S") and t in srcs:
                parts.append(f'<a class="c" href="#{t}" title="{html.escape(srcs[t]["title"])}">{t}</a>')
            else:
                parts.append(f'<a class="c st-retracted" title="не найдено">{t}?</a>')
        return "".join(parts)
    return re.sub(r"\[([^\[\]]{2,120})\](?!\()", rep_block, text)


def _source_location(source: dict, project: Path) -> str:
    links = []
    url = source.get("url") or ""
    if urlsplit(url).scheme in ("http", "https"):
        links.append(f'<a href="{html.escape(url, quote=True)}">Страница источника</a>')
    for rel in (source.get("text_path"), source.get("path")):
        if not rel:
            continue
        snapshot = (project / rel).resolve()
        if not snapshot.is_relative_to(project.resolve()) or not snapshot.is_file():
            continue
        name = snapshot.relative_to(project.resolve()).as_posix()
        links.append(f'<a class="screen-only" href="../{quote(name)}">Сохранённый снимок</a>'
                     f'<span class="print-only">{html.escape(name)}</span>')
        break
    return "<br>".join(links) or "В реестре нет доступного снимка"


def _claim_basis(claim: dict, claims: dict, sources: dict) -> str:
    ids = claim.get("sources", []) + claim.get("depends_on", [])
    parts = [_claim_links("[" + ", ".join(ids) + "]", claims, sources)] if ids else []
    for field in ("locator", "method"):
        if claim.get(field):
            parts.append(html.escape(claim[field]))
    return "<br>".join(parts) or "—"


def build(pid=None, pdf: bool = False) -> dict:
    d = project_dir(pid)
    st = load_state(pid)
    claims = {c["id"]: c for c in load_claims(pid)}
    srcs = {s["id"]: s for s in load_sources(pid)}
    cs = cost_summary(d.name)
    body = [f"<h1>{html.escape(st.get('title', d.name))}</h1>",
            f"<p class='meta'>Проект <code>{d.name}</code> · стадия: {STAGE_TITLES.get(st['stage'])} · "
            f"обновлено {st.get('updated', '')[:16]} · отчёт собран {now()[:16]}</p>",
            "<div class='kpi'>"
            f"<div><b>{len(srcs)}</b>источников</div>"
            f"<div><b>{sum(1 for c in claims.values() if c.get('status') == 'active')}</b>утверждений</div>"
            f"<div><b>{sum(1 for c in claims.values() if c['kind'] == 'fact' and c.get('status') == 'active')}</b>фактов с источником</div>"
            f"<div><b>≈${cs['project_usd']:.2f}</b>стоимость проекта</div>"
            f"<div><b>${cs['external_usd']:.3f}</b>из них внешние модели</div></div>"
            + (f"<p class='meta'>В стоимость проекта входят внешние модели, субагенты и ручные оценки. Основной чат IDE "
               f"(≈${cs['session_usd']:.2f}) показан отдельно: {html.escape(cs['session_note'] or 'в том же чате шла другая работа')}.</p>"
               if cs["session_mixed"] else ""),
            "<p class='legend'><span><a class='c'>C001</a> факт/расчёт</span><span><a class='c k-hypothesis'>C002</a> гипотеза/прогноз/допущение</span>"
            "<span><a class='c k-synthetic'>C003</a> синтетика</span><span><a class='c st-retracted'>C004</a> отозвано</span>"
            " — наведите курсор на метку, чтобы увидеть утверждение и источник.</p>"]
    toc, sections = [], []
    order = list(ORDER)
    deliv = (st.get("deliverable") or {}).get("file")
    if deliv and deliv not in [r for r, _ in order]:
        # документ, которого требует бриф (например, «пять частей»), идёт сразу после резюме
        order.insert(1, (deliv, "Стратегия в формате брифа"))
    for rel, title in order:
        f = d / rel
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        text = re.sub(r"^#\s+.+\n", "", text, count=1)
        h = md.markdown(_claim_links(text, claims, srcs), extensions=["tables", "fenced_code", "sane_lists"])
        h = re.sub(r"<h1>", "<h3>", h).replace("</h1>", "</h3>")
        anchor = re.sub(r"[^a-z]+", "-", rel)
        toc.append(f"<li><a href='#{anchor}'>{title}</a></li>")
        sections.append(f"<section class='doc' id='{anchor}'><h2>{title}</h2>{h}</section>")
    decs = load_decisions(pid)
    if decs:
        rows = "".join(f"<tr><td>{x['id']}</td><td>{html.escape(x.get('title', ''))}</td><td>{html.escape(str(x.get('chosen', '')))}</td>"
                       f"<td>[{', '.join(x.get('rationale_claims', []))}]</td><td>{len(x.get('commitments', []))}</td>"
                       f"<td>{'; '.join(html.escape(str(t.get('note') or t.get('value') or t.get('claim'))) for t in x.get('review_triggers', []))}</td></tr>"
                       for x in decs)
        sections.append("<section class='doc' id='decisions'><h2>Журнал решений</h2><table><tr><th>ID</th><th>Решение</th>"
                        "<th>Выбрано</th><th>Основания</th><th>Обязательств</th><th>Условия пересмотра</th></tr>"
                        f"{_claim_links(rows, claims, srcs)}</table></section>")
        toc.append("<li><a href='#decisions'>Журнал решений</a></li>")
        commitments = []
        for decision in decs:
            tasks = decision.get("commitments", [])
            status_by_id = {task["id"]: task.get("status", "open") for task in tasks}
            for task in tasks:
                waiting = [key for key in task.get("depends_on", []) if status_by_id.get(key) != "done"]
                status = {"done": "Выполнено", "open": "К выполнению"}.get(task.get("status"), task.get("status") or "К выполнению")
                if waiting and task.get("status") != "done":
                    status = "Ожидает " + ", ".join(waiting)
                cells = [f"{decision['id']}/{task['id']}", task.get("what"), task.get("owner"), task.get("due"), status]
                commitments.append("<tr>" + "".join(f"<td>{html.escape(str(cell or '—'))}</td>" for cell in cells) + "</tr>")
        if commitments:
            sections.append("<section id='commitments'><h3>Обязательства</h3><table><tr><th>ID</th><th>Что сделать</th>"
                            "<th>Ответственный</th><th>Срок</th><th>Статус</th></tr>" + "".join(commitments) + "</table></section>")
    # реестры
    crow = "".join(
        f"<tr id='{c['id']}'><td>{c['id']}</td><td>{CLAIM_KIND_RU.get(c['kind'], c['kind'])}</td><td>{html.escape(c['text'])}"
        f"{'<br><i>«' + html.escape(c['quote']) + '»</i>' if c.get('quote') else ''}</td>"
        f"<td>{_claim_basis(c, claims, srcs)}</td><td>{c.get('confidence', '')}</td>"
        f"<td>{c.get('status')}</td></tr>" for c in claims.values())
    srow = "".join(
        f"<tr id='{s['id']}'><td>{s['id']}</td><td>{html.escape(s['title'])}</td><td>{html.escape(s.get('publisher') or '')}</td>"
        f"<td>{s.get('published', '')}</td><td>{s.get('reliability')}</td>"
        f"<td>{_source_location(s, d)}</td>"
        f"<td>{'⚠ ' + str(len(s.get('injection_flags', []))) if s.get('injection_flags') else ''}</td></tr>" for s in srcs.values())
    sections.append(f"<section class='doc' id='claims'><h2>Реестр утверждений</h2><table><tr><th>ID</th><th>Тип</th><th>Утверждение и цитата</th>"
                    f"<th>Основание</th><th>Уверенность</th><th>Статус</th></tr>{crow}</table></section>")
    sections.append(f"<section class='doc' id='sources'><h2>Источники</h2><p class='meta'>Надёжность: A — первичный/официальный, "
                    f"B — авторитетный вторичный, C — вторичный, D — непроверенный/синтетика.</p><table><tr><th>ID</th><th>Название</th>"
                    f"<th>Издатель</th><th>Дата</th><th>Надёжн.</th><th>Где</th><th>Инъекции</th></tr>{srow}</table></section>")
    jr = read_jsonl(d / "journal.jsonl")
    acts: dict[str, int] = {}
    for r in jr:
        acts[r.get("action", "?")] = acts.get(r.get("action", "?"), 0) + 1
    by_task = "".join(f"<tr><td>{k}</td><td>${v:.4f}</td></tr>" for k, v in sorted(cs["by_task"].items(), key=lambda x: -x[1]))
    sections.append("<section class='doc' id='transparency'><h2>Прозрачность: что сделано и сколько стоило</h2>"
                    f"<p>Действий в журнале: {len(jr)}; сбоев: {sum(1 for r in jr if r.get('status') == 'failed')}. "
                    f"Внешние модели: ${cs['external_usd']:.4f} за {cs['external_calls']} вызовов (из кэша без оплаты: {cs['cached_calls']}). "
                    f"Субагенты и ручные записи: ≈${cs['subagent_usd']:.2f}; основной чат IDE: ≈${cs['session_usd']:.2f}"
                    f"{' — не входит в стоимость проекта: ' + html.escape(cs['session_note']) if cs['session_mixed'] else ''}. "
                    f"<b>Стоимость проекта: ≈${cs['project_usd']:.2f}</b> (по журналу и ручным оценкам).</p>"
                    "<div class='chips'>" + "".join(f"<span>{html.escape(k)}: {v}</span>" for k, v in sorted(acts.items(), key=lambda x: -x[1])) + "</div>"
                    f"<h3>Внешние модели по задачам</h3><table><tr><th>Задача</th><th>USD</th></tr>{by_task}</table></section>")
    toc += ["<li><a href='#claims'>Реестр утверждений</a></li>", "<li><a href='#sources'>Источники</a></li>",
            "<li><a href='#transparency'>Прозрачность и стоимость</a></li>"]
    page = (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(st.get('title', d.name))}</title><style>{CSS}</style></head><body><main>"
            + "".join(body) + f"<nav><h3>Содержание</h3><ol>{''.join(toc)}</ol></nav>" + "".join(sections) + "</main></body></html>")
    out = d / "report" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    res = {"html": out.relative_to(d).as_posix()}
    if pdf:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(out.resolve().as_uri())
            pg.emulate_media(color_scheme="light")
            pg.pdf(path=str(out.with_suffix(".pdf")), format="A4", print_background=True,
                   margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            b.close()
        res["pdf"] = out.with_suffix(".pdf").relative_to(d).as_posix()
    journal("report_rendered", str(res), pid=pid, actor="tool")
    return res
