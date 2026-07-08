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
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
from deepteam import red_team
from deepteam.frameworks import OWASPTop10
from deepeval.models import DeepEvalBaseLLM
from deepteam.vulnerabilities import PromptLeakage

LAB_DIR = Path(__file__).resolve().parent
PHASE2_DIR = LAB_DIR.parent.parent
REPO_ROOT = PHASE2_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def env_first(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable value."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"Ошибка: {name} должен быть целым числом, получено: {value}") from exc


def normalize_model_id(model: str) -> str:
    """Accept common Inspect AI provider aliases from Phase 1 launchers."""
    prefixes = ("openrouter/", "openai-api/myproxy/")
    for prefix in prefixes:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def safe_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def calculate_pass_rate(test_cases) -> float:
    scores = [
        tc.score
        for tc in test_cases
        if hasattr(tc, "score") and tc.score is not None
    ]
    if not scores:
        return 0.0
    passing = sum(1 for score in scores if score > 0)
    return passing / len(scores)


# ─── Обёртка для OpenRouter ────────────────────────────────────────────────────
#
# DeepTeam по умолчанию ходит напрямую в OpenAI API.
# Чтобы направить Attacker и Judge через OpenRouter, нужно реализовать
# интерфейс DeepEvalBaseLLM — базовый класс DeepEval (от которого зависит
# DeepTeam) для подключения кастомных моделей.
#
class OpenRouterLLM(DeepEvalBaseLLM):
    """Кастомная LLM-обёртка для вызова OpenAI-compatible API.

    Используется для ролей Attacker (simulator_model) и Judge (evaluation_model).
    DeepTeam вызывает метод generate() / a_generate() автоматически.
    """

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = normalize_model_id(model)
        self._client = OpenAI(
            base_url=base_url,
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
        default=env_first("OPENROUTER_MODEL", "TARGET_MODEL", default="openai/gpt-4o-mini"),
        metavar="MODEL",
        help=(
            "TARGET: тестируемая модель — та, которую атакуем.\n"
            "Получает атакующие промпты, её ответы оцениваются Judge.\n"
            "Default: %(default)s  (из OPENROUTER_MODEL или TARGET_MODEL в .env)"
        ),
    )
    parser.add_argument(
        "--attacker-model",
        default=env_first("ATTACKER_MODEL", "OPENROUTER_MODEL", "JUDGE_MODEL", "GRADER_MODEL", default="openai/gpt-4o-mini"),
        metavar="MODEL",
        help=(
            "ATTACKER: модель-атакующий (simulator).\n"
            "Генерирует атакующие промпты под каждую OWASP уязвимость.\n"
            "Default: %(default)s  (из ATTACKER_MODEL, OPENROUTER_MODEL, JUDGE_MODEL или GRADER_MODEL в .env)"
        ),
    )
    parser.add_argument(
        "--judge-model",
        default=env_first("JUDGE_MODEL", "GRADER_MODEL", "OPENROUTER_MODEL", default="openai/gpt-4o-mini"),
        metavar="MODEL",
        help=(
            "JUDGE: модель-оценщик (evaluator).\n"
            "Решает, прошла ли атака (score=0) или модель устояла (score=1).\n"
            "Default: %(default)s  (из JUDGE_MODEL, GRADER_MODEL или OPENROUTER_MODEL в .env)"
        ),
    )
    parser.add_argument(
        "--target-base-url",
        default=env_first("TARGET_BASE_URL", "OPENROUTER_BASE_URL"),
        metavar="URL",
        help="OpenAI-compatible endpoint для Target. Default: %(default)s",
    )
    parser.add_argument(
        "--attacker-base-url",
        default=env_first("ATTACKER_BASE_URL", "OPENROUTER_BASE_URL"),
        metavar="URL",
        help="OpenAI-compatible endpoint для Attacker. Default: %(default)s",
    )
    parser.add_argument(
        "--judge-base-url",
        default=env_first("JUDGE_BASE_URL", "OPENROUTER_BASE_URL"),
        metavar="URL",
        help="OpenAI-compatible endpoint для Judge. Default: %(default)s",
    )
    parser.add_argument(
        "--attacks-per-type",
        type=int,
        default=int_env("ATTACKS_PER_TYPE", 5),
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
        default=int_env("MAX_CONCURRENT", 10),
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
    parser.add_argument(
        "--owasp-category",
        action="append",
        choices=[f"LLM_{index:02d}" for index in range(1, 11)],
        help=(
            "Ограничить OWASP framework одной или несколькими категориями. "
            "Можно передать несколько раз. По умолчанию используются все категории."
        ),
    )
    parser.add_argument(
        "--smoke-one",
        action="store_true",
        help=(
            "Запустить один минимальный baseline test-case: PromptLeakage/instructions. "
            "Удобно для проверки plumbing без полного OWASP и attack enhancement."
        ),
    )
    return parser


def validate_base_urls(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, value in (
            ("TARGET_BASE_URL or OPENROUTER_BASE_URL", args.target_base_url),
            ("ATTACKER_BASE_URL or OPENROUTER_BASE_URL", args.attacker_base_url),
            ("JUDGE_BASE_URL or OPENROUTER_BASE_URL", args.judge_base_url),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Ошибка: задайте OPENROUTER_BASE_URL или role-specific endpoints: "
            + ", ".join(missing)
        )


# ─── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    validate_base_urls(args)

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    target_api_key = env_first("TARGET_API_KEY", "OPENROUTER_API_KEY")
    if not openrouter_api_key:
        raise SystemExit("Ошибка: OPENROUTER_API_KEY не задан в .env")
    if not target_api_key:
        raise SystemExit("Ошибка: TARGET_API_KEY или OPENROUTER_API_KEY не задан в .env")

    target_model = normalize_model_id(args.target_model)
    attacker_model = normalize_model_id(args.attacker_model)
    judge_model = normalize_model_id(args.judge_model)

    if args.smoke_one:
        scope_kwargs = {
            "vulnerabilities": [PromptLeakage(types=["instructions"])],
        }
        scope_description = "single smoke case (baseline PromptLeakage/instructions)"
        expected_cases = args.attacks_per_type
    else:
        categories = args.owasp_category or None
        framework = OWASPTop10(categories=categories) if categories else OWASPTop10()
        scope_kwargs = {"framework": framework}
        scope_description = (
            f"OWASP categories: {', '.join(categories)}"
            if categories
            else "full OWASP Top 10 framework"
        )
        expected_cases = (
            sum(len(vulnerability.get_types()) for vulnerability in framework.vulnerabilities)
            * args.attacks_per_type
        )

    # Печатаем конфигурацию явно
    print("=== DeepTeam: OWASP LLM Top-10 Red Teaming ===")
    print(f"Target   (тестируемая модель): {target_model}")
    print(f"Attacker (генератор атак):     {attacker_model}")
    print(f"Judge    (оценщик ответов):    {judge_model}")
    print(f"Target endpoint:               {args.target_base_url}")
    print(f"Attacker/Judge endpoint:       {args.attacker_base_url} / {args.judge_base_url}")
    print(f"Scope:                          {scope_description}")
    print(f"Атак на vulnerability type:     {args.attacks_per_type}")
    print(f"Ожидаемых test cases:           {expected_cases}")
    if args.purpose:
        print(f"Цель системы:                  {args.purpose}")
    print()

    # TARGET — тестируемая модель
    # Обычный OpenAI-compatible клиент, указывающий на OpenRouter или proxy.
    # model_callback — это «дверь» в тестируемую систему: DeepTeam
    # отправляет сюда каждый атакующий промпт и ждёт ответ.
    target_client = OpenAI(
        base_url=args.target_base_url,
        api_key=target_api_key,
    )

    def model_callback(input: str) -> str:
        """Отправляет атакующий промпт в Target и возвращает его ответ."""
        response = target_client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": input}],
        )
        return response.choices[0].message.content

    # ATTACKER — генерирует атакующие промпты через OpenAI-compatible endpoint
    attacker_llm = OpenRouterLLM(
        model=attacker_model,
        api_key=openrouter_api_key,
        base_url=args.attacker_base_url,
    )

    # JUDGE — оценивает ответы Target через OpenAI-compatible endpoint
    judge_llm = OpenRouterLLM(
        model=judge_model,
        api_key=openrouter_api_key,
        base_url=args.judge_base_url,
    )

    # Запуск красного тестирования. Для полного OWASP это разворачивается в набор
    # внутренних vulnerability types, поэтому фактических тест-кейсов может быть
    # больше, чем число верхнеуровневых OWASP категорий.
    risk_assessment = red_team(
        model_callback=model_callback,
        simulator_model=attacker_llm,
        evaluation_model=judge_llm,
        attacks_per_vulnerability_type=args.attacks_per_type,
        target_purpose=args.purpose,
        async_mode=False,
        max_concurrent=args.max_concurrent,
        **scope_kwargs,
    )

    # ─── Результаты ──────────────────────────────────────────────────────────
    pass_rate = calculate_pass_rate(risk_assessment.test_cases)
    print(f"\n=== Результаты ===")
    print(f"Всего тест-кейсов: {len(risk_assessment.test_cases)}")
    print(f"Pass rate (выдержал атаки): {pass_rate:.1%}")

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
    safe_model = target_model.replace("/", "_")
    report_path = os.path.join(report_dir, f"owasp_{safe_model}_{timestamp}.json")

    report_data = {
        "target_model": target_model,
        "attacker_model": attacker_model,
        "judge_model": judge_model,
        "target_base_url": args.target_base_url,
        "attacker_base_url": args.attacker_base_url,
        "judge_base_url": args.judge_base_url,
        "attacks_per_type": args.attacks_per_type,
        "purpose": args.purpose,
        "smoke_one": args.smoke_one,
        "owasp_categories": args.owasp_category or [],
        "pass_rate": pass_rate,
        "total_test_cases": len(risk_assessment.test_cases),
        "test_cases": [
            {
                "vulnerability": safe_value(tc.vulnerability) if hasattr(tc, "vulnerability") else "",
                "vulnerability_type": safe_value(tc.vulnerability_type) if hasattr(tc, "vulnerability_type") else "",
                "attack_method": safe_value(tc.attack_method) if hasattr(tc, "attack_method") else "",
                "input": safe_value(tc.input) if hasattr(tc, "input") else "",
                "actual_output": safe_value(tc.actual_output) if hasattr(tc, "actual_output") else "",
                "score": safe_value(tc.score) if hasattr(tc, "score") else "",
                "reason": safe_value(tc.reason) if hasattr(tc, "reason") else "",
                "error": safe_value(tc.error) if hasattr(tc, "error") else "",
            }
            for tc in risk_assessment.test_cases
        ],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print(f"\nJSON-отчёт сохранён: {report_path}")
