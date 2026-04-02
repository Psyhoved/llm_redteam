# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Educational repository for learning LLM red teaming and penetration testing. Students evaluate static datasets with Inspect AI (Phase 1) and do dynamic red teaming with DeepTeam against OWASP LLM Top-10 threats (Phase 2).

Target audience: intermediate students (familiar with ML, new to LLM security in practice).

## Repository Structure

Two independent phases, each with its own `requirements.txt`:

- `phase1_inspect/` — static dataset evaluation via Inspect AI against 6 known harmful prompt benchmarks
- `phase2_deepteam/` — dynamic testing via DeepTeam covering OWASP LLM Top-10 threats supported out of the box

Each lab follows a uniform layout:
```
labN_name/
├── README.md           # Goal, theory, assignment, reflection questions
├── run.py              # Main script (intentionally transparent/readable)
└── report_template.md  # Template for student conclusions
```

## Frameworks

- **Phase 1:** [Inspect AI](https://inspect.aisi.org.uk/) — static dataset evaluation. Native OpenRouter support via `--model openrouter/<model-id>`. Tasks defined with `@task` decorator.
- **Phase 2:** [DeepTeam](https://github.com/confident-ai/deepteam) — dynamic red teaming. Model connected via `model_callback: str -> str`.

## LLM API

All labs use **OpenRouter** as the LLM provider. Configuration via `.env` file (see `.env.example`). Key env vars: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (e.g. `openai/gpt-4o-mini`).

## Lab Output Convention

Each lab produces two artifacts:
1. Auto-generated report from the framework (JSON or HTML in `reports/`)
2. Student-authored `report.md` filled from `report_template.md`

The `reports/` directories are `.gitignored`.

## Phase 1 Datasets (Inspect AI)

Each dataset tests a different failure mode — this is intentional and pedagogically important.

| Lab | Dataset | Tests for | Prompt column | Size | Load via |
|-----|---------|-----------|---------------|------|----------|
| lab1 | AdvBench | Harmful content generation | `goal` (+ `target`) | 520 | pandas CSV |
| lab2 | XSTest | Over-refusal on safe prompts | `prompt` (+ `label`) | 451 | pandas CSV |
| lab3 | ToxicChat | Real-world toxic conversations | `user_input` (+ `toxicity`, `jailbreaking`) | 10K+ | HuggingFace `lmsys/toxic-chat` |
| lab4 | WildJailbreak | Adversarial jailbreak variants | `vanilla`/`adversarial` (+ `data_type`) | 262K | HuggingFace `allenai/wildjailbreak` |
| lab5 | Do-Not-Answer | Harm taxonomy by category | `question` (+ `risk_area`) | 939 | HuggingFace `LibrAI/do-not-answer` |
| lab6 | Aya Redteaming | Multilingual attacks (8 languages) | `harmful_prompt` | 7,419 | HuggingFace `CohereLabs/aya_redteaming` |

Datasets are not stored in the repo — `datasets/download_datasets.py` fetches them.

**Note on XSTest:** scorer logic is inverted — safe prompts should receive an answer, not a refusal. This is the key teaching point about precision vs recall in LLM safety.

## Phase 2 Dynamic Testing (DeepTeam)

Cover only OWASP LLM Top-10 threats supported by DeepTeam out of the box. No custom attack scenarios.

DeepTeam entry point:
```python
from deepteam import red_team
from deepteam.frameworks import OWASPTop10

risk_assessment = red_team(
    model_callback=your_model_callback,  # function: str -> str via OpenRouter
    framework=OWASPTop10(),
    attacks_per_vulnerability_type=5
)
```
OWASP 2025 coverage: LLM01 Prompt Injection, LLM02 Sensitive Info Disclosure, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM09 Misinformation, LLM10 Unbounded Consumption (and others supported out of the box).

## Code Style Principles

- Scripts must be **intentionally readable** — students learn by reading the code
- No abstraction layers that hide what's happening (no magic wrappers)
- Each `run.py` should be understandable without reading other files
- Comments explain *why*, not *what*
