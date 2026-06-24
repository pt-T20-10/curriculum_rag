"""
Publisher Agent for AI Textbook Generator.

This agent finalizes the generated content by:
1. Merging accumulated content + last subsection buffer
2. Prepending the preface (Lời nói đầu) with LaTeX artifact stripping
3. Normalizing line endings and applying fix passes (math, headings, pagebreaks)
4. Assembling the Typst front matter (title page, TOC, figure list, numbering)
5. Saving the Markdown source file
6. Converting independently to PDF and DOCX via Pandoc
7. Returning explicit Markdown/PDF/DOCX artifact paths and export errors
8. Cleaning up temporary image files (always, via finally block)

PDF pipeline: Pandoc → Typst (not xelatex).
Math delimiters: Pandoc-compatible $...$ and $$...$$ consumed by Typst's renderer.

Page structure:
    Title page     — centered vertically + horizontally, no page number
    TOC            — no page number
    Danh mục hình  — no page number (optional, when enable_images=True)
    Lời nói đầu   — page 1  ← numbering starts here
    CHƯƠNG 1 …    — continues from page 1
"""
import textwrap
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
import re

try:
    import pypandoc
except ImportError:
    pypandoc = None

from app.schemas.curriculum import AgentState
from app.config import settings
from app.services.textbook.language import get_language_profile
from app.utils.log_config import setup_logger

BASE_DIR = settings.BASE_DIR

logger = setup_logger(name="PublisherAgent", logfile="logs/agents.log")

# Temporary image directory — created by Illustrator, cleaned up by Publisher.
image_dir = BASE_DIR / "outputs" / "images"


def _document_font() -> str:
    """Return the configured font, tolerating a pre-restart Settings singleton."""
    return getattr(settings, "DOCUMENT_FONT", "Times New Roman")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def cleanup_temp_images() -> None:
    """
    Remove the temporary images directory created by the Illustrator node.

    Called in a finally block inside publish_curriculum() to guarantee
    execution regardless of whether PDF generation succeeded or fell back
    to Markdown-only output.
    """
    if image_dir.exists():
        try:
            shutil.rmtree(image_dir)
            logger.info(f"✓ Cleaned up temporary images: {image_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup images directory: {e}")
    else:
        logger.debug("No temporary images directory to clean up")


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """
    Sanitize user input for safe use as a filename component.

    Transformations applied:
        1. Remove all characters except word chars, spaces, and hyphens
        2. Strip leading/trailing whitespace
        3. Replace spaces with underscores
        4. Truncate to max_length characters
        5. Fallback to "Textbook" if the result is empty

    Args:
        name:       Raw string (typically from state["request"]).
        max_length: Maximum character length for the output.

    Returns:
        Safe filename string suitable for use in Path construction.
    """
    safe = re.sub(r'[^\w\s\-]', '', name)
    safe = safe.strip().replace(' ', '_')
    safe = safe[:max_length]
    return safe if safe else "Textbook"


def _typst_string_literal(value: str) -> str:
    """Encode untrusted/dynamic text as a Typst-compatible string literal."""
    return json.dumps(str(value), ensure_ascii=False)


def _valid_artifact(path: Path, suffix: str) -> bool:
    """Return True only for a non-empty file with the expected extension."""
    return path.suffix.lower() == suffix and path.is_file() and path.stat().st_size > 0
# ---------------------------------------------------------------------------
# Unicode → math conversion maps
#
# Times New Roman (the textbook body font) does not include Unicode
# subscript/superscript characters (e.g. ₂ U+2082, ⁺ U+207A).
# Typst renders missing glyphs as □ boxes, so these must be converted to
# Pandoc-compatible $...$ math notation before compilation.
# ---------------------------------------------------------------------------

SUBSCRIPT_MAP: dict[str, str] = {
    '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4',
    '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9',
}
SUPERSCRIPT_MAP: dict[str, str] = {
    '⁺': '+', '⁻': '-', '⁰': '0', '¹': '1', '²': '2', '³': '3',
    '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', 'ⁿ': 'n',
}
# ---------------------------------------------------------------------------
# fix_* pass functions
# Applied in sequence inside publish_curriculum() after CRLF normalization.
# ---------------------------------------------------------------------------

def fix_unicode_math(content: str) -> str:
    """
    Convert Unicode subscript/superscript characters to Pandoc math notation.

    Applied before fix_math_formatting() so all Unicode chars are converted
    before the more complex math pass runs.

    Conversion examples:
        H₂O    → H$_2$O
        CO₂    → CO$_2$
        Na⁺    → Na$^+$
        Cl⁻    → Cl$^-$
        1s²    → 1s$^2$
        H₂SO₄ → H$_2$SO$_4$

    Consecutive subscript digits are grouped: ₁₂ → $_{12}$ (not $_{1}$$_{2}$).
    """
    result: list[str] = []
    i = 0
    while i < len(content):
        ch = content[i]
        if ch in SUBSCRIPT_MAP:
            # Consume consecutive subscript digits as a single group
            digits = ''
            while i < len(content) and content[i] in SUBSCRIPT_MAP:
                digits += SUBSCRIPT_MAP[content[i]]
                i += 1
            result.append(f'$_{{{digits}}}$' if len(digits) > 1 else f'$_{digits}$')
        elif ch in SUPERSCRIPT_MAP:
            val = SUPERSCRIPT_MAP[ch]
            result.append(f'$^{{{val}}}$')
            i += 1
        else:
            result.append(ch)
            i += 1

    converted = ''.join(result)
    if converted != content:
        logger.info("✓ Unicode math characters converted to Pandoc math notation")
    return converted
