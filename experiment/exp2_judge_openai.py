"""
exp2_judge_openai.py
================
Experiment 2 — Pedagogical Quality Assessment (LLM-as-Judge)

Evaluates textbook chapters using OpenAI o3 as judge across 4 criteria
derived from the HK Education Bureau Guiding Principles for Quality
Textbooks (Revised June 2016).

Criteria (unweighted, scored 1–5 each):
  C   — Content Quality         (C-2, C-3, C-4, C-7)
  LT  — Learning and Teaching   (L/T-2, L/T-5, L/T-9)
  SO  — Structure & Organisation (S/O-1, S/O-2, S/O-3)
  LA  — Language Quality        (L-1, L-2, L-5, L-6)

Context approach (Approach A):
  When judging chapter N, the judge also receives a brief summary
  (heading + first 1,500 chars) of each preceding chapter, enabling
  assessment of inter-chapter continuity (C-7, S/O-1).

Suggested pilot: AATG source only (6 textbooks × 5 chapters × 1 run = 30 calls).
Use --source to restrict by source; omit to run all three sources.

Usage:
  Set OPENAI_API_KEY, then run from experiment/:
  python exp2_judge_openai.py --preflight-only
  python exp2_judge_openai.py --output results/exp2_o3 --runs 3
  python exp2_judge_openai.py --output results/exp2_o3 --runs 3 --resume

Outputs:
  exp2_chapter_scores.csv    per chapter × run
  exp2_textbook_scores.csv   per textbook (mean over chapters and runs)
  exp2_group_scores.csv      per source group
  exp2_stats.json            Mann-Whitney U + bootstrap CI + Cohen's d
  exp2_cost_report.txt       actual token usage and USD cost
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from exp2_common import (
    CHAPTER_SCORES_NAME,
    OPENAI_JUDGE_MODEL,
    RESULTS_DIR,
    SOURCE_ROOTS,
    build_dataset_manifest,
    check_prompt_size,
    coverage_report,
    evaluation_key,
    load_all_books,
    load_books as common_load_books,
    prepare_output,
    resume_rows,
    sha256_text,
)

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pip install openai")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── constants ───────────────────────────────────────────────────────────────
JUDGE_MODEL       = OPENAI_JUDGE_MODEL
MAX_WORKERS       = 3
DEFAULT_RUNS      = 3
PRIOR_SUMMARY_CHARS = 1_500
DEFAULT_MAX_INPUT_TOKENS = 100_000
INTER_CALL_SLEEP = 2.0

# Approximate o3 pricing (USD per 1M tokens) — update if pricing changes
O3_INPUT_PRICE_PER_M  = 10.0
O3_OUTPUT_PRICE_PER_M = 40.0

# Tier 1 o3 rate limits
TPM_LIMIT     = 0        # disabled by default; set --tpm-limit to your account limit
TOKEN_WINDOW  = 62       # seconds — slightly > 60 for safety margin

# ─── Token rate limiter ───────────────────────────────────────────────────────

import threading as _threading

class TokenRateLimiter:
    """
    Sliding-window TPM rate limiter shared across all worker threads.

    Before each API call, workers call acquire(estimated_tokens).
    If the 60-second window is full, the call blocks until budget frees up.
    This prevents 429 errors caused by concurrent workers bursting tokens.
    """
    def __init__(self, tpm_limit: int = TPM_LIMIT, window: float = TOKEN_WINDOW):
        self.tpm_limit = tpm_limit
        self.window    = window
        self._calls: list[tuple[float, int]] = []   # (timestamp, tokens)
        self._lock  = _threading.Lock()

    def acquire(self, estimated_tokens: int) -> None:
        """Block until there is token budget for estimated_tokens."""
        if self.tpm_limit <= 0:
            return
        if estimated_tokens > self.tpm_limit:
            logger.warning(
                "Single request estimate %d exceeds local TPM limit %d; "
                "letting the API enforce the account limit.",
                estimated_tokens, self.tpm_limit,
            )
            return
        while True:
            with self._lock:
                now = time.time()
                # Evict calls outside the sliding window
                self._calls = [
                    (t, tok) for t, tok in self._calls
                    if now - t < self.window
                ]
                used = sum(tok for _, tok in self._calls)
                if used + estimated_tokens <= self.tpm_limit:
                    self._calls.append((now, estimated_tokens))
                    return
                # Oldest call will expire at:
                oldest = self._calls[0][0] if self._calls else now
                wait   = max(0.5, self.window - (now - oldest))
            logger.debug("TPM budget full (%d/%d) — waiting %.1fs",
                         used, self.tpm_limit, wait)
            time.sleep(min(wait, 5.0))   # sleep in chunks for responsiveness

_rate_limiter = TokenRateLimiter()

TOPICS = [
    "antoanhedieuhanh",
    "laptrinhhuongdoituong",
    "ngonngulaptrinhcpp",
    "ngonngulaptrinhjava",
    "nhapmoncnpm",
    "nhapmonttnt",
]

# ─── loading ─────────────────────────────────────────────────────────────────

def load_books(source_root: Path, source_name: str) -> list[dict]:
    books = common_load_books(source_root, source_name)
    logger.info("Loaded %d books for source=%s", len(books), source_name)
    return books


def read_chapter(chapters_dir: Path, filename: str) -> str:
    path = chapters_dir / filename
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.DOTALL)
    return text.strip()


def extract_summary(text: str, max_chars: int = PRIOR_SUMMARY_CHARS) -> str:
    """Take first max_chars of chapter as prior-chapter summary."""
    return text[:max_chars].strip()


# ─── judge prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert academic textbook reviewer evaluating university-level \
computer science and technology textbooks written in Vietnamese.
Your task is to score a single chapter on 4 pedagogical quality criteria.
Output ONLY valid JSON — no preamble, no explanation outside the JSON object.\
"""

