"""Скриншот вывода команды в виде окна терминала (для отчёта): python scripts/term_shot.py <out.png> "<команда>" [заголовок]

Команда выполняется в корне репозитория; вывод (с ANSI-цветами rich) превращается в HTML и снимается Playwright.
"""
import html
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANSI = re.compile(r"\x1b\[([0-9;]*)m")
COLORS = {"31": "#ff6b6b", "32": "#5fd068", "33": "#f5c451", "34": "#6aa6ff", "35": "#d08cff", "36": "#56d4dd",
          "91": "#ff8787", "92": "#8ce99a", "93": "#ffe066", "94": "#91a7ff", "95": "#e599f7", "96": "#66d9e8"}


def ansi_to_html(text: str) -> str:
    out, open_spans = [], 0
    pos = 0
    for m in ANSI.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        codes = m.group(1).split(";") if m.group(1) else ["0"]
        if "0" in codes or codes == [""]:
            out.append("</span>" * open_spans)
            open_spans = 0
        style = []
        for c in codes:
            if c == "1":
                style.append("font-weight:700")
            elif c in COLORS:
                style.append(f"color:{COLORS[c]}")
        if style:
            out.append(f'<span style="{";".join(style)}">')
            open_spans += 1
        pos = m.end()
    out.append(html.escape(text[pos:]))
    out.append("</span>" * open_spans)
    return "".join(out)


def main():
    out_png, cmd = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else cmd
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "FORCE_COLOR": "1", "COLUMNS": "118", "TERM": "xterm-256color"}
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, env=env, timeout=600)
    text = (r.stdout + r.stderr).decode("utf-8", "replace")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:#e9ecef;font-family:Segoe UI,Arial}}
.win{{margin:18px;border-radius:10px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,.25);background:#1e1f24;width:1100px}}
.bar{{background:#2d2f36;color:#c9ccd3;padding:8px 14px;font-size:13px}}
.bar b{{color:#8ce99a}}
pre{{margin:0;padding:14px 16px;color:#e6e6e6;font:13px/1.45 Consolas,'Cascadia Mono',monospace;white-space:pre-wrap}}
</style></head><body><div class="win"><div class="bar">● ● ● &nbsp; <b>$</b> {html.escape(title)}</div>
<pre>{ansi_to_html(text)}</pre></div></body></html>"""
    tmp = ROOT / ".cache" / "term_shot.html"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(page, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1140, "height": 400}, device_scale_factor=1)
        pg.goto(tmp.as_uri())
        pg.locator(".win").screenshot(path=out_png)
        b.close()
    print(f"{out_png} (код возврата {r.returncode})")


if __name__ == "__main__":
    main()
