# Датасеты Phase 1

Скачай все датасеты одной командой из директории `phase1_inspect/`:

```bash
python datasets/download_datasets.py
```

## Описание датасетов

### AdvBench
- **Источник:** github.com/llm-attacks/llm-attacks
- **Размер:** 520 промптов
- **Что тестирует:** Реагирует ли модель на прямые запросы вредоносного контента
- **Ключевая колонка:** `goal` — инструкция, `target` — ожидаемое начало вредоносного ответа

### XSTest
- **Источник:** github.com/paul-rottger/xstest
- **Размер:** 451 промпт (250 безопасных + 200 небезопасных)
- **Что тестирует:** Избыточный отказ — модель НЕ должна отказывать на безопасных промптах
- **Ключевые колонки:** `prompt`, `label` (safe/unsafe), `type` (категория)

### ToxicChat
- **Источник:** huggingface.co/datasets/lmsys/toxic-chat
- **Размер:** ~10 000 примеров
- **Что тестирует:** Реальные токсичные и джейлбрейк-запросы от пользователей ChatGPT
- **Ключевые колонки:** `user_input`, `toxicity` (0/1), `jailbreaking` (0/1)

### WildJailbreak
- **Источник:** huggingface.co/datasets/allenai/wildjailbreak
- **Размер:** 262K примеров (используем выборку по 100)
- **Что тестирует:** Эффективность адверсариальных техник джейлбрейка vs. vanilla запросов
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
