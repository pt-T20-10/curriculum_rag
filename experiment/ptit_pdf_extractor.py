"""Layout-aware implementation used by :mod:`pdf_to_markdown`.

Generated Markdown is always written to ``.extract_staging`` first.  Passing
``--promote`` atomically copies only validated files into the topic folders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import statistics
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

try:
    import pymupdf
except ImportError:
    print("ERROR: PyMuPDF is required. Run: pip install pymupdf")
    raise SystemExit(1)


DEFAULT_CONFIG = Path(__file__).with_name("ptit_extraction_config.json")
STAGING_DIR = ".extract_staging"

SPACE_RE = re.compile(r"[ \t\r\f\v]+")
PAGE_RE = re.compile(r"^[-–—]?\s*\d{1,4}\s*[-–—]?$|^Trang\s+\d+$", re.I)
NUMBER_RE = re.compile(r"^(?P<num>\d+(?:\s*\.\s*\d+){1,3})\s*\.?\s+(?P<title>\S.*)$")
NUMBER_ONLY_RE = re.compile(r"^\d+(?:\s*\.\s*\d+){1,3}\s*\.?$")
RAW_CHAPTER_RE = re.compile(r"^CHƯƠNG\s+\d{1,2}(?:\s*[\.:])?(?:\s|$)", re.I)
BULLET_RE = re.compile(r"^[\uf0b7\uf0a7•●▪◦]\s*")
WATERMARK_RE = re.compile(r"^(?:PT|IT|PTIT)$", re.I)
CODE_RE = re.compile(
    r"^(?:#\s*(?:include|define)|(?:public|private|protected)\s*:|"
    r"(?:class|interface|enum|struct|package|import|using|namespace)\b|"
    r"(?:if|else|for|while|switch|case|try|catch|finally|return|throw|new)\b|"
    r"(?:void|int|long|float|double|char|bool|boolean|String|static)\b)", re.I
)
LEGACY_MAP = str.maketrans({
    "ƣ": "ư", "Ƣ": "Ư", "ð": "đ", "Ð": "Đ", "": "•", "": "•",
    # Adobe Symbol/Wingdings glyphs exposed by the source PDFs as private-use
    # code points.  Meanings were verified against their surrounding formulae.
    "\uf020": " ", "\uf022": "∀", "\uf02b": "+", "\uf02d": "−",
    "\uf061": "a", "\uf062": "b", "\uf063": "c", "\uf06e": "•",
    "\uf070": "π", "\uf076": "•", "\uf0a3": "≤", "\uf0b3": "≥",
    "\uf0b4": "×", "\uf0c6": "∅", "\uf0c7": "∧", "\uf0ce": "∈",
    "\uf0de": "⇒", "\uf0e0": "→", "\uf0e8": "⇒",
    # Extender pieces around floor/conditioning symbols; the visible base
    # glyph is already extracted next to them.
    "\uf8e6": "", "\uf8f0": "", "\uf8fb": "",
})


@dataclass(frozen=True)
class Line:
    page: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    fonts: tuple[str, ...]
    bold: bool
    italic: bool
    mono: bool


@dataclass
class Report:
    pdf: str
    topic: str
    pdf_sha256: str
    pages: int
    characters: int
    expected_chapters: list[int]
    detected_chapters: list[int]
    heading_counts: dict[str, int]
    first_five_present: bool
    standalone_watermarks: int
    private_use_chars: int
    malformed_h1: int
    invalid_markdown_headings: list[str]
    chapter_mismatches: list[str]
    warnings: list[str]
    passed: bool


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text.translate(LEGACY_MAP))
    text = text.replace("\xa0", " ").replace("\u200b", "")
    return SPACE_RE.sub(" ", text).strip()


def ascii_key(text: str) -> str:
    text = text.replace("Đ", "D").replace("đ", "d")
    return "".join(
        char for char in unicodedata.normalize("NFD", clean(text))
        if unicodedata.category(char) != "Mn"
    ).casefold()


def mostly_upper(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and sum(char.isupper() for char in letters) / len(letters) >= .72


def traits(fonts: Iterable[str]) -> tuple[bool, bool, bool]:
    joined = " ".join(fonts).casefold()
    return (
        "bold" in joined or "black" in joined,
        "italic" in joined or "oblique" in joined,
        any(word in joined for word in ("courier", "consol", "mono", "code")),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("books"), dict):
        raise ValueError(f"Invalid extraction config: {path}")
    return data


def page_lines(page: Any, number: int) -> list[Line]:
    """Read horizontal lines and join only number/bullet fragments on one baseline."""
    fragments: list[Line] = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT).get("blocks", []):
        if block.get("type") != 0:
            continue
        for raw in block.get("lines", []):
            direction = raw.get("dir", (1., 0.))
            # PTIT watermarks are diagonal; legitimate corpus text is horizontal.
            if abs(direction[1]) > .05 or direction[0] < .95:
                continue
            spans = [span for span in raw.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            # PDF producers frequently store the heading number and its title in
            # adjacent spans without a literal separating space ("1.1Giới thiệu").
            text = clean(" ".join(span.get("text", "").strip() for span in spans))
            if not text:
                continue
            fonts = tuple(sorted({str(span.get("font", "")) for span in spans}))
            bold, italic, mono = traits(fonts)
            x0, y0, x1, y1 = map(float, raw["bbox"])
            fragments.append(Line(number, text, x0, y0, x1, y1,
                                  max(float(s.get("size", 0)) for s in spans),
                                  fonts, bold, italic, mono))
    fragments.sort(key=lambda item: (item.y0, item.x0))

    used: set[int] = set()
    result: list[Line] = []
    for index, line in enumerate(fragments):
        if index in used:
            continue
        group = [line]
        for other_index in range(index + 1, len(fragments)):
            other = fragments[other_index]
            if other.y0 - line.y0 > 1.8:
                break
            joinable = (NUMBER_ONLY_RE.match(line.text) or NUMBER_ONLY_RE.match(other.text)
                        or BULLET_RE.match(line.text) or BULLET_RE.match(other.text))
            if abs(other.y0 - line.y0) <= 1.8 and joinable:
                group.append(other)
                used.add(other_index)
        if len(group) == 1:
            result.append(line)
            continue
        group.sort(key=lambda item: item.x0)
        fonts = tuple(sorted({font for item in group for font in item.fonts}))
        bold, italic, mono = traits(fonts)
        result.append(Line(number, clean(" ".join(item.text for item in group)),
                           min(i.x0 for i in group), min(i.y0 for i in group),
                           max(i.x1 for i in group), max(i.y1 for i in group),
                           max(i.size for i in group), fonts, bold, italic, mono))
    return sorted(result, key=lambda item: (item.y0, item.x0))


def repeat_key(text: str) -> str:
    return re.sub(r"\d+", "#", ascii_key(text))


def collect(doc: Any, defaults: dict[str, Any]) -> tuple[dict[int, list[Line]], set[str]]:
    pages: dict[int, list[Line]] = {}
    margins: Counter[str] = Counter()
    top, bottom = defaults.get("top_margin_ratio", .06), defaults.get("bottom_margin_ratio", .94)
    for index, page in enumerate(doc):
        lines = page_lines(page, index + 1)
        pages[index + 1] = lines
        for line in lines:
            if line.y0 < page.rect.height * top or line.y1 > page.rect.height * bottom:
                margins[repeat_key(line.text)] += 1
    threshold = max(3, math.ceil(len(doc) * defaults.get("repeat_ratio", .08)))
    return pages, {key for key, count in margins.items() if count >= threshold}


def artifact(line: Line, height: float, repeated: set[str], defaults: dict, book: dict) -> bool:
    top, bottom = defaults.get("top_margin_ratio", .06), defaults.get("bottom_margin_ratio", .94)
    in_margin = line.y0 < height * top or line.y1 > height * bottom
    if WATERMARK_RE.fullmatch(line.text) or PAGE_RE.fullmatch(line.text):
        return True
    # Real chapter titles in this corpus start below the 6% band.  Dropping the
    # entire band is safer than frequency-only filtering because short chapters
    # otherwise leave their running header fewer times than the repeat threshold.
    if in_margin and (repeat_key(line.text) in repeated or not line.bold):
        return True
    return any(re.search(pattern, line.text, re.I)
               for pattern in defaults.get("drop_patterns", []) + book.get("drop_patterns", []))


def fix_line(text: str, book: dict) -> str:
    text = clean(text)
    for old, new in book.get("replacements", {}).items():
        text = text.replace(old, new)
    text = re.sub(r"\s*\.{4,}\s*\d*\s*$", "", text)
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def heading(line: Line, chapter: int | None) -> str | None:
    match = NUMBER_RE.match(line.text)
    if not match:
        return None
    number = re.sub(r"\s+", "", match.group("num")).rstrip(".")
    title = match.group("title").strip()
    parts = number.split(".")
    if not 2 <= len(parts) <= 4 or (chapter is not None and int(parts[0]) != chapter):
        return None
    # Avoid turning numbered prose/exercises into headings.
    if not (line.bold or line.italic or mostly_upper(title)):
        return None
    return f"{'#' * len(parts)} {number}. {title}"


def code_line(line: Line) -> bool:
    text, score = line.text.strip(), 0
    if line.mono and len(text) > 1:
        return True
    if CODE_RE.match(text): score += 2
    if text in {"{", "}", "};"} or text.endswith(("{", "};")): score += 2
    if text.endswith(";"): score += 1
    if any(token in text for token in ("++", "--", "==", "!=", "->", "::", "()")): score += 1
    if re.search(r"\b(?:System\.out|printf|scanf|cout|cin|std::|public static void)\b", text): score += 2
    return score >= 2


class Renderer:
    def __init__(self) -> None:
        self.output: list[str] = []
        self.paragraph: list[str] = []
        self.code: list[str] = []

    def blank(self) -> None:
        if self.output and self.output[-1] != "": self.output.append("")

    def flush_paragraph(self) -> None:
        if not self.paragraph: return
        text = self.paragraph[0]
        for part in self.paragraph[1:]:
            text = text[:-1] + part if text.endswith("-") and part[:1].islower() else text + " " + part
        text = clean(text)
        # Formula fragments can begin with literal '#'.  Escape them so they do
        # not become accidental Markdown headings.
        if text.startswith("#"): text = "\\" + text
        self.blank(); self.output.append(text); self.paragraph.clear()

    def flush_code(self) -> None:
        if not self.code: return
        self.flush_paragraph(); self.blank(); self.output.extend(["```text", *self.code, "```"])
        self.code.clear()

    def add_heading(self, text: str) -> None:
        self.flush_code(); self.flush_paragraph(); self.blank(); self.output.extend([text, ""])

    def add_body(self, line: Line, new_paragraph: bool) -> None:
        if code_line(line):
            self.flush_paragraph(); self.code.append(line.text); return
        self.flush_code()
        bullet = BULLET_RE.match(line.text)
        if bullet:
            self.flush_paragraph(); self.blank(); self.output.append("- " + line.text[bullet.end():].strip()); return
        if new_paragraph: self.flush_paragraph()
        self.paragraph.append(line.text)

    def finish(self) -> str:
        self.flush_code(); self.flush_paragraph()
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.output).strip()) + "\n"


def extract(pdf: Path, book: dict, defaults: dict) -> tuple[str, int]:
    doc = pymupdf.open(pdf)
    pages, repeated = collect(doc, defaults)
    starts = {int(ch["page"]): ch for ch in book["chapters"]}
    if len(starts) != len(book["chapters"]): raise ValueError("Duplicate chapter page")
    renderer, current, previous = Renderer(), None, None
    lefts: list[float] = []
    for page_number in range(min(starts), len(doc) + 1):
        page = doc[page_number - 1]
        chapter = starts.get(page_number)
        skipping_title = chapter is not None
        if chapter:
            current = int(chapter["number"])
            renderer.add_heading(f"# CHƯƠNG {current}: {chapter['title'].strip()}")
            previous = None
        for raw in pages[page_number]:
            if artifact(raw, page.rect.height, repeated, defaults, book): continue
            line = replace(raw, text=fix_line(raw.text, book))
            if not line.text or RAW_CHAPTER_RE.match(line.text): continue
            md_heading = heading(line, current)
            if skipping_title:
                if md_heading: skipping_title = False
                elif line.bold and (mostly_upper(line.text) or line.size >= 13): continue
                else: skipping_title = False
            if md_heading:
                renderer.add_heading(md_heading); previous = None; continue
            lefts.append(line.x0)
            typical_left = statistics.median(lefts[-200:])
            gap = line.y0 - previous.y1 if previous and previous.page == line.page else 0
            new_para = bool(previous and (previous.page != line.page or gap > max(8, line.size * .65)
                            or (line.x0 - typical_left > 18 and previous.text.endswith((".", ":", ";", "?", "!")))))
            renderer.add_body(line, new_para); previous = line
    return renderer.finish(), len(doc)


def outline(markdown: str) -> str:
    rows = ["OUTLINE", "=" * 72, ""]
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if match: rows.append("  " * (len(match.group(1)) - 1) + match.group(2))
    return "\n".join(rows).rstrip() + "\n"


def validate(markdown: str, pdf: Path, topic: str, expected: list[int], pages: int) -> Report:
    detected = [int(n) for n in re.findall(r"^# CHƯƠNG\s+(\d+):", markdown, re.M)]
    counts = {f"h{i}": len(re.findall(rf"^{'#' * i} ", markdown, re.M)) for i in range(1, 5)}
    watermarks = sum(bool(WATERMARK_RE.fullmatch(line.strip())) for line in markdown.splitlines())
    private_use = sum(0xE000 <= ord(char) <= 0xF8FF for char in markdown)
    malformed = len(re.findall(r"^#\s+\d+(?:\.\d+)+", markdown, re.M))
    mismatches, invalid_headings, current, in_fence = [], [], None, False
    for number, line in enumerate(markdown.splitlines(), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("#") and not (
            re.match(r"^# CH.+? \d+:", line)
            or re.match(r"^#{2,4} \d+(?:\.\d+){1,3}\. ", line)
        ):
            invalid_headings.append(f"line {number}: {line}")
        found = re.match(r"^# CHƯƠNG\s+(\d+):", line)
        if found: current = int(found.group(1)); continue
        found = re.match(r"^#{2,4}\s+(\d+)\.", line)
        if found and current is not None and int(found.group(1)) != current:
            mismatches.append(f"line {number}: {line}")
    warnings = []
    if detected != expected: warnings.append(f"chapter sequence {detected} != {expected}")
    if counts["h2"] == 0: warnings.append("no H2 sections")
    if len(markdown) < 5000 * min(5, len(expected)): warnings.append("content unexpectedly short")
    if watermarks: warnings.append(f"{watermarks} watermark tokens remain")
    if private_use: warnings.append(f"{private_use} private-use font glyphs remain")
    if malformed: warnings.append(f"{malformed} malformed H1 headings")
    if invalid_headings: warnings.append(f"{len(invalid_headings)} invalid Markdown headings")
    if mismatches: warnings.append(f"{len(mismatches)} chapter/heading mismatches")
    first_five = all(n in detected for n in range(1, 6))
    passed = (detected == expected and first_five and counts["h2"] > 0
              and not watermarks and not private_use and not malformed
              and not invalid_headings and not mismatches)
    return Report(pdf.name, topic, sha256(pdf), pages, len(markdown), expected, detected,
                  counts, first_five, watermarks, private_use, malformed,
                  invalid_headings, mismatches, warnings, passed)


def write_outputs(root: Path, topic: str, markdown: str, report: Report) -> Path:
    target = root / topic; target.mkdir(parents=True, exist_ok=True)
    (target / "full.md").write_text(markdown, encoding="utf-8")
    (target / "outline.txt").write_text(outline(markdown), encoding="utf-8")
    (target / "extraction_report.json").write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def book_for(config: dict, pdf: Path) -> dict:
    if pdf.name in config["books"]: return config["books"][pdf.name]
    matches = [book for name, book in config["books"].items() if ascii_key(name) == ascii_key(pdf.name)]
    if len(matches) != 1: raise KeyError(f"No unique config for {pdf.name}")
    return matches[0]


def convert(pdf: Path, out: Path, config: dict, promote: bool) -> Report:
    book, defaults = book_for(config, pdf), config.get("defaults", {})
    topic = book["topic"]; print(f"\n[{topic}] {pdf.name}")
    markdown, pages = extract(pdf, book, defaults)
    expected = [int(ch["number"]) for ch in book["chapters"]]
    report = validate(markdown, pdf, topic, expected, pages)
    staged = write_outputs(out / STAGING_DIR, topic, markdown, report)
    print(f"  {'PASS' if report.passed else 'FAIL'}: {len(markdown):,} chars; chapters={report.detected_chapters}; {report.heading_counts}")
    for warning in report.warnings: print(f"  WARNING: {warning}")
    if promote:
        if not report.passed: raise RuntimeError(f"Refusing to promote failed topic {topic}")
        destination = out / topic; destination.mkdir(parents=True, exist_ok=True)
        for name in ("full.md", "outline.txt", "extraction_report.json"):
            source = staged / name
            # The validation gate above is the transaction boundary.  A direct
            # overwrite is used because managed Windows workspaces can deny
            # os.replace even when source and destination are both writable.
            shutil.copy2(source, destination / name)
        print(f"  Promoted -> {destination}")
    else: print(f"  Staged -> {staged}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Layout-aware PTIT PDF to Markdown extractor")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path); source.add_argument("--folder", type=Path)
    parser.add_argument("--out", "-o", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--promote", action="store_true", help="Replace outputs only after validation passes")
    args = parser.parse_args(); config = load_config(args.config); args.out.mkdir(parents=True, exist_ok=True)
    pdfs = [args.pdf] if args.pdf else sorted(args.folder.glob("*.pdf"))
    if not pdfs or any(not pdf.is_file() for pdf in pdfs): parser.error("No valid PDF input found")
    reports = [convert(pdf, args.out, config, args.promote) for pdf in pdfs]
    corpus = {"books": len(reports), "passed": sum(r.passed for r in reports),
              "all_passed": all(r.passed for r in reports), "promoted": args.promote and all(r.passed for r in reports),
              "reports": [asdict(r) for r in reports]}
    report_path = args.out / STAGING_DIR / "corpus_extraction_report.json"
    report_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nCorpus: {corpus['passed']}/{corpus['books']} passed\nReport: {report_path}")
    if not corpus["all_passed"]: raise SystemExit(2)


if __name__ == "__main__": main()
