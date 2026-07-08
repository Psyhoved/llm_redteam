# Phase 1 Admin UI

Веб-админка для запуска и мониторинга Phase 1 benchmark runs (Inspect AI).

## Требования

- Python venv в `phase1_inspect/.venv` с зависимостями из `requirements.txt`
- Заполненный `../.env` (модели, proxy, API keys)
- Установленный `screen` (для фоновых прогонов benchmark/HF import)
- LM Studio CLI (`~/.lmstudio/bin/lms`) — для локального guard-моделя
- Скачанные датасеты (`python ./datasets/download_datasets.py`)

## Запуск админки

```bash
cd ~/llm_redteam/phase1_inspect
uv venv                              # если .venv ещё нет
source .venv/bin/activate
uv pip install -r requirements.txt   # первый раз (через uv, не python -m pip)
chmod +x ./run_phase1_admin.sh
./run_phase1_admin.sh
```

По умолчанию слушает `0.0.0.0:8080`. Переменные:

- `PHASE1_ADMIN_HOST` — bind host (default `0.0.0.0`)
- `PHASE1_ADMIN_PORT` — порт (default `8080`)

### Доступ с локальной машины (SSH tunnel)

```bash
ssh -L 8080:127.0.0.1:8080 administrator@<SERVER_IP>
```

Откройте в браузере: http://127.0.0.1:8080

### Запуск через supervisor (рекомендуется)

Три долгоживущих сервиса управляются **supervisor** (user-level, без root): админка, Inspect View и LM Studio guard.

**Важно:** screen-сессий для admin/inspect больше не будет — это нормально. Прогоны benchmark по-прежнему создают временные screen `phase1_<timestamp>`.

```bash
cd ~/llm_redteam/phase1_inspect
uv pip install -r requirements.txt          # включает supervisor
chmod +x ./scripts/*.sh

# поднять / починить сервисы (без убийства screen)
./scripts/supervisor_ensure.sh
./scripts/services_health.sh
```

Команды управления:

```bash
./scripts/supervisor_ctl.sh status
./scripts/supervisor_ctl.sh restart phase1_admin
./scripts/supervisor_ctl.sh restart inspect_view
./scripts/supervisor_ctl.sh restart lms_guard
./scripts/supervisor_ctl.sh tail phase1_admin
./scripts/services_health.sh                # быстрая проверка всех портов
```

После `git pull` перезапустите админку:

```bash
./scripts/supervisor_ctl.sh restart phase1_admin
```

**Автозапуск и self-heal** (cron, без root):

```bash
crontab -l
# @reboot  — supervisor_ensure.sh
# */5 * * * * — health-check + restart упавших сервисов
```

Конфиг supervisor: [`deploy/supervisor/phase1_services.conf`](deploy/supervisor/phase1_services.conf).

Миграция со старых screen admin/inspect (только если нужно убрать дубликаты портов):

```bash
./scripts/supervisor_migrate.sh --replace-screens
```

### Ручной запуск (для отладки)

```bash
./run_phase1_admin.sh
```

### Устаревший способ: screen

```bash
screen -dmS phase1_admin bash -lc 'cd ~/llm_redteam/phase1_inspect && ./run_phase1_admin.sh'
screen -r phase1_admin
```

Не используйте screen и supervisor одновременно — будет конфликт портов.

### UI-тесты

```bash
cd phase1_inspect
source .venv/bin/activate
pytest admin/tests/test_new_run_template.py -v          # без браузера
pytest admin/tests/test_new_run_ui.py -v --browser chromium  # Playwright (нужны deps)
playwright install chromium
sudo playwright install-deps chromium   # один раз на сервере
```

## Что умеет UI

### Новый прогон (`/`)

- Все бенчмарки или выбранный набор (10 бенчмарков)
- Limit с пресетами (1 / 10 / 50 / 800)
- Отложенный старт по MSK (`-a` для orchestrator)
- Overrides: `TARGET_MODEL`, `GRADER_MODEL`, `PHASE1_MAX_CONNECTIONS` (без правки `.env`)
- Имя screen-сессии

Прогон стартует через `run_phase1_in_screen.sh` → `run_phase1_all_proxy.sh`.

### Прогоны (`/runs`)

История из `logs/phase1_runs.sqlite`: статус, limit, число успешных бенчмарков.

### Детали прогона (`/runs/{id}`)

- **Live-панель** (HTMX каждые 3 с): статус, progress bar, таблица бенчмарков — без F5; polling останавливается при завершении
- **Samples (live)**: компактная таблица промпт / ответ / оценка из текущего `.eval`
- **Inspect Live**: ссылка на dashboard + iframe (если viewer online)
- Live tail screen-лога (HTMX polling)
- Кнопка сборки `reports/phase1_metrics/run_<id>/report.html`