def build_judge_prompt(
    prior_summaries: list[dict],
    chapter_heading: str,
    chapter_text:    str,
) -> str:
    """
    Build the user-turn prompt for the judge.

    Args:
        prior_summaries: list of {chapter_num, heading, summary} for preceding chapters
        chapter_heading: heading of the chapter being evaluated
        chapter_text:    full text of the chapter (never truncated)
    """
    # ── Prior chapter context (Approach A) ────────────────────────────────────
    if prior_summaries:
        prior_block = "## Prior Chapters in This Textbook (context for continuity assessment)\n"
        for ps in prior_summaries:
            prior_block += (
                f"\n### Chapter {ps['chapter_num']}: {ps['heading']}\n"
                f"*(Summary — first ~1,500 characters)*\n"
                f"{ps['summary']}\n"
            )
        prior_block += "\n---\n"
    else:
        prior_block = (
            "## Prior Chapters\n"
            "This is the first chapter — no prior chapter context available.\n\n---\n"
        )

    # ── Chapter content ───────────────────────────────────────────────────────
    return f"""\
{prior_block}
## Chapter Being Evaluated
**Heading:** {chapter_heading}

**Content:**
{chapter_text}

---

## Scoring Instructions
Score each criterion from **1 to 5** (integers only):
1 = Poor  |  2 = Below Average  |  3 = Average  |  4 = Good  |  5 = Excellent

### Criterion 1 — Content Quality (C)
Evaluate based on:
- Accuracy and precision of concepts and information presented
- New concepts are explicitly built upon previously introduced ones (scaffolding)
- **Continuity with prior chapters**: this chapter clearly extends content from
  preceding chapters; related topics are connected and unnecessary repetition
  is avoided (HK Guiding Principle C-7)
- Adequate, relevant examples that connect abstract concepts to real applications
- Appropriate depth and breadth for university-level study

### Criterion 2 — Learning and Teaching (LT)
Evaluate based on:
- Higher-order thinking (analysis, evaluation, synthesis) is incorporated,
  not just factual recall or memorisation
- The **CORE framework** is applied: content Connects to prior knowledge,
  Organises new material logically, prompts Reflection, and Extends to
  real-world or novel contexts (HK Guiding Principle L/T-5)
- Learning activities, exercises, or worked examples actively engage the reader
- Opportunities for reflection or self-assessment are present

### Criterion 3 — Structure and Organisation (SO)
Evaluate based on:
- The content sequence within this chapter is **logical and progressive**:
  foundational concepts precede advanced ones (HK Guiding Principle S/O-1)
- The chapter's **position in the textbook is coherent**: it builds naturally
  on what came before (as seen in prior chapter summaries above) and prepares
  the reader for subsequent topics
- Chapter title, headings, and subheadings clearly reveal the internal structure
- Key terms are identified and highlighted at first use

### Criterion 4 — Language Quality (LA)
Evaluate based on:
- The Vietnamese academic prose is accurate, precise, and grammatically correct
- The text is coherent and supports independent reading without external aids
- Technical vocabulary is introduced in context with adequate explanation
- Language facilitates comprehension at university undergraduate level

---

## Required Output Format
Return **exactly** this JSON object — no other text:
{{
  "C":  <integer 1-5>,
  "LT": <integer 1-5>,
  "SO": <integer 1-5>,
  "LA": <integer 1-5>,
  "reasoning": {{
    "C":  "<one concise sentence justifying the C score>",
    "LT": "<one concise sentence justifying the LT score>",
    "SO": "<one concise sentence justifying the SO score>",
    "LA": "<one concise sentence justifying the LA score>"
  }}
}}
"""


