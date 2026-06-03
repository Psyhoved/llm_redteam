# Ubuntu: launcher-скрипты для всех датасетов Phase 1

Этот документ описывает запуск всех lab'ов Phase 1 через proxy/OpenRouter.

## Требования

- Корень репозитория: `~/llm_redteam`
- Рабочая директория: `~/llm_redteam/phase1_inspect`
- Заполненный `../.env` с proxy/OpenRouter переменными
- Подготовленная `.venv` и установленные зависимости
- Скачанные датасеты

## Обязательные переменные в `.env`

```dotenv
OPENROUTER_API_KEY=...
TARGET_MODEL=openai-api/myproxy/AlphaGaO/Qwen3-14B-GPTQ
GRADER_MODEL=openrouter/inclusionai/ling-2.6-flash:free
MYPROXY_BASE_URL=http://10.70.54.230:8008/v1
MYPROXY_API_KEY=dummy
```

Дополнительно:

- `TARGET_LANG` — используется для `aya` (если не передан явно, по умолчанию `en`)
- `WILDJAILBREAK_SAMPLES` — влияет только на внутреннюю выборку в lab4

## Подготовка

```bash
cd ~/llm_redteam/phase1_inspect
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python ./datasets/download_datasets.py
chmod +x ./run_*.sh
```

Если `wildjailbreak` не скачивается, нужна авторизация Hugging Face (`HF_TOKEN` или `huggingface-cli login`).

## Отдельные запуски по лабам

Все скрипты принимают опциональный `limit` первым аргументом.

```bash
./run_advbench_proxy.sh 800
./run_xstest_proxy.sh 800
./run_toxicchat_proxy.sh 800
./run_wildjailbreak_proxy.sh 800
./run_do_not_answer_proxy.sh 800
./run_ukrf_proxy.sh 800
./run_fin_oil_proxy.sh 800
./run_pii_bench_proxy.sh 800
./run_aya_proxy.sh 800 en
./run_aya_proxy.sh 800 ru
```

Смок одного примера (как в `UBUNTU_PROXY_RUN.md`): `./run_fin_oil_proxy.sh 1` или `./run_pii_bench_proxy.sh 1`.

Для `run_aya_proxy.sh`:

- аргумент 1: `limit`
- аргумент 2: язык (`en`, `ru`, и т.д.), по умолчанию `en`

## Последовательный запуск всех датасетов

```bash
./run_phase1_all_proxy.sh
```

По умолчанию этот скрипт:

- запускает все lab'ы последовательно, включая `wildjailbreak`;
- использует `limit=800`;
- для Aya запускает `en` и `ru`;
- не останавливается на первой ошибке;
- в конце печатает сводку и возвращает код `1`, если был хотя бы один сбой.

Чтобы задать другой лимит:

```bash
./run_phase1_all_proxy.sh 200
```

## Как устроена архитектура launcher-слоя

- `run_phase1_lab_proxy.sh` — общий внутренний runner (чтение `.env`, preflight, запуск `inspect_ai`)
- `run_*_proxy.sh` — явные wrapper-скрипты по lab'ам
- `run_phase1_all_proxy.sh` — последовательный orchestration runner
