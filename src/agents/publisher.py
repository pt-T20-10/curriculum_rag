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
from src.config import BASE_DIR, PDF_BODY_FONTSIZE, PDF_CHAPTER_FONTSIZE, PDF_TOC_TITLE
from src.log_config import setup_logger

logger = setup_logger(name="PublisherAgent", logfile="logs/agents.log")


def cleanup_temp_images() -> None:
    """
    Clean up temporary images directory after export.
    
    Called in finally block to guarantee execution regardless of
    whether PDF generation succeeded or fell back to Markdown.
    """
    image_dir = BASE_DIR / "outputs" / "images"
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
            # Collect consecutive subscript digits into one $_{}$ block
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


def fix_math_formatting(content: str) -> str:
    """
    Fix common math formatting issues that cause xelatex compilation errors.

    Problems addressed (in order of application):

    1. Nested `$ ... $` inside `$$ ... $$` blocks — the #1 cause of failures.
       Writer sometimes wraps inline math inside display math:
         $$               $$
         $\\formula$  →   \\formula
         $$               $$
       Also handles mixed cases like:
         $$               $$
         text $formula$   text \\formula
         $$               $$

    2. Partial nesting — leading/trailing text stuck inside $$ with $formula$:
         $$                    $$
         k_n = $\\frac{n}{a}$  k_n = \\frac{n}{a}
         $$                    $$

    3. `$ [...]` — space between $ and [ causes Pandoc to escape [ as {[}
       Fix: remove space → $[...

    4. Blank lines inside $$ blocks — xelatex treats blank line as paragraph break
       Fix: remove blank lines between $$ delimiters

    Args:
        content: Raw markdown content from Writer

    Returns:
        Content with math formatting corrected.
    """

    # ------------------------------------------------------------------
    # Fix 1 & 2: Strip nested $ ... $ inside $$ ... $$ blocks
    # Covers all patterns found in analysis:
    #   $$\n$formula$\n$$          → $$\nformula\n$$
    #   $$\ntext $formula$\n$$     → $$\ntext formula\n$$
    #   $$\nprefix$formula$suffix  → $$\nprefixformulasuffix
    # ------------------------------------------------------------------
    def clean_display_block(m: re.Match) -> str:
        inner = m.group(1)
        # Remove all $ that are NOT part of $$
        # Strategy: replace $...$ pairs with their content
        # Loop until no more single $ remain
        prev = None
        while prev != inner:
            prev = inner
            # Remove inline $ wrappers: $content$ → content
            # Use non-greedy, single-line content only (no newlines inside $...$)
            inner = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)', r'\1', inner)
        # Remove blank lines inside block
        lines = inner.split('\n')
        lines = [l for l in lines if l.strip() != '']
        inner = '\n' + '\n'.join(lines) + '\n'
        return f'$$\n{inner.strip()}\n$$'

    # Match $$ blocks (non-greedy, including newlines)
    content = re.sub(
        r'\$\$\n(.*?)\n[ \t]*\$\$',
        clean_display_block,
        content,
        flags=re.DOTALL
    )

    # ------------------------------------------------------------------
    # Fix 3: $ [...] — space between $ and [ bracket
    # e.g. "$ [0, \frac{a}{2}]$" → "$[0, \frac{a}{2}]$"
    # ------------------------------------------------------------------
    content = re.sub(r'\$\s+\[', '$[', content)
    content = re.sub(r'\]\s+\$', ']$', content)

    # ------------------------------------------------------------------
    # Fix 4: Stray single $ at start of line (not part of inline math)
    # e.g. "$\Delta" on its own line → "$$\n\Delta\n$$"
    # Pattern: line starts with $ followed immediately by a LaTeX command
    # ------------------------------------------------------------------
    content = re.sub(
        r'^(\$)(\\[a-zA-Z]+(?:\{[^}]*\})*)$',
        r'$$\n\2\n$$',
        content,
        flags=re.MULTILINE
    )

    # ------------------------------------------------------------------
    # Fix 5: Collapse multiline inline $...$ to a single line.
    # Writer LLM sometimes breaks inline math across two lines:
    #   "$v_\ni$"  →  "$v_i$"
    # Pattern: opening $ (not $$) ... newline ... closing $ (not $$)
    # Only matches short spans (no $ inside) to avoid over-matching.
    # ------------------------------------------------------------------
    content = re.sub(
        r'(?<!\$)\$(?!\$)([^$\n]{0,60}?)\n([^$\n]{0,60}?)\$(?!\$)',
        lambda m: '$' + m.group(1).rstrip() + ' ' + m.group(2).lstrip() + '$',
        content
    )

    # ------------------------------------------------------------------
    # Fix 6: Remove blank lines surrounding a lone inline $var$ line.
    # A single inline $x_i$ surrounded by blank lines looks like a
    # separate paragraph to Pandoc and may render as display math.
    # ------------------------------------------------------------------
    content = re.sub(r'\n\n(\$(?!\$)[^$\n]+\$(?!\$))\n\n', r'\n\1\n', content)

    return content

