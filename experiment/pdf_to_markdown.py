"""
pdf_to_markdown.py
==================
Convert PTIT textbook PDFs to clean Markdown (layout-aware).

The CLI delegates to the PyMuPDF layout-aware extractor, which uses font,
position and line direction to handle the heading formats found in PTIT books:

  Format A — single-line chapter, dots in section numbers:
    CHƯƠNG 1:   GIỚI THIỆU CHUNG
    1.1. TIÊU ĐỀ ALL CAPS
    1.1.1. Tiêu đề mixed case

  Format B — multi-line chapter, no dots:
    CHƯƠNG 1
    TIÊU ĐỀ ALL CAPS
    TIẾP THEO DÒNG 2
    1.1 TIÊU ĐỀ ALL CAPS
    1.1.1 Tiêu đề mixed case

Both produce identical Markdown output:
    # CHƯƠNG 1: Tiêu Đề
    ## 1.1. Tiêu Đề
    ### 1.1.1. Tiêu đề

Artifacts cleaned: rotated PTIT watermark, repeated headers/footers, page
numbers, TOC pages and legacy private-use font glyphs.

Usage:
  python pdf_to_markdown.py --pdf path/to/book.pdf --out path/to/PTIT/
  python pdf_to_markdown.py --folder path/to/PTIT/ --out path/to/PTIT/
  python pdf_to_markdown.py --folder path/to/PTIT/ --out path/to/PTIT/ --promote

Output is staged first:
  output/.extract_staging/<topic>/{full.md,outline.txt,extraction_report.json}

With --promote, validated files are copied to:
  output/<topic>/{full.md,outline.txt,extraction_report.json}
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    # The legacy implementation below remains for import compatibility.  CLI
    # execution is delegated to the PyMuPDF layout-aware implementation.
    pdfplumber = None

# ---------------------------------------------------------------------------
# Skip patterns
# ---------------------------------------------------------------------------

_SKIP_EXACT = {
    "PT", "IT", "PTIT",
    "HỌC VIỆN CÔNG NGHỆ BƯU CHÍNH VIỄN THÔNG",
    "KHOA CÔNG NGHỆ THÔNG TIN 1",
    "KHOA CÔNG NGHỆ THÔNG TIN",
}

_PAGE_NUM_RE  = re.compile(r"^\s*\d{1,4}\s*$")
_TOC_ENTRY_RE = re.compile(r"\.{4,}")
_PHAN_RE      = re.compile(r"^PHẦN\s+\d+$")   # "PHẦN 1" grouping — not a chapter

# ---------------------------------------------------------------------------
# Heading patterns
# ---------------------------------------------------------------------------

# Format A: "CHƯƠNG 1: TITLE" — colon + title on same line
_CH_A_RE = re.compile(r"^(CHƯƠNG\s+\d+)\s*:\s*(.+)$")

# Format B: "CHƯƠNG 1" — standalone, title follows on next line(s)
_CH_B_RE = re.compile(r"^(CHƯƠNG\s+\d+)\s*$")

# Section: "1.1." or "1.1 " + ALL CAPS (dot optional)
_SEC_RE = re.compile(
    r"^(\d+\.\d+)\.?\s+"
    r"([A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲÝỴỶỸ]"
    r"[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲÝỴỶỸ\s\(\),/\-–]+)$"
)

# Subsection: "1.1.1." or "1.1.1 " + any content (dot optional)
_SUB_RE = re.compile(r"^(\d+\.\d+\.\d+)\.?\s+(.+)$")


def _is_mostly_upper(text: str) -> bool:
    """True if >70% of alpha chars are uppercase (Vietnamese-aware)."""
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return False
    return sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.70


def _clean_line(line: str) -> str:
    line = line.replace("\t", " ").replace("\r", "").replace("\f", "")
    line = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", line)
    return line.strip()


def _should_skip(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in _SKIP_EXACT:
        return True
    if _PAGE_NUM_RE.match(stripped):
        return True
    if _TOC_ENTRY_RE.search(stripped):
        return True
    if _PHAN_RE.match(stripped):
        return True
    return False


def _is_toc_block(lines: list) -> bool:
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return False
    return sum(1 for l in non_empty if _TOC_ENTRY_RE.search(l)) / len(non_empty) > 0.40


# ---------------------------------------------------------------------------
# Core converter
# ---------------------------------------------------------------------------

def pdf_to_markdown(pdf_path: Path, out_dir: Path) -> Path:
    book_dir = out_dir / pdf_path.stem
    book_dir.mkdir(parents=True, exist_ok=True)
    out_path = book_dir / "full.md"

    print(f"\nProcessing: {pdf_path.name}")

    md_lines:        list = []
    pending_chapter: str  = ""   # Format B: "CHƯƠNG N" waiting for its title
    prev_blank:      bool = False

    def emit(line: str) -> None:
        nonlocal prev_blank
        is_heading = line.startswith("#")
        is_blank   = (line == "")

        if is_heading:
            if md_lines and md_lines[-1] != "":
                md_lines.append("")
            md_lines.append(line)
            md_lines.append("")
            prev_blank = True
        elif is_blank:
            if not prev_blank:
                md_lines.append("")
            prev_blank = True
        else:
            md_lines.append(line)
            prev_blank = False

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"  Pages: {total}")

        for page in pdf.pages:
            raw        = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            page_lines = raw.split("\n")

            if _is_toc_block(page_lines):
                continue

            for raw_line in page_lines:
                clean = _clean_line(raw_line)

                if _should_skip(clean):
                    # Flush any pending Format B chapter without a title
                    if pending_chapter:
                        emit(f"# {pending_chapter}: (Không có tiêu đề)")
                        pending_chapter = ""
                    continue

                if not clean:
                    # Blank line — flush pending chapter, then emit blank
                    if pending_chapter:
                        emit(f"# {pending_chapter}: (Không có tiêu đề)")
                        pending_chapter = ""
                    emit("")
                    continue

                # ── Format A chapter: "CHƯƠNG N: TITLE" ─────────────────
                m = _CH_A_RE.match(clean)
                if m:
                    pending_chapter = ""
                    emit(f"# {m.group(1)}: {m.group(2).strip().title()}")
                    continue

                # ── Format B chapter part 1: "CHƯƠNG N" standalone ───────
                m = _CH_B_RE.match(clean)
                if m:
                    if pending_chapter:
                        # Previous chapter had no title — flush it
                        emit(f"# {pending_chapter}: (Không có tiêu đề)")
                    pending_chapter = m.group(1)
                    continue

                # ── Format B chapter part 2: collect title ───────────────
                if pending_chapter:
                    if _is_mostly_upper(clean):
                        # This is the chapter title (possibly continues on next line)
                        emit(f"# {pending_chapter}: {clean.title()}")
                        pending_chapter = ""
                        continue
                    else:
                        # Non-uppercase line — flush pending chapter, treat as body
                        emit(f"# {pending_chapter}: (Không có tiêu đề)")
                        pending_chapter = ""
                        # Fall through to process as body text

                # ── Subsection: N.N.N[.] Title ───────────────────────────
                m = _SUB_RE.match(clean)
                if m:
                    emit(f"### {m.group(1)}. {m.group(2).strip()}")
                    continue

                # ── Section: N.N[.] TITLE ALL CAPS ───────────────────────
                m = _SEC_RE.match(clean)
                if m:
                    rest = m.group(2).strip()
                    if _is_mostly_upper(rest):
                        emit(f"## {m.group(1)}. {rest.title()}")
                        continue

                # ── Body text ─────────────────────────────────────────────
                emit(clean)

        # Flush any remaining pending chapter at end of document
        if pending_chapter:
            emit(f"# {pending_chapter}: (Không có tiêu đề)")

    content = "\n".join(md_lines).strip()
    content = re.sub(r"\n{3,}", "\n\n", content)

    out_path.write_text(content, encoding="utf-8")
    print(f"  → {out_path}")
    print(f"  → {len(content):,} characters")

    lines = content.splitlines()
    h1 = sum(1 for l in lines if l.startswith("# CHƯƠNG"))
    h2 = sum(1 for l in lines if l.startswith("## "))
    h3 = sum(1 for l in lines if l.startswith("### "))
    print(f"  Headings: {h1} chapters, {h2} sections, {h3} subsections")

    return out_path


def batch_convert(folder: Path, out_dir: Path) -> list:
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {folder}")
        return []
    print(f"Found {len(pdfs)} PDF(s)")
    results = []
    for pdf in pdfs:
        try:
            results.append(pdf_to_markdown(pdf, out_dir))
        except Exception as e:
            print(f"  ERROR {pdf.name}: {e}")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert PTIT PDFs to Markdown (handles both heading formats)."
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--pdf",    type=Path)
    grp.add_argument("--folder", type=Path)
    parser.add_argument("--out", "-o", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    if args.pdf:
        if not args.pdf.exists():
            print(f"ERROR: {args.pdf}"); sys.exit(1)
        pdf_to_markdown(args.pdf, args.out)
    else:
        if not args.folder.exists():
            print(f"ERROR: {args.folder}"); sys.exit(1)
        batch_convert(args.folder, args.out)

    print("\nDone.")


if __name__ == "__main__":
    from ptit_pdf_extractor import main as layout_aware_main

    layout_aware_main()
