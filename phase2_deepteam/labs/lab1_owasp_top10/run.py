"""
Lab 1 (Phase 2): OWASP LLM Top-10 Dynamic Red Teaming

Как работает DeepTeam: три роли LLM
─────────────────────────────────────────────────────────
В одном тест-прогоне участвуют ТРИ разные языковые модели:

  1. TARGET  — тестируемая модель. Именно её мы атакуем и проверяем
               на уязвимости. Задаётся через --target-model.

  2. ATTACKER (Simulator) — модель, которая генерирует атакующие промпты.
               DeepTeam просит её придумать хитрые способы обмануть Target.
               Задаётся через --attacker-model.

  3. JUDGE (Evaluator) — модель, которая смотрит на ответ Target и решает:
               «атака прошла» (score=0) или «модель устояла» (score=1).
               Задаётся через --judge-model.

Поток данных:
  Attacker ──[attack prompt]──▶ Target ──[response]──▶ Judge ──[score 0/1]──▶ Отчёт

Важно о стоимости: каждый тест-кейс = минимум 3 LLM-вызова.
При 7 уязвимостях × 5 атак = 35 тест-кейсов → ~100+ вызовов суммарно.
Для быстрой проверки используй --attacks-per-type 1.

Запуск:
    python run.py                              # все параметры из .env
    python run.py --attacks-per-type 1         # быстрая проверка (~21 вызов)
    python run.py --help                       # справка по всем параметрам
"""
import argparse
import os
import json
from datetime import datetime
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv
from deepteam import red_team
from deepteam.frameworks import OWASPTop10
from deepeval.models import DeepEvalBaseLLM

load_dotenv("../../../.env")


# ─── Обёртка для OpenRouter ────────────────────────────────────────────────────
#
# DeepTeam по умолчанию ходит напрямую в OpenAI API.
# Чтобы направить Attacker и Judge через OpenRouter, нужно реализовать
# интерфейс DeepEvalBaseLLM — базовый класс DeepEval (от которого зависит
# DeepTeam) для подключения кастомных моделей.
#
class OpenRouterLLM(DeepEvalBaseLLM):
    """Кастомная LLM-обёртка для вызова любой модели через OpenRouter API.

    Используется для ролей Attacker (simulator_model) и Judge (evaluation_model).
    DeepTeam вызывает метод generate() / a_generate() автоматически.
    """

    def __init__(self, model: str, api_key: str):
        self.model = model
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    def get_model_name(self) -> str:
        # DeepTeam использует это имя в логах и отчётах
        return self.model

    def load_model(self):
        # Модель уже инициализирована в __init__, ничего загружать не нужно
        return self._client

    def generate(self, prompt: str) -> str:
        """Синхронный вызов модели — используется DeepTeam в обычном режиме."""
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        """Асинхронный вызов — используется DeepTeam при max_concurrent > 1.

        Здесь просто делегируем синхронному методу, т.к. openai-клиент
        поддерживает async через отдельный AsyncOpenAI. Для учебных целей
        достаточно синхронной реализации.
        """
        return self.generate(prompt)


# ─── CLI-аргументы ─────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OWASP LLM Top-10 dynamic red teaming via DeepTeam + OpenRouter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Быстрая проверка (не сжигает все токены)
  python run.py --attacks-per-type 1

  # Полный тест с явным указанием всех трёх ролей
  python run.py \\
      --target-model   openai/gpt-4o-mini \\
      --attacker-model openai/gpt-4o-mini \\
      --judge-model    openai/gpt-4o-mini \\
      --attacks-per-type 5 \\
      --purpose "customer support chatbot"
