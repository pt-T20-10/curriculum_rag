"""
exp2_ensemble.py
================
Compute ensemble scores from 5 LLM judges for Experiment 2.

Reads exp2_textbook_scores.csv from each judge folder and computes
the ensemble mean across all judges per textbook.

Input folders (one per judge):
    exp2_o3/
    exp2_nemotron49b/
    exp2_mistral_nem/
    exp2_qwen80b/
    exp2_llama70b/

Each folder must contain exp2_textbook_scores.csv.

Outputs (written to --output folder):
    exp2_ensemble_textbook_scores.csv    18 rows — ensemble mean per textbook
    exp2_ensemble_group_scores.csv        3 rows — group mean + CI
    exp2_ensemble_stats.json             Mann-Whitney U + bootstrap CI + Cohen's d
    exp2_ensemble_judge_summary.csv       5 rows — per-judge means for paper

Usage:
    python exp2_ensemble.py \\
        --o3          results/exp2_o3 \\
        --nemotron49b results/exp2_nemotron49b \\
        --mistral-nem results/exp2_mistral_nem \\
        --qwen80b     results/exp2_qwen80b \\
        --llama70b    results/exp2_llama70b \\
        --output      results/exp2_ensemble
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from exp2_common import MANIFEST_NAME, TOPICS


# ─── constants ───────────────────────────────────────────────────────────────

JUDGE_ARGS = [
    ("o3",          "--o3"),
    ("nemotron49b", "--nemotron49b"),
    ("mistral_nem", "--mistral-nem"),
    ("qwen80b",     "--qwen80b"),
    ("llama70b",    "--llama70b"),
]

CRITERIA = ["C_mean", "LT_mean", "SO_mean", "LA_mean"]


# ─── loading ─────────────────────────────────────────────────────────────────

def load_judge(folder: Path, judge_name: str) -> pd.DataFrame:
    """Load exp2_textbook_scores.csv from one judge folder."""
    path = folder / "exp2_textbook_scores.csv"
    if not path.exists():
        print(f"ERROR: Missing {path}")
        sys.exit(1)
    df = pd.read_csv(path)
    manifest_path = folder / MANIFEST_NAME
    coverage_path = folder / "coverage_report.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Missing reproducibility manifest: {manifest_path}")
    if not coverage_path.exists():
        raise RuntimeError(f"Missing coverage report: {coverage_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    if not coverage.get("complete"):
        raise RuntimeError(f"Incomplete judge results: {coverage_path}")
    if manifest.get("judge_name") != judge_name:
        raise RuntimeError(
            f"Judge folder mismatch: expected {judge_name}, "
            f"manifest contains {manifest.get('judge_name')}"
        )
    if len(df) != 18 or set(df["source"].value_counts().to_dict().values()) != {6}:
        raise RuntimeError(f"Expected 18 textbooks (6/source) in {path}, got {len(df)}")
    if set(df["topic"]) != set(TOPICS) or not (df["n_chapters"] == 5).all():
        raise RuntimeError(f"Invalid topic/chapter coverage in {path}")
    df["judge"] = judge_name
    df.attrs["dataset_fingerprint"] = manifest["dataset_fingerprint"]
    df.attrs["judge_model"] = manifest["judge_model"]
    return df


# ─── ensemble aggregation ────────────────────────────────────────────────────

def compute_ensemble_textbook(all_judges: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Compute ensemble mean per textbook across all judges.

    For each book_id, average mean_score and per-criterion scores
    across all judge DataFrames.
    """
    combined = pd.concat(all_judges, ignore_index=True)

    agg_cols = {"mean_score": "mean"}
    for c in CRITERIA:
        if c in combined.columns:
            agg_cols[c] = "mean"

    ensemble = (
        combined.groupby(["book_id", "source", "topic"])
        .agg(
            n_judges    = ("judge",      "nunique"),
            n_chapters  = ("n_chapters", "first"),
            mean_score  = ("mean_score", "mean"),
            std_score   = ("mean_score", "std"),
            C_mean      = ("C_mean",     "mean"),
            LT_mean     = ("LT_mean",    "mean"),
            SO_mean     = ("SO_mean",    "mean"),
            LA_mean     = ("LA_mean",    "mean"),
        )
        .reset_index()
    )

    ensemble["mean_score"] = ensemble["mean_score"].round(4)
    ensemble["std_score"]  = ensemble["std_score"].round(4)
    for c in CRITERIA:
        ensemble[c] = ensemble[c].round(4)

    return ensemble


