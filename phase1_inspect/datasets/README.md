# Датасеты Phase 1

Команды ниже запускаются из директории `phase1_inspect/`.

Скачать только один датасет:

```powershell
python .\datasets\download_datasets.py advbench
```

Скачать несколько конкретных датасетов:

```powershell
python .\datasets\download_datasets.py advbench xstest toxicchat
```

Попробовать скачать всё сразу:

```powershell
python .\datasets\download_datasets.py
```

Если Hugging Face dataset gated, как `wildjailbreak`, скрипт выведет предупреждение
и продолжит скачивание остальных наборов. Чтобы скачать `wildjailbreak`, понадобится
аутентификация в HF Hub (`HF_TOKEN` или `huggingface-cli login`).

`wildjailbreak` скачивается как subset `eval` и сохраняется в `datasets/wildjailbreak/`.
Если у тебя там уже лежит старый локальный вариант датасета, удали эту папку перед
повторным скачиванием, иначе downloader пропустит её как уже существующую.

## Описание датасетов

### AdvBench
- **Источник:** github.com/llm-attacks/llm-attacks
- **Размер:** 520 промптов
- **Что тестирует:** Реагирует ли модель на прямые запросы вредоносного контента
- **Ключевая колонка:** `goal` — инструкция, `target` — ожидаемое начало вредоносного ответа

### XSTest
- **Источник:** github.com/paul-rottger/xstest
- **Размер:** ~500 промптов (безопасные и небезопасные примеры)
- **Что тестирует:** Избыточный отказ — модель НЕ должна отказывать на безопасных промптах
- **Ключевые колонки:** `prompt`, `label` (safe/unsafe), `type` (категория)

### ToxicChat
- **Источник:** huggingface.co/datasets/lmsys/toxic-chat
- **Размер:** ~10 000 примеров
- **Что тестирует:** Реальные токсичные и джейлбрейк-запросы от пользователей ChatGPT
- **Ключевые колонки:** `user_input`, `toxicity` (0/1), `jailbreaking` (0/1)

### WildJailbreak
- **Источник:** huggingface.co/datasets/allenai/wildjailbreak
- **Локально скачиваем:** subset `eval` (gated dataset)
- **Размер eval:** ~2.2K примеров
- **Что тестирует:** Пропускает ли модель harmful jailbreak-запросы и не переотказывает ли benign jailbreak-запросам
- **Ключевые колонки:** `vanilla`, `adversarial`, `data_type`

### Do-Not-Answer
- **Источник:** huggingface.co/datasets/LibrAI/do-not-answer
- **Размер:** 939 вопросов
- **Что тестирует:** Таксономия вреда: 5 зон риска × 12 типов вреда
- **Ключевые колонки:** `question`, `risk_area`, `types_of_harm`

### Aya Redteaming
- **Источник:** huggingface.co/datasets/CohereLabs/aya_redteaming
- **Размер:** ~7 400 примеров на 8 языках
- **Что тестирует:** Работают ли защиты модели на языках кроме английского
- **Ключевые колонки:** `prompt`, `language`, `harm_category`

### PII-Bench
- **Источник:** huggingface.co/datasets/hivetrace/pii-bench
- **Размер:** 1810 примеров (`domain` + `entity`; отдельного split `test` нет)
- **Что тестирует:** Отказывается ли модель раскрывать/воспроизводить ПДн в текстах с разметкой PII
- **Ключевые колонки:** `text`, `entities` (span-level PII), `domain`
- **Разметка для Phase 1:** `entities` непустой → harmful/refuse; пустой → benign/answer

### Fin-Oil (FP / over-refusal)
- **Источник:** локальный `datasets/fin_oil_dataset.xlsx`; стабильная копия `datasets/fin_oil/fin_oil_prompts.csv`
- **Размер:** 132 легитимных промпта (после очистки пустых строк)
- **Что тестирует:** Доля отказов на доменных бенигных запросах (прокси-метрика ложных срабатываний при оценке по ответу модели через `model_graded_qa`, см. Lab 8)
- **Ключевые колонки:** `prompt`, `category` (категория после forward-fill из колонки `Категория`)
- **Обновление CSV из xlsx:**
  ```bash
  python datasets/prepare_fin_oil.py
  ```
