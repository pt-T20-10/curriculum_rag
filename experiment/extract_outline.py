"""
extract_outline.py
==================
Extract the structural outline from a textbook full.md file.

Reads heading lines (# ## ###) and outputs:
  outline.txt  — human-readable tree
  outline.json — structured JSON for script consumption

Usage:
  # Single file
  python extract_outline.py --md path/to/full.md

  # Batch: all full.md files under a root folder
  python extract_outline.py --root path/to/PTIT/

  # All sources at once
  python extract_outline.py --root path/to/data/

Output is written alongside the input full.md file.
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def extract_outline(md_path: Path) -> dict:
    """
    Parse heading lines from a Markdown file and return structured outline.

    Returns:
        {
          "source": "filename",
          "title":  "Detected book title if any",
          "chapters": [
            {
              "num":   "1",
              "title": "Giới thiệu chung",
              "heading": "# CHƯƠNG 1: Giới thiệu chung",
              "sections": [
                {
                  "num":    "1.1",
                  "title":  "Các thành phần của hệ thống máy tính",
                  "heading": "## 1.1. ...",
                  "subsections": [
                    {"num": "1.1.1", "title": "...", "heading": "..."}
                  ]
                }
              ]
            }
          ]
        }
    """
    text = md_path.read_text(encoding="utf-8")
    # DirectChat wraps headings in **...** while AATG/PTIT use plain Markdown.
    # Normalise presentation before applying the shared structural patterns.
    text = re.sub(
        r"^(#{1,4})\s+\*\*(.+?)\*\*\s*$",
        r"\1 \2",
        text,
        flags=re.MULTILINE,
    )

    CH_RE  = re.compile(r"^#\s+(CHƯƠNG\s+\d+)\s*:\s*(.+)$", re.MULTILINE)
    SEC_RE = re.compile(r"^##\s+(\d+\.\d+)\.?\s+(.+)$",      re.MULTILINE)
    SUB_RE = re.compile(r"^###\s+(\d+\.\d+\.\d+)\.?\s+(.+)$", re.MULTILINE)

    # Build a flat list of all headings with their positions
    headings = []
    for m in CH_RE.finditer(text):
        headings.append({
            "pos":     m.start(),
            "level":   1,
            "num":     m.group(1).strip(),
            "title":   m.group(2).strip(),
            "heading": m.group(0).strip(),
        })
    for m in SEC_RE.finditer(text):
        headings.append({
            "pos":     m.start(),
            "level":   2,
            "num":     m.group(1).strip(),
            "title":   m.group(2).strip(),
            "heading": m.group(0).strip(),
        })
    for m in SUB_RE.finditer(text):
        headings.append({
            "pos":     m.start(),
            "level":   3,
            "num":     m.group(1).strip(),
            "title":   m.group(2).strip(),
            "heading": m.group(0).strip(),
        })

    # Sort by position in document
    headings.sort(key=lambda h: h["pos"])

    # Build nested structure
    chapters = []
    current_ch  = None
    current_sec = None

    for h in headings:
        if h["level"] == 1:
            current_ch = {
                "num":      h["num"],
                "title":    h["title"],
                "heading":  h["heading"],
                "sections": [],
            }
            chapters.append(current_ch)
            current_sec = None

        elif h["level"] == 2:
            current_sec = {
                "num":         h["num"],
                "title":       h["title"],
                "heading":     h["heading"],
                "subsections": [],
            }
            if current_ch is not None:
                current_ch["sections"].append(current_sec)

        elif h["level"] == 3:
            sub = {
                "num":     h["num"],
                "title":   h["title"],
                "heading": h["heading"],
            }
            if current_sec is not None:
                current_sec["subsections"].append(sub)

    return {
        "source":   md_path.name,
        "path":     str(md_path),
        "chapters": chapters,
    }


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def to_plain_text(outline: dict) -> str:
    """Render outline as indented plain text tree."""
    lines = [f"SOURCE: {outline['source']}", "=" * 60]
    for ch in outline["chapters"]:
        lines.append(f"\n{ch['num']}: {ch['title']}")
        for sec in ch["sections"]:
            lines.append(f"  {sec['num']}. {sec['title']}")
            for sub in sec["subsections"]:
                lines.append(f"    {sub['num']}. {sub['title']}")
    return "\n".join(lines)


def save_outline(md_path: Path) -> tuple[Path, Path]:
    """
    Extract outline from md_path and save outline.txt + outline.json
    in the same directory as md_path.

    Returns:
        (txt_path, json_path)
    """
    out_dir = md_path.parent
    outline  = extract_outline(md_path)

    txt_path  = out_dir / "outline.txt"
    json_path = out_dir / "outline.json"

    txt_path.write_text(to_plain_text(outline), encoding="utf-8")
    json_path.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    n_ch  = len(outline["chapters"])
    n_sec = sum(len(ch["sections"]) for ch in outline["chapters"])
    n_sub = sum(
        len(sec["subsections"])
        for ch in outline["chapters"]
        for sec in ch["sections"]
    )

    print(f"  Outline: {n_ch} chapters, {n_sec} sections, {n_sub} subsections")
    print(f"  → {txt_path}")
    print(f"  → {json_path}")
    return txt_path, json_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract structural outline from textbook Markdown files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--md", type=Path,
        help="Single full.md file to process.",
    )
    group.add_argument(
        "--root", type=Path,
        help="Root folder — recursively finds all full.md files.",
    )
    args = parser.parse_args()

    if args.md:
        if not args.md.exists():
            print(f"ERROR: File not found: {args.md}")
            sys.exit(1)
        print(f"\nProcessing: {args.md}")
        save_outline(args.md)
    else:
        md_files = sorted(args.root.rglob("full.md"))
        if not md_files:
            print(f"No full.md files found under {args.root}")
            sys.exit(1)
        print(f"Found {len(md_files)} full.md file(s)")
        for md in md_files:
            print(f"\nProcessing: {md}")
            save_outline(md)

    print("\nDone.")


if __name__ == "__main__":
    main()