def compute_group(tb: pd.DataFrame, source: str) -> dict:
    scores = tb[tb["source"] == source]["mean_score"].tolist()
    if not scores:
        return {}
    arr = np.array(scores)
    return {
        "source":  source,
        "n_books": len(scores),
        "mean":    round(float(np.mean(arr)), 4),
        "std":     round(float(np.std(arr)),  4),
        "min":     round(float(np.min(arr)),  4),
        "max":     round(float(np.max(arr)),  4),
    }


def compute_judge_summary(all_judges: list[pd.DataFrame]) -> pd.DataFrame:
    """Per-judge group means — for documenting inter-judge agreement."""
    rows = []
    for df in all_judges:
        judge = df["judge"].iloc[0]
        for src in ["AATG", "PTIT", "DirectChat"]:
            scores = df[df["source"] == src]["mean_score"].tolist()
            if scores:
                rows.append({
                    "judge":  judge,
                    "source": src,
                    "mean":   round(float(np.mean(scores)), 4),
                    "std":    round(float(np.std(scores)),  4),
                })
    return pd.DataFrame(rows)


# ─── statistics ──────────────────────────────────────────────────────────────

def bootstrap_ci(scores: list[float], n_iter: int = 2000, alpha: float = 0.05):
    arr   = np.array(scores)
    means = [np.mean(np.random.choice(arr, size=len(arr), replace=True))
             for _ in range(n_iter)]
    return (
        round(float(np.percentile(means, 100 * alpha / 2)),       4),
        round(float(np.percentile(means, 100 * (1 - alpha / 2))), 4),
    )


def cohens_d(a: list[float], b: list[float]) -> float:
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    pooled = np.sqrt(
        ((na-1)*np.var(a, ddof=1) + (nb-1)*np.var(b, ddof=1)) / (na+nb-2)
    )
    return 0.0 if pooled == 0 else float((np.mean(a) - np.mean(b)) / pooled)