# Regex matching complex LaTeX commands that must stay as display math.
# Expressions matching this pattern are never converted to inline $ by
# fix_inline_display_math().
_COMPLEX_MATH_RE = re.compile(
    r'\\(?:frac|int|sum|prod|lim|begin|end|sqrt|left|right|binom|matrix|pmatrix|cases)'
)
_WORD_PAGEBREAK = (
    '```{=openxml}\n'
    '<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n'
    '```'
)

def fix_inline_display_math(content: str) -> str:
    """
    Convert trivially-simple $$ display blocks to inline $ math.

    The LLM sometimes wraps a single variable or short expression in display
    math ($$...$$) when it appears mid-sentence. This causes it to render as
    a centred block equation that interrupts prose flow.

    Only converts blocks where:
        - The inner expression is ≤ 40 characters
        - The inner expression contains no complex LaTeX commands
        - The $$ delimiters are on their own lines (standard LLM output)

    Leading/trailing whitespace on the content line is tolerated

    Kept as display math (no conversion):
        $$\\n\\frac{a}{b}\\n$$   — complex command
        $$\\n<very long expr>\\n$$  — > 40 chars

    Examples converted:
        $$\\nf(x)\\n$$   →  $f(x)$
        $$\\nQ_s\\n$$    →  $Q_s$
    """
    def maybe_inline(m: re.Match) -> str:
        expr = m.group(1).strip()
        if _COMPLEX_MATH_RE.search(expr):
            return m.group(0)
        if len(expr) > 40:
            return m.group(0)
        return f'${expr}$'

    
        # Pass A — multiline: $$\nexpr\n$$
    content = re.sub(
        r'\$\$\n[ \t]*([^\n]{1,40})[ \t]*\n[ \t]*\$\$',
        maybe_inline,
        content,
    )
    # Pass B — single-line inline: $$expr$$ with no newline inside
    # LLM sometimes writes $$\Omega$$ mid-sentence; Pandoc renders as
    # a centred display block, breaking prose flow.
    content = re.sub(
        r'(?<!\$)\$\$([^$\n]{1,40})\$\$(?!\$)',
        maybe_inline,
        content,
    )
    return content


def fix_math_formatting(content: str) -> str:
    """
    Fix common math formatting issues that cause Typst/Pandoc compilation errors.

    Problems addressed (applied in order):
        1. Nested $ inside $$ blocks — strip inner $ delimiters
        2. Space between $ and [  →  $[
        3. Space-padded inline $ x $ → $x$
        4. Stray single $ command at line start → wrapped in $$
        5. Multiline inline $...\\n...$  → joined to single line
        6. Lone inline $var$ surrounded by blank lines → remove surrounding blanks
    """
    def clean_display_block(m: re.Match) -> str:
        inner = m.group(1)
        # BUG-03 FIX: cap iterations to prevent infinite loop on malformed input
        max_iter = 10
        prev = None
        for _ in range(max_iter):
            if inner == prev:
                break
            prev = inner
            inner = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)', r'\1', inner)
        else:
            if inner != prev:
                logger.warning(
                    "fix_math_formatting: max iterations reached — "
                    "possible malformed LaTeX input"
                )
        lines = [l for l in inner.split('\n') if l.strip() != '']
        return f'$$\n{chr(10).join(lines).strip()}\n$$'

    content = re.sub(
        r'\$\$\n(.*?)\n[ \t]*\$\$',
        clean_display_block,
        content,
        flags=re.DOTALL,
    )
    content = re.sub(r'\$\s+\[', '$[', content)
    content = re.sub(r'\]\s+\$', ']$', content)
    content = re.sub(
        r'(?<!\$)\$ +([^$\n]+?) +\$(?!\$)',
        lambda m: '$' + m.group(1).strip() + '$',
        content,
    )
    content = re.sub(
        r'^(\$)(\\[a-zA-Z]+(?:\{[^}]*\})*)$',
        r'$$\n\2\n$$',
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r'(?<!\$)\$(?!\$)([^$\n]{0,60}?)\n([^$\n]{0,60}?)\$(?!\$)',
        lambda m: '$' + m.group(1).rstrip() + ' ' + m.group(2).lstrip() + '$',
        content,
    )
    content = re.sub(r'\n\n(\$(?!\$)[^$\n]+\$(?!\$))\n\n', r'\n\1\n', content)
    return content


def _apply_outside_fenced_blocks(content: str, transform) -> str:
    """Apply a text transform outside Markdown fenced code/raw blocks."""
    fence_re = re.compile(r'(^```[^\n]*\n.*?^```[ \t]*$)', re.MULTILINE | re.DOTALL)
    parts = fence_re.split(content)
    for idx, part in enumerate(parts):
        if not part:
            continue
        if part.lstrip().startswith("```"):
            continue
        parts[idx] = transform(part)
    return "".join(parts)


_PYTHON_INLINE_CODE_WORDS = {
    "if", "elif", "else", "for", "while", "break", "continue", "return",
    "import", "from", "class", "def", "and", "or", "not", "in", "is",
    "True", "False", "None", "TypeError", "ValueError", "IndentationError",
    "KeyError", "IndexError", "int", "float", "str", "bool", "list", "dict",
    "tuple", "set",
}

_PYTHON_INLINE_CALLS = {
    "type", "str", "int", "float", "bool", "input", "range", "len", "print",
    "keys", "values", "items", "append", "insert", "remove",
}


