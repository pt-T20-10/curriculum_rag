"""
split_chapters.py
=================
Split a textbook full.md into individual chapter files.

Handles THREE source formats:

  PTIT (human textbooks):
    # CHƯƠNG N: Title          ← plain heading

  AATG (pipeline output):
    # CHƯƠNG N: TITLE          ← plain heading
                               + YAML frontmatter at top
                               + ```{=typst}...``` blocks to strip
                               + # Lời nói đầu front matter

  DirectChat (Gemini baseline):
    # **CHƯƠNG N: TITLE**      ← bold markers ** wrapping heading

All three formats are normalised before splitting so the same
chapter-boundary regex handles all sources.

Usage:
  # Single file (auto-detects format)
  python split_chapters.py --md path/to/full.md

  # Batch: all full.md files under a root folder
  python split_chapters.py --root path/to/folder/

  # Batch with glob pattern (e.g. files with spaces in name)
  python split_chapters.py --root Data/DirectChat/

Output alongside the input file:
  chapters/
    ch00_frontmatter.md   (pre-chapter content, excluded from scoring)
    ch01.md
    ch02.md
    ...

Each chapter file includes a metadata comment at the top.
"""

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Chapter heading regex — matches after normalisation
# Works for PTIT, AATG, and DirectChat (after bold stripping)
# ---------------------------------------------------------------------------
_CHAPTER_RE = re.compile(
    r"^(#\s+CHƯƠNG\s+(\d+)\s*:.+)$",
    re.MULTILINE,
)

# Front-matter section titles to treat as pre-chapter content
_FRONTMATTER_TITLES = {
    "lời nói đầu",
    "giới thiệu",
    "mục lục",
    "lời mở đầu",
    "preface",
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _strip_yaml_frontmatter(text: str) -> str:
    """Remove YAML frontmatter block (---...---) at the very start of file."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text
    end = stripped.find("\n---", 3)
    if end == -1:
        return text
    return stripped[end + 4:].lstrip("\n")


def _strip_typst_blocks(text: str) -> str:
    """Remove ```{=typst}...``` blocks produced by the AATG Pandoc pipeline."""
    return re.sub(
        r"```\{=typst\}.*?```",
        "",
        text,
        flags=re.DOTALL,
    )


def _normalise_bold_headings(text: str) -> str:
    """
    Convert DirectChat bold headings to plain headings.

    # **CHƯƠNG 1: TITLE**   →   # CHƯƠNG 1: TITLE
    ## **1.1 Title**         →   ## 1.1 Title
    ### **1.1.1 Title**      →   ### 1.1.1 Title
    """
    # Remove ** immediately after opening # markers and at end of heading line
    return re.sub(
        r"^(#{1,4})\s+\*\*(.+?)\*\*\s*$",
        r"\1 \2",
        text,
        flags=re.MULTILINE,
    )


def _normalise(text: str) -> str:
    """Apply all normalisation steps in order."""
    text = _strip_yaml_frontmatter(text)
    text = _strip_typst_blocks(text)
    text = _normalise_bold_headings(text)
    return text


# ---------------------------------------------------------------------------
# Core splitter
# ---------------------------------------------------------------------------

def split_chapters(md_path: Path) -> list[Path]:
    """
    Split a normalised full.md into chapter files.

    Args:
        md_path: Path to the source Markdown file (any filename).

    Returns:
        List of created chapter file paths (excluding frontmatter).
    """
    raw  = md_path.read_text(encoding="utf-8", errors="replace")
    text = _normalise(raw)

    matches = list(_CHAPTER_RE.finditer(text))

    if not matches:
        print(f"  WARNING: No chapter headings found in {md_path.name}")
        print("  Expected (after normalisation): '# CHƯƠNG N: Title'")
        return []

    out_dir = md_path.parent / "chapters"
    out_dir.mkdir(exist_ok=True)

    created: list[Path] = []

    # --- Front matter (everything before first # CHƯƠNG) ---
    frontmatter = text[: matches[0].start()].strip()
    if frontmatter:
        fm_path = out_dir / "ch00_frontmatter.md"
        fm_path.write_text(frontmatter, encoding="utf-8")
        print(f"  ch00_frontmatter.md — {len(frontmatter):,} chars (excluded from scoring)")

    # --- Each chapter ---
    for i, m in enumerate(matches):
        chap_num = int(m.group(2))
        start    = m.start()
        end      = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content  = text[start:end].strip()

        filename = f"ch{chap_num:02d}.md"
        out_path = out_dir / filename

        header = (
            f"<!-- source: {md_path.name} | "
            f"chapter: {chap_num} | "
            f"chars: {len(content):,} -->\n\n"
        )
        out_path.write_text(header + content, encoding="utf-8")
        print(f"  {filename} — {len(content):,} chars")
        created.append(out_path)

    print(f"  → {len(created)} chapter file(s) in {out_dir}")
    return created


def _find_md_files(root: Path) -> list[Path]:
    """
    Find canonical full.md textbook sources below root.
    """
    return sorted(root.rglob("full.md"))


def batch_split(root: Path) -> None:
    md_files = _find_md_files(root)
    if not md_files:
        print(f"No .md files found under {root}")
        return
    print(f"Found {len(md_files)} file(s)")
    for md in md_files:
        print(f"\nSplitting: {md}")
        split_chapters(md)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Split textbook Markdown files into individual chapter files.\n"
            "Handles PTIT, AATG, and DirectChat (Gemini) formats automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--md", type=Path,
        help="Single Markdown file to split.",
    )
    group.add_argument(
        "--root", type=Path,
        help="Root folder — recursively finds canonical full.md files.",
    )
    args = parser.parse_args()

    if args.md:
        if not args.md.exists():
            print(f"ERROR: File not found: {args.md}")
            sys.exit(1)
        print(f"\nSplitting: {args.md}")
        split_chapters(args.md)
    else:
        if not args.root.exists():
            print(f"ERROR: Folder not found: {args.root}")
            sys.exit(1)
        batch_split(args.root)

    print("\nDone.")


if __name__ == "__main__":
    main()