# ─── judge call ──────────────────────────────────────────────────────────────

def call_judge(
    prompt:  str,
    client:  OpenAI,
    book_id: str,
    ch_num:  int,
    run:     int,
    estimated_input_tokens: int,
    retries: int = 3,
) -> Optional[dict]:
    """
    Call o3 judge once. Returns parsed dict or None on failure.
    Acquires token budget from the shared rate limiter before each attempt.
    """
    estimated_tokens = estimated_input_tokens + 800

    for attempt in range(1, retries + 1):
        # Acquire token budget — blocks if window is full
        _rate_limiter.acquire(estimated_tokens)

        try:
            resp = client.chat.completions.create(
                model    = JUDGE_MODEL,
                messages = [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_completion_tokens = 800,
            )
            raw_text = resp.choices[0].message.content.strip() # pyright: ignore[reportOptionalMemberAccess]
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$",           "", raw_text)

            parsed = json.loads(raw_text)
            for key in ("C", "LT", "SO", "LA"):
                value = parsed.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"Invalid {key} score type: {value!r}")
                if float(value) != int(value) or not 1 <= int(value) <= 5:
                    raise ValueError(f"Invalid {key} score outside integer 1..5: {value!r}")

            # Update rate limiter with actual tokens used
            actual = resp.usage.prompt_tokens + resp.usage.completion_tokens # pyright: ignore[reportOptionalMemberAccess]
            _rate_limiter.acquire(max(0, actual - estimated_tokens))

            return {
                "scores":        {k: int(parsed[k]) for k in ("C", "LT", "SO", "LA")},
                "reasoning":     parsed.get("reasoning", {}),
                "input_tokens":  resp.usage.prompt_tokens, # pyright: ignore[reportOptionalMemberAccess]
                "output_tokens": resp.usage.completion_tokens,  # pyright: ignore[reportOptionalMemberAccess]
            }

        except Exception as e:
            logger.warning("[%s ch%02d run%d] Attempt %d failed: %s",
                           book_id, ch_num, run, attempt, e)
            if attempt < retries:
                time.sleep(5 * attempt)   # back off before retry

    logger.error("[%s ch%02d run%d] All %d attempts failed — skipping",
                 book_id, ch_num, run, retries)
    return None


# ─── per-book evaluation ──────────────────────────────────────────────────────