Список прогонов (`/runs`) тоже авто-обновляется, пока есть `running` строки.

### Датасеты (`/datasets`)

- Каталог встроенных датасетов Phase 1 и пользовательских загрузок
- **Предпросмотр** первых 50 строк для каждого датасета на диске (`/datasets/{id}`)
- **Загрузка файла** CSV / JSONL / XLSX (до 50 MB):
  1. выберите файл → «Проверить файл» (маппинг колонок + sample rows);
  2. укажите `input` (обязательно), `target` (опционально), metadata-колонки;
  3. сохраните — датасет появится в каталоге и в форме «Новый прогон» как `custom_<slug>`.
- **Импорт с Hugging Face** (до 8 GB):
  1. укажите ссылку (`org/name` или URL), опционально config и split → «Проверить датасет»;
  2. preview через streaming (без полной загрузки), маппинг колонок как у файлов;
  3. до ~500 MB — синхронное сохранение; больше — **фоновый job в screen** (`/datasets/import-jobs/{id}`);
  4. пример: `piimb/privy` (4+ GB) — колонка input: `full_text` или `masked`.
- Для gated-датасетов: `HF_TOKEN` в окружении или `huggingface-cli login`.
- Scoring для custom: если задана колонка `target`, она используется в `model_graded_qa`; иначе дефолт AdvBench-style refuse.
- **Удаление** — только пользовательские датасеты (кнопка в каталоге и на странице предпросмотра); встроенные 10 наборов удалить нельзя.
- Файлы хранятся в `datasets/custom/<slug>/` (`data.csv` + `meta.json`), реестр — `datasets/custom/registry.json`.

## Inspect view

Inspect View входит в supervisor-группу `phase1_services` (см. выше).

Ручной запуск (отладка):

```bash
cd ~/llm_redteam/phase1_inspect
chmod +x ./run_inspect_view.sh
./run_inspect_view.sh
```

SSH-туннель для админки, Inspect и LM Studio:

```bash
ssh -L 8080:127.0.0.1:8080 -L 7575:127.0.0.1:7575 -L 1234:127.0.0.1:1234 administrator@<SERVER_IP>
# админка: http://127.0.0.1:8080
# inspect:  http://127.0.0.1:7575
# lms api:  http://127.0.0.1:1234/v1
```

Переменные: `PHASE1_INSPECT_VIEW_PORT`, `PHASE1_INSPECT_VIEW_URL` (default `http://127.0.0.1:7575`).

## LM Studio guard (qwen3guard-gen-8b)

Локальный inference для guard/grader через LM Studio CLI. Watchdog `lms_guard` в supervisor:

1. держит API-сервер на `:1234` (`lms server start`);
2. каждые 30 с проверяет, что модель `qwen3guard-gen-8b` загружена, и перезагружает при необходимости.

Переменные (опционально, в `../.env` или окружении):

| Переменная | Default | Описание |
|---|---|---|
| `LMS_PORT` | `1234` | порт LM Studio API |
| `LMS_BIND` | `0.0.0.0` | bind address |
| `LMS_GUARD_MODEL` | `qwen3guard-gen-8b` | ключ модели (`lms ls`) |
| `LMS_CHECK_INTERVAL` | `30` | интервал health-check (сек) |
| `LMS_LOAD_PARALLEL` | `4` | `--parallel` при load |
| `LMS_CONTEXT_LENGTH` | `4096` | context length |

Проверка:

```bash
lms ps
curl http://127.0.0.1:1234/v1/models
./scripts/services_health.sh
```

Пример использования как grader в Phase 1 (в `../.env`, если нужен локальный judge вместо OpenRouter):

```dotenv
GRADER_MODEL=openai/qwen3guard-gen-8b
OPENAI_API_KEY=lm-studio
OPENAI_BASE_URL=http://127.0.0.1:1234/v1
```

Inspect AI подхватит grader через OpenAI-compatible endpoint LM Studio.

## CLI (без UI)

```bash
# выбранные бенчмарки
./run_phase1_all_proxy.sh 50 --benchmarks advbench,xstest,fin_oil

# список прогонов
python scripts/phase1_log.py list-runs --db logs/phase1_runs.sqlite

# детали прогона
python scripts/phase1_log.py get-run --db logs/phase1_runs.sqlite --run-id 11
```

## Архитектура

```
Browser → FastAPI (admin/app.py)
       → runner.launch() → screen → run_phase1_all_proxy.sh
       → phase1_log.py → logs/phase1_runs.sqlite
```

Метаданные UI-запусков: `logs/admin_launches/<screen_session>.json`.

## Не входит в MVP

- Auth / RBAC
- Отмена running job из UI
- Phase 2 (DeepTeam)
- Редактирование `.env` через браузер
