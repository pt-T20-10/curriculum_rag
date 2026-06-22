"""Shared, reproducible data and resume utilities for Experiment 2."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


EXPERIMENT_DIR = Path(__file__).resolve().parent
DATA_DIR = EXPERIMENT_DIR / "Data"
RESULTS_DIR = EXPERIMENT_DIR / "results"

TOPICS = [
    "antoanhedieuhanh",
    "laptrinhhuongdoituong",
    "ngonngulaptrinhcpp",
    "ngonngulaptrinhjava",
    "nhapmoncnpm",
    "nhapmonttnt",
]
SOURCE_ROOTS = {
    "AATG": DATA_DIR / "AATG",
    "PTIT": DATA_DIR / "PTIT",
    "DirectChat": DATA_DIR / "DirectChat",
}

OPENAI_JUDGE_NAME = "o3"
OPENAI_JUDGE_MODEL = "o3-2025-04-16"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_CORE_JUDGES = {
    "nemotron49b": "nvidia/llama-3.3-nemotron-super-49b-v1",
    "mistral_nem": "mistralai/mistral-nemotron",
    "llama70b": "meta/llama-3.3-70b-instruct",
    "qwen80b": "qwen/qwen3-next-80b-a3b-instruct",
}
NVIDIA_JUDGES = dict(NVIDIA_CORE_JUDGES)

MANIFEST_NAME = "dataset_manifest.json"
CHAPTER_SCORES_NAME = "exp2_chapter_scores.csv"
REQUIRED_RESUME_COLUMNS = {
    "judge_name", "judge_model", "dataset_fingerprint", "chapter_sha256",
    "book_id", "chapter_num", "run",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_chapter(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Chapter not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.DOTALL)
    text = text.strip()
    if not text:
        raise ValueError(f"Chapter is empty: {path}")
    return text


def load_books(source_root: Path, source_name: str) -> list[dict[str, Any]]:
    """Load exactly five chapters per configured topic using relocatable paths."""
    books: list[dict[str, Any]] = []
    for topic in TOPICS:
        metadata_path = source_root / topic / "core_chapters.json"
        if not metadata_path.is_file():
            raise FileNotFoundError(f"Missing metadata: {metadata_path}")
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        selected = data.get("selected", [])
        if len(selected) != 5:
            raise ValueError(f"Expected 5 chapters in {metadata_path}, got {len(selected)}")

        # Always prefer the directory next to metadata. This avoids stale
        # machine-specific absolute paths from older directory layouts.
        chapters_dir = metadata_path.parent / "chapters"
        if not chapters_dir.is_dir():
            legacy = Path(data.get("chapters_dir", ""))
            if not legacy.is_dir():
                raise FileNotFoundError(f"Missing chapters directory: {chapters_dir}")
            chapters_dir = legacy

        enriched = []
        for chapter in selected:
            path = chapters_dir / chapter["filename"]
            text = read_chapter(path)
            enriched.append({
                **chapter,
                "chapter_num": int(chapter["chapter_num"]),
                "path": path,
                "text": text,
                "sha256": sha256_text(text),
                "char_count_actual": len(text),
            })
        numbers = [chapter["chapter_num"] for chapter in enriched]
        if numbers != [1, 2, 3, 4, 5]:
            raise ValueError(f"Expected chapters 1..5 in {metadata_path}, got {numbers}")
        books.append({
            "source": source_name,
            "topic": topic,
            "book_id": f"{source_name}_{topic}",
            "metadata_path": metadata_path,
            "chapters_dir": chapters_dir,
            "selected": enriched,
        })
    return books


def load_all_books(sources: dict[str, Path]) -> list[dict[str, Any]]:
    books = []
    for source_name in ("AATG", "PTIT", "DirectChat"):
        if source_name in sources:
            books.extend(load_books(sources[source_name], source_name))
    expected = len(sources) * len(TOPICS)
    if len(books) != expected:
        raise ValueError(f"Expected {expected} books, loaded {len(books)}")
    return books


def build_dataset_manifest(books: list[dict[str, Any]]) -> dict[str, Any]:
    chapters = []
    for book in sorted(books, key=lambda item: item["book_id"]):
        for chapter in book["selected"]:
            chapters.append({
                "book_id": book["book_id"],
                "source": book["source"],
                "topic": book["topic"],
                "chapter_num": chapter["chapter_num"],
                "chapter_file": chapter["filename"],
                "chapter_sha256": chapter["sha256"],
                "characters": chapter["char_count_actual"],
            })
    canonical = json.dumps(chapters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 2,
        "dataset_fingerprint": sha256_text(canonical),
        "n_books": len(books),
        "n_chapters": len(chapters),
        "chapters": chapters,
    }


def prepare_output(
    output_dir: Path,
    manifest: dict[str, Any],
    judge_name: str,
    judge_model: str,
    resume: bool,
) -> str:
    """Write/validate manifest and refuse unsafe overwrite or resume."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / MANIFEST_NAME
    score_path = output_dir / CHAPTER_SCORES_NAME
    payload = {
        **manifest,
        "judge_name": judge_name,
        "judge_model": judge_model,
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for key in ("dataset_fingerprint", "judge_name", "judge_model"):
            if existing.get(key) != payload.get(key):
                raise RuntimeError(
                    f"Output manifest mismatch for {key}: "
                    f"existing={existing.get(key)!r}, current={payload.get(key)!r}. "
                    "Use a new output folder."
                )
    elif resume and score_path.exists():
        raise RuntimeError("Cannot safely resume legacy results without dataset_manifest.json")

    if score_path.exists() and not resume:
        raise RuntimeError(f"{score_path} already exists; use --resume or a new output folder")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest["dataset_fingerprint"]


def resume_rows(
    csv_path: Path,
    resume: bool,
    fingerprint: str,
    judge_name: str,
    judge_model: str,
) -> tuple[list[dict[str, Any]], set[tuple[Any, ...]]]:
    if not resume or not csv_path.exists():
        return [], set()
    import pandas as pd
    frame = pd.read_csv(csv_path)
    missing = REQUIRED_RESUME_COLUMNS - set(frame.columns)
    if missing:
        raise RuntimeError(f"Unsafe legacy resume; CSV lacks columns: {sorted(missing)}")
    checks = {
        "dataset_fingerprint": fingerprint,
        "judge_name": judge_name,
        "judge_model": judge_model,
    }
    for column, expected in checks.items():
        actual = set(frame[column].dropna().astype(str))
        if actual != {str(expected)}:
            raise RuntimeError(f"Resume mismatch in {column}: {sorted(actual)} != {expected}")
    rows = frame.to_dict("records")
    keys = {
        (r["judge_model"], r["book_id"], int(r["chapter_num"]), int(r["run"]), r["chapter_sha256"])
        for r in rows
    }
    if len(keys) != len(rows):
        raise RuntimeError("Duplicate evaluation keys found in existing chapter scores")
    return rows, keys #type: ignore


def evaluation_key(judge_model: str, book_id: str, chapter: dict, run: int) -> tuple[Any, ...]:
    return judge_model, book_id, int(chapter["chapter_num"]), int(run), chapter["sha256"]


def estimate_tokens(text: str, model: str) -> tuple[int, str]:
    """Count with tiktoken when available; otherwise use a conservative fallback."""
    try:
        import tiktoken
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text)), encoding.name
    except ImportError:
        # Vietnamese prose is commonly 2–3 characters/token.  Dividing by 2 is
        # deliberately conservative and is reported as an estimate.
        return math.ceil(len(text) / 2), "conservative-char-estimate"