def _looks_like_programming_inline(expr: str) -> bool:
    expr = expr.strip().strip("`")
    if not expr:
        return False

    # Preserve real LaTeX/math commands. Escaped underscores are allowed because
    # LLMs often emit Python identifiers as math, e.g. $student\_scores$.
    latexish = expr.replace(r"\_", "")
    if "\\" in latexish:
        return False

    plain = expr.replace(r"\_", "_")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", plain):
        return plain in _PYTHON_INLINE_CODE_WORDS
    if "-" in plain:
        parts = plain.split("-")
        if all(part in _PYTHON_INLINE_CODE_WORDS for part in parts):
            return True

    call_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\(\)", plain)
    if call_match:
        return call_match.group(1) in _PYTHON_INLINE_CALLS

    if re.search(r"[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*", plain):
        return True
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*\s*\[", plain):
        return True
    if re.search(r"['\"]", plain) and re.search(r"[A-Za-z_][A-Za-z0-9_]*", plain):
        return True
    if re.match(r"(del|return|import|from|class|def)\s+", plain):
        return True
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*", plain) and re.search(
        r"(\+=|-=|\*=|/=|//=|%=|\*\*|==|!=|<=|>=)", plain
    ):
        return True

    return False


def fix_programming_inline_code(content: str) -> str:
    """
    Convert common programming-code fragments that LLMs incorrectly wrap as
    math into Markdown inline code, and repair mixed backtick/dollar spans.

    This is intentionally conservative and runs outside fenced code blocks only.
    """
    def transform(text: str) -> str:
        def fix_malformed_backtick(match: re.Match) -> str:
            expr = match.group(1).strip()
            if _looks_like_programming_inline(expr) or re.fullmatch(r'"[^"\n]+"', expr):
                cleaned = expr.replace(r"\_", "_")
                return f"`{cleaned}`"
            return match.group(0)

        text = re.sub(r'`("[^"\n]{1,80}")\$', fix_malformed_backtick, text)
        text = re.sub(
            r"`([A-Za-z_][A-Za-z0-9_]*(?:\(\)|\[[^\]\n]+\])?)\$",
            fix_malformed_backtick,
            text,
        )

        codeish_math_re = re.compile(
            r"\$("
            r"(?:[A-Za-z_][A-Za-z0-9_]*\\_[A-Za-z0-9_]*(?:\s*[+\-*/]\s*\d+)?)"
            r"|(?:[A-Za-z_][A-Za-z0-9_]*\[[^$\n]+\](?:\s*=\s*[^$\n]+)?)"
            r"|(?:(?:if|elif|else|for|while|break|continue|and|or|not)(?:-[A-Za-z]+)?)"
            r"|(?:True|False|None|TypeError|ValueError|IndentationError|KeyError|IndexError)"
            r"|(?:(?:type|str|int|float|bool|input|range|len|print|keys|values|items|append|insert|remove)\(\))"
            r")\$"
        )

        def fix_targeted_math_code(match: re.Match) -> str:
            cleaned = match.group(1).strip().replace(r"\_", "_")
            return f"`{cleaned}`"

        text = codeish_math_re.sub(fix_targeted_math_code, text)

        def fix_math_code(match: re.Match) -> str:
            expr = match.group(1).strip()
            if _looks_like_programming_inline(expr):
                cleaned = expr.replace(r"\_", "_")
                return f"`{cleaned}`"
            return match.group(0)

        text = re.sub(r"(?<!\$)\$(?!\$)([^$\n]{1,120}?)(?<!\$)\$(?!\$)", fix_math_code, text)

        # Separate inline code from adjacent prose: `x`returns -> `x` returns.
        # The lookahead after the opening backtick avoids treating a closing
        # backtick as a new span.
        text = re.sub(r"(`(?=[A-Za-z_\"'])[^`\n]+`)(?=[A-Za-z])", r"\1 ", text)
        text = re.sub(r"(?<=[A-Za-z0-9)])(`(?=[A-Za-z_\"'])[^`\n]+`)", r" \1", text)

        # Add a space after safe inline math spans when prose is glued to them.
        text = re.sub(r"(^|[\s(\[,;:])(\$[^$\n]+\$)(?=[A-Za-z])", r"\1\2 ", text)
        text = re.sub(r"(?<=[A-Za-z])(\$(?=[0-9\\+\-*/{#;])[^$\n]+\$)", r" \1", text)
        return text

    return _apply_outside_fenced_blocks(content, transform)


def normalize_english_dashes(content: str) -> str:
    """Avoid em/en dashes in English output; Typst line breaking handles ASCII better."""
    def transform(text: str) -> str:
        text = re.sub(r"\s*[—–]\s*", " - ", text)
        return re.sub(r" {2,}", " ", text)

    return _apply_outside_fenced_blocks(content, transform)


def fix_typst_deprecated_symbols(content: str) -> str:
    """
    Replace deprecated Typst math symbol names with their current equivalents.

    Applied before Pandoc conversion to eliminate compiler warnings that
    appear in the Typst output even when the PDF renders correctly.

    Replacements:
        times.circle → times.o  (tensor product ⊗, renamed in Typst ≥ 0.12)
    """
    content = content.replace("times.circle", "times.o")
    content = content.replace(" sect ", " inter ")
    return content


def fix_markdown_headings(content: str) -> str:
    """
    Ensure ## and ### headings always appear on their own lines.

    Under token pressure the LLM occasionally emits headings inline:
        '...end of sentence.## 5.2 Title\n### 5.2.1 Sub ...'

    This function inserts the required blank lines before ## and ### headings
    so that Pandoc parses them correctly as ATX headings.
    """
    # Insert blank line before any ##/### heading not already on its own line
    content = re.sub(
        r'([^\n])\s*(#{2,3} \d)',
        r'\1\n\n\2',
        content,
    )
    # Insert blank line after any ##/### heading not already followed by one
    content = re.sub(
        r'^(#{2,3} [^\n]+)\n(?!\n)',
        r'\1\n\n',
        content,
        flags=re.MULTILINE,
    )
    return content