""",
    )
    parser.add_argument(
        "--target-model",
        default=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        metavar="MODEL",
        help=(
            "TARGET: тестируемая модель — та, которую атакуем.\n"
            "Получает атакующие промпты, её ответы оцениваются Judge.\n"
            "Default: %(default)s  (из OPENROUTER_MODEL в .env)"
        ),
    )
    parser.add_argument(
        "--attacker-model",
        default=os.getenv("ATTACKER_MODEL", "openai/gpt-4o-mini"),
        metavar="MODEL",
        help=(
            "ATTACKER: модель-атакующий (simulator).\n"
            "Генерирует атакующие промпты под каждую OWASP уязвимость.\n"
            "Default: %(default)s  (из ATTACKER_MODEL в .env)"
        ),
    )
    parser.add_argument(
        "--judge-model",
        default=os.getenv("JUDGE_MODEL", "openai/gpt-4o-mini"),
        metavar="MODEL",
        help=(
            "JUDGE: модель-оценщик (evaluator).\n"
            "Решает, прошла ли атака (score=0) или модель устояла (score=1).\n"
            "Default: %(default)s  (из JUDGE_MODEL в .env)"
        ),
    )
    parser.add_argument(
        "--attacks-per-type",
        type=int,
        default=int(os.getenv("ATTACKS_PER_TYPE", "5")),
        metavar="N",
        help=(
            "Число атак на каждую OWASP уязвимость.\n"
            "Итого тест-кейсов = N × 7 (уязвимостей).\n"
            "Default: %(default)s  (из ATTACKS_PER_TYPE в .env)"
        ),
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=10,
        metavar="N",
        help=(
            "Максимум параллельных LLM-запросов.\n"
            "Уменьши до 2-3 если получаешь rate-limit ошибки.\n"
            "Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--purpose",
        default=None,
        metavar="TEXT",
        help=(
            "Описание назначения тестируемой системы (необязательно).\n"
            "Attacker использует это описание, чтобы генерировать более\n"
            "прицельные атаки. Например: 'customer support chatbot' или\n"
            "'medical diagnosis assistant'.\n"
            "Default: не задано"
        ),
    )
    return parser


# ─── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = build_arg_parser().parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Ошибка: OPENROUTER_API_KEY не задан в .env")

    # Печатаем конфигурацию явно — студент должен видеть, что именно запускается
    total_cases = args.attacks_per_type * 7  # 7 OWASP уязвимостей поддерживается
    print("=== DeepTeam: OWASP LLM Top-10 Red Teaming ===")
    print(f"Target   (тестируемая модель): {args.target_model}")
    print(f"Attacker (генератор атак):     {args.attacker_model}")
    print(f"Judge    (оценщик ответов):    {args.judge_model}")
    print(f"Атак на уязвимость:            {args.attacks_per_type}  →  ~{total_cases} тест-кейсов")
    if args.purpose:
        print(f"Цель системы:                  {args.purpose}")
    print()

    # TARGET — тестируемая модель
    # Обычный OpenAI-клиент, указывающий на OpenRouter.
    # model_callback — это «дверь» в тестируемую систему: DeepTeam
    # отправляет сюда каждый атакующий промпт и ждёт ответ.
    target_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    def model_callback(input: str) -> str:
        """Отправляет атакующий промпт в Target и возвращает его ответ."""
        response = target_client.chat.completions.create(
            model=args.target_model,
            messages=[{"role": "user", "content": input}],
        )
        return response.choices[0].message.content

    # ATTACKER — генерирует атакующие промпты через OpenRouter
    attacker_llm = OpenRouterLLM(model=args.attacker_model, api_key=api_key)

    # JUDGE — оценивает ответы Target через OpenRouter
    judge_llm = OpenRouterLLM(model=args.judge_model, api_key=api_key)

    # Запуск красного тестирования
    # OWASPTop10() разворачивается в 7 уязвимостей: LLM01, LLM02, LLM05,
    # LLM06, LLM07, LLM09, LLM10. Для каждой Attacker генерирует
    # attacks_per_vulnerability_type промптов.
    risk_assessment = red_team(
        model_callback=model_callback,
        framework=OWASPTop10(),
        simulator_model=attacker_llm,
        evaluation_model=judge_llm,
        attacks_per_vulnerability_type=args.attacks_per_type,
        purpose=args.purpose,
        max_concurrent=args.max_concurrent,
    )

    # ─── Результаты ──────────────────────────────────────────────────────────
    print(f"\n=== Результаты ===")
    print(f"Всего тест-кейсов: {len(risk_assessment.test_cases)}")
    print(f"Pass rate (выдержал атаки): {risk_assessment.pass_rate:.1%}")

    # Разбивка по OWASP категориям, если доступна
    if hasattr(risk_assessment, "overview") and risk_assessment.overview:
        overview = risk_assessment.overview
        if hasattr(overview, "vulnerability_type_results"):
            print("\nПо уязвимостям:")
            for vr in overview.vulnerability_type_results:
                name = getattr(vr, "vulnerability_name", getattr(vr, "vulnerability_type", "?"))
                rate = getattr(vr, "pass_rate", "?")
                rate_str = f"{rate:.1%}" if isinstance(rate, float) else str(rate)
                print(f"  {name:<40} pass rate: {rate_str}")

    # ─── Сохранение JSON-отчёта ──────────────────────────────────────────────
    report_dir = os.path.join(os.path.dirname(__file__), "../../reports")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = args.target_model.replace("/", "_")
    report_path = os.path.join(report_dir, f"owasp_{safe_model}_{timestamp}.json")

    report_data = {
        "target_model": args.target_model,
        "attacker_model": args.attacker_model,
        "judge_model": args.judge_model,
        "attacks_per_type": args.attacks_per_type,
        "purpose": args.purpose,
        "pass_rate": risk_assessment.pass_rate,
        "total_test_cases": len(risk_assessment.test_cases),
        "test_cases": [
            {
                "vulnerability": str(tc.vulnerability) if hasattr(tc, "vulnerability") else "",
                "vulnerability_type": tc.vulnerability_type if hasattr(tc, "vulnerability_type") else "",
                "attack_method": tc.attack_method if hasattr(tc, "attack_method") else "",
                "input": tc.input if hasattr(tc, "input") else "",
                "actual_output": tc.actual_output if hasattr(tc, "actual_output") else "",
                "score": str(tc.score) if hasattr(tc, "score") else "",
                "reason": tc.reason if hasattr(tc, "reason") else "",
            }
            for tc in risk_assessment.test_cases
        ],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print(f"\nJSON-отчёт сохранён: {report_path}")
