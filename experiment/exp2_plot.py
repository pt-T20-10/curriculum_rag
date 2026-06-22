"""
exp2_plot.py
============
Plot figures and table for Experiment 2 — Pedagogical Quality Assessment.
Works with ensemble output files from exp2_ensemble.py.

Reads:
    exp2_ensemble_textbook_scores.csv
    exp2_ensemble_group_scores.csv
    exp2_ensemble_stats.json
    exp2_ensemble_judge_summary.csv

Produces:
    exp2_fig2A_group_main.png     Group bar chart (main figure)
    exp2_fig2B_criteria.png       Per-criterion breakdown
    exp2_fig2C_judges.png         Per-judge mean comparison
    exp2_table_t2.csv / .txt      Per-topic scores table

Usage:
    python exp2_plot.py --input results/exp2_ensemble/ --output results/exp2_ensemble/figures/
    python exp2_plot.py --input results/exp2_ensemble/ --dpi 300
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ─── style constants ──────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "PTIT":       "#4C72B0",
    "AATG":       "#2CA02C",
    "DirectChat": "#D62728",
}
SOURCE_LABELS = {
    "PTIT":       "PTIT Textbooks\n(Human Baseline)",
    "AATG":       "Proposed System\n(AATG)",
    "DirectChat": "Direct Chat\n(Gemini 3.1 Pro)",
}
SOURCE_ORDER = ["PTIT", "AATG", "DirectChat"]

CRITERIA_LABELS = {
    "C_mean":  "Content\nQuality (C)",
    "LT_mean": "Learning &\nTeaching (LT)",
    "SO_mean": "Structure &\nOrganisation (SO)",
    "LA_mean": "Language\nQuality (LA)",
}
CRITERIA_ORDER = ["C_mean", "LT_mean", "SO_mean", "LA_mean"]

JUDGE_LABELS = {
    "o3":          "o3-2025\n(OpenAI)",
    "mistral_nem": "Mistral\nNemotron",
    "nemotron49b": "Nemotron\n49B",
    "llama70b":    "Llama 3.3\n70B",
    "qwen80b":     "Qwen3\n80B",
}
JUDGE_ORDER = ["o3", "mistral_nem", "nemotron49b", "llama70b", "qwen80b"]

TOPIC_FULL = {
    "antoanhedieuhanh":      "An toàn hệ điều hành",
    "laptrinhhuongdoituong": "Lập trình hướng đối tượng",
    "ngonngulaptrinhcpp":    "Ngôn ngữ lập trình C++",
    "ngonngulaptrinhjava":   "Ngôn ngữ lập trình Java",
    "nhapmoncnpm":           "Nhập môn CNPM",
    "nhapmonttnt":           "Nhập môn TTNT",
}
TOPIC_ORDER = list(TOPIC_FULL.keys())

plt.rcParams.update({
    "font.family":        "DejaVu Sans",
    "font.size":          11,
    "axes.titlesize":     13,
    "axes.labelsize":     11,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "figure.facecolor":   "white",
    "axes.facecolor":     "#FAFAFA",
    "grid.color":         "#E0E0E0",
    "grid.linewidth":     0.8,
})


def _sig_label(p: float) -> str:
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


def _add_sig_bracket(ax, x1, x2, y, label, dy=0.04):
    ax.plot([x1, x1, x2, x2], [y, y+dy, y+dy, y], lw=1.2, c="black")
    ax.text(
        (x1+x2)/2, y+dy+0.01, label,
        ha="center", va="bottom", fontsize=10,
        fontweight="bold" if label != "ns" else "normal",
    )


# ─── Figure 2A — group-level bar chart (main) ────────────────────────────────

def plot_2a(grp: pd.DataFrame, stats: dict, output_dir: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    x = np.arange(len(SOURCE_ORDER))

    for i, src in enumerate(SOURCE_ORDER):
        row = grp[grp["source"] == src]
        if row.empty:
            continue
        row   = row.iloc[0]
        mean  = row["mean"]
        ci_lo = stats["bootstrap_ci"].get(src, {}).get("ci_low",  mean)
        ci_hi = stats["bootstrap_ci"].get(src, {}).get("ci_high", mean)
        yerr  = np.array([[mean - ci_lo], [ci_hi - mean]])

        ax.bar(
            i, mean, 0.55,
            color=SOURCE_COLORS[src], alpha=0.88,
            yerr=yerr, capsize=6,
            error_kw={"linewidth": 1.8, "ecolor": "black"},
            zorder=3,
        )
        baseline = 2.5
        ax.text(
            i, baseline + (mean - baseline) * 0.55,
            f"{mean:.4f}",
            ha="center", va="center",
            fontsize=11, fontweight="bold", color="white",
            zorder=4,
        )

    # Significance brackets
    comps     = stats.get("comparisons", {})
    bracket_y = grp["mean"].max() + 0.15

    for key, x1, x2 in [
        ("ptit_vs_dc",   0, 2),
        ("aatg_vs_ptit", 0, 1),
        ("aatg_vs_dc",   1, 2),
    ]:
        c = comps.get(key)
        if c is None:
            continue
        lbl = _sig_label(c["p_value"])
        _add_sig_bracket(ax, x1, x2, bracket_y, lbl, dy=0.04)
        bracket_y += 0.12

    ax.set_xticks(x)
    ax.set_xticklabels(
        [SOURCE_LABELS[s] for s in SOURCE_ORDER],
        fontsize=10, linespacing=1.4,
    )
    ax.set_ylabel("Mean Pedagogical Quality Score  (scale 1–5)")
    ax.set_ylim(2.5, bracket_y + 0.15)
    ax.axhline(3.0, color="grey", ls="--", lw=0.8, alpha=0.5,
               label="Score = 3.0 (Average)")
    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, loc="lower right")
    

    plt.tight_layout()

    fig.text(
    0.01, -0.04,
    "95% Bootstrap CI (n = 2,000)  |  ** p < 0.01    * p < 0.05    ns: not significant\n"
    "Statistical test: Mann-Whitney U (two-sided)",
    fontsize=8, color="grey",
    va="top", ha="left",
    )

    out = output_dir / "exp2_fig2A_group_main.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
 
    plt.close()
    print(f"  Figure 2A saved → {out}")


# ─── Figure 2B — per-criterion breakdown ─────────────────────────────────────

def plot_2b(tb: pd.DataFrame, output_dir: Path, dpi: int) -> None:
    """
    Grouped bar chart: 4 criteria × 3 sources.
    Uses textbook-level criteria means (C_mean, LT_mean, SO_mean, LA_mean).
    """
    x       = np.arange(len(CRITERIA_ORDER))
    width   = 0.25
    offsets = [-width, 0, width]

    fig, ax = plt.subplots(figsize=(11, 6))

    for i, src in enumerate(SOURCE_ORDER):
        sub  = tb[tb["source"] == src]
        vals = [float(sub[c].mean()) for c in CRITERIA_ORDER]
        sems = [float(sub[c].sem()) if len(sub) > 1 else 0.0  #type: ignore
                for c in CRITERIA_ORDER]

        ax.bar(
            x + offsets[i], vals, width,
            color=SOURCE_COLORS[src], alpha=0.88,
            label=SOURCE_LABELS[src].replace("\n", " "),
            yerr=sems, capsize=4,
            error_kw={"linewidth": 1.2},
            zorder=3,
        )
        for j, v in enumerate(vals):
            baseline = 2.5
            label_y  = baseline + (v - baseline) * 0.55
            ax.text(
                x[j] + offsets[i], label_y,
                f"{v:.2f}",
                ha="center", va="center",
                fontsize=8.5, fontweight="bold", color="white",
                zorder=4,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(
        [CRITERIA_LABELS[c] for c in CRITERIA_ORDER],
        fontsize=10, linespacing=1.4,
    )
    ax.set_ylabel("Mean Score  (scale 1–5)")
    ax.set_ylim(2.5, 5.5)
    ax.axhline(3.0, color="grey", ls="--", lw=0.8, alpha=0.5)
    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)

    plt.tight_layout()
    out = output_dir / "exp2_fig2B_criteria.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 2B saved → {out}")


# ─── Figure 2C — per-judge mean comparison ───────────────────────────────────

def plot_2c(judge_df: pd.DataFrame, output_dir: Path, dpi: int) -> None:
    """
    Grouped bar chart: 5 judges × 3 sources.
    Documents inter-judge calibration for paper methodology section.
    """
    judges  = [j for j in JUDGE_ORDER if j in judge_df["judge"].unique()]
    x       = np.arange(len(judges))
    width   = 0.25
    offsets = [-width, 0, width]

    fig, ax = plt.subplots(figsize=(12, 6))

    for i, src in enumerate(SOURCE_ORDER):
        vals = []
        for jdg in judges:
            row = judge_df[(judge_df["judge"] == jdg) & (judge_df["source"] == src)]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)

        ax.bar(
            x + offsets[i], vals, width,
            color=SOURCE_COLORS[src], alpha=0.88,
            label=SOURCE_LABELS[src].replace("\n", " "),
            zorder=3,
        )
        for j, v in enumerate(vals):
            baseline = 2.5
            label_y  = baseline + (v - baseline) * 0.55
            ax.text(
                x[j] + offsets[i], label_y,
                f"{v:.2f}",
                ha="center", va="center",
                fontsize=8, fontweight="bold", color="white",
                zorder=4,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(
        [JUDGE_LABELS.get(j, j) for j in judges],
        fontsize=10, linespacing=1.4,
    )
    ax.set_ylabel("Mean Pedagogical Quality Score  (scale 1–5)")
    ax.set_ylim(2.5, 5.6)
    ax.axhline(3.0, color="grey", ls="--", lw=0.8, alpha=0.5)
    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)

    plt.tight_layout()
    out = output_dir / "exp2_fig2C_judges.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 2C saved → {out}")


# ─── Table T2 — per-topic ensemble scores ────────────────────────────────────

def make_table_t2(tb: pd.DataFrame, output_dir: Path) -> None:
    rows = []
    for topic in TOPIC_ORDER:
        row = {"Topic": TOPIC_FULL.get(topic, topic)}
        for src in SOURCE_ORDER:
            sub = tb[(tb["source"] == src) & (tb["topic"] == topic)]
            if len(sub):
                m = sub["mean_score"].iloc[0]
                s = sub["std_score"].iloc[0]
                row[src] = f"{m:.4f} ± {s:.4f}"
            else:
                row[src] = "—"
        rows.append(row)

    df = pd.DataFrame(rows)
    csv_path = output_dir / "exp2_table_t2.csv"
    df.to_csv(csv_path, index=False)

    col_w  = [28, 22, 22, 22]
    header = (
        f"{'Topic':<{col_w[0]}}"
        f"{'PTIT (Human)':<{col_w[1]}}"
        f"{'AATG (Proposed)':<{col_w[2]}}"
        f"{'DirectChat':<{col_w[3]}}"
    )
    sep   = "─" * sum(col_w)
    lines = [
        "Table T2 — Per-topic Pedagogical Quality Scores (Ensemble Mean ± Std)",
        "Scores on scale 1–5; ensemble of 5 LLM judges × 3 runs per chapter",
        sep, header, sep,
    ]
    for r in rows:
        lines.append(
            f"{r['Topic']:<{col_w[0]}}"
            f"{r['PTIT']:<{col_w[1]}}"
            f"{r['AATG']:<{col_w[2]}}"
            f"{r['DirectChat']:<{col_w[3]}}"
        )
    lines.append(sep)
    lines.append("")
    lines.append("Group means:")
    for src in SOURCE_ORDER:
        vals = tb[tb["source"] == src]["mean_score"].tolist()
        if vals:
            lines.append(
                f"  {src:<22} {np.mean(vals):.4f} ± {np.std(vals):.4f}"
            )

    txt_path = output_dir / "exp2_table_t2.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Table T2 saved  → {csv_path}")
    print(f"  Table T2 (txt)  → {txt_path}")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot figures for Experiment 2 ensemble results."
    )
    parser.add_argument("--input",  "-i", type=Path, required=True,
                        help="Ensemble output folder (contains exp2_ensemble_*.csv/json).")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output directory for figures (default: same as --input).")
    parser.add_argument("--dpi",    type=int, default=150,
                        help="PNG resolution (default: 150; use 300 for print).")
    args = parser.parse_args()

    inp = args.input
    out = args.output or inp
    out.mkdir(parents=True, exist_ok=True)

    required = [
        "exp2_ensemble_textbook_scores.csv",
        "exp2_ensemble_group_scores.csv",
        "exp2_ensemble_stats.json",
        "exp2_ensemble_judge_summary.csv",
    ]
    for fname in required:
        if not (inp / fname).exists():
            print(f"ERROR: {inp / fname} not found.")
            sys.exit(1)

    tb       = pd.read_csv(inp / "exp2_ensemble_textbook_scores.csv")
    grp      = pd.read_csv(inp / "exp2_ensemble_group_scores.csv")
    stats    = json.loads((inp / "exp2_ensemble_stats.json").read_text(encoding="utf-8"))
    judge_df = pd.read_csv(inp / "exp2_ensemble_judge_summary.csv")

    print(f"\nGenerating Experiment 2 ensemble figures  (DPI = {args.dpi})\n{'─'*48}")
    plot_2a(grp,      stats, out, args.dpi)
    plot_2b(tb,              out, args.dpi)
    plot_2c(judge_df,        out, args.dpi)
    make_table_t2(tb,        out)
    print(f"\nDone → {out}\n")


if __name__ == "__main__":
    main()
