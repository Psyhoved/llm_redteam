# Ubuntu: запуск Phase 2 через proxy/OpenRouter

Этот документ описывает smoke и боевой запуск `lab1_owasp_top10` в Phase 2.

## Требования

- Корень репозитория: `~/llm_redteam`
- Рабочая директория: `~/llm_redteam/phase2_deepteam`
- Заполненный `../.env`
- Подготовленная `.venv` и установленные зависимости

## Подготовка

```bash
cd ~/llm_redteam/phase2_deepteam
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
chmod +x ./run_owasp_top10_proxy.sh
chmod +x ./run_owasp_top10_smoke_proxy.sh
```

## Переменные `.env`

Нативный Phase 2 вариант:

```dotenv
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
ATTACKER_MODEL=openai/gpt-4o-mini
JUDGE_MODEL=openai/gpt-4o-mini
ATTACKS_PER_TYPE=1
MAX_CONCURRENT=1
```

Совместимый с Phase 1 proxy вариант:

```dotenv
OPENROUTER_API_KEY=...
TARGET_MODEL=openai-api/myproxy/AlphaGaO/Qwen3-14B-GPTQ
GRADER_MODEL=openrouter/inclusionai/ling-2.6-flash:free
MYPROXY_BASE_URL=http://10.70.54.230:8008/v1
MYPROXY_API_KEY=dummy
```

Если `OPENROUTER_MODEL` не задан, runner берёт Target из `TARGET_MODEL`.
В этом режиме при наличии `MYPROXY_BASE_URL` Target вызывается через proxy,
а Attacker/Judge остаются на OpenRouter.

## Smoke

```bash
./run_owasp_top10_smoke_proxy.sh
```

Это эквивалентно минимальному запуску одного тест-кейса:

```bash
./run_owasp_top10_smoke_proxy.sh 1 1
```

Аргументы:

- `1` — атак на каждую OWASP-категорию
- `1` — максимум параллельных запросов
- опциональный третий аргумент — `purpose`, например `"customer support chatbot"`

Smoke-runner добавляет `--smoke-one`, чтобы проверить plumbing на одном generated prompt,
а не разворачивать весь OWASP framework.

## Боевой запуск

Основной runner запускает полный OWASP benchmark по умолчанию:

```bash
./run_owasp_top10_proxy.sh 1 1
```

Аргументы:

- `1` — атак на каждый DeepTeam vulnerability type
- `1` — максимум параллельных запросов
- опциональный третий аргумент — `purpose`
- опциональный четвёртый аргумент — OWASP категории через запятую

Примеры:

```bash
# Полный OWASP Top 10, минимальная нагрузка
./run_owasp_top10_proxy.sh 1 1

# Полный OWASP Top 10, больше атак и умеренная параллельность
./run_owasp_top10_proxy.sh 5 2 "customer support chatbot"

# Только Prompt Injection и Sensitive Information Disclosure
./run_owasp_top10_proxy.sh 1 1 "" "LLM_01,LLM_02"
```

При полном OWASP текущая версия DeepTeam разворачивает категории в десятки
внутренних vulnerability types. Поэтому `attacks_per_type=1` — это не один вопрос,
а полный минимальный benchmark по всем внутренним типам.

Ожидаемый результат:

- runner проходит preflight `.env`, `.venv`, Python-пакетов;
- DeepTeam выполняет минимальный OWASP-прогон;
- JSON-отчёт сохраняется в `phase2_deepteam/reports/`.

Если preflight падает на `deepteam` или `deepeval`, установи зависимости:

```bash
./.venv/bin/python -m pip install -r requirements.txt
```
