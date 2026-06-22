"""
exp1_sdiv.py  —  Experiment 1: Semantic Diversity (Sdiv)
=========================================================
Computes inter-chapter semantic diversity for 18 textbooks
(6 topics × 3 sources, first 5 chapters each) and exports 4 output levels.

Sdiv(Ci, Cj) = 0.5*(1 − ROUGE-L(Ci,Cj)) + 0.5*(1 − cos(Ei,Ej))
Sdiv_book    = mean of C(5,2)=10 pairwise scores

Sources:
    PTIT        human academic textbooks
    AATG        proposed multi-agent CRAG system
    DirectChat  Gemini 3.1 Pro direct-generation baseline

Outputs:
    exp1_pairwise_raw.csv    180 rows  (18 books × 10 pairs)
    exp1_textbook_scores.csv  18 rows  (per textbook)
    exp1_group_scores.csv      3 rows  (per source group)
    exp1_stats.json           Mann-Whitney U + bootstrap CI + Cohen's d

Usage:
    python exp1_sdiv.py \\
        --openai-key "YOUR_OPENAI_API_KEY"

    # Re-run plots without re-embedding (uses cache):
    python exp1_sdiv.py ... (omit --no-cache)

    # Force re-embed:
    python exp1_sdiv.py ... --no-cache
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from rouge_score import rouge_scorer
from scipy import stats as scipy_stats

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
EXPERIMENT_DIR   = Path(__file__).resolve().parent
DATA_DIR         = EXPERIMENT_DIR / "Data"
DEFAULT_PTIT     = DATA_DIR / "PTIT"
DEFAULT_AATG     = DATA_DIR / "AATG"
DEFAULT_DC       = DATA_DIR / "DirectChat"
DEFAULT_OUTPUT   = EXPERIMENT_DIR / "results" / "exp1"
EMBED_MODEL      = "text-embedding-3-small"
MAX_CHARS_ROUGE  = 30_000
MAX_TOKENS_CHUNK = 7_500   # per chunk — well under 8,192 limit
CHARS_PER_CHUNK  = 16_000  # fallback estimate: ~6,000-7,500 tokens for Vietnamese

# Try to load tiktoken for precise token-based chunking.
# Falls back to char-based chunking if unavailable.
try:
    import tiktoken as _tiktoken
    _enc = _tiktoken.get_encoding("cl100k_base")
    logger.info("tiktoken loaded — using token-based chunking")
    _USE_TIKTOKEN = True
except Exception:
    logger.info("tiktoken not available — using char-based chunking (16K chars/chunk)")
    _enc = None
    _USE_TIKTOKEN = False


def _chunk_text(text: str) -> list[str]:
    """
    Split text into chunks that fit within MAX_TOKENS_CHUNK.

    Uses tiktoken for precise token counts when available,
    falls back to character-based splitting (16K chars ≈ 6K-7.5K tokens
    for Vietnamese text).

    Mean pooling over chunks ensures full chapter coverage without
    information loss from simple truncation.
    """
    if not text:
        return []

    if _USE_TIKTOKEN and _enc is not None:
        tokens = _enc.encode(text)
        if len(tokens) <= MAX_TOKENS_CHUNK:
            return [text]
        chunks = []
        for start in range(0, len(tokens), MAX_TOKENS_CHUNK):
            chunk_tokens = tokens[start : start + MAX_TOKENS_CHUNK]
            chunks.append(_enc.decode(chunk_tokens))
        return chunks
    else:
        # Character-based fallback
        if len(text) <= CHARS_PER_CHUNK:
            return [text]
        return [
            text[i : i + CHARS_PER_CHUNK]
            for i in range(0, len(text), CHARS_PER_CHUNK)
        ]

TOPICS = [
    "antoanhedieuhanh",
    # "hedieuhanh" excluded — only 4 chapters, insufficient for 5-chapter protocol
    "laptrinhhuongdoituong",
    "ngonngulaptrinhcpp",
    "ngonngulaptrinhjava",
    "nhapmoncnpm",
    "nhapmonttnt",
]

_rouge = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)


# ─── loading ─────────────────────────────────────────────────────────────────

def load_all_books(ptit_root, aatg_root, dc_root):
    books = []
    for source, root in [("PTIT", ptit_root), ("AATG", aatg_root), ("DirectChat", dc_root)]:
        for topic in TOPICS:
            jp = root / topic / "core_chapters.json"
            if not jp.exists():
                raise FileNotFoundError(f"Missing metadata: {jp}")
            data = json.loads(jp.read_text(encoding="utf-8"))
            selected = data.get("selected", [])
            if len(selected) != 5:
                raise ValueError(f"Expected 5 selected chapters in {jp}, got {len(selected)}")
            # Resolve relative to core_chapters.json. Older metadata may contain
            # stale absolute paths from older directory layouts.
            chapters_dir = jp.parent / "chapters"
            if not chapters_dir.is_dir():
                raise FileNotFoundError(f"Missing chapters directory: {chapters_dir}")
            for chapter in selected:
                chapter_path = chapters_dir / chapter["filename"]
                if not chapter_path.is_file() or chapter_path.stat().st_size == 0:
                    raise ValueError(f"Missing or empty chapter: {chapter_path}")
            books.append({
                "source":       source,
                "topic":        topic,
                "book_id":      f"{source}_{topic}",
                "chapters_dir": chapters_dir,
                "selected":     selected,
                "n_selected":   len(selected),
            })
    if len(books) != 18:
        raise ValueError(f"Expected 18 textbooks, loaded {len(books)}")
    logger.info("Loaded %d textbooks", len(books))
    return books


def read_chapter(chapters_dir, filename):
    path = chapters_dir / filename
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.DOTALL)
    return text.strip()


# ─── Vietnamese stop words ───────────────────────────────────────────────────
# Removing high-frequency function words before ROUGE-L makes the lexical
# diversity signal more content-driven and less affected by shared grammar.

_VI_STOPWORDS: set[str] = {
    # Pronouns / demonstratives
    "tôi", "chúng", "họ", "nó", "ta", "này", "đó", "kia", "đây", "ấy",
    "những", "các", "mỗi", "mọi", "một", "hai", "ba",
    # Conjunctions / connectives
    "và", "với", "hay", "hoặc", "nhưng", "tuy", "mà", "vì", "nên",
    "bởi", "do", "để", "dù", "dẫu", "song", "thì", "là", "như",
    "khi", "nếu", "vậy", "vẫn", "tức", "thế", "cũng", "chỉ",
    # Prepositions / particles
    "của", "cho", "từ", "trong", "trên", "dưới", "về", "theo",
    "qua", "bằng", "đến", "tới", "lên", "xuống", "ra", "vào",
    "sang", "lại", "tại", "ở", "trước", "sau", "giữa",
    # Auxiliaries / adverbs
    "được", "đã", "đang", "sẽ", "có", "không", "rất", "quá",
    "hơn", "nhất", "thêm", "bao", "rồi", "nữa", "luôn", "ngay",
    "phải", "cần", "hết", "cả",
    # Question / misc
    "gì", "nào", "sao", "thôi", "nhé", "ạ", "ơi",
    "tất", "đều", "chứ", "chẳng", "mới",
}

_SW_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_VI_STOPWORDS, key=len, reverse=True)) + r")\b",
    re.UNICODE,
)

def _strip_stopwords(text: str) -> str:
    """Remove Vietnamese stop words and collapse extra whitespace."""
    return re.sub(r"\s+", " ", _SW_RE.sub(" ", text.lower())).strip()


# ─── ROUGE-L ─────────────────────────────────────────────────────────────────

def rouge_l(a, b, strip_sw: bool = True):
    a, b = a[:MAX_CHARS_ROUGE], b[:MAX_CHARS_ROUGE]
    if not a or not b:
        return 0.0
    if strip_sw:
        a, b = _strip_stopwords(a), _strip_stopwords(b)
    return float(_rouge.score(a, b)["rougeL"].fmeasure)


# ─── embeddings ──────────────────────────────────────────────────────────────

def _embed_chapter(text: str, client: OpenAI) -> list[float]:
    """
    Embed one chapter text using chunk + mean pooling.

    The chapter is split into non-overlapping chunks of at most
    MAX_TOKENS_CHUNK tokens (or CHARS_PER_CHUNK chars as fallback).
    Each chunk is embedded independently, then the mean vector is
    returned — ensuring full document coverage with no information loss.
    """
    chunks = _chunk_text(text)
    if not chunks:
        return [0.0] * 1536

    # Embed all chunks in one API call
    BATCH = 20
    all_vecs = []
    for i in range(0, len(chunks), BATCH):
        resp = client.embeddings.create(
            model=EMBED_MODEL, input=chunks[i : i + BATCH]
        )
        all_vecs.extend([item.embedding for item in resp.data])

    if len(all_vecs) == 1:
        return all_vecs[0]
    # Mean pooling over all chunk embeddings
    return np.mean(np.array(all_vecs), axis=0).tolist()


def compute_embeddings(books, client, cache_path, no_cache=False):
    cache = {}
    if cache_path.exists() and not no_cache:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        logger.info("Loaded %d cached embeddings", len(cache))

    to_embed = []
    for book in books:
        for ch in book["selected"]:
            key = f"{book['source']}|{book['topic']}|{ch['filename']}"
            if key not in cache:
                text = read_chapter(book["chapters_dir"], ch["filename"])
                to_embed.append((key, text))

    if not to_embed:
        logger.info("All embeddings cached — skipping API")
        return cache

    logger.info("Embedding %d chapters via %s (chunk+mean pooling) ...",
                len(to_embed), EMBED_MODEL)

    for i, (key, text) in enumerate(to_embed):
        n_chunks = len(_chunk_text(text))
        label    = key.split("|")[-1]
        if n_chunks > 1:
            logger.info("  [%d/%d] %s → %d chunks", i+1, len(to_embed), label, n_chunks)
        else:
            logger.info("  [%d/%d] %s", i+1, len(to_embed), label)
        cache[key] = _embed_chapter(text, client)
        time.sleep(0.05)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    logger.info("Cache saved → %s", cache_path.name)
    return cache


def cos_dist(v1, v2):
    a, b  = np.array(v1, dtype=float), np.array(v2, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return 0.0 if denom == 0 else float(1.0 - np.dot(a, b) / denom)


# ─── Sdiv computation ────────────────────────────────────────────────────────

def compute_sdiv_book(book, embeddings, use_stopwords: bool = True):
    pairs = []
    for ch_a, ch_b in combinations(book["selected"], 2):
        ta = read_chapter(book["chapters_dir"], ch_a["filename"])
        tb = read_chapter(book["chapters_dir"], ch_b["filename"])
        rl = rouge_l(ta, tb, strip_sw=use_stopwords)

        ka  = f"{book['source']}|{book['topic']}|{ch_a['filename']}"
        kb  = f"{book['source']}|{book['topic']}|{ch_b['filename']}"
        cd  = cos_dist(embeddings.get(ka, []), embeddings.get(kb, []))
        sdv = 0.5 * (1.0 - rl) + 0.5 * cd

        pairs.append({
            "book_id":     book["book_id"],
            "source":      book["source"],
            "topic":       book["topic"],
            "ch_i":        ch_a["filename"],
            "ch_j":        ch_b["filename"],
            "rouge_l":     round(rl, 6),
            "cosine_dist": round(cd, 6),
            "sdiv":        round(sdv, 6),
        })
    return pairs


# ─── aggregation ─────────────────────────────────────────────────────────────

def agg_textbook(pairs, book):
    sdivs = [p["sdiv"] for p in pairs]
    return {
        "book_id":      book["book_id"],
        "source":       book["source"],
        "topic":        book["topic"],
        "n_chapters":   book["n_selected"],
        "n_pairs":      len(sdivs),
        "sdiv_mean":    round(float(np.mean(sdivs)), 6),
        "sdiv_std":     round(float(np.std(sdivs)),  6),
        "sdiv_min":     round(float(np.min(sdivs)),  6),
        "sdiv_max":     round(float(np.max(sdivs)),  6),
        "rouge_l_mean": round(float(np.mean([p["rouge_l"]     for p in pairs])), 6),
        "cosine_mean":  round(float(np.mean([p["cosine_dist"] for p in pairs])), 6),
    }


def agg_group(rows, source):
    scores = [r["sdiv_mean"] for r in rows if r["source"] == source]
    arr    = np.array(scores)
    return {
        "source":    source,
        "n_books":   len(scores),
        "sdiv_mean": round(float(np.mean(arr)), 6),
        "sdiv_std":  round(float(np.std(arr)),  6),
        "sdiv_min":  round(float(np.min(arr)),  6),
        "sdiv_max":  round(float(np.max(arr)),  6),
    }


# ─── statistics ──────────────────────────────────────────────────────────────

def bootstrap_ci(scores, n_iter=2000, alpha=0.05):
    arr   = np.array(scores)
    means = [np.mean(np.random.choice(arr, size=len(arr), replace=True))
             for _ in range(n_iter)]
    return (
        round(float(np.percentile(means, 100 * alpha / 2)),       6),
        round(float(np.percentile(means, 100 * (1 - alpha / 2))), 6),
    )


def cohens_d(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    pooled = np.sqrt(
        ((na-1)*np.var(a, ddof=1) + (nb-1)*np.var(b, ddof=1)) / (na+nb-2)
    )
    return 0.0 if pooled == 0 else float((np.mean(a) - np.mean(b)) / pooled)


def run_stats(rows):
    by = {src: [r["sdiv_mean"] for r in rows if r["source"] == src]
          for src in ["PTIT", "AATG", "DirectChat"]}

    comps = {}
    for a_src, b_src, key in [
        ("AATG", "PTIT",       "aatg_vs_ptit"),
        ("AATG", "DirectChat", "aatg_vs_dc"),
        ("PTIT", "DirectChat", "ptit_vs_dc"),
    ]:
        a, b  = by[a_src], by[b_src]
        U, p  = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
        d     = cohens_d(a, b)
        comps[key] = {
            "source_a":    a_src,
            "source_b":    b_src,
            "mean_a":      round(float(np.mean(a)), 6),
            "mean_b":      round(float(np.mean(b)), 6),
            "diff":        round(float(np.mean(a) - np.mean(b)), 6),
            "U_statistic": float(U),
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
        ci[src] = {"mean": round(float(np.mean(scores)), 6),
                   "ci_low": lo, "ci_high": hi}

    return {
        "comparisons":  comps,
        "bootstrap_ci": ci,
        "n_per_group":  {s: len(v) for s, v in by.items()},
        "test":         "Mann-Whitney U (two-sided), bootstrap CI 95% n=2000",
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Experiment 1 — Semantic Diversity (Sdiv).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phases (--phase):
  all        Run full pipeline end-to-end (default)
  embed      Compute/cache embeddings only
  compute    Pairwise Sdiv → exp1_pairwise_raw.csv
  aggregate  Aggregate → textbook + group CSVs + stats JSON
  stats      Stats only → update stats JSON + group CSV
        """,
    )
    p.add_argument("--ptit-root",     type=Path, default=DEFAULT_PTIT)
    p.add_argument("--aatg-root",     type=Path, default=DEFAULT_AATG)
    p.add_argument("--dc-root",       type=Path, default=DEFAULT_DC)
    p.add_argument("--output",        type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--openai-key",    type=str,  default=None)
    p.add_argument("--preflight-only", action="store_true",
                   help="Validate 18 books and 90 chapters without API calls.")
    p.add_argument("--no-cache",      action="store_true",
                   help="Force re-computation of all embeddings.")
    p.add_argument("--no-stopwords",  action="store_true",
                   help="Disable Vietnamese stop word removal before ROUGE-L.")
    p.add_argument("--phase", type=str, default="all",
                   choices=["all", "embed", "compute", "aggregate", "stats"])
    args = p.parse_args()

    if args.preflight_only:
        books = load_all_books(args.ptit_root, args.aatg_root, args.dc_root)
        chapter_count = sum(book["n_selected"] for book in books)
        print(f"Preflight OK: {len(books)} books, {chapter_count} chapters")
        return

    out    = args.output
    out.mkdir(parents=True, exist_ok=True)
    key    = args.openai_key or os.getenv("OPENAI_API_KEY", "")
    use_sw = not args.no_stopwords

    # ── stats only ────────────────────────────────────────────────────────────
    if args.phase == "stats":
        p1 = out / "exp1_textbook_scores.csv"
        if not p1.exists():
            print(f"ERROR: {p1} not found. Run --phase aggregate first.")
            sys.exit(1)
        tb_rows   = pd.read_csv(p1).to_dict("records")
        stats_out = run_stats(tb_rows)
        grp_rows  = [agg_group(tb_rows, s) for s in ["PTIT", "AATG", "DirectChat"]]
        for row in grp_rows:
            ci = stats_out["bootstrap_ci"][row["source"]]
            row["ci_low"], row["ci_high"] = ci["ci_low"], ci["ci_high"]
        (out / "exp1_stats.json").write_text(
            json.dumps(stats_out, ensure_ascii=False, indent=2), encoding="utf-8")
        pd.DataFrame(grp_rows).to_csv(out / "exp1_group_scores.csv", index=False)
        print("Stats updated.")
        return

    # ── aggregate only ────────────────────────────────────────────────────────
    if args.phase == "aggregate":
        p0 = out / "exp1_pairwise_raw.csv"
        if not p0.exists():
            print(f"ERROR: {p0} not found. Run --phase compute first.")
            sys.exit(1)
        pw      = pd.read_csv(p0)
        tb_rows = []
        for bid, grp_df in pw.groupby("book_id"):
            row  = grp_df.iloc[0]
            book = {"source": row["source"], "topic": row["topic"],
                    "book_id": bid, "n_selected": 5}
            tb_rows.append(agg_textbook(grp_df.to_dict("records"), book))
        grp_rows  = [agg_group(tb_rows, s) for s in ["PTIT", "AATG", "DirectChat"]]
        stats_out = run_stats(tb_rows)
        for row in grp_rows:
            ci = stats_out["bootstrap_ci"][row["source"]]
            row["ci_low"], row["ci_high"] = ci["ci_low"], ci["ci_high"]
        pd.DataFrame(tb_rows ).to_csv(out / "exp1_textbook_scores.csv", index=False)
        pd.DataFrame(grp_rows).to_csv(out / "exp1_group_scores.csv",    index=False)
        (out / "exp1_stats.json").write_text(
            json.dumps(stats_out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Aggregation complete.")
        return

    # ── phases requiring source roots ─────────────────────────────────────────
    for attr, name in [("ptit_root","--ptit-root"), ("aatg_root","--aatg-root"),
                       ("dc_root","--dc-root")]:
        val = getattr(args, attr, None)
        if val is None or not val.exists():
            print(f"ERROR: {name} required for --phase {args.phase}")
            sys.exit(1)
    if not key:
        print("ERROR: --openai-key or OPENAI_API_KEY required")
        sys.exit(1)

    books      = load_all_books(args.ptit_root, args.aatg_root, args.dc_root)
    client     = OpenAI(api_key=key)
    cache_path = out / "embedding_cache.json"
    embeddings = compute_embeddings(books, client, cache_path, args.no_cache)

    if args.phase == "embed":
        print(f"Embeddings cached → {cache_path}")
        return

    # ── compute (or all) ──────────────────────────────────────────────────────
    sw_msg = "with stop word removal" if use_sw else "without stop word removal"
    print(f"[3] Computing pairwise Sdiv ({sw_msg}) ...")
    all_pairs, tb_rows = [], []
    for i, book in enumerate(books, 1):
        print(f"  [{i:2d}/{len(books)}] {book['book_id']}")
        pairs = compute_sdiv_book(book, embeddings, use_stopwords=use_sw)
        all_pairs.extend(pairs)
        tb_rows.append(agg_textbook(pairs, book))

    pd.DataFrame(all_pairs).to_csv(out / "exp1_pairwise_raw.csv", index=False)
    print(f"  Pairwise saved → {out / 'exp1_pairwise_raw.csv'}")

    if args.phase == "compute":
        return

    # ── all — aggregate + stats + export ─────────────────────────────────────
    grp_rows  = [agg_group(tb_rows, s) for s in ["PTIT", "AATG", "DirectChat"]]
    stats_out = run_stats(tb_rows)
    for row in grp_rows:
        ci = stats_out["bootstrap_ci"][row["source"]]
        row["ci_low"], row["ci_high"] = ci["ci_low"], ci["ci_high"]

    pd.DataFrame(tb_rows ).to_csv(out / "exp1_textbook_scores.csv", index=False)
    pd.DataFrame(grp_rows).to_csv(out / "exp1_group_scores.csv",    index=False)
    (out / "exp1_stats.json").write_text(
        json.dumps(stats_out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*65}\n  RESULTS SUMMARY\n{'='*65}")
    print(f"  {'Source':<14} {'Mean':>8} {'Std':>7}  95% CI")
    print(f"  {'-'*55}")
    for row in grp_rows:
        print(f"  {row['source']:<14} {row['sdiv_mean']:>8.4f} "
              f"{row['sdiv_std']:>7.4f}  [{row['ci_low']:.4f}, {row['ci_high']:.4f}]")
    print(f"\n  Pairwise tests (Mann-Whitney U, two-sided):")
    for key_c, c in stats_out["comparisons"].items():
        sig = "**" if c["p_value"] < 0.01 else ("*" if c["p_value"] < 0.05 else "ns")
        print(f"  {c['source_a']} vs {c['source_b']:<14} "
              f"Δ={c['diff']:+.4f}  p={c['p_value']:.4f}{sig}  "
              f"d={c['cohens_d']:.3f}({c['effect_size']})")
    print(f"\n  Results → {out}\n")


if __name__ == "__main__":
    main()
