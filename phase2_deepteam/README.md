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

## OWASP LLM Top-10 (2025)

DeepTeam покрывает из коробки:
- **LLM01** Prompt Injection
- **LLM02** Sensitive Information Disclosure
- **LLM05** Improper Output Handling
- **LLM06** Excessive Agency
- **LLM07** System Prompt Leakage
- **LLM09** Misinformation
- **LLM10** Unbounded Consumption

*Не покрыты (требуют инфраструктурный доступ):* LLM03 (Supply Chain), LLM04 (Data and Model Poisoning), LLM08 (Vector and Embedding Weaknesses)

## Установка и запуск

```bash
pip install -r requirements.txt
cp ../.env.example ../.env  # если ещё не сделано
cd labs/lab1_owasp_top10
python run.py
```
