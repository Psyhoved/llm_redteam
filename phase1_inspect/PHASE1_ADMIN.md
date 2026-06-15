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

После `git pull` **перезапустите** админку — uvicorn не подхватывает код автоматически:

```bash
screen -S phase1_admin -X quit
screen -dmS phase1_admin bash -lc 'cd ~/llm_redteam/phase1_inspect && ./run_phase1_admin.sh'
```

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
- **Загрузка** CSV / JSONL / XLSX (до 50 MB):
  1. выберите файл → «Проверить файл» (маппинг колонок + sample rows);
  2. укажите `input` (обязательно), `target` (опционально), metadata-колонки;
  3. сохраните — датасет появится в каталоге и в форме «Новый прогон» как `custom_<slug>`.
- Scoring для custom: если задана колонка `target`, она используется в `model_graded_qa`; иначе дефолт AdvBench-style refuse.
- **Удаление** — только пользовательские датасеты (кнопка в каталоге и на странице предпросмотра); встроенные 10 наборов удалить нельзя.
- Файлы хранятся в `datasets/custom/<slug>/` (`data.csv` + `meta.json`), реестр — `datasets/custom/registry.json`.

## Inspect view

Запуск viewer (отдельный процесс):

```bash
cd ~/llm_redteam/phase1_inspect
chmod +x ./run_inspect_view.sh
screen -dmS inspect_view bash -lc './run_inspect_view.sh'
```

SSH-туннель для админки **и** Inspect:

```bash
ssh -L 8080:127.0.0.1:8080 -L 7575:127.0.0.1:7575 administrator@<SERVER_IP>
# админка: http://127.0.0.1:8080
# inspect:  http://127.0.0.1:7575
```

Переменные: `PHASE1_INSPECT_VIEW_PORT`, `PHASE1_INSPECT_VIEW_URL` (default `http://127.0.0.1:7575`).

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