def _prompt_for_chapter(book: dict, chapter_index: int) -> str:
    chapters = book["selected"]
    chapter = chapters[chapter_index]
    prior_summaries = [
        {
            "chapter_num": previous["chapter_num"],
            "heading": previous["heading"],
            "summary": extract_summary(previous["text"]),
        }
        for previous in chapters[:chapter_index]
    ]
    return build_judge_prompt(prior_summaries, chapter["heading"], chapter["text"])


def preflight_prompts(books: list[dict], max_input_tokens: int) -> dict[tuple[str, int], int]:
    """Validate every full prompt before the first paid API request."""
    sizes: dict[tuple[str, int], int] = {}
    methods = set()
    for book in books:
        for index, chapter in enumerate(book["selected"]):
            prompt = _prompt_for_chapter(book, index)
            tokens, method = check_prompt_size(
                prompt, JUDGE_MODEL, max_input_tokens,
                f"{book['book_id']} ch{chapter['chapter_num']:02d}",
            )
            sizes[(book["book_id"], chapter["chapter_num"])] = tokens
            methods.add(method)
    logger.info(
        "Prompt preflight passed: %d prompts, max=%d tokens, method=%s",
        len(sizes), max(sizes.values()), ",".join(sorted(methods)),
    )
    return sizes


def evaluate_book(book: dict, client: OpenAI, judge_model: str,
                  dataset_fingerprint: str, prompt_sizes: dict,
                  n_runs: int, done_keys: set = None,
                  inter_sleep: float = INTER_CALL_SLEEP) -> list[dict]:
    """
    Evaluate all chapters of one textbook, n_runs times each.
    Returns list of row dicts for exp2_chapter_scores.csv.
    """
    rows       = []
    chapters   = book["selected"]

    # Evaluate each chapter
    for ch_idx, ch in enumerate(chapters):
        ch_num   = ch["chapter_num"]
        heading  = ch["heading"]
        prompt = _prompt_for_chapter(book, ch_idx)
        prompt_sha256 = sha256_text(prompt)
        estimated_input_tokens = prompt_sizes[(book["book_id"], ch_num)]

        # Run n_runs times sequentially for this chapter
        # (parallelism is at the book level, not chapter level)
        for run in range(1, n_runs + 1):
            # Skip if already computed in a previous run
            key = evaluation_key(judge_model, book["book_id"], ch, run)
            if done_keys and key in done_keys:
                logger.debug("Skip (already done): %s ch%02d run%d",
                             book["book_id"], ch_num, run)
                continue
            logger.info("[%s] ch%02d run %d/%d ...",
                        book["book_id"], ch_num, run, n_runs)
            result = call_judge(
                prompt, client, book["book_id"], ch_num, run,
                estimated_input_tokens,
            )

            if result is None:
                continue

            s = result["scores"]
            rows.append({
                "judge_name":    "o3",
                "judge_model":   judge_model,
                "dataset_fingerprint": dataset_fingerprint,
                "chapter_sha256": ch["sha256"],
                "prompt_sha256": prompt_sha256,
                "chapter_characters": ch["char_count_actual"],
                "estimated_input_tokens": estimated_input_tokens,
                "book_id":       book["book_id"],
                "source":        book["source"],
                "topic":         book["topic"],
                "chapter_num":   ch_num,
                "chapter_file":  ch["filename"],
                "run":           run,
                "C":             s["C"],
                "LT":            s["LT"],
                "SO":            s["SO"],
                "LA":            s["LA"],
                "mean_score":    round(np.mean([s["C"], s["LT"], s["SO"], s["LA"]]), 4),
                "reasoning_C":   result["reasoning"].get("C", ""),
                "reasoning_LT":  result["reasoning"].get("LT", ""),
                "reasoning_SO":  result["reasoning"].get("SO", ""),
                "reasoning_LA":  result["reasoning"].get("LA", ""),
                "input_tokens":  result["input_tokens"],
                "output_tokens": result["output_tokens"],
            })
            time.sleep(inter_sleep)

    return rows


# ─── aggregation ─────────────────────────────────────────────────────────────

