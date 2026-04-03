"""
Download all Phase 1 datasets into subdirectories.
Run from phase1_inspect/: python datasets/download_datasets.py

Expected disk usage:
- AdvBench: ~50KB
- XSTest: ~100KB
- ToxicChat: ~10MB
- WildJailbreak: ~1GB (large! ensure sufficient disk space)
- Do-Not-Answer: ~1MB
- Aya Redteaming: ~10MB
"""
import os
import requests
from pathlib import Path
from datasets import load_dataset

DATASETS_DIR = Path(__file__).parent


def download_advbench():
    out = DATASETS_DIR / "advbench"
    dest = out / "harmful_behaviors.csv"
    if dest.exists():
        print(f"  AdvBench: already exists, skipping")
        return
    out.mkdir(exist_ok=True)
    url = "https://raw.githubusercontent.com/llm-attacks/llm-attacks/main/data/advbench/harmful_behaviors.csv"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f"  AdvBench: {len(r.content)//1024}KB saved to {dest}")


def download_xstest():
    out = DATASETS_DIR / "xstest"
    dest = out / "xstest_prompts.csv"
    if dest.exists():
        print(f"  XSTest: already exists, skipping")
        return
    out.mkdir(exist_ok=True)
    url = "https://raw.githubusercontent.com/paul-rottger/xstest/main/xstest_prompts.csv"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f"  XSTest: {len(r.content)//1024}KB saved to {dest}")


def download_hf(hf_id: str, name: str, config: str = None):
    out = DATASETS_DIR / name
    if out.exists():
        print(f"  {name}: already exists, skipping")
        return
    kwargs = {"path": hf_id}
    if config:
        kwargs["name"] = config
    try:
        ds = load_dataset(**kwargs)
    except ValueError as e:
        # Config name may have changed on HuggingFace — check the dataset page if this fails
        raise ValueError(f"Failed to load {hf_id} (config={config}). "
                         f"Verify config name at huggingface.co/datasets/{hf_id}") from e
    ds.save_to_disk(str(out))
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) // (1024 * 1024)
    print(f"  {name}: {size}MB saved to {out}")


if __name__ == "__main__":
    print("Downloading Phase 1 datasets...")
    print("  [1/6] AdvBench")
    download_advbench()
    print("  [2/6] XSTest")
    download_xstest()
    print("  [3/6] ToxicChat")
    download_hf("lmsys/toxic-chat", "toxicchat", config="toxicchat0124")
    print("  [4/6] WildJailbreak (~1GB — this will take a while)")
    download_hf("allenai/wildjailbreak", "wildjailbreak")
    print("  [5/6] Do-Not-Answer")
    download_hf("LibrAI/do-not-answer", "do_not_answer")
    print("  [6/6] Aya Redteaming")
    download_hf("CohereLabs/aya_redteaming", "aya_redteaming")
    print("Done. All datasets saved to phase1_inspect/datasets/")