def check_prompt_size(prompt: str, model: str, max_input_tokens: int, label: str) -> tuple[int, str]:
    tokens, method = estimate_tokens(prompt, model)
    if tokens > max_input_tokens:
        raise ValueError(
            f"Full prompt for {label} requires {tokens:,} input tokens ({method}), "
            f"above --max-input-tokens={max_input_tokens:,}. No text was truncated."
        )
    return tokens, method


def coverage_report(
    rows: list[dict[str, Any]],
    books: list[dict[str, Any]],
    judge_model: str,
    n_runs: int,
) -> dict[str, Any]:
    expected = {
        evaluation_key(judge_model, book["book_id"], chapter, run)
        for book in books for chapter in book["selected"] for run in range(1, n_runs + 1)
    }
    actual = {
        (r["judge_model"], r["book_id"], int(r["chapter_num"]), int(r["run"]), r["chapter_sha256"])
        for r in rows
    }
    missing = sorted(expected - actual, key=str)
    extra = sorted(actual - expected, key=str)
    return {
        "expected_rows": len(expected),
        "actual_rows": len(rows),
        "unique_rows": len(actual),
        "complete": not missing and not extra and len(rows) == len(actual),
        "missing": [list(key) for key in missing],
        "extra": [list(key) for key in extra],
    }