def fix_chapter_pagebreaks(content: str, language: str = "vi") -> str:
    """
    Insert a Typst #pagebreak() immediately before each `# CHƯƠNG N` heading.

    Only inserts a break when content precedes the heading (matched via \\n\\n
    before `# CHƯƠNG`) — the very first heading in the document is never
    preceded by a break.

    Scope: `# CHƯƠNG` headings only.
    `# Lời nói đầu` is intentionally excluded — it is separated from the
    front matter by _TYPST_START_NUMBERING which already contains a
    #pagebreak() call, assembled in publish_curriculum().
    """
    pb = "```{=typst}\n#pagebreak()\n```" + "\n\n"
    profile = get_language_profile(language)

    def insert_break(m: re.Match) -> str:
        return m.group(1) + pb + m.group(2)

    return re.sub(
        rf'(\n\n)(# {re.escape(profile.chapter_label)} )',
        insert_break,
        content,
    )


def add_figure_numbers(content: str, language: str = "vi") -> str:
    """
    Prefix image captions with section-scoped figure numbers.

    Tracks the current ## X.Y and ### X.Y.Z heading as images are encountered
    and prefixes each caption with "Hình X.Y.N:" or "Hình X.Y.Z.N:".

    Behaviour:
        - Idempotent: captions already starting with "Hình [digits]" are skipped.
        - Images before the first ## heading are left unchanged.
        - Counter resets to 1 when the tracked section changes.
    """
    lines = content.split('\n')
    result: list[str] = []
    current_section   = ""
    section_img_count: dict[str, int] = {}
    profile = get_language_profile(language)

    for line in lines:
        m2 = re.match(r'^## (\d+\.\d+)', line)
        if m2:
            current_section = m2.group(1)
            result.append(line)
            continue

        m3 = re.match(r'^### (\d+\.\d+\.\d+)', line)
        if m3:
            current_section = m3.group(1)
            result.append(line)
            continue

       
        img_match = re.match(r'^(!\[)([^\]]*?)(\]\()(.+?)(\))(\{.*?\})?$', line)
        if img_match and current_section:
            caption = img_match.group(2)
            path    = img_match.group(4)
            attrs   = img_match.group(6) or ""

            if not re.match(rf'^{re.escape(profile.figure_label)} \d[\d.]*:', caption):
                section_img_count[current_section] = (
                    section_img_count.get(current_section, 0) + 1
                )
                n       = section_img_count[current_section]
                caption = f"{profile.figure_label} {current_section}.{n}: {caption}"
                line    = f"![{caption}]({path}){attrs}"

        result.append(line)

    return '\n'.join(result)


def _prepare_word_md(
    md_content: str,
    title: str,
    enable_images: bool = True,
    language: str = "vi",
) -> str:
    """
    Transform MD content for Word (.docx) output.

    Strategy:
        - Page breaks: OpenXML <w:br w:type="page"/> — only reliable method for docx
        - TOC: Pandoc --toc flag — native, no F9 needed
        - Title: YAML title: — Pandoc renders before TOC automatically
        - Figure list: extracted from existing captions, placed on own page
          before first chapter

    Pipeline:
        1. Strip YAML front matter
        2. Replace {=typst} #pagebreak() blocks → OpenXML page break
        3. Strip remaining {=typst} blocks
        4. Build figure list from existing image captions
        5. Insert figure list before # Lời nói đầu (own page, with page break after)
        6. Add OpenXML page break at body start (TOC → body separation)
        7. Fix image width 70% → 85%
        8. Collapse blank lines
        9. Prepend YAML with title:
    """
    content = md_content
    profile = get_language_profile(language)

    # Step 1 — Strip YAML front matter
    content = re.sub(r'^---.*?---\n\n?', '', content, flags=re.DOTALL)

    # Step 2 — Replace {=typst} #pagebreak() → OpenXML page break
    content = re.sub(
        r'```\{=typst\}\s*#pagebreak\(\)\s*```',
        _WORD_PAGEBREAK,
        content,
        flags=re.DOTALL,
    )

    # Step 3 — Strip all remaining {=typst} blocks
    content = re.sub(r'```\{=typst\}.*?```', '', content, flags=re.DOTALL)

    # Step 4 — Extract figure list from captions already in MD.
    # Captions format: "Figure/Hình X.Y.Z: Caption text" — set by add_figure_numbers()
    # No leading _WORD_PAGEBREAK — Step 5 manages page separation around this block.
    figure_list_md = ""
    if enable_images:
        captions = re.findall(
            rf'!\[({re.escape(profile.figure_label)} [\d.]+:[^\]]+)\]',
            content,
        )
        if captions:
            items = "\n".join(f"- {cap}" for cap in captions)
            figure_list_md = f"# {profile.figure_list_label}\n\n" + items
    # Step 5 — Insert figure list before # Lời nói đầu.
    # Desired Word page order: TOC → Danh mục hình → Lời nói đầu → Chapters
    # _WORD_PAGEBREAK is injected AFTER figure list to separate it from preface.
    # Step 6 below prepends another _WORD_PAGEBREAK at content start (TOC → Danh mục hình).
    if figure_list_md:
        match = re.search(rf'# {re.escape(profile.preface_heading)}', content)
        if match:
            insert_pos = match.start()
            content = (
                content[:insert_pos]
                + figure_list_md + "\n\n"
                + _WORD_PAGEBREAK + "\n\n"
                + content[insert_pos:]
            )

    # Step 6 — Add page break at start of body so TOC and body are separated.
    # Pandoc places --toc between title block and $body$; without a break the
    # TOC runs directly into the first body section (Danh mục hình or Lời nói đầu).
    content = _WORD_PAGEBREAK + "\n\n" + content.lstrip()

    # Step 7 — Fix image width: 70% (tuned for Typst) → 85% (better for Word)
    content = re.sub(r'\{width=70%\}', '{width=85%}', content)

    # Step 8 — Collapse stray blank lines left by stripping
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.strip()

    # Step 9 — Prepend YAML with title:
    # Pandoc renders: title block → --toc TOC → $body$
    safe_title = title.replace('"', '\\"')
    yaml_block = f'---\ntitle: "{safe_title}"\n---\n\n'

    return yaml_block + content


