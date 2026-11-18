---
name: interviews
description: Интервью — подготовка гайда без наводящих вопросов, анализ реальных транскриптов (с согласием и без ПДн) и беседы с модельными (синтетическими) респондентами для поиска гипотез. Используй, когда нужны мотивы, барьеры и слова аудитории.
---
# Навык: интервью и модельные респонденты

## Гайд
1. Прочитай `knowledge/methods/jtbd-interviews.md`. Гайд по шаблону `knowledge/templates/interview-guide.md`
   в `research/interviews/guide.md` — вопросы нумеруются «1. …» (их читает `sf respondents`).
2. Вопросы о прошлом поведении, без названия решения до конца, без «купили бы вы».

## Модельные респонденты (только гипотезы!)
1. Прочитай `knowledge/methods/synthetic-respondents.md`.
2. Персоны в `research/interviews/personas.yaml` (шаблон `knowledge/templates/personas.yaml`): конкретные, с
   противоречиями и ограничениями; включи скептиков.
3. С ключом OpenRouter: `python sf.py respondents --personas research/interviews/personas.yaml --guide research/interviews/guide.md --followups 1`
   (`-p <проект>` при необходимости). Без ключа: субагент `respondent` по одной персоне на вызов; транскрипт сохрани в
   `research/interviews/synthetic/<id>.md` с баннером СИНТЕТИКА и зарегистрируй источник `--kind synthetic --reliability D`.
4. Анализ: `python sf.py interviews research/interviews/synthetic --synthetic`.
5. Выводы → утверждения `--kind synthetic` или `hypothesis` + проверка в плане (реальные интервью/тест).
   Никаких «X% респондентов» и выводов о спросе.

## Реальные интервью
1. Только с согласием: строка `consent: yes` в шапке транскрипта; ФИО/телефоны не записываются.
2. Храни исходную запись реального интервью вне проекта. Расшифруй локально: `python scripts/transcribe_local.py <запись> --out research/interviews/real/R06.md --id R06 --consent "yes — …"` (запись не уходит во внешние сервисы), замени имена на [имя] и проверь обезличивание. В папку проекта помести только проверенный текст с отметкой согласия.
3. `python sf.py interviews research/interviews/real` → темы «n из N» с дословными цитатами.
