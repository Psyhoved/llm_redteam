"""
Lab 1 (Phase 2): OWASP LLM Top-10 Dynamic Red Teaming
Uses DeepTeam to dynamically generate attacks for all supported OWASP LLM 2025 threats.

Unlike Phase 1 (static datasets), DeepTeam generates attack prompts at runtime,
adapting them to the specific model being tested.

Run:
    python run.py
"""
import os
import json
from datetime import datetime
from openai import OpenAI  # used as OpenRouter client — no OpenAI key needed
from dotenv import load_dotenv
from deepteam import red_team
from deepteam.frameworks import OWASPTop10

load_dotenv("../../../.env")

# OpenAI SDK pointed at OpenRouter — set OPENROUTER_API_KEY, not OPENAI_API_KEY
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
ATTACKS_PER_TYPE = int(os.getenv("ATTACKS_PER_TYPE", "5"))


def model_callback(input: str) -> str:
    """Send an attack prompt to the model and return its response."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": input}],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print(f"Testing model: {MODEL}")
    print(f"Attacks per vulnerability type: {ATTACKS_PER_TYPE}")
    print("Running OWASP Top-10 assessment...\n")

    risk_assessment = red_team(
        model_callback=model_callback,
        framework=OWASPTop10(),
        attacks_per_vulnerability_type=ATTACKS_PER_TYPE,
    )

    print(f"\nTotal test cases: {len(risk_assessment.test_cases)}")
    print(f"Pass rate: {risk_assessment.pass_rate:.1%}")

    # Save JSON report for student analysis
    report_dir = os.path.join(os.path.dirname(__file__), "../../reports")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"owasp_{MODEL.replace('/', '_')}_{timestamp}.json")

    report_data = {
        "model": MODEL,
        "pass_rate": risk_assessment.pass_rate,
        "total_test_cases": len(risk_assessment.test_cases),
        "test_cases": [
            {
                "vulnerability": str(tc.vulnerability) if hasattr(tc, "vulnerability") else "",
                "input": tc.input if hasattr(tc, "input") else "",
                "actual_output": tc.actual_output if hasattr(tc, "actual_output") else "",
                "score": str(tc.score) if hasattr(tc, "score") else "",
            }
            for tc in risk_assessment.test_cases
        ],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print(f"\nJSON report saved to: {report_path}")