def agg_textbook(rows: list[dict], book_id: str) -> dict:
    """Mean scores per textbook across all chapters and runs."""
    df  = pd.DataFrame(rows)
    sub = df[df["book_id"] == book_id]
    if sub.empty:
        return {}
    row0 = sub.iloc[0]
    return {
        "book_id":    book_id,
        "source":     row0["source"],
        "topic":      row0["topic"],
        "n_chapters": sub["chapter_num"].nunique(),
        "n_runs":     sub["run"].max(),
        "C_mean":     round(sub["C"].mean(),    4),
        "LT_mean":    round(sub["LT"].mean(),   4),
        "SO_mean":    round(sub["SO"].mean(),   4),
        "LA_mean":    round(sub["LA"].mean(),   4),
        "mean_score": round(sub["mean_score"].mean(), 4),
        "std_score":  round(sub["mean_score"].std(),  4),
    }


def agg_group(tb_rows: list[dict], source: str) -> dict:
    scores = [r["mean_score"] for r in tb_rows if r["source"] == source]
    if not scores:
        return {}
    arr = np.array(scores)
    return {
        "source":    source,
        "n_books":   len(scores),
        "mean":      round(float(np.mean(arr)), 4),
        "std":       round(float(np.std(arr)),  4),
        "min":       round(float(np.min(arr)),  4),
        "max":       round(float(np.max(arr)),  4),
    }


# ─── statistics ──────────────────────────────────────────────────────────────

def bootstrap_ci(scores, n_iter=2000, alpha=0.05):
    arr   = np.array(scores)
    means = [np.mean(np.random.choice(arr, size=len(arr), replace=True))
             for _ in range(n_iter)]
    return (
        round(float(np.percentile(means, 100 * alpha / 2)),       4),
        round(float(np.percentile(means, 100 * (1 - alpha / 2))), 4),
    )