def run_stats(tb: pd.DataFrame) -> dict:
    by = {
        src: tb[tb["source"] == src]["mean_score"].tolist()
        for src in ["AATG", "PTIT", "DirectChat"]
    }

    comps = {}
    for a_src, b_src, key in [
        ("AATG", "PTIT",       "aatg_vs_ptit"),
        ("AATG", "DirectChat", "aatg_vs_dc"),
        ("PTIT", "DirectChat", "ptit_vs_dc"),
    ]:
        if a_src not in by or b_src not in by:
            continue
        a, b = by[a_src], by[b_src]
        if len(a) < 2 or len(b) < 2:
            continue
        U, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
        d    = cohens_d(a, b)
        comps[key] = {
            "source_a":    a_src,
            "source_b":    b_src,
            "mean_a":      round(float(np.mean(a)), 4),
            "mean_b":      round(float(np.mean(b)), 4),
            "diff":        round(float(np.mean(a) - np.mean(b)), 4),
            "U":           float(U),
            "p_value":     round(float(p), 6),
            "significant": bool(p < 0.05),
            "cohens_d":    round(d, 4),
            "effect_size": (
                "large"  if abs(d) >= 0.8 else
                "medium" if abs(d) >= 0.5 else
                "small"  if abs(d) >= 0.2 else
                "negligible"
            ),
        }

    ci = {}
    for src, scores in by.items():
        lo, hi = bootstrap_ci(scores)
        ci[src] = {
            "mean":    round(float(np.mean(scores)), 4),
            "ci_low":  lo,
            "ci_high": hi,
        }

    return {
        "comparisons":  comps,
        "bootstrap_ci": ci,
        "n_per_group":  {s: len(v) for s, v in by.items()},
        "n_judges":     5,
        "test":         "Mann-Whitney U (two-sided), bootstrap CI 95% n=2000",
    }


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Compute ensemble scores from 5 LLM judges for Experiment 2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--o3", type=Path, required=True,
                   help="Folder containing OpenAI o3 judge results")
    p.add_argument("--nemotron49b", type=Path, required=True)
    p.add_argument("--mistral-nem", type=Path, required=True, dest="mistral_nem")
    p.add_argument("--qwen80b",     type=Path, required=True)
    p.add_argument("--llama70b",    type=Path, required=True)
    p.add_argument("--output",      type=Path, required=True,
                   help="Output folder for ensemble results.")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # Load all judges
    judge_folders = [
        (args.o3,          "o3"),
        (args.nemotron49b, "nemotron49b"),
        (args.mistral_nem, "mistral_nem"),
        (args.qwen80b,     "qwen80b"),
        (args.llama70b,    "llama70b"),
    ]

    all_judges = []
    for folder, name in judge_folders:
        if not folder.exists():
            print(f"ERROR: Folder not found: {folder}")
            sys.exit(1)
        df = load_judge(folder, name)
        all_judges.append(df)
        print(f"  Loaded {name}: {len(df)} textbooks")

    fingerprints = {df.attrs["dataset_fingerprint"] for df in all_judges}
    if len(fingerprints) != 1:
        raise RuntimeError(f"Judge dataset fingerprints differ: {sorted(fingerprints)}")

    # Ensemble textbook scores
    tb = compute_ensemble_textbook(all_judges)
    if len(tb) != 18 or not (tb["n_judges"] == 5).all():
        raise RuntimeError("Ensemble is incomplete: expected 18 books with all 5 judges")

    # Group scores
    sources  = ["AATG", "PTIT", "DirectChat"]
    grp_rows = [r for r in [compute_group(tb, s) for s in sources] if r]

    # Stats
    stats_out = run_stats(tb)

    # Add CI to group rows
    for row in grp_rows:
        ci = stats_out["bootstrap_ci"].get(row["source"], {})
        row["ci_low"]  = ci.get("ci_low",  row["mean"])
        row["ci_high"] = ci.get("ci_high", row["mean"])

    # Judge summary
    judge_summary = compute_judge_summary(all_judges)

    # Export
    tb_path     = args.output / "exp2_ensemble_textbook_scores.csv"
    grp_path    = args.output / "exp2_ensemble_group_scores.csv"
    stats_path  = args.output / "exp2_ensemble_stats.json"
    judge_path  = args.output / "exp2_ensemble_judge_summary.csv"

    tb.to_csv(tb_path,            index=False)
    pd.DataFrame(grp_rows).to_csv(grp_path, index=False)
    stats_path.write_text(
        json.dumps(stats_out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    judge_summary.to_csv(judge_path, index=False)
    (args.output / "ensemble_manifest.json").write_text(
        json.dumps({
            "dataset_fingerprint": next(iter(fingerprints)),
            "n_judges": 5,
            "n_textbooks": len(tb),
            "judges": [
                {"name": name, "model": df.attrs["judge_model"]}
                for (_, name), df in zip(judge_folders, all_judges)
            ],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Console summary
    print(f"\n{'='*60}\n  ENSEMBLE RESULTS (5 judges)\n{'='*60}")
    print(f"  {'Source':<14} {'N':>4} {'Mean':>8} {'Std':>7}  95% CI")
    print(f"  {'-'*55}")
    for row in grp_rows:
        print(f"  {row['source']:<14} {row['n_books']:>4} "
              f"{row['mean']:>8.4f} {row['std']:>7.4f}  "
              f"[{row['ci_low']:.4f}, {row['ci_high']:.4f}]")

    print(f"\n  Pairwise tests (Mann-Whitney U, two-sided):")
    for key, c in stats_out["comparisons"].items():
        sig = "**" if c["p_value"] < 0.01 else ("*" if c["p_value"] < 0.05 else "ns")
        print(f"  {c['source_a']} vs {c['source_b']:<14} "
              f"Δ={c['diff']:+.4f}  p={c['p_value']:.4f}{sig}  "
              f"d={c['cohens_d']:.3f}({c['effect_size']})")

    print(f"\n  Per-judge means:")
    pivot = judge_summary.pivot(index="judge", columns="source", values="mean")
    print(pivot.to_string())

    print(f"\n  Saved → {args.output}\n")


if __name__ == "__main__":
    main()
