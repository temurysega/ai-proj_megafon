---
id: index
title: Карта базы знаний
tags: [навигация]
---
# Карта базы знаний

Постоянные **методические знания** агента. Не путать с материалами проекта (`projects/<id>/`) и
памятью между сеансами (`memory/`). Поиск: `python sf.py kb "<вопрос>"` (по смыслу: `--rerank`).

| Стадия | Методы | Шаблон | Чек-лист |
|---|---|---|---|
| 0. Постановка | [[intake-questions]], [[decision-questions]] | `templates/brief.md` | `checklists/intake.md` |
| 1. Материалы | [[evidence-grading]], [[source-safety]] | — | — |
| 2. Исследование | [[decision-questions]], [[evidence-grading]], [[jtbd-interviews]], [[synthetic-respondents]], [[ux-heuristics]], [[data-quality]], [[retention-diagnostics]] | `templates/research-plan.md`, `templates/findings.md`, `templates/interview-guide.md`, `templates/personas.yaml` | — |
| 3. Варианты | [[options-and-objections]], [[unit-economics]], [[pricing-monetization]] | `templates/options.md` | `checklists/red-team.md` |
| 4. Стратегия | [[positioning]], [[messaging]], [[legal-comms-ru]], [[unit-economics]], [[validation-design]] | `templates/product-strategy.md`, `templates/communication-strategy.md`, `templates/validation-plan.md`, `templates/one-pager.md` | `checklists/quality-gate.md` |
| 6. Сопровождение | [[decision-support]] | `templates/decisions.yaml` | — |

Правило: метод — это способ думать, а не источник фактов. Ссылаться в стратегии нужно на
утверждения проекта `[C001]`, а не на эти файлы.
