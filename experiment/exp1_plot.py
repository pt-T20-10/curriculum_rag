"""
exp1_plot.py
============
Plot 4 figures for Experiment 1 — Semantic Diversity (Sdiv).

Reads from 4 output files produced by exp1_sdiv.py:
    exp1_pairwise_raw.csv
    exp1_textbook_scores.csv
    exp1_group_scores.csv
    exp1_stats.json

Produces 4 separate PNG files:
    exp1_fig1A_per_topic.png     -- Grouped bar chart by topic
    exp1_fig1B_group_main.png    -- Group-level bar chart (main figure for paper)
    exp1_fig1C_boxplot.png       -- Box plot distribution
    exp1_fig1D_components.png    -- ROUGE-L vs Cosine component breakdown

Usage:
    python exp1_plot.py --input results/exp1/ --output results/exp1/figures/
    python exp1_plot.py --input results/exp1/ --output results/exp1/figures/ --dpi 300
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# ─── labels & style ──────────────────────────────────────────────────────────

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

TOPIC_LABELS = {
    "antoanhedieuhanh":      "An toàn\nhệ điều hành",
    "laptrinhhuongdoituong": "Lập trình\nhướng đối tượng",
    "ngonngulaptrinhcpp":    "Ngôn ngữ\nlập trình C++",
    "ngonngulaptrinhjava":   "Ngôn ngữ\nlập trình Java",
    "nhapmoncnpm":           "Nhập môn\nCNPM",
    "nhapmonttnt":           "Nhập môn\nTTNT",
}
TOPIC_ORDER = [
    "antoanhedieuhanh", "laptrinhhuongdoituong",
    "ngonngulaptrinhcpp", "ngonngulaptrinhjava",
    "nhapmoncnpm", "nhapmonttnt",
]

TOPIC_FULL = {
    "antoanhedieuhanh":      "An toàn hệ điều hành",
    "laptrinhhuongdoituong": "Lập trình hướng đối tượng",
    "ngonngulaptrinhcpp":    "Ngôn ngữ lập trình C++",
    "ngonngulaptrinhjava":   "Ngôn ngữ lập trình Java",
    "nhapmoncnpm":           "Nhập môn CNPM",
    "nhapmonttnt":           "Nhập môn TTNT",
}

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


def _add_sig_bracket(ax, x1, x2, y, label, dy=0.005):
    ax.plot([x1, x1, x2, x2], [y, y + dy, y + dy, y], lw=1.2, c="black")
    ax.text(
        (x1 + x2) / 2, y + dy + 0.001, label,
        ha="center", va="bottom", fontsize=10,
        fontweight="bold" if label != "ns" else "normal",
    )


# ─── Figure 1A — per-topic grouped bar ───────────────────────────────────────

def plot_1a(tb: pd.DataFrame, output_dir: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(14, 6))
    x      = np.arange(len(TOPIC_ORDER))
    width  = 0.26
    offset = [-width, 0, width]

    for i, src in enumerate(SOURCE_ORDER):
        vals, errs = [], []
        for topic in TOPIC_ORDER:
            row = tb[(tb["source"] == src) & (tb["topic"] == topic)]
            vals.append(row["sdiv_mean"].iloc[0] if len(row) else 0)
            errs.append(row["sdiv_std"].iloc[0]  if len(row) else 0)

        ax.bar(
            x + offset[i], vals, width,
            color=SOURCE_COLORS[src], alpha=0.88,
            label=SOURCE_LABELS[src].replace("\n", " "),
            yerr=errs, capsize=3,
            error_kw={"linewidth": 1.2},
        )
    for i, src in enumerate(SOURCE_ORDER):
        vals, errs = [], []
        for topic in TOPIC_ORDER:
            row = tb[(tb["source"] == src) & (tb["topic"] == topic)]
            vals.append(row["sdiv_mean"].iloc[0] if len(row) else 0)
            errs.append(row["sdiv_std"].iloc[0]  if len(row) else 0)

        bars = ax.bar(
            x + offset[i], vals, width,
            color=SOURCE_COLORS[src], alpha=0.88,
            label=SOURCE_LABELS[src].replace("\n", " "),
            yerr=errs, capsize=3,
            error_kw={"linewidth": 1.2},
        )
        # ↓ thêm đoạn này
        baseline = 0.35
        for j, v in enumerate(vals):
            ax.text(
                x[j] + offset[i],
                baseline + (v - baseline) * 0.55,
                f"{v:.4f}",
                ha="center", va="center",
                fontsize=7, fontweight="bold", color="white",
                zorder=4,
            ) 
    ax.set_xticks(x)
    ax.set_xticklabels([TOPIC_LABELS[t] for t in TOPIC_ORDER], fontsize=10)
    ax.set_ylabel("Mean Sdiv Score")
    ax.set_ylim(0.35, 0.56)
    
    ax.axhline(0.45, color="grey", ls="--", lw=0.8, alpha=0.6, label="Reference 0.45")
    ax.yaxis.grid(True, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

    plt.tight_layout()
    out = output_dir / "exp1_fig1A_per_topic.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 1A saved → {out}")


# ─── Figure 1B — group-level main figure ─────────────────────────────────────

def plot_1b(grp: pd.DataFrame, stats: dict, output_dir: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    x = np.arange(len(SOURCE_ORDER))

    for i, src in enumerate(SOURCE_ORDER):
        row   = grp[grp["source"] == src].iloc[0]
        mean  = row["sdiv_mean"]
        ci_lo = row["ci_low"]
        ci_hi = row["ci_high"]
        yerr  = np.array([[mean - ci_lo], [ci_hi - mean]])

        ax.bar(
            i, mean, 0.55,
            color=SOURCE_COLORS[src], alpha=0.88,
            yerr=yerr, capsize=6,
            error_kw={"linewidth": 1.8, "ecolor": "black"},
            zorder=3,
        )
        baseline = 0.38
        ax.text(
            i, baseline + (mean - baseline) * 0.55,
            f"{mean:.4f}",
            ha="center", va="center",
            fontsize=11, fontweight="bold", color="white",
            zorder=4,
            )
    # Significance brackets
    y_top = grp["sdiv_mean"].max() + 0.04
    comps = stats["comparisons"]
    bracket_y = y_top
    for key, x1, x2 in [
        ("aatg_vs_dc",   1, 2),
        ("aatg_vs_ptit", 0, 1),
    ]:
        c   = comps[key]
        lbl = _sig_label(c["p_value"])
        _add_sig_bracket(ax, x1, x2, bracket_y, lbl, dy=0.006)
        bracket_y += 0.022

    ax.set_xticks(x)
    ax.set_xticklabels(
        [SOURCE_LABELS[s] for s in SOURCE_ORDER],
        fontsize=10, linespacing=1.4,
    )
    
    ax.set_ylim(0.38, bracket_y + 0.025)
    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)

    plt.tight_layout()

    fig.text(
    0.01, -0.04,
    "95% Bootstrap CI (n = 2,000)  |  ** p < 0.01    * p < 0.05    ns: not significant\n"
    "Statistical test: Mann-Whitney U (two-sided)",
    fontsize=8, color="grey",
    va="top", ha="left",
    )
    out = output_dir / "exp1_fig1B_group_main.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 1B saved → {out}")


# ─── Figure 1C — box plots ───────────────────────────────────────────────────

def plot_1c(tb: pd.DataFrame, output_dir: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))

    data   = [tb[tb["source"] == src]["sdiv_mean"].values for src in SOURCE_ORDER]
    labels = [SOURCE_LABELS[s].replace("\n", " ") for s in SOURCE_ORDER]
    colors = [SOURCE_COLORS[s] for s in SOURCE_ORDER]

    bp = ax.boxplot(
        data, #type: ignore
        tick_labels=labels,
        patch_artist=True,
        medianprops={"color": "black", "linewidth": 2},
        whiskerprops={"linewidth": 1.5},
        capprops={"linewidth": 1.5},
        flierprops={"marker": "o", "markersize": 6, "alpha": 0.7},
        widths=0.45,
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)

    # Overlay individual data points with jitter
    rng = np.random.default_rng(42)
    for i, (d, color) in enumerate(zip(data, colors), start=1):
        jitter = rng.uniform(-0.08, 0.08, size=len(d))
        ax.scatter(
            np.full_like(d, i) + jitter, d, #type: ignore
            color=color, edgecolors="black", linewidths=0.6,
            zorder=5, s=55, alpha=0.85,
        )

    ax.set_ylabel("Mean Sdiv Score (per textbook)")

    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)

    plt.tight_layout()
    out = output_dir / "exp1_fig1C_boxplot.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 1C saved → {out}")


# ─── Figure 1D — component breakdown ─────────────────────────────────────────

def plot_1d(tb: pd.DataFrame, output_dir: Path, dpi: int) -> None:
    """
    Stacked bar showing ROUGE-L and Cosine contributions to Sdiv per group.

    Lexical component  = 0.5 × (1 − mean ROUGE-L)
    Semantic component = 0.5 × mean Cosine distance
    """
    fig, ax = plt.subplots(figsize=(8, 6))
    x     = np.arange(len(SOURCE_ORDER))
    width = 0.5

    for i, src in enumerate(SOURCE_ORDER):
        subset = tb[tb["source"] == src]
        lex    = 0.5 * (1.0 - subset["rouge_l_mean"].mean())
        sem    = 0.5 * subset["cosine_mean"].mean()

        ax.bar(
            i, lex, width,
            color=SOURCE_COLORS[src], alpha=0.9, zorder=3,
        )
        ax.bar(
            i, sem, width, bottom=lex,
            color=SOURCE_COLORS[src], alpha=0.45, hatch="///", zorder=3,
        )

        ax.text(i, lex / 2,       f"{lex:.3f}",
                ha="center", va="center", fontsize=10,
                fontweight="bold", color="white")
        ax.text(i, lex + sem / 2, f"{sem:.3f}",
                ha="center", va="center", fontsize=10,
                fontweight="bold", color="black")

    ax.set_xticks(x)
    ax.set_xticklabels(
        [SOURCE_LABELS[s].replace("\n", " ") for s in SOURCE_ORDER], fontsize=10,
    )
    ax.set_ylabel("Contribution to Sdiv Score")
    ax.set_ylim(0, 0.55)
    
    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)

    solid_patch = mpatches.Patch(color="grey", alpha=0.9,
                                 label="Lexical diversity  0.5×(1 − ROUGE-L)")
    hatch_patch = mpatches.Patch(color="grey", alpha=0.45, hatch="///",
                                 label="Semantic diversity  0.5×Cosine distance")
    ax.legend(handles=[solid_patch, hatch_patch], loc="upper right", fontsize=9)

    plt.tight_layout()
    out = output_dir / "exp1_fig1D_components.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 1D saved → {out}")


# ─── Figure 1F — chapter position distance pattern ───────────────────────────

def plot_1f(pw: pd.DataFrame, output_dir: Path, dpi: int) -> None:
    """
    Line chart: mean Sdiv by chapter-position distance (1–4).

    Distance = |rank_i − rank_j| where rank is the chapter's position
    in the 5-chapter selection (1–5), not the raw chapter number.
    A rising slope for DirectChat indicates quality degradation as
    the session context window fills; a flat line for AATG confirms
    independent per-section RAG processing.
    """
    import re as _re

    # Build rank mapping from filename: ch01→1, ch02→2, etc.
    def _rank(fname: str) -> int:
        m = _re.search(r"ch(\d+)", fname)
        return int(m.group(1)) if m else 0

    pw = pw.copy()
    pw["rank_i"]    = pw["ch_i"].apply(_rank)
    pw["rank_j"]    = pw["ch_j"].apply(_rank)
    pw["ch_dist"]   = (pw["rank_j"] - pw["rank_i"]).abs()

    # Group: mean Sdiv per (source, distance)
    grp = (
        pw.groupby(["source", "ch_dist"])["sdiv"]
        .agg(mean="mean", sem=lambda x: x.std() / (len(x) ** 0.5))
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(8, 6))
    markers = {"PTIT": "o", "AATG": "s", "DirectChat": "^"}

    for src in SOURCE_ORDER:
        sub = grp[grp["source"] == src].sort_values("ch_dist")
        ax.plot(
            sub["ch_dist"], sub["mean"],
            color=SOURCE_COLORS[src], marker=markers[src],
            linewidth=2.2, markersize=8,
            label=SOURCE_LABELS[src].replace("\n", " "),
        )
        ax.fill_between(
            sub["ch_dist"],
            sub["mean"] - sub["sem"],
            sub["mean"] + sub["sem"],
            color=SOURCE_COLORS[src], alpha=0.12,
        )

    ax.set_xticks([1, 2, 3, 4])
    ax.set_xticklabels(
        ["Adjacent\n(dist=1)", "Skip-1\n(dist=2)",
         "Skip-2\n(dist=3)", "Furthest\n(dist=4)"],
        fontsize=10,
    )
    ax.set_xlabel("Chapter Position Distance")
    ax.set_ylabel("Mean Sdiv Score")
  
    ax.yaxis.grid(True, zorder=0, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, framealpha=0.9)

    plt.tight_layout()
    out = output_dir / "exp1_fig1F_distance.png"
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close()
    print(f"  Figure 1F saved → {out}")


# ─── Table T1 — per-textbook scores ──────────────────────────────────────────

def make_table_t1(tb: pd.DataFrame, output_dir: Path) -> None:
    """
    Export Table T1: per-topic Sdiv mean ± std, one row per topic,
    three source columns. Saved as CSV and a formatted TXT for the paper.
    """
    rows = []
    for topic in TOPIC_ORDER:
        row = {"Topic": TOPIC_FULL[topic]}
        for src in SOURCE_ORDER:
            sub = tb[(tb["source"] == src) & (tb["topic"] == topic)]
            if len(sub):
                m = sub["sdiv_mean"].iloc[0]
                s = sub["sdiv_std"].iloc[0]
                row[src] = f"{m:.4f} ± {s:.4f}"
            else:
                row[src] = "—"
        rows.append(row)

    df = pd.DataFrame(rows)

    # CSV
    csv_path = output_dir / "exp1_table_t1.csv"
    df.to_csv(csv_path, index=False)

    # Human-readable TXT for paper
    txt_path = output_dir / "exp1_table_t1.txt"
    col_w = [22, 22, 22, 22]
    header = (f"{'Topic':<{col_w[0]}}"
              f"{'PTIT (Human)':<{col_w[1]}}"
              f"{'AATG (Proposed)':<{col_w[2]}}"
              f"{'DirectChat':<{col_w[3]}}")
    sep = "─" * sum(col_w)
    lines = [
        "Table T1 — Per-topic Sdiv Scores (Mean ± Std, n=5 chapters each)",
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

    # Group means row
    lines.append("")
    lines.append("Group means:")
    for src in SOURCE_ORDER:
        vals = [r["sdiv_mean"] for _, r in tb[tb["source"] == src].iterrows()
                if r["topic"] in TOPIC_ORDER]
        if vals:
            import numpy as _np
            lines.append(f"  {src:<20} {_np.mean(vals):.4f} ± {_np.std(vals):.4f}")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Table T1 saved  → {csv_path}")
    print(f"  Table T1 (txt)  → {txt_path}")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot figures and tables for Experiment 1 — Sdiv."
    )
    parser.add_argument("--input",  "-i", type=Path, required=True,
                        help="Directory containing the CSV/JSON files from exp1_sdiv.py.")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output directory for PNG/CSV files (default: same as --input).")
    parser.add_argument("--dpi",    type=int, default=150,
                        help="PNG resolution in DPI (default: 150; use 300 for print).")
    args = parser.parse_args()

    inp = args.input
    out = args.output or inp
    out.mkdir(parents=True, exist_ok=True)

    for fname in ["exp1_pairwise_raw.csv", "exp1_textbook_scores.csv",
                  "exp1_group_scores.csv", "exp1_stats.json"]:
        if not (inp / fname).exists():
            print(f"ERROR: {inp / fname} not found.")
            sys.exit(1)

    pw    = pd.read_csv(inp / "exp1_pairwise_raw.csv")
    tb    = pd.read_csv(inp / "exp1_textbook_scores.csv")
    grp   = pd.read_csv(inp / "exp1_group_scores.csv")
    stats = json.loads((inp / "exp1_stats.json").read_text(encoding="utf-8"))

    print(f"\nGenerating Experiment 1 figures  (DPI = {args.dpi})\n{'─' * 45}")
    plot_1a(tb,  out, args.dpi)
    plot_1b(grp, stats, out, args.dpi)
    plot_1c(tb,  out, args.dpi)
    plot_1d(tb,  out, args.dpi)
    plot_1f(pw,  out, args.dpi)
    make_table_t1(tb, out)
    print(f"\nDone → {out}\n")


if __name__ == "__main__":
    main()