"""
select_core_chapters.py
=======================
Select core chapters from each textbook's chapters/ folder for Exp1 Sdiv.

Selection protocol (applied identically to PTIT, AATG, DirectChat):
  Take the first N consecutive chapters (ch01 → chN) in order.
  Default N = 5 (use --n 5).

  Textbooks with fewer than N chapters are skipped automatically.
  The topic 'hedieuhanh' (4 chapters only) is excluded from Exp1
  to ensure all books have the same chapter count for positional analysis.

Output:
  core_chapters.json  written alongside the chapters/ folder

Usage:
  # Single textbook
  python select_core_chapters.py --book path/to/antoanhedieuhanh/

  # All textbooks under a source root
  python select_core_chapters.py --root Data/PTIT/
  python select_core_chapters.py --root Data/DirectChat/
  python select_core_chapters.py --root Data/AATG/
"""

import argparse
import json
import re
import sys
from pathlib import Path


# Topics excluded from Exp1 (insufficient chapters for 5-chapter protocol)
_EXCLUDED_TOPICS = {"hedieuhanh"}

# Minimum character count to consider a chapter non-trivial
_MIN_CHARS = 1_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_char_count(md_path: Path) -> int:
    """
    Read char count from the metadata comment injected by split_chapters.py.

    Comment format:
        <!-- source: ... | chapter: N | chars: 12,345 -->

    Falls back to len(text) if comment is absent.
    """
    text = md_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"chars:\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return len(text)


def _read_first_heading(md_path: Path) -> str:
    """Return the first non-comment # heading line (lowercase, stripped)."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("<!--"):
            continue
        # Strip bold markers from DirectChat headings
        line = re.sub(r"\*\*", "", line)
        if line.startswith("#"):
            return line.lstrip("#").strip().lower()
    return ""


# def _is_skip_candidate(heading: str) -> bool:
#     """True if the heading suggests a non-core chapter."""
#     return any(kw in heading for kw in _SKIP_KEYWORDS)


def _chapter_num(md_path: Path) -> int:
    """Extract chapter number from filename (ch01.md → 1)."""
    m = re.search(r"ch(\d+)", md_path.stem)
    return int(m.group(1)) if m else 999


# ---------------------------------------------------------------------------
# Core selection
# ---------------------------------------------------------------------------

def select_core_chapters(
    book_dir: Path,
    n_select: int = 5,
) -> dict:
    """
    Select the first n_select consecutive chapters (ch01 → chN).

    Args:
        book_dir:  Directory that contains (or IS) the chapters/ subfolder.
        n_select:  Number of chapters to select (default 5).

    Returns:
        Dict written to core_chapters.json, or {} if insufficient chapters.
    """
    # Skip excluded topics
    if book_dir.name in _EXCLUDED_TOPICS:
        print(f"  SKIPPED — topic '{book_dir.name}' excluded from Exp1")
        return {}

    # Locate chapters/ subfolder
    if (book_dir / "chapters").exists():
        ch_dir = book_dir / "chapters"
        metadata_dir = book_dir
    elif book_dir.name == "chapters":
        ch_dir = book_dir
        metadata_dir = book_dir.parent
    else:
        print(f"  WARNING: No chapters/ subfolder found in {book_dir}")
        return {}

    # Gather all chapter files sorted by chapter number
    all_chs = sorted(
        [p for p in ch_dir.glob("ch*.md") if "frontmatter" not in p.name],
        key=_chapter_num,
    )

    if len(all_chs) < n_select:
        print(f"  SKIPPED — only {len(all_chs)} chapters found, need {n_select}")
        return {}

    # Take first n_select chapters sequentially
    selected_paths = all_chs[:n_select]

    selected = []
    for p in selected_paths:
        char_count = _read_char_count(p)
        heading    = _read_first_heading(p)
        selected.append({
            "filename":    p.name,
            "chapter_num": _chapter_num(p),
            "char_count":  char_count,
            "heading":     heading[:80],
            "skip_reason": None,
        })

    result = {
        # Relocatable paths interpreted relative to core_chapters.json.
        "book_dir":       ".",
        "chapters_dir":   "chapters",
        "n_total":        len(all_chs),
        "n_selected":     len(selected),
        "selected":       selected,
        "skipped":        [],
        "protocol":       f"Sequential ch01–ch{n_select:02d} (first {n_select} chapters)",
    }

    out_path = metadata_dir / "core_chapters.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_chars = sum(e["char_count"] for e in selected)
    print(f"  Selected ch01–ch{n_select:02d}  ({total_chars:,} chars total):")
    for e in selected:
        print(f"    {e['filename']:15s}  {e['char_count']:>8,} chars"
              f"  | {e['heading'][:55]}")
    return result


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------

def _find_book_dirs(root: Path) -> list[Path]:
    """
    Find all directories under root that contain a chapters/ subfolder
    with at least one ch*.md file.
    """
    found = []
    for ch_dir in root.rglob("chapters"):
        if not ch_dir.is_dir():
            continue
        if any(ch_dir.glob("ch[0-9]*.md")):
            found.append(ch_dir.parent)
    return sorted(set(found))


def batch_select(root: Path, n_select: int = 5) -> None:
    book_dirs = _find_book_dirs(root)
    if not book_dirs:
        print(f"No textbook directories found under {root}")
        return
    print(f"Found {len(book_dirs)} textbook(s) under {root}\n")
    for book_dir in book_dirs:
        print(f"── {book_dir.name}")
        select_core_chapters(book_dir, n_select=n_select)
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select core chapters for Exp1 Sdiv evaluation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--book", type=Path,
        help="Single textbook directory (must contain a chapters/ subfolder).",
    )
    group.add_argument(
        "--root", type=Path,
        help="Root folder — finds all subdirectories with chapters/ automatically.",
    )
    parser.add_argument(
        "--n", type=int, default=5,
        help="Number of core chapters to select per textbook (default: 5).",
    )
    args = parser.parse_args()

    if args.book:
        if not args.book.exists():
            print(f"ERROR: Not found: {args.book}")
            sys.exit(1)
        print(f"── {args.book.name}")
        select_core_chapters(args.book, n_select=args.n)
    else:
        if not args.root.exists():
            print(f"ERROR: Not found: {args.root}")
            sys.exit(1)
        batch_select(args.root, n_select=args.n)

    print("Done.")


if __name__ == "__main__":
    main()
