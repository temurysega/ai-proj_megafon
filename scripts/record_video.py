"""Запись демо-видео сквозного пути: python scripts/record_video.py

Записывает браузер (Playwright, 1280×720) по сценарию: настоящие файлы проекта, живые запуски команд `sf`,
отчёт, сайт. Субтитры встраиваются в кадр; параллельно пишется SRT. Результат:
  docs/video/demo.mp4, docs/video/subtitles.srt, docs/video/timeline.json
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from scripts.term_shot import ansi_to_html  # noqa: E402

import yaml  # noqa: E402

W, H = 1280, 720
P = "antifraud-family"
OUT = ROOT / "docs" / "video"
TMP = ROOT / ".cache" / "video"
SITE = os.environ.get("STRATEGIST_SITE", "https://mgim.neblanki.tech")
REPORT = (ROOT / "projects" / P / "report" / "index.html").resolve().as_uri()
REPORT2 = (ROOT / "projects" / "esim-travel" / "report" / "index.html").resolve().as_uri()
DESC = (ROOT / "docs" / "report" / "description.html").resolve().as_uri()

FONT = "-apple-system,'Segoe UI','Inter',Arial,sans-serif"
CAPTION_JS = """(t)=>{let c=document.getElementById('__cap');
 if(!c){c=document.createElement('div');c.id='__cap';
  c.style.cssText='position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:1100px;z-index:2147483647;'+
  'background:rgba(0,0,0,.78);color:#fff;font:600 22px/1.35 -apple-system,Segoe UI,Inter,Arial,sans-serif;padding:12px 20px;border-radius:14px;'+
  'text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.35);letter-spacing:-.005em';document.body.appendChild(c);}
 c.textContent=t; c.style.display=t?'block':'none';}"""

timeline = []
T0 = [0.0]


def run(cmd: str) -> str:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "FORCE_COLOR": "1", "COLUMNS": "104", "STRATEGIST_QUIET": "1"}
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, env=env, timeout=300)
    return (r.stdout + r.stderr).decode("utf-8", "replace")


def page_shell(body: str, dark=False, extra_css="") -> str:
    bg, fg = ("#000", "#f5f5f7") if dark else ("#f5f5f7", "#1d1d1f")
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><style>"
            f"html,body{{margin:0;height:100%;background:{bg};color:{fg};font-family:{FONT};-webkit-font-smoothing:antialiased}}"
            f"{extra_css}</style></head><body>{body}</body></html>")


def title_card(kicker: str, title: str, sub: str = "") -> str:
    css = (".c{height:100%;display:grid;place-content:center;text-align:center;gap:14px;padding:0 80px}"
           ".k{font-size:22px;font-weight:600;color:#86868b}.t{font-size:64px;font-weight:700;letter-spacing:-.03em;line-height:1.05}"
           ".s{font-size:26px;color:#a1a1a6;font-weight:500;max-width:980px;margin:0 auto}"
           ".g{background:linear-gradient(90deg,#2997ff,#a78bfa 55%,#ff6aa2);-webkit-background-clip:text;color:transparent}")
    return page_shell(f"<div class='c'><div class='k'>{kicker}</div><div class='t'>{title}</div><div class='s'>{sub}</div></div>",
                      dark=True, extra_css=css)


def terminal(cmd_title: str, cmd: str, output_html: str, speed_ms: int = 55) -> str:
    css = ("body{display:grid;place-items:center}.w{width:1180px;height:600px;background:#1e1f24;border-radius:14px;overflow:hidden;"
           "box-shadow:0 18px 50px rgba(0,0,0,.35);display:flex;flex-direction:column}"
           ".b{background:#2d2f36;color:#c9ccd3;padding:9px 14px;font-size:13px}"
           "pre{margin:0;padding:14px 18px;color:#e6e6e6;font:15px/1.5 Consolas,'Cascadia Mono',monospace;white-space:pre-wrap;"
           "overflow:hidden;flex:1}.p{color:#8ce99a}.cur{display:inline-block;width:9px;height:17px;background:#e6e6e6;vertical-align:-3px}")
    lines = output_html.split("\n")
    body = (f"<div class='w'><div class='b'>● ● ● &nbsp; {html.escape(cmd_title)}</div><pre id='o'><span class='p'>$ </span>"
            f"<span id='cmd'></span><span class='cur' id='cur'></span>\n</pre></div>"
            f"<script>(()=>{{const cmd={json.dumps(cmd)};const L={json.dumps(lines)};let i=0;const o=document.getElementById('o');"
            f"const c=document.getElementById('cmd');const t=setInterval(()=>{{c.textContent=cmd.slice(0,++i);if(i>=cmd.length){{clearInterval(t);"
            f"document.getElementById('cur').remove();let j=0;const u=setInterval(()=>{{if(j>=L.length){{clearInterval(u);return}}"
            f"o.insertAdjacentHTML('beforeend',L[j++]+'\\n');o.scrollTop=o.scrollHeight}},{speed_ms})}}}},38);}})();</script>")
    return page_shell(body, dark=False, extra_css=css)


def chat_page(messages) -> str:
    css = (".w{max-width:980px;margin:0 auto;padding:40px 30px;display:grid;gap:14px}"
           ".m{max-width:820px;padding:14px 18px;border-radius:18px;font-size:19px;line-height:1.45;opacity:0;transform:translateY(8px);"
           "transition:all .45s}.m.on{opacity:1;transform:none}.u{background:#0071e3;color:#fff;justify-self:end;border-bottom-right-radius:6px}"
           ".a{background:#fff;border:1px solid #d2d2d7;border-bottom-left-radius:6px}.n{font-size:13px;color:#86868b;margin-bottom:4px;font-weight:600}"
           ".u .n{color:#cfe3ff}.q{margin:6px 0 0 0;padding-left:20px}.q li{margin:4px 0}.sm{font-size:15px;color:#6e6e73}")
    parts = []
    for who, name, text in messages:
        parts.append(f"<div class='m {who}'><div class='n'>{name}</div>{text}</div>")
    js = ("<script>(()=>{const M=[...document.querySelectorAll('.m')];let k=0;window.nx=function(){if(k<M.length){M[k++].classList.add('on');"
          "window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'})}};})();</script>")
    return page_shell(f"<div class='w'>{''.join(parts)}</div>{js}", extra_css=css)


def md_page(md_text: str, title: str) -> str:
    import markdown
    body = markdown.markdown(md_text, extensions=["tables"])
    css = (".w{max-width:1080px;margin:0 auto;padding:36px 40px 120px;font-size:17px;line-height:1.5}"
           "table{border-collapse:collapse;width:100%;font-size:14px;background:#fff;border-radius:12px;overflow:hidden}"
           "th,td{border-bottom:1px solid #e5e5ea;padding:8px 10px;text-align:left;vertical-align:top}th{background:#f2f2f7}"
           "h1{font-size:34px;letter-spacing:-.02em}h2{font-size:24px}")
    return page_shell(f"<div class='w'><div style='color:#86868b;font-weight:600'>{html.escape(title)}</div>{body}</div>", extra_css=css)


def finish_media(ff: str, mp4: Path, timeline: list) -> None:
    """Субтитры WebVTT для плеера на сайте и обложка (кадр заставки)."""
    def ts(x):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    vtt = ["WEBVTT\n"] + [f"{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n" for c in timeline]
    (OUT / "demo.vtt").write_text("\n".join(vtt), encoding="utf-8")
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "2.5", "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
                    str(OUT / "demo-poster.jpg")], check=True)


def main():
    from playwright.sync_api import sync_playwright
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)

    # --- реальные данные и выводы команд (заранее, чтобы в записи не было ожиданий) ---
    st = yaml.safe_load((ROOT / "projects" / P / "state.yaml").read_text(encoding="utf-8"))
    out_status = ansi_to_html(run(f"python sf.py status -p {P} --plain --brief"))
    out_check = ansi_to_html(run(f"python sf.py check -p {P} --max-warnings 3"))
    raw_impact = run(f"python sf.py impact C013 -p {P}")
    try:  # тот же JSON, компактно: одна строка на раздел, чтобы ответ целиком помещался на экран
        d = json.loads(raw_impact)
        dj = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731
        raw_impact = "\n".join(["{", f'  "claim": {dj(d["claim"])},', f'  "dependent_claims": {dj(d["dependent_claims"])},',
                                '  "sections": ['] + [f"    {dj(s)}," for s in d["sections"]] +
                               ["  ],", f'  "decisions": {dj(d.get("decisions", []))}', "}"])
    except Exception:
        pass
    out_impact = ansi_to_html(raw_impact)
    out_due = ansi_to_html(run(f"python sf.py decisions due -p {P}"))
    out_guard = ansi_to_html(run("python scripts/demo_guardrails.py"))
    # Настоящий текст, который хук SessionStart подал при реальном обрыве сессии на вопросе G2 (docs/dev-log/03).
    dl = (ROOT / "docs" / "dev-log" / "03-resume-after-break.md").read_text(encoding="utf-8")
    ctx = dl.split("```", 2)[1].strip("\n")
    out_resume = html.escape("\n".join(l for l in ctx.splitlines() if not l.startswith("Стоимость")))
    jr = [json.loads(l) for l in (ROOT / "projects" / P / "journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pick = [r for r in jr if r.get("action") in ("fetched", "claim_added", "research_imported", "gate", "checkpoint", "stage",
                                                    "synthetic_interview", "analysis_run", "check", "fact_check", "impact_marked_stale",
                                                    "question_asked", "question_answered", "captured", "revisit")][:150]
    jl = []
    for r in pick:
        col = {"human": "#ffd166", "tool": "#9ec5ff", "subagent": "#d0a2ff"}.get(r.get("actor"), "#8ce99a")
        jl.append(f"<span style='color:#86868b'>{r['ts'][5:16].replace('T', ' ')}</span> <span style='color:{col}'>{r.get('actor','')}</span> "
                  f"{html.escape(r.get('action',''))}: {html.escape(str(r.get('detail',''))[:92])}")
    out_journal = "\n".join(jl)
    redteam = (ROOT / "projects" / P / "research" / "quality" / "red-team-strategy.md").read_text(encoding="utf-8")

    q = st["open_questions"]
    chat = [("u", "Руководитель продукта", html.escape(st["request"])),
            ("a", "Стратег", "Создал проект <b>antifraud-family</b>, заполнил бриф по шаблону. Прежде чем исследовать — три вопроса, "
                             "от которых зависит план (у каждого — зачем и значение по умолчанию):<ol class='q'>" +
             "".join(f"<li>{html.escape(x['question'])}<div class='sm'>Зачем: {html.escape(x['why'])}</div></li>" for x in q) + "</ol>"),
            ("u", "Руководитель продукта", "<br>".join(f"{x['id']}: {html.escape(x.get('answer',''))}" for x in q)),
            ("a", "Стратег", "Принял. Бриф подтверждён — <b>ворота G1 пройдены</b>. Перехожу к сбору материалов и исследованию: "
                             "план из 6 решающих вопросов, параллельно 5 исследователей.")]

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx_b = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(TMP),
                              record_video_size={"width": W, "height": H}, locale="ru-RU", device_scale_factor=1)
        pg = ctx_b.new_page()
        pg.on("pageerror", lambda e: print("[pageerror]", e, flush=True))
        T0[0] = time.time()

        def cap(text):
            now = time.time() - T0[0]
            if timeline and timeline[-1]["end"] is None:
                timeline[-1]["end"] = now
            if text:
                timeline.append({"start": now, "end": None, "text": text})
            pg.evaluate(CAPTION_JS, text)

        def wait(s):
            pg.wait_for_timeout(int(s * 1000))

        def show(content, caption=None, settle=0.4):
            pg.set_content(content)
            wait(settle)
            if caption:
                cap(caption)

        def goto(url, caption=None, anchor=None):
            pg.goto(url, wait_until="load")
            pg.add_style_tag(content="html{scroll-behavior:smooth}")
            if anchor:
                pg.evaluate("(a)=>{const e=document.getElementById(a);if(e)window.scrollTo(0,e.getBoundingClientRect().top+window.scrollY-10)}", anchor)
            wait(0.6)
            if caption:
                cap(caption)

        def scroll(px, seconds, steps=None):
            steps = steps or max(1, int(seconds * 4))
            for _ in range(steps):
                pg.evaluate("(d)=>window.scrollBy({top:d,behavior:'smooth'})", px / steps)
                wait(seconds / steps)

        # 0. Заставка
        show(title_card("Хакатон «Стратег Фабрики продуктов»", "Стратег. <span class='g'>Сквозной путь</span>",
                        "Запрос → исследование → варианты → стратегия → продолжение после перерыва → сопровождение решения"))
        cap("ИИ-агент для руководителя цифрового продукта. Демо-проект: семейная защита от телефонных мошенников")
        wait(7)

        # 1. Запрос и вопросы
        show(chat_page(chat), "1. Запрос. Агент заполняет бриф и задаёт только вопросы, от которых зависит план")
        for k in range(len(chat)):
            pg.evaluate("window.nx()")
            wait(7 if k in (1, 2) else 5)
        cap("Человек ответил — ворота G1 пройдены. Дальше агент работает сам")
        wait(5)

        # 2. Автономная работа: журнал
        show(terminal("журнал действий агента (projects/antifraud-family/journal.jsonl)", "tail -f journal.jsonl", out_journal, speed_ms=95),
             "2. Исследование: агент сам ищет источники, сохраняет снимки, записывает утверждения с цитатами")
        wait(9)
        cap("Пять исследователей работали параллельно; каждая цитата сверялась со снимком источника")
        wait(9)
        cap("Синие строки — инструменты, жёлтые — решения человека. Всё записано в журнал")
        wait(8)

        # 2b. Проверка доказательной базы
        show(terminal("проверка доказательной базы", "python sf.py check", out_check, speed_ms=60),
             "Проверка: факт без источника, битая ссылка или синтетика как довод о спросе — ошибка")
        wait(10)
        cap("72 утверждения, 100% фактов с дословной цитатой, 0 ошибок")
        wait(7)

        # 2c. Данные и интерфейсы
        goto((ROOT / "projects" / P / "research" / "data" / "cbr_quarterly.png").resolve().as_uri(),
             "Анализ данных воспроизводимым скриптом: ряд ЦБ с учётом двух смен методики")
        wait(9)
        goto(REPORT, "Картина ситуации: что известно, что предполагаем, чего не знаем, где источники спорят", anchor="research-findings-md")
        scroll(1500, 12)
        cap("Чего не знаем — сказано прямо: почему, как влияет на решение и как узнать")
        scroll(1300, 9)

        # 3. Варианты
        goto(REPORT, "3. Варианты: семь содержательно разных, включая «оставить как есть» и «закрыть направление»", anchor="options-md")
        wait(5)
        scroll(1600, 12)
        cap("У каждого варианта — что должно быть правдой, экономика и сильные возражения")
        scroll(2600, 14)
        cap("Красная команда нашла соломенное чучело и ошибку в модели экономики — исправлено до показа человеку")
        scroll(2400, 12)
        cap("Сравнение и рекомендация с условиями, при которых она меняется. Выбирает человек — ворота G2")
        scroll(1800, 9)

        # 4. Перерыв и продолжение
        show(title_card("4. Пауза", "Сессия оборвалась на вопросе G2.", "Новый чат. Человек пишет одно слово: «продолжай»"))
        cap("Состояние живёт в файлах проекта, а не в истории переписки")
        wait(7)
        show(terminal("новый чат: хук SessionStart подал состояние автоматически", "продолжай", out_resume, speed_ms=70),
             "Хук при старте подал состояние: стадию, ворота, следующее действие, последние шаги")
        wait(10)
        cap("Агент не переспрашивал бриф и не повторял исследование — сразу задал вопрос G2. Человек выбрал вариант A+")
        wait(9)

        # 5. Стратегия
        goto(REPORT, "5. Стратегия. Резюме для руководителя на одну страницу", anchor="strategy-one-pager-md")
        scroll(1300, 12)
        goto(REPORT, "Продуктовая стратегия: аудитория и задача, альтернативы, направление, осознанные отказы, экономика", anchor="strategy-product-md")
        scroll(2200, 14)
        goto(REPORT, "Коммуникационная: барьер, ключевое сообщение, подтверждение, роль каналов", anchor="strategy-communication-md")
        scroll(1800, 10)
        cap("Обещания сверены с продуктом: то, чего нет в продукте, не обещаем")
        scroll(1500, 9)
        goto(REPORT, "План проверки: ожидаемое изменение, с чем сравниваем, срок, нежелательные последствия", anchor="strategy-validation-md")
        scroll(1800, 11)

        # 5b. Проверка качества
        show(md_page(redteam, "research/quality/red-team-strategy.md"),
             "Перед показом — проверка фактов и красная команда по стратегии")
        scroll(900, 9)
        cap("Например: SMS родителю переписан честно, эксперимент пересчитан с учётом доли принявших")
        scroll(900, 8)

        # 6. Пересмотр
        show(terminal("пересмотр при новых данных", "python sf.py impact C013", out_impact, speed_ms=55),
             "6. Новые данные: ЦБ с 2026 года считает по 12 признакам вместо 6")
        wait(8)
        cap("Граф зависимостей показал затронутые расчёты и разделы. Вывод «рост в 2026» заменён, решения не затронуты")
        wait(9)

        # 7. Сопровождение
        show(terminal("что решать сейчас", "python sf.py decisions due", out_due, speed_ms=90),
             "7. После решения: обязательства, сроки, зависимости и условия пересмотра")
        wait(10)
        cap("Агент подсказывает, что срочно, а что заблокировано до выполнения других шагов")
        wait(6)

        # 8. Безопасность
        show(terminal("защитные хуки на реальных вызовах", "python scripts/demo_guardrails.py", out_guard, speed_ms=45),
             "8. Безопасность: источники — данные, не инструкции; секреты и правила защищены")
        wait(12)

        # 9. Второй проект
        goto(REPORT2, "9. Новая задача с нуля: «eSIM для путешествий». Агент без памяти о первом проекте, без участия человека")
        wait(5)
        scroll(1400, 10)
        cap("32 источника, 45 утверждений, 0 ошибок проверки")
        wait(5)

        # 10. Сайт и итоги
        goto(SITE + "/#proof", "Сайт проекта: mgim.neblanki.tech — основные пути работы агента")
        wait(3)
        try:
            pg.click("button.c[data-c='C023']")
        except Exception:
            pass
        wait(6)
        goto(SITE + "/#results", "Итоги: 2 проекта, 0 ошибок проверки, 12 из 12 решающих фактов против 0–4 у обычного чата")
        wait(8)
        goto(DESC, "Описание работы в PDF: архитектура, модели, промпты, экономичность и ограничения")
        wait(3)
        pg.evaluate("()=>{const h=[...document.querySelectorAll('h2')].find(x=>x.textContent.includes('Экономичность'));if(h)window.scrollTo(0,h.offsetTop-10)}")
        wait(1)
        cap("Новый проект целиком — около двух долларов и полчаса работы агента")
        scroll(700, 9)

        # 11. Финал
        show(title_card("Стратег Фабрики продуктов", "Решения, которым <span class='g'>можно доверять</span>",
                        "mgim.neblanki.tech · github.com/temurysega/ai-proj_megafon"))
        cap("")
        wait(6)
        if timeline and timeline[-1]["end"] is None:
            timeline[-1]["end"] = time.time() - T0[0]
        video_path = pg.video.path()
        ctx_b.close()
        b.close()

    # --- сборка mp4 и субтитров ---
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    mp4 = OUT / "demo.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(video_path), "-c:v", "libx264", "-preset", "slow", "-crf", "30",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)

    def ts(x):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")
    srt = []
    for i, c in enumerate(timeline, 1):
        srt.append(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n")
    (OUT / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
    (OUT / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    finish_media(ff, mp4, timeline)
    dur = timeline[-1]["end"] if timeline else 0
    print(f"Готово: {mp4} ({mp4.stat().st_size // 1024 // 1024} МБ), длительность ≈{dur / 60:.1f} мин, субтитров {len(timeline)}")


if __name__ == "__main__":
    main()
