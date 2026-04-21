# LLM Pentest Course

Учебный репозиторий для изучения методов LLM red teaming и пентеста.

## Структура

| Фаза | Фреймворк | Что изучаем |
|------|-----------|-------------|
| [Phase 1](phase1_inspect/) | Inspect AI | Статические бенчмарки — 6 датасетов, разные режимы отказа |
| [Phase 2](phase2_deepteam/) | DeepTeam | Динамическое тестирование по OWASP LLM Top-10 |

## Требования

- Python 3.10+
- Аккаунт на [OpenRouter](https://openrouter.ai/) с API ключом

Важно: `uv pip install` не создает виртуальное окружение автоматически.
На свежей машине сначала выполни `uv venv` в той директории, где хочешь держать `.venv`.
Если дальше используешь обычную команду `python`, активируй окружение сразу после `uv venv`.

## Quickstart

```powershell
Copy-Item .env.example .env
# Заполни OPENROUTER_API_KEY в .env

# Phase 1
cd .\phase1_inspect
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r .\requirements.txt
python .\datasets\download_datasets.py advbench
cd .\labs\lab1_advbench
python -m inspect_ai eval run.py --model openrouter/openai/gpt-4o-mini --limit 10

# Phase 2
cd ..\..\phase2_deepteam
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r .\requirements.txt
cd .\labs\lab1_owasp_top10
python run.py
```
