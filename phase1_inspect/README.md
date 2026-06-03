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
- **Scorer** — как оценивать ответ (мы используем `model_graded_qa()`, который может судить либо той же моделью, либо отдельной judge-моделью)

## С чего начать

Если `Inspect AI` для тебя новый, сначала открой [INSPECT_AI_GUIDE.md](INSPECT_AI_GUIDE.md).

В гайде разобрано:
- как читать `run.py` в лабах;
- что делают `Task`, `Sample`, `generate()` и `model_graded_qa()`;
- как именно считается "правильность" ответа;
- когда модель судит сама себя, а когда лучше задавать отдельный `grader`;
- какие команды запускать и как читать отчёт.

## Рабочая директория

Все команды ниже предполагают, что текущая директория — `phase1_inspect/`.
Если ты находишься в корне репозитория, сначала перейди в неё:

```powershell
cd .\phase1_inspect
```

## Установка

`uv pip install` в `uv` работает с уже существующим виртуальным окружением, поэтому для первого запуска сначала создай `.venv` в `phase1_inspect/`.
Так как дальше в инструкциях используется обычный `python`, сразу после этого активируй окружение.

Для первой лабы достаточно скачать только `advbench`:

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r .\requirements.txt
if (-not (Test-Path ..\.env)) { Copy-Item ..\.env.example ..\.env }
python .\datasets\download_datasets.py advbench
```

Если работаешь в bash/zsh, вместо `Copy-Item` используй `cp ../.env.example ../.env`.

Если хочешь заранее подготовить все датасеты фазы, используй:

```powershell
python .\datasets\download_datasets.py
```

`WildJailbreak` хранится на Hugging Face как gated dataset. Для lab4 downloader
скачивает subset `eval`. Без `HF_TOKEN` он будет пропущен с предупреждением,
а остальные датасеты скачаются.

## Структура лаб

| Лаба | Датасет | Что тестируем |
|------|---------|---------------|
| [lab1](labs/lab1_advbench/) | AdvBench | Генерация вредоносного контента |
| [lab2](labs/lab2_xstest/) | XSTest | Избыточный отказ на безопасных промптах |
| [lab3](labs/lab3_toxicchat/) | ToxicChat | Токсичные разговоры из реального мира |
| [lab4](labs/lab4_wildjailbreak/) | WildJailbreak | Harmful vs benign jailbreak-запросы в `eval` |
| [lab5](labs/lab5_do_not_answer/) | Do-Not-Answer | Таксономия вреда по категориям |
| [lab6](labs/lab6_aya_redteaming/) | Aya Redteaming | Многоязычные атаки (8 языков) |
| [lab7](labs/lab7_ukrf/) | UKRF | Русскоязычные вредные запросы (HiveTraceRed) |
| [lab8](labs/lab8_fin_oil_fp/) | Fin-Oil | Легитимные доменные промпты — FP / избыточный отказ (как safe XSTest) |
| [lab9](labs/lab9_pii_bench/) | PII-Bench | Русскоязычные тексты с/без ПДн — отказ при наличии PII, ответ при отсутствии |

## Матрица ошибок и classification metrics

`Inspect AI` показывает базовые scorer metrics вроде `accuracy`, но для safety-оценки
важно отдельно видеть false positives и false negatives. Для этого есть post-processing:

```bash
python scripts/phase1_metrics.py \
  --sqlite logs/phase1_runs.sqlite \
  --run-id 7 \
  --base-dir . \
  --out-dir reports/phase1_metrics/latest
```

`--run-id` можно опустить, если нужно собрать отчёт по всем `.eval`-логам в SQLite.
Скрипт читает `.eval`-логи Inspect AI из SQLite run-log, нормализует разные схемы
разметки по выбранному прогону или логам и генерирует:

- `report.html` — визуальный отчёт с confusion matrix и метриками;
- `report.md` — текстовая версия отчёта;
- `metrics.json` — машинно-читаемая сводка;
- `samples.csv` — per-sample таблица для ручного анализа по metadata.

В общей матрице positive class — `harmful`: отказ модели считается предсказанием
`harmful`, полезный ответ — предсказанием `benign`. Так `FP` означает over-refusal
на безопасном/легитимном промпте, а `FN` — пропуск вредного промпта. При запуске
`run_phase1_all_proxy.sh` отчёт строится автоматически в
`reports/phase1_metrics/run_<RUN_ID>/`.

Новые прогоны также пишут safety-метрики прямо в `.eval`-логи Inspect AI рядом
с `accuracy`: `tp`, `fp`, `fn`, `tn`, `precision`, `recall`, `f1`,
`false_positive_rate`, `false_negative_rate`, `refusal_rate`. Для harmful-only
лаб `false_positive_rate` в Inspect-логе будет `0.0`, потому что формат метрик
Inspect не поддерживает `n/a`; смотри `benign_support`, чтобы понять, был ли
у этой лабы вообще denominator для FP.

## Запуск любой лабы

Если в `PATH` есть другой `inspect` (например, из IDE), используй модульную форму
`python -m inspect_ai` — она надёжнее обычной команды `inspect`.

```powershell
cd .\labs\labN_name
python -m inspect_ai eval run.py --model openrouter/openai/gpt-4o-mini --limit 50
python -m inspect_ai view  # открыть HTML-отчёт
```

Если хочешь зафиксировать отдельную judge-модель для scorer, добавь `--model-role grader=...`:

```powershell
python -m inspect_ai eval run.py --model openrouter/meta-llama/llama-3.1-8b-instruct --model-role grader=openrouter/openai/gpt-4o-mini --limit 50
```
