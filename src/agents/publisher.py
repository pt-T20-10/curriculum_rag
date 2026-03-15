"""
Publisher Agent for AI Textbook Generator.

This agent finalizes the generated content by:
1. Adding LaTeX/YAML headers for PDF compilation
2. Saving Markdown file
3. Converting to PDF via Pandoc
4. Cleaning up temporary image resources (always, via finally block)
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
image_dir = BASE_DIR / "outputs" / "images"

def cleanup_temp_images() -> None:
    """
    Clean up temporary images directory after export.
    
    Called in finally block to guarantee execution regardless of
    whether PDF generation succeeded or fell back to Markdown.
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
    Sanitize user input for safe use as filename.
    
    - Remove all characters except alphanumeric, spaces, hyphens
    - Replace spaces with underscores
    - Truncate to max_length
    - Fallback to 'Textbook' if result is empty after sanitization
    
    Args:
        name: Raw filename string (typically from user request)
        max_length: Maximum character length
        
    Returns:
        Safe filename string.
    """
    safe = re.sub(r'[^\w\s\-]', '', name)
    safe = safe.strip().replace(' ', '_')
    safe = safe[:max_length]
    return safe if safe else "Textbook"


SUBSCRIPT_MAP = {
    '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4',
    '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9',
}
SUPERSCRIPT_MAP = {
    '⁺': '+', '⁻': '-', '⁰': '0', '¹': '1', '²': '2', '³': '3',
    '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', 'ⁿ': 'n',
}


def fix_unicode_math(content: str) -> str:
    """
    Convert Unicode subscript/superscript characters to LaTeX math equivalents.

    Times New Roman does not include Unicode sub/superscript chars (₂ U+2082,
    ⁺ U+207A, etc.) — xelatex emits 'Missing character' warnings and renders
    them as □ boxes in the PDF.

    Applied as a safety net BEFORE fix_math_formatting() so any Unicode chars
    the LLM generates are converted before further math processing.

    Examples:
        H₂O    → H$_2$O
        CO₂    → CO$_2$
        Na⁺    → Na$^+$
        Cl⁻    → Cl$^-$
        1s²    → 1s$^2$
        H₂SO₄ → H$_2$SO$_4$
    """
    result: list[str] = []
    i = 0
    while i < len(content):
        ch = content[i]
        if ch in SUBSCRIPT_MAP:
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
        logger.info("✓ Unicode math characters converted to LaTeX")
    return converted


_COMPLEX_MATH_RE = re.compile(
    r'\\(?:frac|int|sum|prod|lim|begin|end|sqrt|left|right|binom|matrix|pmatrix|cases)'
)


def fix_inline_display_math(content: str) -> str:
    """
    Convert simple $$ display math blocks to inline $ math.

    The LLM sometimes wraps single variables or short expressions in display
    math ($$...$$) when they appear in the middle of prose sentences. This
    causes them to render as centered block equations instead of staying
    inline with the surrounding text.

    Examples:
        $$\\nf(x)\\n$$        →  $f(x)$
        $$\\nQ_s\\n$$         →  $Q_s$
        $$\\n\\frac{a}{b}\\n$$  →  (kept as display — complex)
    """
    def maybe_inline(m: re.Match) -> str:
        expr = m.group(1).strip()
        if _COMPLEX_MATH_RE.search(expr):
            return m.group(0)
        if len(expr) > 40:
            return m.group(0)
        return f'${expr}$'

    return re.sub(
        r'\$\$\n([^\n]{1,40})\n[ \t]*\$\$',
        maybe_inline,
        content
    )


_TYPST_PAGEBREAK = "```{=typst}\n#pagebreak()\n```"

# ---------------------------------------------------------------------------
# Typst front-matter blocks
# ---------------------------------------------------------------------------

# TOC block — global show/set rules + Mục lục page.
#
# Page numbering strategy:
#   • Title page (YAML-generated):  no number  ← #set page(numbering: none)
#   • TOC + Danh mục hình pages:    no number  ← numbering still none here
#   • Lời nói đầu onward:           1, 2, 3…   ← enabled by _TYPST_START_NUMBERING
#
# The #set page(numbering: none) here covers the title page AND the TOC/figure
# list pages that follow — _TYPST_START_NUMBERING re-enables it just before
# the first body page (Lời nói đầu).
_TYPST_TOC_BLOCK = (
    "```{=typst}\n"
    "#show heading.where(level: 1): it => align(center, it)\n"
    "#set figure(numbering: none)\n"          # disable "Figure X:" prefix
    "#set page(numbering: none)\n"            # title page + TOC: no page numbers
    "#pagebreak()\n"
    "#v(1em)\n"
    "#align(center)[\n"
    '  #text(weight: "bold", size: 1.4em)[Mục lục]\n'
    "]\n"
    "#v(0.5em)\n"
    "#outline(title: none, indent: auto)\n"
    "```"
)

# Figure-list block — only included when enable_images=True.
# Inherits numbering: none from _TYPST_TOC_BLOCK (still in front-matter).
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
# Placed after the last front-matter #pagebreak() so page 1 = Lời nói đầu.
_TYPST_START_NUMBERING = (
    "```{=typst}\n"
    '#set page(numbering: "1")\n'             # enable Arabic numbering
    "#counter(page).update(1)\n"              # reset counter → page 1
    "```"
)


def fix_markdown_headings(content: str) -> str:
    """
    Ensure ## and ### headings always appear on their own lines.

    When the LLM hits token limits near the end of a long section, it may
    emit headings inline without proper newline separators:
        '...sentence.## 5.2 Title ### 5.2.1 Sub Content...'
    """
    content = re.sub(
        r'([^\n])\s*(#{2,3} \d)',
        r'\1\n\n\2',
        content
    )
    content = re.sub(
        r'^(#{2,3} [^\n]+)\n(?!\n)',
        r'\1\n\n',
        content,
        flags=re.MULTILINE
    )
    return content


def fix_chapter_pagebreaks(content: str) -> str:
    """
    Insert a Typst #pagebreak() before each level-1 heading (# CHƯƠNG N or # Lời nói đầu).

    Only inserts a break when content precedes the heading (i.e., the heading
    is not the very first element). This ensures each chapter and the preface
    start on a fresh page.
    """
    pb = _TYPST_PAGEBREAK + "\n\n"

    def insert_break(m: re.Match) -> str:
        return m.group(1) + pb + m.group(2)

    return re.sub(r'(\n\n)(# )', insert_break, content)


def fix_math_formatting(content: str) -> str:
    """
    Fix common math formatting issues that cause xelatex compilation errors.

    Problems addressed (in order of application):
    1. Nested $ inside $$ blocks
    2. Partial nesting — leading/trailing text stuck inside $$
    3. $ [...] — space between $ and [
    4. Blank lines inside $$ blocks
    5. Stray single $ at start of line
    6. Multiline inline $...$
    7. Lone inline $var$ surrounded by blank lines
    """
    def clean_display_block(m: re.Match) -> str:
        inner = m.group(1)
        prev = None
        while prev != inner:
            prev = inner
            inner = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)', r'\1', inner)
        lines = inner.split('\n')
        lines = [l for l in lines if l.strip() != '']
        inner = '\n' + '\n'.join(lines) + '\n'
        return f'$$\n{inner.strip()}\n$$'

    content = re.sub(
        r'\$\$\n(.*?)\n[ \t]*\$\$',
        clean_display_block,
        content,
        flags=re.DOTALL
    )
    content = re.sub(r'\$\s+\[', '$[', content)
    content = re.sub(r'\]\s+\$', ']$', content)
    content = re.sub(
        r'(?<!\$)\$ +([^$\n]+?) +\$(?!\$)',
        lambda m: '$' + m.group(1).strip() + '$',
        content
    )
    content = re.sub(
        r'^(\$)(\\[a-zA-Z]+(?:\{[^}]*\})*)$',
        r'$$\n\2\n$$',
        content,
        flags=re.MULTILINE
    )
    content = re.sub(
        r'(?<!\$)\$(?!\$)([^$\n]{0,60}?)\n([^$\n]{0,60}?)\$(?!\$)',
        lambda m: '$' + m.group(1).rstrip() + ' ' + m.group(2).lstrip() + '$',
        content
    )
    content = re.sub(r'\n\n(\$(?!\$)[^$\n]+\$(?!\$))\n\n', r'\n\1\n', content)
    return content


def add_figure_numbers(content: str) -> str:
    """
    Post-process assembled markdown to prefix image captions with section numbers.

    Tracks ## X.Y and ### X.Y.Z headings; numbers images per-section starting at 1.
    Format: "Hình X.Y.N: original caption" or "Hình X.Y.Z.N: original caption"

    Idempotent — skips captions already starting with "Hình [digits]".
    Images before the first ## heading are left unchanged.
    """
    lines = content.split('\n')
    result = []
    current_section = ""
    section_img_count: dict = {}

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

        img_match = re.match(r'^(!\[)(.*?)(\]\()(.+?)(\))(\{.*?\})?$', line)
        if img_match and current_section:
            caption = img_match.group(2)
            path    = img_match.group(4)
            attrs   = img_match.group(6) or ""

            if not re.match(r'^Hình \d[\d.]*:', caption):
                section_img_count[current_section] = (
                    section_img_count.get(current_section, 0) + 1
                )
                n = section_img_count[current_section]
                caption = f"Hình {current_section}.{n}: {caption}"
                line = f"![{caption}]({path}){attrs}"

        result.append(line)

    return '\n'.join(result)


def publish_curriculum(state: AgentState) -> dict:
    """
    Publisher node: Finalize and export document.
    
    Workflow integration:
    - Input: state["final_content"] + state["current_content"] (last section)
    - Output: state["final_filepath"] (path to generated file)
    
    Pipeline:
    1. Merge final_content + current_content (ensures last section included)
    2. Add YAML/LaTeX headers
    3. Apply fix passes (unicode math, headings, math formatting, page breaks,
       figure numbering)
    4. Assemble front matter:
         Title page (no number) → TOC → [Danh mục hình] → START NUMBERING → body
    5. Save Markdown file
    6. Convert to PDF (if pypandoc available)
    7. Cleanup temporary images (ALWAYS — via finally block)
    
    Page numbering:
    - Title page:          no number
    - TOC + figure list:   no number
    - Lời nói đầu onward:  1, 2, 3 …
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with file path and status messages.
    """
    logger.info("=" * 60)
    logger.info("NODE: Publisher - Finalizing document")
    logger.info("=" * 60)

    # Merge final_content + current_content
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

    # Prepend preface (Lời nói đầu) if available
    preface = state.get("preface_content", "")
    if preface:
        preface_clean = re.sub(
            r'^\s*\\(new|clear)page\s*', '', preface, count=1
        ).lstrip()
        preface_block = "# Lời nói đầu\n\n" + preface_clean
        full_content = preface_block + "\n\n" + full_content

    # Prepare output paths
    raw_topic    = state.get("request", "Textbook")
    request_topic = sanitize_filename(raw_topic)
    output_dir   = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base    = f"{request_topic}_{timestamp}"
    md_filename  = output_dir / f"{file_base}.md"
    pdf_filename = output_dir / f"{file_base}.pdf"

    # YAML header — Typst-compatible metadata
    title = state.get("textbook_title") or state.get("request", "Giáo trình")
    yaml_header = f'---\ntitle: "{title}"\nfontsize: 12pt\nmainfont: "Times New Roman"\n---\n\n'

    # Apply fix passes
    full_content = fix_unicode_math(full_content)
    full_content = fix_markdown_headings(full_content)
    full_content = fix_inline_display_math(full_content)
    full_content = fix_math_formatting(full_content)
    full_content = fix_chapter_pagebreaks(full_content)
    full_content = add_figure_numbers(full_content)
    logger.info("✓ Figure numbers added (Hình X.Y.N format)")

    # Assemble front matter + body
    # Structure:
    #   _TYPST_TOC_BLOCK          (title→TOC, page numbering: none)
    #   [_TYPST_FIGURE_LIST_BLOCK] (optional, page numbering still none)
    #   _TYPST_PAGEBREAK           (separator before body)
    #   _TYPST_START_NUMBERING     (enable page numbers, reset to 1)
    #   body content               (Lời nói đầu = page 1, chapters follow)
    front_matter = _TYPST_TOC_BLOCK
    if state.get("enable_images", True):
        front_matter += "\n\n" + _TYPST_FIGURE_LIST_BLOCK

    full_content = (
        front_matter
        + "\n\n" + _TYPST_PAGEBREAK
        + "\n\n" + _TYPST_START_NUMBERING
        + "\n\n" + full_content
    )
    logger.info("✓ Math formatting and page structure fixed")

    final_document = yaml_header + full_content
    safe_document  = re.sub(r'([^\n])\n(#+ )', r'\1\n\n\2', final_document)

    # Save Markdown
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

    # Convert to PDF
    result_filepath = str(md_filename)

    if pypandoc:
        pandoc_tmp = BASE_DIR / ".pandoc_tmp"
        pandoc_tmp.mkdir(exist_ok=True)
        typst_root = BASE_DIR.anchor
        _old_env = {k: os.environ.get(k) for k in ("TEMP", "TMP")}
        os.environ["TEMP"] = str(pandoc_tmp)
        os.environ["TMP"]  = str(pandoc_tmp)
        try:
            typst_bin = shutil.which("typst") or "typst"
            logger.info(f"Converting to PDF (typst engine: {typst_bin})...")
            pypandoc.convert_file(
                str(md_filename),
                to="pdf",
                outputfile=str(pdf_filename),
                extra_args=[
                    f"--pdf-engine={typst_bin}",
                    "--pdf-engine-opt=--root",
                    f"--pdf-engine-opt={typst_root}",
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