def publish_curriculum(state: AgentState) -> dict:

    """
    Publisher node: Finalize and export document.
    
    Workflow integration:
    - Input: state["final_content"] + state["current_content"] (last section)
    - Output: state["final_filepath"] (path to generated file)
    
    Pipeline:
    1. Merge final_content + current_content (ensures last section included)
    2. Add YAML/LaTeX headers
    3. Save Markdown file
    4. Convert to PDF (if pypandoc available)
    5. Cleanup temporary images (ALWAYS — via finally block)
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with file path and status messages.
    """
    logger.info("=" * 60)
    logger.info("NODE: Publisher - Finalizing document")
    logger.info("=" * 60)
    
    # Merge final_content + current_content
    # current_content holds the last subsection which hasn't been accumulated yet
    current = state.get("current_content", "")
    final = state.get("final_content", "")
    full_content = final + "\n\n" + current if (final and current) else (final or current)

    if not full_content:
        logger.error("No content found to publish")
        return {
            "messages": ["✗ Publisher failed: No content to publish"],
            "final_filepath": None
        }

    # Prepend preface (Lời nói đầu) if available
    preface = state.get("preface_content", "")
    if preface:
        # Strip any leading \newpage the LLM may have generated (page breaks handled here)
        preface_clean = re.sub(r'^\s*\\(new|clear)page\s*', '', preface, count=1).lstrip()
        preface_block = (
            "\\clearpage\n"
            "\\pagenumbering{arabic}\n"
            "\\setcounter{page}{1}\n\n"
            "\\phantomsection\n"
            "\\addcontentsline{toc}{chapter}{Lời nói đầu}\n\n"
            + preface_clean
        )
        full_content = preface_block + "\n\n\\clearpage\n\n" + full_content

    # Prepare output paths
    raw_topic = state.get("request", "Textbook")
    request_topic = sanitize_filename(raw_topic)
    
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base_name = f"{request_topic}_{timestamp}"
    md_filename = output_dir / f"{file_base_name}.md"
    pdf_filename = output_dir / f"{file_base_name}.pdf"
    
    # YAML header — LaTeX config for Vietnamese + Math + Image support
    title = state.get("textbook_title") or state.get("request", "Giáo trình")
    yaml_header = f"""---
title: "{title}"
fontsize: {PDF_BODY_FONTSIZE}
geometry: "left=2.5cm,right=2.5cm,top=2cm,bottom=2cm"
mainfont: "Times New Roman"
header-includes:
  - \\usepackage{{titling}}
  - \\renewcommand{{\\maketitle}}{{\\begin{{titlepage}}\\null\\vfill\\begin{{center}}{{\\Large\\bfseries\\thetitle}}\\end{{center}}\\vfill\\null\\end{{titlepage}}}}
  - \\usepackage{{amsmath}}
  - \\usepackage{{amssymb}}
  - \\usepackage{{hyperref}}
  - \\hypersetup{{colorlinks=true, linkcolor=blue, urlcolor=blue}}
  - \\usepackage{{indentfirst}}
  - \\usepackage{{float}}
  - \\usepackage{{graphicx}}
  - \\usepackage[font=small,labelfont=bf]{{caption}}
  - \\captionsetup[figure]{{labelformat=empty}}
  - \\let\\origfigure\\figure
  - \\let\\endorigfigure\\endfigure
  - \\renewenvironment{{figure}}[1][2] {{\\expandafter\\origfigure\\expandafter[H]}} {{\\endorigfigure}}
  - \\usepackage{{tocloft}}
  - \\renewcommand{{\\cfttoctitlefont}}{{\\hfill\\Large\\bfseries}}
  - \\renewcommand{{\\cftaftertoctitle}}{{\\hfill\\mbox{{}}}}
  - \\renewcommand{{\\contentsname}}{{{PDF_TOC_TITLE}}}
  - \\pagenumbering{{gobble}}
---

"""

    full_content = fix_unicode_math(full_content)
    full_content = fix_math_formatting(full_content)
    logger.info("✓ Math formatting fixed")

    final_document = yaml_header + full_content

    # Save Markdown
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(final_document)
        logger.info(f"✓ Markdown saved: {md_filename}")
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}", exc_info=True)
        cleanup_temp_images()  # Cleanup even on early exit
        return {
            "messages": ["✗ Publisher failed: Could not save Markdown"],
            "final_filepath": None
        }

    # Convert to PDF — cleanup images in finally to guarantee execution
    result_filepath = str(md_filename)  # Default fallback to MD

    if pypandoc:
        try:
            logger.info("Converting to PDF (xelatex engine)...")
            pypandoc.convert_text(
                source=final_document,
                to='pdf',
                format='md',
                outputfile=str(pdf_filename),
                extra_args=[
                    '--pdf-engine=xelatex',
                    '-V', 'mainfont=Times New Roman',
                    '--toc',
                ]
            )
            logger.info(f"✓ PDF saved: {pdf_filename}")
            result_filepath = str(pdf_filename)
        except Exception as e:
            logger.warning(f"PDF generation failed: {e}", exc_info=True)
            logger.info("Falling back to Markdown output only")
        finally:
            # ALWAYS cleanup images — whether PDF succeeded, failed, or crashed
            cleanup_temp_images()

    else:
        logger.warning("pypandoc not installed - skipping PDF generation")
        # Still cleanup images even if PDF was never attempted
        cleanup_temp_images()

    return {
        "messages": [
            f"✓ Document finalized: {os.path.basename(result_filepath)}"
        ],
        "final_filepath": result_filepath
    }