def cohens_d(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    pooled = np.sqrt(
        ((na-1)*np.var(a, ddof=1) + (nb-1)*np.var(b, ddof=1)) / (na+nb-2)
    )
    return 0.0 if pooled == 0 else float((np.mean(a) - np.mean(b)) / pooled)


def run_stats(tb_rows: list[dict]) -> dict:
    sources = list({r["source"] for r in tb_rows})
    by      = {s: [r["mean_score"] for r in tb_rows if r["source"] == s]
               for s in sources}

    comps = {}
    pairs = [("AATG", "PTIT",       "aatg_vs_ptit"),
             ("AATG", "DirectChat", "aatg_vs_dc"),
             ("PTIT", "DirectChat", "ptit_vs_dc")]

    for a_src, b_src, key in pairs:
        if a_src not in by or b_src not in by:
            continue
        a, b = by[a_src], by[b_src]
        if len(a) < 2 or len(b) < 2:
            continue
        U, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
        d    = cohens_d(a, b)
        comps[key] = {
            "source_a": a_src, "source_b": b_src,
            "mean_a":   round(float(np.mean(a)), 4),
            "mean_b":   round(float(np.mean(b)), 4),
            "diff":     round(float(np.mean(a) - np.mean(b)), 4),
            "U":        float(U),
            "p_value":  round(float(p), 6),
            "significant": bool(p < 0.05),
            "cohens_d": round(d, 4),
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
        ci[src] = {"mean": round(float(np.mean(scores)), 4),
                   "ci_low": lo, "ci_high": hi}

    return {
        "comparisons":  comps,
        "bootstrap_ci": ci,
        "n_per_group":  {s: len(v) for s, v in by.items()},
        "test":         "Mann-Whitney U (two-sided), bootstrap CI 95% n=2000",
    }






def run_experiment(
    sources:    dict[str, Path],
    output_dir: Path,
    openai_key: str,
    n_runs:     int  = DEFAULT_RUNS,
    max_workers: int = MAX_WORKERS,
    resume:     bool = False,
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    tpm_limit: int = TPM_LIMIT,
    inter_sleep: float = INTER_CALL_SLEEP,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / CHAPTER_SCORES_NAME

    all_books = load_all_books(sources)
    manifest = build_dataset_manifest(all_books)
    fingerprint = prepare_output(
        output_dir, manifest, "o3", JUDGE_MODEL, resume,
    )
    prompt_sizes = preflight_prompts(all_books, max_input_tokens)
    _rate_limiter.tpm_limit = tpm_limit
    client = OpenAI(api_key=openai_key)

    # ── Resume: load existing results ────────────────────────────────────────
    existing_rows, done_keys = resume_rows(
        csv_path, resume, fingerprint, "o3", JUDGE_MODEL,
    )
    if existing_rows:
        logger.info("Resume: %d existing rows", len(existing_rows))

    total_calls = sum(len(book["selected"]) for book in all_books) * n_runs
    remaining   = total_calls - len(done_keys)
    print(f"\n{'='*60}")
    print(f"  Experiment 2 — Pedagogical Quality Assessment")
    print(f"  Books: {len(all_books)}  |  Runs: {n_runs}  |  Total calls: {total_calls}")
    print(f"  Already done: {len(done_keys)}  |  Remaining: {remaining}")
    print(f"{'='*60}\n")

    new_rows: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                evaluate_book, book, client, JUDGE_MODEL, fingerprint,
                prompt_sizes, n_runs, done_keys, inter_sleep,
            ): book
            for book in all_books
        }
        done = 0
        for future in as_completed(futures):
            book = futures[future]
            try:
                rows = future.result()
                new_rows.extend(rows)
                done += 1
                logger.info("[%d/%d] Completed: %s  (%d new rows)",
                            done, len(all_books), book["book_id"], len(rows))
                combined = existing_rows + new_rows
                pd.DataFrame(combined).to_csv(csv_path, index=False)
            except Exception as e:
                logger.error("Book %s failed: %s", book["book_id"], e)

    all_rows = existing_rows + new_rows
    if not all_rows:
        print("No results collected.")
        return

    # ── Aggregate ─────────────────────────────────────────────────────────────
    book_ids      = list({r["book_id"] for r in all_rows})
    tb_rows       = [r for r in [agg_textbook(all_rows, bid) for bid in book_ids] if r]
    sources_found = list({r["source"] for r in tb_rows})
    grp_rows      = [r for r in [agg_group(tb_rows, s) for s in sources_found] if r]
    stats_out     = run_stats(tb_rows) if len(sources_found) > 1 else {}

    # ── Export ────────────────────────────────────────────────────────────────
    pd.DataFrame(all_rows).to_csv(csv_path, index=False)
    pd.DataFrame(tb_rows ).to_csv(output_dir / "exp2_textbook_scores.csv", index=False)
    pd.DataFrame(grp_rows).to_csv(output_dir / "exp2_group_scores.csv",    index=False)
    if stats_out:
        (output_dir / "exp2_stats.json").write_text(
            json.dumps(stats_out, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    coverage = coverage_report(all_rows, all_books, JUDGE_MODEL, n_runs)
    (output_dir / "coverage_report.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    input_tokens = sum(int(row.get("input_tokens", 0)) for row in all_rows)
    output_tokens = sum(int(row.get("output_tokens", 0)) for row in all_rows)
    estimated_cost = (
        input_tokens / 1_000_000 * O3_INPUT_PRICE_PER_M
        + output_tokens / 1_000_000 * O3_OUTPUT_PRICE_PER_M
    )
    (output_dir / "exp2_cost_report.txt").write_text(
        "\n".join([
            f"model: {JUDGE_MODEL}",
            f"dataset_fingerprint: {fingerprint}",
            f"input_tokens: {input_tokens}",
            f"output_tokens: {output_tokens}",
            f"estimated_cost_usd: {estimated_cost:.4f}",
            "pricing_note: estimate using constants in exp2_judge_openai.py; verify current pricing",
        ]) + "\n",
        encoding="utf-8",
    )

    print(f"\n{'='*60}\n  RESULTS SUMMARY\n{'='*60}")
    print(f"  {'Source':<14} {'Books':>5} {'Mean':>8} {'Std':>7}")
    print(f"  {'-'*38}")
    for row in grp_rows:
        print(f"  {row['source']:<14} {row['n_books']:>5} "
              f"{row['mean']:>8.4f} {row['std']:>7.4f}")
    print(f"  Coverage: {coverage['actual_rows']}/{coverage['expected_rows']} "
          f"({'complete' if coverage['complete'] else 'INCOMPLETE'})")
    print(f"\n  Results → {output_dir}\n")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Experiment 2 — LLM-as-Judge pedagogical quality assessment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--aatg-root",  type=Path, default=SOURCE_ROOTS["AATG"])
    p.add_argument("--ptit-root",  type=Path, default=SOURCE_ROOTS["PTIT"])
    p.add_argument("--dc-root",    type=Path, default=SOURCE_ROOTS["DirectChat"])
    p.add_argument("--output",     type=Path, default=RESULTS_DIR / "exp2_o3")
    p.add_argument("--openai-key", type=str, default=None,
                   help="Prefer OPENAI_API_KEY; CLI value may remain in shell history.")
    p.add_argument("--source",     type=str,  default=None,
                   choices=["AATG", "PTIT", "DirectChat"],
                   help="Run only one source (default: all provided roots).")
    p.add_argument("--runs",       type=int,  default=DEFAULT_RUNS,
                   help=f"Judge runs per chapter (default: {DEFAULT_RUNS}).")
    p.add_argument("--workers",    type=int,  default=MAX_WORKERS,
                   help=f"Parallel workers (default: {MAX_WORKERS}).")
    p.add_argument("--resume", action="store_true",
                   help="Load existing exp2_chapter_scores.csv and skip done evaluations.")
    p.add_argument("--max-input-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS,
                   help="Fail before API calls if any full prompt exceeds this limit.")
    p.add_argument("--tpm-limit", type=int,
                   default=int(os.getenv("OPENAI_TPM_LIMIT", str(TPM_LIMIT))),
                   help="Optional local TPM throttle; 0 disables it (default).")
    p.add_argument("--sleep", type=float, default=INTER_CALL_SLEEP,
                   help=f"Seconds between calls in each worker (default: {INTER_CALL_SLEEP}).")
    p.add_argument("--preflight-only", action="store_true",
                   help="Validate 18 books, hashes and full prompt sizes without API calls.")
    args = p.parse_args()

    # Build sources dict based on args
    source_map = {"AATG": args.aatg_root, "PTIT": args.ptit_root,
                  "DirectChat": args.dc_root}

    if args.source:
        # Single source mode
        root = source_map[args.source]
        if root is None or not root.exists():
            print(f"ERROR: root not found for --source {args.source}: {root}")
            sys.exit(1)
        sources = {args.source: root}
    else:
        missing = {name: root for name, root in source_map.items()
                   if root is None or not root.exists()}
        if missing:
            print(f"ERROR: Full run requires all three source roots; missing={missing}")
            sys.exit(1)
        sources = source_map

    if args.preflight_only:
        books = load_all_books(sources)
        manifest = build_dataset_manifest(books)
        sizes = preflight_prompts(books, args.max_input_tokens)
        print(f"Preflight OK: {manifest['n_books']} books, {manifest['n_chapters']} chapters")
        print(f"Dataset fingerprint: {manifest['dataset_fingerprint']}")
        print(f"Largest full prompt: {max(sizes.values()):,} estimated input tokens")
        return

    key = args.openai_key or os.getenv("OPENAI_API_KEY", "")
    if not key:
        print("ERROR: --openai-key or OPENAI_API_KEY required")
        sys.exit(1)

    run_experiment(
        sources     = sources,
        output_dir  = args.output,
        openai_key  = key,
        n_runs      = args.runs,
        max_workers = args.workers,
        resume      = args.resume,
        max_input_tokens = args.max_input_tokens,
        tpm_limit   = args.tpm_limit,
        inter_sleep = args.sleep,
    )


if __name__ == "__main__":
    main()