def _get_word_reference_doc(pandoc_tmp: Path) -> Path | None:
    """
    Return path to Word reference .docx for --reference-doc flag.

    Priority:
        1. assets/reference.docx  — project-level custom template
        2. Pandoc default          — generated once and cached in pandoc_tmp

    The reference doc controls heading styles, fonts, margins, and TOC style.
    To customise: run `pandoc --print-default-data-file reference.docx > assets/reference.docx`
    then edit styles in Word.

    Returns None on any failure — caller omits --reference-doc flag.
    """
    custom = BASE_DIR / "assets" / "reference.docx"
    if custom.exists():
        logger.info(f"Using custom Word reference doc: {custom}")
        return custom

    cached = pandoc_tmp / "reference.docx"
    if cached.exists():
        return cached

    try:
        import subprocess
        from docx import Document as DocxDocument
        from docx.shared import Pt
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        with open(cached, "wb") as f:
            subprocess.run(
                ["pandoc", "--print-default-data-file", "reference.docx"],
                stdout=f,
                check=True,
            )

        # Override the default font for all styles.
        # Modifying the document-level default (w:docDefaults) ensures
        # every style that doesn't explicitly set a font inherits TNR.
        ref_doc = DocxDocument(cached) # type: ignore

        # 1. Patch w:docDefaults → rPrDefault → rPr → w:rFonts
        styles_element = ref_doc.styles.element
        doc_defaults = styles_element.find(qn("w:docDefaults"))
        if doc_defaults is not None:
            rpr_default = doc_defaults.find(qn("w:rPrDefault"))
            if rpr_default is None:
                rpr_default = OxmlElement("w:rPrDefault")
                doc_defaults.append(rpr_default)
            rpr = rpr_default.find(qn("w:rPr"))
            if rpr is None:
                rpr = OxmlElement("w:rPr")
                rpr_default.append(rpr)
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = OxmlElement("w:rFonts")
                rpr.insert(0, rfonts)
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rfonts.set(qn(attr), _document_font())

        # 2. Patch Normal style explicitly as a safety net
        for style in ref_doc.styles:
            if style.name == "Normal":
                from docx.styles.style import _ParagraphStyle
                if isinstance(style, _ParagraphStyle):
                    style.font.name = _document_font()
                    style.font.size = Pt(12)
                break

        # 3. Set "TOC Heading" style to page-break-before.
        # Pandoc renders: Title paragraph → TOC Heading → TOC entries → $body$.
        # Without this, the title and TOC share the same page.
        # w:pageBreakBefore on TOC Heading forces title onto its own page.
        for style in ref_doc.styles:
            if style.name == "TOC Heading":
                pPr = style.element.get_or_add_pPr()
                pb = OxmlElement("w:pageBreakBefore")
                pb.set(qn("w:val"), "true")
                pPr.append(pb)
                logger.info("✓ TOC Heading style patched with page break before")
                break

        ref_doc.save(cached)  # type: ignore
        logger.info("✓ reference.docx generated with %s default font", _document_font())
        return cached
    except Exception as e:
        logger.warning(f"Could not generate reference.docx: {e} — using Pandoc built-in default")
        return None
# ---------------------------------------------------------------------------
# Typst front-matter constants
#
# Page structure assembled in publish_curriculum():
#
#   _TYPST_SETUP_BLOCK         — global show/set rules applied from page 1
#   _build_title_block(title)  — vertically + horizontally centred title page
#   _TYPST_TOC_BLOCK           — Mục lục page (numbering still none)
#   [_TYPST_FIGURE_LIST_BLOCK] — Danh mục hình (optional, numbering none)
#   _TYPST_START_NUMBERING     — enable Arabic page numbers, reset to 1
#   body content               — Lời nói đầu = page 1, chapters follow
# ---------------------------------------------------------------------------


# Global show/set rules applied once at document start.
# Placed before the title block so the rules cover every page including title.
# Page numbering is disabled here and re-enabled by _TYPST_START_NUMBERING
# just before the body content.
_TYPST_SETUP_BLOCK = (
    "```{=typst}\n"
    "#show heading.where(level: 1): it => align(center, it)\n"
    "#set figure(numbering: none)\n"   # disable "Figure X:" prefix globally
    "#set page(numbering: none)\n"     # title + TOC + figure list: no page numbers
    "```"
)


