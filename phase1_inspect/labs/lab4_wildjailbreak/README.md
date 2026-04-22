# Lab 4: WildJailbreak — Adversarial Jailbreak Techniques

## Цель

Прогнать held-out `eval` subset датасета **WildJailbreak** одним запуском и
измерить два режима ошибки одновременно:
- пропуск вредоносных jailbreak-запросов;
- ложные отказы на benign-запросах.

## Датасет

Для lab4 локально скачивается именно **`eval`** subset из `allenai/wildjailbreak`.
Он включает:
- `adversarial_harmful` — вредоносные jailbreak-запросы, на которые модель должна отказать;
- `adversarial_benign` — легитимные запросы в jailbreak-обёртке, на которые модель должна отвечать.

Скрипт загружает весь локальный `eval`, детерминированно перемешивает выборку,
а параметр `--limit` в `inspect eval` задаёт размер запуска.

## Разметка

Логика здесь такая же, как в `lab2_xstest`:
- harmful prompt -> **ожидается отказ**;
- benign prompt -> **ожидается нормальный полезный ответ**.

Поэтому метрики нужно смотреть с разбивкой по `metadata.data_type`.

## Задание

```bash
python -m inspect_ai eval run.py --model openrouter/openai/gpt-4o-mini --limit 100
python -m inspect_ai view
```

В отчёте разбей результаты по `data_type` через metadata filter в `inspect view`.
