"""Tests for the ToxicChat Inspect task dataset loader."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from phase1_safety_metrics import (
    BEHAVIOR_ANSWER,
    BEHAVIOR_REFUSE,
    PROMPT_BENIGN,
    PROMPT_HARMFUL,
)


def _load_toxicchat_module(monkeypatch):
    """Import the lab module without reading the repo .env file."""
    fake_dotenv = ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    module_path = Path(__file__).resolve().parents[2] / "labs" / "lab3_toxicchat" / "run.py"
    spec = importlib.util.spec_from_file_location("test_lab3_toxicchat_run", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_toxicchat_loader_uses_train_and_test_with_dynamic_targets(monkeypatch):
    module = _load_toxicchat_module(monkeypatch)
    fake_dataset = {
        "train": [
            {"user_input": "train harmful", "toxicity": 1, "jailbreaking": 0},
            {"user_input": "train benign", "toxicity": 0, "jailbreaking": 0},
        ],
        "test": [
            {"user_input": "test jailbreak", "toxicity": 0, "jailbreaking": 1},
            {"user_input": "test benign", "toxicity": 0, "jailbreaking": 0},
        ],
    }
    monkeypatch.setattr(module, "load_from_disk", lambda _: fake_dataset)

    samples = module.load_toxicchat()
    by_input = {sample.input: sample for sample in samples}

    assert set(by_input) == {
        "train harmful",
        "train benign",
        "test jailbreak",
        "test benign",
    }
    assert len(samples) == 4
    assert {name: sample.target for name, sample in by_input.items()} == {
        "train harmful": module.HARMFUL_TARGET,
        "train benign": module.BENIGN_TARGET,
        "test jailbreak": module.HARMFUL_TARGET,
        "test benign": module.BENIGN_TARGET,
    }
    assert {
        sample.input: (
            sample.metadata["split"],
            sample.metadata["is_harmful"],
            sample.metadata["safety_label"],
            sample.metadata["expected_behavior"],
        )
        for sample in samples
    } == {
        "train harmful": ("train", True, PROMPT_HARMFUL, BEHAVIOR_REFUSE),
        "train benign": ("train", False, PROMPT_BENIGN, BEHAVIOR_ANSWER),
        "test jailbreak": ("test", True, PROMPT_HARMFUL, BEHAVIOR_REFUSE),
        "test benign": ("test", False, PROMPT_BENIGN, BEHAVIOR_ANSWER),
    }


def test_toxicchat_loader_shuffles_before_limit_sampling(monkeypatch):
    module = _load_toxicchat_module(monkeypatch)
    fake_dataset = {
        "train": [
            {"user_input": f"train {i}", "toxicity": 0, "jailbreaking": 0}
            for i in range(10)
        ],
        "test": [
            {"user_input": f"test {i}", "toxicity": 0, "jailbreaking": 0}
            for i in range(10)
        ],
    }
    monkeypatch.setattr(module, "load_from_disk", lambda _: fake_dataset)

    samples = module.load_toxicchat()

    assert [sample.input for sample in samples[:5]] != [
        "train 0",
        "train 1",
        "train 2",
        "train 3",
        "train 4",
    ]
    assert any(sample.metadata["split"] == "test" for sample in samples[:5])


def test_toxicchat_loader_handles_dataset_dict_column_names(monkeypatch):
    module = _load_toxicchat_module(monkeypatch)

    class FakeDatasetDict(dict):
        @property
        def column_names(self):
            return {name: ["user_input", "toxicity", "jailbreaking"] for name in self}

    fake_dataset = FakeDatasetDict(
        {
            "train": [{"user_input": "train row", "toxicity": 0, "jailbreaking": 0}],
            "test": [{"user_input": "test row", "toxicity": 1, "jailbreaking": 0}],
        }
    )
    monkeypatch.setattr(module, "load_from_disk", lambda _: fake_dataset)

    samples = module.load_toxicchat()

    assert {sample.input for sample in samples} == {"train row", "test row"}

