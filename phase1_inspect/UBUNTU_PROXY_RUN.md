# Ubuntu: запуск `lab1_advbench` через прокси

Этот сценарий нужен для запуска `Inspect AI` на Ubuntu-сервере, где:

- тестируемая модель идёт через OpenAI-compatible proxy;
- judge-модель идёт через OpenRouter;
- конфиг читается из корневого `.env`;
- если передан `limit`, запускается указанное число samples, а без него запускается весь датасет.

## Что должно быть в `.env`

В корне репозитория нужен файл `.env` со значениями вида:

```dotenv
OPENROUTER_API_KEY=...
TARGET_MODEL=openai-api/myproxy/AlphaGaO/Qwen3-14B-GPTQ
GRADER_MODEL=openrouter/inclusionai/ling-2.6-flash:free
MYPROXY_BASE_URL=http://10.70.54.230:8008/v1
MYPROXY_API_KEY=dummy
```

Скрипт `run_advbench_proxy.sh` сам читает этот файл перед запуском `inspect_ai`.

## Подготовка окружения

Из директории `phase1_inspect/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python ./datasets/download_datasets.py advbench
chmod +x ./run_advbench_proxy.sh
```

Если `advbench` уже скачан, повторно загружать его не нужно.

## Запуск с ограничением

Чтобы запустить только один sample:

```bash
./run_advbench_proxy.sh 1
```

Аргумент `1` будет передан как `--limit 1`.

Если хочешь запускать вручную без launcher-скрипта, используй именно POSIX-путь:

```bash
python -m inspect_ai eval ./labs/lab1_advbench/run.py \
  --model "openai-api/myproxy/AlphaGaO/Qwen3-14B-GPTQ" \
  --model-role "grader=openrouter/inclusionai/ling-2.6-flash:free" \
  --limit 1 \
  --display plain \
  --max-connections 1 \
  --env MYPROXY_BASE_URL=http://10.70.54.230:8008/v1 \
  --env MYPROXY_API_KEY=dummy
```

Важно:

- на Ubuntu используй `./labs/...`, а не `.\labs\...`;
- `inspect_ai` на Linux ожидает относительный путь к task file, а не Windows-путь;
- launcher `run_advbench_proxy.sh` уже делает это автоматически.

## Полный запуск датасета

Чтобы запустить весь `advbench`, просто не передавай `limit`:

```bash
./run_advbench_proxy.sh
```

## Что проверяет скрипт

Перед запуском скрипт валидирует:

- что существует корневой `.env`;
- что есть `phase1_inspect/.venv/bin/python`;
- что существует `labs/lab1_advbench/run.py`;
- что скачан `datasets/advbench/harmful_behaviors.csv`;
- что в `.env` заданы `OPENROUTER_API_KEY`, `TARGET_MODEL`, `GRADER_MODEL`, `MYPROXY_BASE_URL`, `MYPROXY_API_KEY`.

## Типовой сценарий работы

1. Один раз настроить `.env`.
2. Один раз подготовить `.venv` и датасет.
3. При необходимости ограничить прогон командой `./run_advbench_proxy.sh 1` или `./run_advbench_proxy.sh 10`.
4. Для полного прогона запускать весь датасет командой `./run_advbench_proxy.sh`.

## Замечание про `wildjailbreak`

Этот launcher сделан для `lab1_advbench`. Для больших датасетов вроде `wildjailbreak` лучше делать отдельный сценарий запуска и отдельно управлять лимитами/стоимостью.
