# Phase 1 — Статическое тестирование с Inspect AI

## Что такое статические бенчмарки?

Статические бенчмарки — это заранее собранные датасеты вредоносных или пограничных промптов.
Каждый датасет тестирует **конкретный режим отказа** модели. Понимание различия между режимами
— главная цель этой фазы.

## Фреймворк: Inspect AI

[Inspect AI](https://inspect.aisi.org.uk/) — фреймворк для оценки LLM от UK AI Safety Institute.

Три ключевых концепта:
- **Task** — определяет датасет + решатель (solver) + scorer
- **Solver** — как генерировать ответ (обычно `generate()`)
- **Scorer** — как оценивать ответ (мы используем `model_graded_qa()`)

## Установка

```bash
pip install -r requirements.txt
cp ../../.env.example ../../.env  # если ещё не сделано
python datasets/download_datasets.py
```

## Структура лаб

| Лаба | Датасет | Что тестируем |
|------|---------|---------------|
| [lab1](labs/lab1_advbench/) | AdvBench | Генерация вредоносного контента |
| [lab2](labs/lab2_xstest/) | XSTest | Избыточный отказ на безопасных промптах |
| [lab3](labs/lab3_toxicchat/) | ToxicChat | Токсичные разговоры из реального мира |
| [lab4](labs/lab4_wildjailbreak/) | WildJailbreak | Адверсариальные джейлбрейки |
| [lab5](labs/lab5_do_not_answer/) | Do-Not-Answer | Таксономия вреда по категориям |
| [lab6](labs/lab6_aya_redteaming/) | Aya Redteaming | Многоязычные атаки (8 языков) |

## Запуск любой лабы

```bash
cd labs/labN_name
inspect eval run.py --model openrouter/openai/gpt-4o-mini --limit 50
inspect view  # открыть HTML-отчёт
```
