"""
test_nvidia_models.py
=====================
Connectivity test for the four NVIDIA judges used in Experiment 2.

Usage:
    python test_nvidia_models.py --api-key "YOUR_NVIDIA_API_KEY"
    # Or set env var:
    export NVIDIA_API_KEY="YOUR_NVIDIA_API_KEY"
    python test_nvidia_models.py
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

from exp2_common import (
    NVIDIA_BASE_URL,
    NVIDIA_CORE_JUDGES,
)

# ─── Labels ──────────────────────────────────────────────────────────────────

MODEL_LABELS = {
    "nemotron49b": "Nemotron Super 49B",
    "mistral_nem": "Mistral Nemotron",
    "llama70b": "Llama 3.3 70B Instruct",
    "qwen80b": "Qwen3 Next 80B MoE",
}

TEST_PROMPT  = "Reply with exactly one sentence: What is 2 + 2?"

# ─── test runner ─────────────────────────────────────────────────────────────

def test_model(client: OpenAI, model_id: str, model_name: str) -> dict:
    start = time.time()
    try:
        response = client.chat.completions.create(
            model      = model_id,
            messages   = [{"role": "user", "content": TEST_PROMPT}],
            max_tokens = 256,
        )
        elapsed = round(time.time() - start, 2)
        content = response.choices[0].message.content.strip()  # type: ignore
        tokens  = response.usage.total_tokens if response.usage else "N/A"
        return {
            "status":  "✅ OK",
            "reply":   content[:120],
            "tokens":  tokens,
            "elapsed": elapsed,
            "error":   None,
        }
    except Exception as e:
        return {
            "status":  "❌ FAILED",
            "reply":   None,
            "tokens":  None,
            "elapsed": round(time.time() - start, 2),
            "error":   str(e),
        }


def run_tests(api_key: str, models: dict[str, str]) -> list[dict]:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)

    print(f"\n{'='*60}")
    print(f"  NVIDIA NIM — Model Connectivity Test")
    print(f"  Prompt: \"{TEST_PROMPT}\"")
    print(f"{'='*60}\n")

    results = []
    for alias, model in models.items():
        name = MODEL_LABELS.get(alias, alias)
        print(f"Testing: {name} [{alias}] ({model}) ...")
        result = test_model(client, model, name)
        result["alias"] = alias
        result["name"]  = name
        result["model"] = model
        results.append(result)

        print(f"  Status:  {result['status']}")
        if result["reply"]:
            print(f"  Reply:   {result['reply']}")
            print(f"  Tokens:  {result['tokens']}")
        if result["error"]:
            print(f"  Error:   {result['error']}")
        print(f"  Elapsed: {result['elapsed']}s\n")

    passed = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]

    print(f"{'='*60}")
    print(f"  SUMMARY: {len(passed)}/{len(models)} models accessible")
    print(f"{'='*60}")
    for r in passed:
        print(f"  ✅ {r['name']}")
    for r in failed:
        print(f"  ❌ {r['name']} — {r['error'][:80]}")
    print()
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test the four NVIDIA judges used in Experiment 2."
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="NVIDIA NIM API key (falls back to NVIDIA_API_KEY env var).",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--model", choices=sorted(NVIDIA_CORE_JUDGES),
        help="Test one model alias.",
    )
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional JSON result file.")
    args   = parser.parse_args()
    api_key = args.api_key or os.getenv("NVIDIA_API_KEY", "")
    if not api_key:
        parser.error("Provide --api-key or set NVIDIA_API_KEY env var.")

    if args.model:
        models = {args.model: NVIDIA_CORE_JUDGES[args.model]}
    else:
        models = NVIDIA_CORE_JUDGES

    results = run_tests(api_key, models)
    report = {"all_ok": all(result["error"] is None for result in results),
              "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    if not report["all_ok"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
