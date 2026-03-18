"""
Publisher Agent for AI Textbook Generator.

This agent finalizes the generated content by:
1. Merging accumulated content + last subsection buffer
2. Prepending the preface (Lời nói đầu) with LaTeX artifact stripping
3. Normalizing line endings and applying fix passes (math, headings, pagebreaks)
4. Assembling the Typst front matter (title page, TOC, figure list, numbering)
5. Saving the Markdown source file
6. Converting to PDF via Pandoc → Typst engine (falls back to .md if unavailable)
7. Cleaning up temporary image files (always, via finally block)

PDF pipeline: Pandoc → Typst (not xelatex).
Math delimiters: Pandoc-compatible $...$ and $$...$$ consumed by Typst's renderer.

Page structure:
    Title page     — centered vertically + horizontally, no page number
    TOC            — no page number
    Danh mục hình  — no page number (optional, when enable_images=True)
    Lời nói đầu   — page 1  ← numbering starts here
    CHƯƠNG 1 …    — continues from page 1
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
import re

try:
    import pypandoc
except ImportError:
    pypandoc = None

from src.graph.state import AgentState
from src.config import BASE_DIR
from src.log_config import setup_logger

logger = setup_logger(name="PublisherAgent", logfile="logs/agents.log")

# Temporary image directory — created by Illustrator, cleaned up by Publisher.
image_dir = BASE_DIR / "outputs" / "images"


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

    Leading/trailing whitespace on the content line is tolerated (BUG-12 fix).

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

    # BUG-12 FIX: allow optional leading/trailing whitespace on the content line
    return re.sub(
        r'\$\$\n[ \t]*([^\n]{1,40?})[ \t]*\n[ \t]*\$\$',
        maybe_inline,
        content,
    )


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

    BUG-03 FIX: clean_display_block's while loop now has a max_iter=10 cap
    to prevent infinite spin on pathological LaTeX input (e.g. unclosed $ chars).
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


def fix_typst_deprecated_symbols(content: str) -> str:
    """
    Replace deprecated Typst math symbol names with their current equivalents.

    Applied before Pandoc conversion to eliminate compiler warnings that
    appear in the Typst output even when the PDF renders correctly.

    Replacements:
        times.circle → times.o  (tensor product ⊗, renamed in Typst ≥ 0.12)
    """
    return content.replace("times.circle", "times.o")


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


def fix_chapter_pagebreaks(content: str) -> str:
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

    def insert_break(m: re.Match) -> str:
        return m.group(1) + pb + m.group(2)

    return re.sub(r'(\n\n)(# CHƯƠNG )', insert_break, content)


def add_figure_numbers(content: str) -> str:
    """
    Prefix image captions with section-scoped figure numbers.

    Tracks the current ## X.Y and ### X.Y.Z heading as images are encountered
    and prefixes each caption with "Hình X.Y.N:" or "Hình X.Y.Z.N:".

    Behaviour:
        - Idempotent: captions already starting with "Hình [digits]" are skipped.
        - Images before the first ## heading are left unchanged.
        - Counter resets to 1 when the tracked section changes.

    BUG-08 FIX: regex group 2 changed from `(.*?)` (non-greedy, breaks on
    captions containing `](`) to `([^\\]]*?)` (excludes `]`, correct for
    standard Pandoc Markdown figure syntax).
    """
    lines = content.split('\n')
    result: list[str] = []
    current_section   = ""
    section_img_count: dict[str, int] = {}

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

        # BUG-08 FIX: use [^\]]* for caption group instead of non-greedy .*?
        img_match = re.match(r'^(!\[)([^\]]*?)(\]\()(.+?)(\))(\{.*?\})?$', line)
        if img_match and current_section:
            caption = img_match.group(2)
            path    = img_match.group(4)
            attrs   = img_match.group(6) or ""

            if not re.match(r'^Hình \d[\d.]*:', caption):
                section_img_count[current_section] = (
                    section_img_count.get(current_section, 0) + 1
                )
                n       = section_img_count[current_section]
                caption = f"Hình {current_section}.{n}: {caption}"
                line    = f"![{caption}]({path}){attrs}"

        result.append(line)

    return '\n'.join(result)


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
    safe_title = title.replace('"', '\\"')
    return (
        "```{=typst}\n"
        "#show heading.where(level: 1): it => align(center, it)\n"
        "#set figure(numbering: none)\n"
        "#v(1fr)\n"
        "#align(center)[\n"
        f'  #text(weight: "bold", size: 2em)[{safe_title}]\n'
        "]\n"
        "#v(1fr)\n"
        "#pagebreak()\n"
        "```"
    )
# TOC page — rendered after the title page (numbering still none).
_TYPST_TOC_BLOCK = (
    "```{=typst}\n"
    "#v(1em)\n"
    "#align(center)[\n"
    '  #text(weight: "bold", size: 1.4em)[Mục lục]\n'
    "]\n"
    "#v(0.5em)\n"
    "#outline(title: none, indent: auto)\n"
    "```"
)

# Figure list page — only included when enable_images=True.
# Numbering is still none (inherited from _TYPST_SETUP_BLOCK).
_TYPST_FIGURE_LIST_BLOCK = (
    "```{=typst}\n"
    "#pagebreak()\n"
    "#v(1em)\n"
    "#align(center)[\n"
    '  #text(weight: "bold", size: 1.4em)[Danh mục hình]\n'
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
        5.  fix_markdown_headings()     — headings on own lines
        6.  fix_inline_display_math()   — trivial $$ blocks → inline $
        7.  fix_math_formatting()       — Typst-compatible math (BUG-03 fixed)
        8.  fix_typst_deprecated_symbols() — times.circle → times.o
        9.  fix_chapter_pagebreaks()    — #pagebreak() before # CHƯƠNG (BUG-13)
        10. add_figure_numbers()        — "Hình X.Y.N:" prefixes (BUG-08)
        11. Assemble front matter:
                _TYPST_SETUP_BLOCK
                _build_title_block()   — vertically+horizontally centred title
                _TYPST_TOC_BLOCK
                [_TYPST_FIGURE_LIST_BLOCK]
                _TYPST_PAGEBREAK
                _TYPST_START_NUMBERING → page 1 = Lời nói đầu
                body content
        12. Save .md file
        13. Pandoc → Typst → PDF  (falls back to .md if pypandoc unavailable)
        14. cleanup_temp_images() in finally block

    Page numbering:
        Title page     — no number
        TOC            — no number
        Danh mục hình  — no number (optional)
        Lời nói đầu   — page 1  ← numbering starts here
        Chapters       — continue from page 1

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update with "final_filepath" and "messages".
    """
    logger.info("=" * 60)
    logger.info("NODE: Publisher - Finalizing document")
    logger.info("=" * 60)

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

        full_content = "# Lời nói đầu\n\n" + preface_clean + "\n\n" + full_content
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

    # ------------------------------------------------------------------
    # Step 4 — YAML header (metadata only — title rendered by Typst block)
    #
    # title-meta: sets the PDF document metadata title without triggering
    # Pandoc's default title-block rendering. The visual title is handled
    # by _build_title_block() with proper vertical centering.
    # ------------------------------------------------------------------
    title = state.get("textbook_title") or state.get("request", "Giáo trình")
    yaml_header = (
        f'---\n'
        f'title-meta: "{title}"\n'
        f'fontsize: 12pt\n'
        f'mainfont: "Times New Roman"\n'
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
    full_content = fix_markdown_headings(full_content)
    full_content = fix_inline_display_math(full_content)
    full_content = fix_math_formatting(full_content)
    full_content = fix_typst_deprecated_symbols(full_content)
    full_content = fix_chapter_pagebreaks(full_content)   
    full_content = add_figure_numbers(full_content)        
    logger.info("✓ All fix passes applied")

    # ------------------------------------------------------------------
    # Step 7 — Assemble front matter + body
    # ------------------------------------------------------------------
    front_matter = (
        _build_title_block(title)
        + "\n\n" + _TYPST_TOC_BLOCK
    )
    if state.get("enable_images", True):
        front_matter += "\n\n" + _TYPST_FIGURE_LIST_BLOCK

    full_content = (
        front_matter
        + "\n\n" + _TYPST_START_NUMBERING
        + "\n\n" + full_content
    )
    logger.info("✓ Front matter assembled (title centred, page 1 = Lời nói đầu)")

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
        }

    # ------------------------------------------------------------------
    # Step 9 — Pandoc → Typst → PDF conversion
    # ------------------------------------------------------------------
    result_filepath = str(md_filename)

    if pypandoc:
        pandoc_tmp = BASE_DIR / ".pandoc_tmp"
        pandoc_tmp.mkdir(exist_ok=True)
        typst_root = BASE_DIR.anchor

        # Inject #set page(numbering: none) into Pandoc's template PREAMBLE
        # (before $body$) via --include-in-header. This suppresses Pandoc's
        # default numbering: "1" on front-matter pages WITHOUT causing a page
        # flush — preamble #set page() applies in-place, body #set page() flushes.
        typst_header_file = pandoc_tmp / "typst_header.typ"
        typst_header_file.write_text(
            "#set page(numbering: none)\n",
            encoding="utf-8",
        )

        _old_env: dict[str, str | None] = {}
        try:
            # Redirect TEMP/TMP so Pandoc/Typst write scratch files inside
            # our controlled directory rather than the system temp folder.
            _old_env = {k: os.environ.get(k) for k in ("TEMP", "TMP")}
            os.environ["TEMP"] = str(pandoc_tmp)
            os.environ["TMP"]  = str(pandoc_tmp)

            typst_bin = shutil.which("typst") or "typst"
            logger.info(f"Converting to PDF (Typst engine: {typst_bin})...")
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
            logger.info(f"✓ PDF saved: {pdf_filename}")
            result_filepath = str(pdf_filename)

        except Exception as e:
            logger.warning(f"PDF generation failed: {e}", exc_info=True)
            logger.info("Falling back to Markdown output only")

        finally:
            # Restore original env vars and clean up scratch directory.
            # cleanup_temp_images() is always called here — not in the else
            # branch below — so images are removed regardless of PDF success.
            for k, v in _old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(pandoc_tmp, ignore_errors=True)
            cleanup_temp_images()
    else:
        logger.warning("pypandoc not installed — skipping PDF generation")
        cleanup_temp_images()

    return {
        "messages": [f"✓ Document finalized: {os.path.basename(result_filepath)}"],
        "final_filepath": result_filepath,
    }