# Phase 2 — Динамическое тестирование с DeepTeam

## Статическое vs. динамическое тестирование

В Phase 1 мы использовали заранее собранные датасеты. Проблема:
- Атаки известны заранее — модели могут быть под них дообучены
- Новые техники джейлбрейка не покрыты

**Динамическое тестирование** генерирует атаки в реальном времени, адаптируясь к
конкретной модели. Это ближе к реальному пентесту.

## Фреймворк: DeepTeam

[DeepTeam](https://github.com/confident-ai/deepteam) — LLM red teaming от Confident AI.

Ключевая концепция: `model_callback` — функция `str → str`, которая принимает атакующий
промпт и возвращает ответ тестируемой модели. DeepTeam генерирует промпты и оценивает ответы.

## Архитектура: три роли LLM

В каждом тест-прогоне участвуют **три** языковые модели — не одна:

```
┌─────────────┐   attack prompt   ┌────────────┐   response   ┌───────────┐
│  ATTACKER   │ ────────────────▶ │   TARGET   │ ───────────▶ │   JUDGE   │
│ (simulator) │                   │  (ваша LLM)│              │(evaluator)│
└─────────────┘                   └────────────┘              └───────────┘
  Генерирует хитрые                 Тестируемая                score 0 / 1
  атакующие промпты                  модель                  Атака прошла?
```

| Роль | Параметр `red_team()` | CLI-флаг | По умолчанию |
|------|-----------------------|----------|--------------|
| **Target** — тестируемая модель | `model_callback` | `--target-model` | `OPENROUTER_MODEL` или `TARGET_MODEL` из .env |
| **Attacker** — генерирует атаки | `simulator_model` | `--attacker-model` | `ATTACKER_MODEL`, затем `OPENROUTER_MODEL` |
| **Judge** — оценивает ответы | `evaluation_model` | `--judge-model` | `JUDGE_MODEL`, затем `GRADER_MODEL` |

**О стоимости:** каждый тест-кейс = минимум 3 LLM-вызова (один в каждую роль).
При 7 уязвимостях × 5 атак = 35 тест-кейсов → ~105+ вызовов суммарно.
Для первичной проверки используй `--attacks-per-type 1`.

## OWASP LLM Top-10 (2025)

DeepTeam покрывает из коробки:
- **LLM01** Prompt Injection — вставка инструкций через ввод пользователя
- **LLM02** Sensitive Information Disclosure — утечка конфиденциальных данных
- **LLM05** Improper Output Handling — небезопасная обработка вывода модели
- **LLM06** Excessive Agency — модель выполняет действия за пределами допустимого
- **LLM07** System Prompt Leakage — утечка системного промпта
- **LLM09** Misinformation — генерация дезинформации
- **LLM10** Unbounded Consumption — неограниченное потребление ресурсов

*Не покрыты (требуют инфраструктурный доступ):* LLM03 (Supply Chain), LLM04 (Data and Model Poisoning), LLM08 (Vector and Embedding Weaknesses)

## Установка и запуск на Ubuntu

```bash
cd ~/llm_redteam/phase2_deepteam
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
chmod +x ./run_owasp_top10_proxy.sh
chmod +x ./run_owasp_top10_smoke_proxy.sh
```

**Быстрая проверка** — убедиться что всё работает, не сжигая токены:
```bash
./run_owasp_top10_smoke_proxy.sh
```

Smoke-runner запускает один минимальный test case: `--smoke-one --attacks-per-type 1 --max-concurrent 1`.
Ожидаемый результат: таблица/лог DeepTeam в консоли и JSON-отчёт в `phase2_deepteam/reports/`.

**Боевой запуск через runner**:
```bash
./run_owasp_top10_proxy.sh 1 1
./run_owasp_top10_proxy.sh 5 2 "customer support chatbot"
```

Аргументы runner:

- `1` / `5` — атак на каждый DeepTeam vulnerability type
- `1` / `2` — максимум параллельных запросов
- третий аргумент — необязательный `purpose`
- четвёртый аргумент или `OWASP_CATEGORIES` — необязательный список категорий, например `LLM_01,LLM_02`

Пример запуска только двух OWASP-категорий:

```bash
./run_owasp_top10_proxy.sh 1 1 "" "LLM_01,LLM_02"
```

**Справка по параметрам:**
```bash
./.venv/bin/python ./labs/lab1_owasp_top10/run.py --help
```

## Совместимость с Phase 1 proxy

Runner читает `../.env` и может переиспользовать переменные из Phase 1:

```dotenv
OPENROUTER_API_KEY=...
TARGET_MODEL=openai-api/myproxy/AlphaGaO/Qwen3-14B-GPTQ
GRADER_MODEL=openrouter/inclusionai/ling-2.6-flash:free
MYPROXY_BASE_URL=http://10.70.54.230:8008/v1
MYPROXY_API_KEY=dummy
```

Если задан `OPENROUTER_MODEL`, Target пойдёт через OpenRouter. Если `OPENROUTER_MODEL`
не задан, но есть `TARGET_MODEL` и `MYPROXY_BASE_URL`, Target будет вызван через proxy,
а Attacker/Judge останутся на OpenRouter. Для явного управления используй
`TARGET_BASE_URL`, `TARGET_API_KEY`, `ATTACKER_BASE_URL`, `JUDGE_BASE_URL`.
