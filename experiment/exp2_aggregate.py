"""
exp2_aggregate.py
=================
Compute group-level scores and statistical tests from exp2_textbook_scores.csv.

Reads:
    exp2_textbook_scores.csv   (18 rows — per textbook mean scores)

Writes to the same folder:
    exp2_group_scores.csv      (3 rows — per source group)
    exp2_stats.json            Mann-Whitney U + bootstrap CI + Cohen's d

Usage:
    python exp2_aggregate.py \\
        --input results/exp2_qwen80b/exp2_textbook_scores.csv
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


# ─── aggregation ─────────────────────────────────────────────────────────────

def agg_group(tb: pd.DataFrame, source: str) -> dict:
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
    sources = tb["source"].unique().tolist()
    by      = {s: tb[tb["source"] == s]["mean_score"].tolist() for s in sources}

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
        "test":         "Mann-Whitney U (two-sided), bootstrap CI 95% n=2000",
    }


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Compute group scores and stats from exp2_textbook_scores.csv."
    )
    p.add_argument(
        "--input", "-i", type=Path, required=True,
        help="Path to exp2_textbook_scores.csv",
    )
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: File not found: {args.input}")
        sys.exit(1)

    tb       = pd.read_csv(args.input)
    out_dir  = args.input.parent

    # Validate required columns
    required = {"source", "mean_score", "C_mean", "LT_mean", "SO_mean", "LA_mean"}
    missing  = required - set(tb.columns)
    if missing:
        print(f"ERROR: Missing columns: {missing}")
        sys.exit(1)

    sources  = tb["source"].unique().tolist()

    # Group scores
    grp_rows = [r for r in [agg_group(tb, s) for s in sources] if r]
    grp_df   = pd.DataFrame(grp_rows)

    # Add bootstrap CI to group rows
    stats_out = run_stats(tb)
    for row in grp_rows:
        ci = stats_out["bootstrap_ci"].get(row["source"], {})
        row["ci_low"]  = ci.get("ci_low",  row["mean"])
        row["ci_high"] = ci.get("ci_high", row["mean"])

    # Export
    grp_path   = out_dir / "exp2_group_scores.csv"
    stats_path = out_dir / "exp2_stats.json"

    pd.DataFrame(grp_rows).to_csv(grp_path, index=False)
    stats_path.write_text(
        json.dumps(stats_out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Console summary
    print(f"\n{'='*60}\n  RESULTS SUMMARY\n{'='*60}")
    print(f"  {'Source':<14} {'N':>4} {'Mean':>8} {'Std':>7}  95% CI")
    print(f"  {'-'*55}")
    for row in grp_rows:
        print(f"  {row['source']:<14} {row['n_books']:>4} "
              f"{row['mean']:>8.4f} {row['std']:>7.4f}  "
              f"[{row['ci_low']:.4f}, {row['ci_high']:.4f}]")

    if stats_out["comparisons"]:
        print(f"\n  Pairwise tests (Mann-Whitney U, two-sided):")
        for key, c in stats_out["comparisons"].items():
            sig = "**" if c["p_value"] < 0.01 else ("*" if c["p_value"] < 0.05 else "ns")
            print(f"  {c['source_a']} vs {c['source_b']:<14} "
                  f"Δ={c['diff']:+.4f}  p={c['p_value']:.4f}{sig}  "
                  f"d={c['cohens_d']:.3f}({c['effect_size']})")

    print(f"\n  Saved → {grp_path}")
    print(f"  Saved → {stats_path}\n")


if __name__ == "__main__":
    main()
