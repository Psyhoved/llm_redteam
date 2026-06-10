# Phase 1 Admin UI

Веб-админка для запуска и мониторинга Phase 1 benchmark runs (Inspect AI).

## Требования

- Python venv в `phase1_inspect/.venv` с зависимостями из `requirements.txt`
- Заполненный `../.env` (модели, proxy, API keys)
- Установленный `screen` (для фоновых прогонов)
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

### Запуск в screen (чтобы админка не умирала)

```bash
screen -dmS phase1_admin bash -lc 'cd ~/llm_redteam/phase1_inspect && ./run_phase1_admin.sh'
screen -r phase1_admin
```

## Что умеет UI

### Новый прогон (`/`)

- Все лабы или выбранный набор (10 лаб)
- Limit с пресетами (1 / 10 / 50 / 800)
- Отложенный старт по MSK (`-a` для orchestrator)
- Overrides: `TARGET_MODEL`, `GRADER_MODEL`, `PHASE1_MAX_CONNECTIONS` (без правки `.env`)
- Имя screen-сессии

Прогон стартует через `run_phase1_in_screen.sh` → `run_phase1_all_proxy.sh`.

### Прогоны (`/runs`)

История из `logs/phase1_runs.sqlite`: статус, limit, число успешных лаб.

### Детали прогона (`/runs/{id}`)

- Статус каждой лабы и путь к `.eval`
- Live tail screen-лога (HTMX polling)
- Кнопка сборки `reports/phase1_metrics/run_<id>/report.html`
- Инструкция для Inspect view

## Inspect view (отдельно)

Админка не встраивает Inspect UI. Для просмотра `.eval` логов:

```bash
# на сервере
cd ~/llm_redteam/phase1_inspect
source .venv/bin/activate
screen -dmS inspect_view bash -lc '
  python -m inspect_ai view start \
    --host 0.0.0.0 --port 7575 \
    --log-dir . --recursive
'

# локально
ssh -L 7575:127.0.0.1:7575 administrator@<SERVER_IP>
# http://127.0.0.1:7575
```

## CLI (без UI)

```bash
# выбранные лабы
./run_phase1_all_proxy.sh 50 --labs advbench,xstest,fin_oil

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