def _build_title_block(title: str) -> str:
    """
    Build a Typst raw block that renders the textbook title centred both
    horizontally and vertically on its own page.

    Does NOT call #set page() — any #set page() call inside Pandoc's $body$
    context unconditionally flushes the current page, creating a blank page 1.
    Page numbering suppression for front matter is handled upstream via
    --include-in-header in publish_curriculum(), which injects into the
    Pandoc template preamble where #set page() runs without causing a flush.
    """
    safe_title = _typst_string_literal(title)
    return (
        "```{=typst}\n"
        "#show heading.where(level: 1): it => align(center, it)\n"
        "#set figure(numbering: none)\n"
        "#v(1fr)\n"
        "#align(center)[\n"
        f'  #text({safe_title}, weight: "bold", size: 2em)\n'
        "]\n"
        "#v(1fr)\n"
        "#pagebreak()\n"
        "```"
    )
def _build_typst_toc_block(label: str) -> str:
    safe_label = _typst_string_literal(label)
    return (
        "```{=typst}\n"
        "#v(1em)\n"
        "#align(center)[\n"
        f'  #text({safe_label}, weight: "bold", size: 1.4em)\n'
        "]\n"
        "#v(0.5em)\n"
        "#outline(title: none, indent: auto)\n"
        "```"
    )


def _build_typst_figure_list_block(label: str) -> str:
    safe_label = _typst_string_literal(label)
    return (
        "```{=typst}\n"
        "#pagebreak()\n"
        "#v(1em)\n"
        "#align(center)[\n"
        f'  #text({safe_label}, weight: "bold", size: 1.4em)\n'
        "]\n"
        "#v(0.5em)\n"
        "#outline(\n"
        "  title: none,\n"
        "  target: figure.where(kind: image),\n"
        ")\n"
        "```"
    )

# Numbering start block — injected immediately before body content.
# NO explicit #pagebreak() here: #set page() in Typst already triggers an
# implicit page flush to apply the new settings, so combining it with an
# explicit #pagebreak() produces a double transition = one blank page.
# The implicit flush from #set page() is sufficient to break from the last
# front-matter page (TOC or figure list) to the body.
_TYPST_START_NUMBERING = (
    "```{=typst}\n"
    '#set page(numbering: "1")\n'
    "#counter(page).update(1)\n"
    "```"
)


# ---------------------------------------------------------------------------
# Publisher node
# ---------------------------------------------------------------------------

