"""Сборка описания работы в PDF: python scripts/build_description.py
docs/report/description.md → description.html (изображения встраиваются) → description.pdf (Chromium)."""
import base64
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "report" / "description.md"
CSS = """
body{font:13px/1.5 'Segoe UI',Arial,sans-serif;color:#1c1d21;margin:0}
main{max-width:900px;margin:0 auto;padding:10px 6px}
h1{font-size:24px;color:#00a650;margin:0 0 6px}h2{font-size:18px;margin:22px 0 8px;padding-top:6px;border-top:2px solid #e3e5ea;color:#731982}
h3{font-size:15px;margin:14px 0 6px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:11.5px}th,td{border:1px solid #d0d4da;padding:4px 6px;vertical-align:top;text-align:left}
th{background:#f3f4f6}code{background:#f3f4f6;padding:0 3px;border-radius:3px;font-size:11px}
img{max-width:100%;border:1px solid #e3e5ea;border-radius:6px;margin:6px 0 2px}
p.cap{font-size:11px;color:#5d6270;margin:0 0 10px}
h2{page-break-after:avoid}table,img,svg{page-break-inside:avoid}
"""


def main():
    text = SRC.read_text(encoding="utf-8")

    def img(m):
        alt, rel = m.group(1), m.group(2)
        p = (SRC.parent / rel).resolve()
        data = base64.b64encode(p.read_bytes()).decode()
        return f'<img alt="{alt}" src="data:image/png;base64,{data}"><p class="cap">{alt}</p>'
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img, text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    html = f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Стратег — описание работы</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"
    out = SRC.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(out.as_uri())
        pg.pdf(path=str(SRC.with_suffix(".pdf")), format="A4", print_background=True,
               margin={"top": "12mm", "bottom": "12mm", "left": "11mm", "right": "11mm"},
               display_header_footer=True, header_template="<span></span>",
               footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#888'>Стратег Фабрики продуктов · стр. <span class='pageNumber'></span> из <span class='totalPages'></span></div>")
        b.close()
    print(SRC.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
