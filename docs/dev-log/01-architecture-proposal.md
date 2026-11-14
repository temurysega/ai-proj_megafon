# 01. Проект архитектуры (до ревью)

Дата: 2026-11-14 · Автор: основной агент-разработчик (Claude Opus 5.5, Claude Code)

## Идея в одном абзаце
Агент — это **LLM внутри IDE** (Claude Code / Cursor / Codex / Copilot), которая читает `AGENTS.md`, ведёт работу по стадиям и для всего, что должно быть *проверяемым*, вызывает детерминированные инструменты на Python (CLI `sf` и MCP-сервер). Состояние задачи живёт в файлах проекта (`projects/<id>/state.yaml`, журнал, реестр источников, реестр утверждений), поэтому работу можно остановить и продолжить в новом чате или в другой IDE. Дешёвые массовые операции (классификация, извлечение, модельные респонденты, судья, зрение, аудио) маршрутизируются на китайские модели через OpenRouter с учётом стоимости.

## Разделение знаний (4 слоя)
| Слой | Где | Кто меняет |
|---|---|---|
| Постоянные инструкции | `AGENTS.md`, `.claude/agents`, `.claude/skills`, `config/` | только человек (хук блокирует правку агентом вне dev-режима) |
| Методические знания | `knowledge/` (методы, шаблоны, чек-листы) | человек/агент по запросу |
| Материалы проекта | `projects/<id>/sources`, `evidence`, `research` | агент через инструменты |
| Состояние задачи | `projects/<id>/state.yaml`, `journal.jsonl`, `costs.jsonl` | агент + хуки |
| Память между сеансами | `memory/entries.jsonl` (с происхождением и статусом) | агент, отзыв — `sf memory retract` |

## Рабочий процесс (стадии и ворота)
0 intake → 1 materials → 2 research → 3 options → [человек выбирает] → 4 strategy → 5 review → 6 support (решения, обязательства, пересмотр).
Ворота: G1 «бриф подтверждён», G2 «вариант выбран», G3 «стратегия принята». Режим `checkpoints` (по умолчанию) или `autopilot` (допущения записываются как `assumption`).

## Доказательная база
- `sources/registry.yaml` — S01…: url/путь, издатель, дата, sha256 снимка, флаги инъекций.
- `evidence/claims.jsonl` — C001…: текст, тип (fact / estimate / hypothesis / forecast / assumption / synthetic / opinion), источники, цитата-локатор, уверенность, статус (active / disputed / retracted / superseded), зависимости.
- Все выводы в markdown ссылаются на `[C012]`. `sf check` проверяет: ссылки существуют, у фактов есть источник и цитата, синтетика не подтверждает спрос, в рекомендации нет отозванных утверждений.
- `sf impact C012` — граф зависимостей: какие разделы и решения задеты изменением утверждения.

## Инструменты (Python, CLI `sf` + MCP-сервер с теми же функциями)
new/status/resume/checkpoint · source add/fetch (allowlist + детектор инъекций + снимок) · ingest (pdf/docx/xlsx/csv/html/изображения/аудио/видео) · claim add/update/retract · check · impact · kb search (BM25 + связи + LLM-rerank) · memory add/search/retract · route/ask (OpenRouter, кэш, ретраи, фолбэк, учёт стоимости) · respondents (синтетические интервью) · interview analyze (+ очистка ПДн) · data profile/run · capture (скриншоты сайтов) · decide/commitments/due · revisit · render (HTML/PDF) · cost · eval · doctor.

## Субагенты (Claude Code)
researcher (sonnet) · fact-checker (haiku) · red-team (sonnet) · respondent (haiku, фолбэк) · ux-analyst (sonnet, зрение) · jury (sonnet, оценка по рубрике).

## Навыки (skills)
intake, source-collection, research, options, product-strategy, comms-strategy, validation-plan, interviews, ux-review, data-analysis, decision-support, revisit, report.

## Хуки
SessionStart (подгрузить статус проекта → продолжение в новом чате) · PreToolUse WebFetch (allowlist) · PreToolUse Write/Edit (запрет правки правил и записи секретов) · PostToolUse Write/Edit (журнал + линт ссылок на утверждения) · Stop (учёт токенов IDE-модели из транскрипта + проверка, что state.yaml обновлён) · UserPromptSubmit («стоп/пауза» → чекпойнт).

## Маршрутизация моделей (OpenRouter, цены на 2026-11-14)
| Задача | Модель | Фолбэк |
|---|---|---|
| классификация/роутинг | qwen/qwen3.7-flash | z-ai/glm-5.3-flash |
| извлечение утверждений | deepseek/deepseek-v4.1-flash | qwen/qwen3.8-flash |
| модельные респонденты | ротация: deepseek-v4-flash, qwen3.8-flash, glm-5.3-flash, minimax-m3.1-flash | Haiku-субагент |
| судья/вторая точка зрения | deepseek/deepseek-v4-pro | qwen/qwen3.7-plus |
| зрение | qwen/qwen3.8-flash | z-ai/glm-5.3-flash |
| аудио | qwen/qwen3.8-omni-flash | xiaomi/mimo-v2.6-flash |
Синтез стратегии делает основная IDE-модель (самая сильная) — там, где цена ошибки выше.

## Демо-проект (брифа ещё нет)
«Семейная защита от телефонных мошенников»: базовая защита у операторов стала бесплатной, 76% абонентов считают, что так и должно быть. Что делать с продуктом класса «Защита близких» и как говорить с аудиторией? Только открытые источники.

## Сравнение с исходным способом
Тот же запрос → (а) обычный чат с ИИ одним промптом без инструментов, (б) агент. Слепая оценка двумя судьями разных семейств по рубрике критериев + объективные метрики (доля утверждений с источником, точность по выборочной проверке фактов, число вариантов/возражений), время и стоимость.