def publish_curriculum(state: AgentState) -> dict:
    """
    Publisher node: assemble, fix, and export the complete textbook document.

    Workflow position: final node — called once after all chapters are written.

    Input fields read from state:
        final_content       — accumulated body (all subsections except the last)
        current_content     — last subsection buffer (bypassed checkpoints)
        preface_content     — Lời nói đầu Markdown from Planner
        request             — user topic string (used for filename)
        textbook_title      — formal Vietnamese title from Planner
        enable_images       — controls Danh mục hình inclusion

    Processing pipeline:
        1.  Merge final_content + current_content
        2.  Prepend preface with LaTeX artifact stripping
        3.  CRLF → LF normalization (LLM responses may use Windows line endings)
        4.  fix_unicode_math()          — Unicode sub/superscripts → $math$
        5.  fix_programming_inline_code() — code-like $...$ → `...`
        6.  normalize_english_dashes()  — English em/en dashes → ASCII hyphen
        7.  fix_markdown_headings()     — headings on own lines
        8.  fix_inline_display_math()   — trivial $$ blocks → inline $
        9.  fix_math_formatting()       — Typst-compatible math
        10. fix_typst_deprecated_symbols() — times.circle → times.o
        11. fix_chapter_pagebreaks()    — #pagebreak() before # CHƯƠNG
        12. add_figure_numbers()        — "Hình X.Y.N:"
        13. Assemble front matter:
                _TYPST_SETUP_BLOCK
                _build_title_block()   — vertically+horizontally centred title
                _TYPST_TOC_BLOCK
                [_TYPST_FIGURE_LIST_BLOCK]
                _TYPST_PAGEBREAK
                _TYPST_START_NUMBERING → page 1 = Lời nói đầu
                body content
        14. Save .md file
        15. Pandoc → Typst → PDF and Pandoc → DOCX exports
        16. cleanup_temp_images() in finally block

    Page numbering:
        Title page     — no number
        TOC            — no number
        Danh mục hình  — no number (optional)
        Lời nói đầu   — page 1  ← numbering starts here
        Chapters       — continue from page 1

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update with explicit Markdown/PDF/DOCX artifact paths.
    """
    logger.info("=" * 60)
    logger.info("NODE: Publisher - Finalizing document")
    logger.info("=" * 60)
    language = state.get("language", "vi")
    profile = get_language_profile(language)

    # ------------------------------------------------------------------
    # Step 1 — Merge content buffers
    #
    # The last subsection bypasses the checkpoint nodes (it goes directly
    # from Illustrator to Publisher via WorkflowDecision.FINISHED), so
    # current_content is never accumulated into final_content.
    # Publisher must manually merge the two.
    # ------------------------------------------------------------------
    current = state.get("current_content", "")
    final   = state.get("final_content", "")
    full_content = (
        final + "\n\n" + current if (final and current) else (final or current)
    )

    if not full_content:
        logger.error("No content found to publish")
        return {
            "messages": ["✗ Publisher failed: No content to publish"],
            "final_filepath": None,
            "final_markdown_filepath": None,
            "final_pdf_filepath": None,
            "final_docx_filepath": None,
            "export_errors": {"publisher": "No content to publish"},
        }

    # ------------------------------------------------------------------
    # Step 2 — Prepend preface with LaTeX artifact stripping
    #
    # Older Planner prompts produced preface with \begin{center}...\end{center}
    # LaTeX blocks. The current prompt generates plain Markdown, but the
    # stripping passes are kept as a safety net for any residual artifacts.
    # ------------------------------------------------------------------
    preface = state.get("preface_content", "")
    if preface:
        # Strip \newpage / \clearpage commands
        preface_clean = re.sub(
            r'^\s*\\(new|clear)page\s*', '', preface, count=1
        ).lstrip()

        # Strip LaTeX environments: \begin{...}...\end{...}
        preface_clean = re.sub(
            r'\\begin\{[^}]+\}.*?\\end\{[^}]+\}',
            '',
            preface_clean,
            flags=re.DOTALL,
        )

        # Strip remaining LaTeX commands: \command{args} or standalone \command
        preface_clean = re.sub(r'\\[A-Za-z]+(?:\{[^}]*\})*', '', preface_clean)

        # Collapse blank lines left by stripping
        preface_clean = re.sub(r'\n{3,}', '\n\n', preface_clean).strip()

        full_content = f"# {profile.preface_heading}\n\n" + preface_clean + "\n\n" + full_content
        logger.info("✓ Preface cleaned and prepended")

    # ------------------------------------------------------------------
    # Step 3 — Output path setup
    # ------------------------------------------------------------------
    raw_topic     = state.get("request", "Textbook")
    request_topic = sanitize_filename(raw_topic)
    output_dir    = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base     = f"{request_topic}_{timestamp}"
    md_filename   = output_dir / f"{file_base}.md"
    pdf_filename  = output_dir / f"{file_base}.pdf"
    docx_filename = output_dir / f"{file_base}.docx"
    # ------------------------------------------------------------------
    # Step 4 — YAML header (metadata only — title rendered by Typst block)
    #
    # title-meta: sets the PDF document metadata title without triggering
    # Pandoc's default title-block rendering. The visual title is handled
    # by _build_title_block() with proper vertical centering.
    # ------------------------------------------------------------------
    title = state.get("textbook_title") or state.get("request", profile.default_title_prefix)
    yaml_header = (
        f'---\n'
        f'title-meta: {_typst_string_literal(title)}\n'
        f'fontsize: 12pt\n'
        f'mainfont: {_typst_string_literal(_document_font())}\n'
        f'---\n\n'
    )

    # ------------------------------------------------------------------
    # Step 5 — CRLF normalization
    # Must run before all fix_* passes — regex patterns assume Unix LF only.
    # ------------------------------------------------------------------
    full_content = full_content.replace('\r\n', '\n').replace('\r', '\n')

    # ------------------------------------------------------------------
    # Step 6 — Fix passes (applied in dependency order)
    # ------------------------------------------------------------------
    full_content = fix_unicode_math(full_content)
    full_content = fix_programming_inline_code(full_content)
    if language == "en":
        full_content = normalize_english_dashes(full_content)
    full_content = fix_markdown_headings(full_content)
    full_content = fix_inline_display_math(full_content)
    full_content = fix_math_formatting(full_content)
    full_content = fix_typst_deprecated_symbols(full_content)
    full_content = fix_chapter_pagebreaks(full_content, language=language)
    full_content = add_figure_numbers(full_content, language=language)
    logger.info("✓ All fix passes applied")

    # ------------------------------------------------------------------
    # Step 7 — Assemble front matter + body
    # ------------------------------------------------------------------
    front_matter = (
        _build_title_block(title)
        + "\n\n" + _build_typst_toc_block(profile.toc_label)
    )
    if state.get("enable_images", True):
        front_matter += "\n\n" + _build_typst_figure_list_block(profile.figure_list_label)

    full_content = (
        front_matter
        + "\n\n" + _TYPST_START_NUMBERING
        + "\n\n" + full_content
    )
    logger.info(
        f"✓ Front matter assembled (title centred, page 1 = {profile.preface_heading})"
    )

    # Final safety pass: ensure no heading is directly preceded by a non-blank line
    final_document = yaml_header + full_content
    safe_document  = re.sub(r'([^\n])\n(#+ )', r'\1\n\n\2', final_document)

    # ------------------------------------------------------------------
    # Step 8 — Save Markdown
    # ------------------------------------------------------------------
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(safe_document)
        logger.info(f"✓ Markdown saved: {md_filename}")
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}", exc_info=True)
        cleanup_temp_images()
        return {
            "messages": ["✗ Publisher failed: Could not save Markdown"],
            "final_filepath": None,
            "final_markdown_filepath": None,
            "final_pdf_filepath": None,
            "final_docx_filepath": None,
            "export_errors": {"markdown": str(e)},
        }

    # ------------------------------------------------------------------
    # Step 9 — Export: PDF and/or Word based on state["export_formats"]
    # ------------------------------------------------------------------
    export_formats: list[str] = state.get("export_formats", ["PDF"])   # type: ignore
    want_pdf  = "PDF"  in export_formats
    want_word = "Word" in export_formats

    final_markdown_filepath: str | None = str(md_filename)
    final_pdf_filepath: str | None = None
    final_docx_filepath: str | None = None
    export_errors: dict[str, str] = {}

    if pypandoc and (want_pdf or want_word):
        pandoc_tmp = BASE_DIR / ".pandoc_tmp"
        pandoc_tmp.mkdir(exist_ok=True)
        typst_root = BASE_DIR.anchor

        # Inject #set page(numbering: none) into Pandoc preamble via header file.
        # This prevents blank page 1: #set page() in preamble applies in-place,
        # while #set page() inside $body$ always flushes the current page first.
                # Override Pandoc's conf() function to remove hardcoded numbering: "1".
        # conf() in template.typst has numbering: "1" hardcoded — no variable exists
        # to suppress it from outside. Re-defining conf with numbering: none before
        # the #show: doc => conf(...) call lets our Typst blocks control numbering.
        typst_header_file = pandoc_tmp / "typst_header.typ"
        # Override Pandoc's conf() to remove hardcoded numbering: "1".
        # ..args sink absorbs any unknown parameters Pandoc may add in future
        # versions (e.g. abstract-title in newer Pandoc releases) without
        # requiring updates here when Pandoc is upgraded.
        typst_header_file = pandoc_tmp / "typst_header.typ"
        typst_header_file.write_text(
            textwrap.dedent("""\
                #let conf(
                  title: none,
                  authors: none,
                  date: none,
                  abstract: none,
                  cols: 1,
                  margin: (x: 1.25in, y: 1.25in),
                  paper: "us-letter",
                  lang: "en",
                  region: "US",
                  font: (),
                  fontsize: 11pt,
                  sectionnumbering: none,
                  doc,
                  ..args,
                ) = {
                  set page(
                    paper: paper,
                    margin: margin,
                    numbering: none,
                  )
                  set par(justify: true)
                  set text(lang: lang,
                           region: region,
                           font: font,
                           size: fontsize)
                  set heading(numbering: sectionnumbering)
                  if cols == 1 { doc } else { columns(cols, doc) }
                }
            """),
            encoding="utf-8",
        )

        _old_env: dict[str, str | None] = {}
        try:
            _old_env = {k: os.environ.get(k) for k in ("TEMP", "TMP")}
            os.environ["TEMP"] = str(pandoc_tmp)
            os.environ["TMP"]  = str(pandoc_tmp)

            # ── PDF ──────────────────────────────────────────────────
            if want_pdf:
                typst_bin = shutil.which("typst") or "typst"
                logger.info(f"Converting to PDF (Typst engine: {typst_bin})...")
                try:
                    pypandoc.convert_file(
                        str(md_filename),
                        to="pdf",
                        outputfile=str(pdf_filename),
                        extra_args=[
                            f"--pdf-engine={typst_bin}",
                            "--pdf-engine-opt=--root",
                            f"--pdf-engine-opt={typst_root}",
                            "--include-in-header", str(typst_header_file),
                            "-V", "margin-left=2.5cm",
                            "-V", "margin-right=2.5cm",
                            "-V", "margin-top=2cm",
                            "-V", "margin-bottom=2cm",
                        ],
                    )
                    if not _valid_artifact(pdf_filename, ".pdf"):
                        raise RuntimeError("Pandoc returned without creating a valid PDF file")
                    logger.info(f"✓ PDF saved: {pdf_filename}")
                    final_pdf_filepath = str(pdf_filename)
                except Exception as e:
                    export_errors["pdf"] = str(e)
                    logger.warning(f"PDF generation failed: {e}", exc_info=True)

            # ── Word (.docx) ──────────────────────────────────────────
            if want_word:
                logger.info("Converting to Word (.docx)...")
                try:
                    # Pre-process MD: strip Typst blocks, inject page breaks,
                    # fix title and image widths for Word rendering.
                    word_md_content = _prepare_word_md(
                        safe_document,
                        title,
                        enable_images=bool(state.get("enable_images", True)),
                        language=language,
                    )

                    docx_md = pandoc_tmp / f"{file_base}_word.md"
                    docx_md.write_text(word_md_content, encoding="utf-8")
                    logger.info("✓ Word MD pre-processed")

                    # --toc: Pandoc builds TOC natively, placed after title block
                    # --toc-depth=3: include ##, ### headings
                    word_args = ["--toc", "--toc-depth=3"]
                    ref_doc = _get_word_reference_doc(pandoc_tmp)
                    if ref_doc:
                        word_args += ["--reference-doc", str(ref_doc)]

                    pypandoc.convert_file(
                        str(docx_md),
                        to="docx",
                        outputfile=str(docx_filename),
                        extra_args=word_args,
                    )
                    if not _valid_artifact(docx_filename, ".docx"):
                        raise RuntimeError("Pandoc returned without creating a valid DOCX file")
                    logger.info(f"✓ Word saved: {docx_filename}")
                    final_docx_filepath = str(docx_filename)

                except Exception as e:
                    export_errors["docx"] = str(e)
                    logger.warning(f"Word generation failed: {e}", exc_info=True)

        finally:
            for k, v in _old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(pandoc_tmp, ignore_errors=True)
            cleanup_temp_images()

    else:
        if not pypandoc:
            logger.warning("pypandoc not installed — skipping all export")
            if want_pdf:
                export_errors["pdf"] = "pypandoc is not installed"
            if want_word:
                export_errors["docx"] = "pypandoc is not installed"
        cleanup_temp_images()

    messages = [f"✓ Markdown saved: {os.path.basename(final_markdown_filepath)}"]
    if final_pdf_filepath:
        messages.append(f"✓ PDF export: {os.path.basename(final_pdf_filepath)}")
    if final_docx_filepath:
        messages.append(f"✓ Word export: {os.path.basename(final_docx_filepath)}")
    for artifact, error in export_errors.items():
        messages.append(f"✗ {artifact.upper()} export failed: {error}")

    return {
        "messages":             messages,
        # Compatibility alias: historically named `final_filepath`, but it is
        # now strictly PDF-only and never falls back to Markdown or DOCX.
        "final_filepath":       final_pdf_filepath,
        "final_markdown_filepath": final_markdown_filepath,
        "final_pdf_filepath":   final_pdf_filepath,
        "final_docx_filepath":  final_docx_filepath,
        "export_errors":        export_errors,
    }
