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
import copy
import unicodedata
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
    safe = re.sub(r'[^\w\s\-]', '', name or "")
    safe = re.sub(r'\s+', '_', safe.strip())
    safe = re.sub(r'_+', '_', safe)
    safe = safe.strip('._-')
    safe = safe[:max_length]
    return safe if safe else "Textbook"


def save_partial_markdown_checkpoint(state: dict) -> str | None:
    """
    Save a recoverable Markdown checkpoint after a section has been approved.

    This is intentionally lighter than publish_curriculum(): it avoids Pandoc
    and expensive formatting passes so checkpointing cannot become another
    failure point. The file is overwritten for the same run.
    """
    if not getattr(settings, "CHECKPOINT_MARKDOWN_AFTER_SECTION", True):
        return None

    current = state.get("current_content", "")
    final = state.get("final_content", "")
    body = final + "\n\n" + current if (final and current) else (final or current)
    if not body.strip():
        return None

    language = state.get("language", "vi")
    profile = get_language_profile(language)
    title = state.get("textbook_title") or state.get("request", profile.default_title_prefix)
    preface = state.get("preface_content", "")
    if preface:
        body = f"# {profile.preface_heading}\n\n{preface.strip()}\n\n{body}"

    checkpoint_dir = BASE_DIR / "outputs" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    topic_part = sanitize_filename(state.get("request", title), max_length=36)
    run_part = sanitize_filename(
        state.get("rag_collection_name", "") or title,
        max_length=72,
    )
    path = checkpoint_dir / f"{topic_part}_{run_part}.partial.md"

    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    subsection = int(state.get("current_subsection_index", 0) or 0) + 1
    header = (
        "<!-- Auto-saved checkpoint. "
        f"Last completed/polished section: {chapter}.{subsection}. "
        "Final PDF/DOCX export may not have completed yet. -->\n\n"
        f"# {title}\n\n"
    )

    try:
        path.write_text(header + body.strip() + "\n", encoding="utf-8")
        logger.info("✓ Partial Markdown checkpoint saved: %s", path)
        return str(path)
    except Exception as e:
        logger.warning("Could not save partial Markdown checkpoint: %s", e, exc_info=True)
        return None


def _typst_string_literal(value: str) -> str:
    """Encode untrusted/dynamic text as a Typst-compatible string literal."""
    return json.dumps(str(value), ensure_ascii=False)


def _valid_artifact(path: Path, suffix: str) -> bool:
    """Return True only for a non-empty file with the expected extension."""
    return path.suffix.lower() == suffix and path.is_file() and path.stat().st_size > 0


_WORD_FONT_STYLE_IDS = {
    "Normal",
    "Title",
    "TOCHeading",
    "TOC1",
    "TOC2",
    "TOC3",
    "Heading1",
    "Heading2",
    "Heading3",
}


def _set_style_font(style, font_name: str, size_pt: int | None = None) -> None:
    """Force a python-docx style to use a concrete font, not a theme font."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    if size_pt is not None:
        style.font.size = Pt(size_pt)
    style.font.name = font_name

    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)

    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), font_name)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if rfonts.get(qn(attr)) is not None:
            del rfonts.attrib[qn(attr)]


def _set_paragraph_alignment_xml(paragraph_element, alignment: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    ppr = paragraph_element.get_or_add_pPr()
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        ppr.append(jc)
    jc.set(qn("w:val"), alignment)


def _set_ppr_alignment_xml(ppr_element, alignment: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    jc = ppr_element.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        ppr_element.append(jc)
    jc.set(qn("w:val"), alignment)


def _paragraph_text_xml(paragraph_element) -> str:
    from docx.oxml.ns import qn

    return "".join(t.text or "" for t in paragraph_element.iter(qn("w:t")))


def _replace_paragraph_text_xml(paragraph_element, text: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for child in list(paragraph_element):
        paragraph_element.remove(child)
    ppr = OxmlElement("w:pPr")
    pstyle = OxmlElement("w:pStyle")
    pstyle.set(qn("w:val"), "TOCHeading")
    ppr.append(pstyle)
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), "center")
    ppr.append(jc)
    paragraph_element.append(ppr)

    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), _document_font())
    rpr.append(rfonts)
    bold = OxmlElement("w:b")
    rpr.append(bold)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    paragraph_element.append(run)


def _patch_word_document_styles(doc) -> None:
    font_name = _document_font()
    for style in doc.styles:
        style_id = getattr(style, "style_id", "")
        if style_id in _WORD_FONT_STYLE_IDS:
            _set_style_font(style, font_name, size_pt=12 if style_id == "Normal" else None)
            if style_id == "TOCHeading":
                _set_ppr_alignment_xml(style.element.get_or_add_pPr(), "center")


def _word_paragraph_has_tag(paragraph, tag_names: set[str]) -> bool:
    from docx.oxml.ns import qn

    resolved = {qn(tag_name) for tag_name in tag_names}
    return any(element.tag in resolved for element in paragraph._p.iter())


def _word_style_tokens(paragraph) -> str:
    style = getattr(paragraph, "style", None)
    style_id = getattr(style, "style_id", "") or ""
    style_name = getattr(style, "name", "") or ""
    return f"{style_id} {style_name}".lower()


def _is_word_code_paragraph(paragraph) -> bool:
    tokens = _word_style_tokens(paragraph)
    code_markers = (
        "sourcecode",
        "source code",
        "code",
        "verbatim",
        "preformatted",
        "htmlpre",
    )
    return any(marker in tokens for marker in code_markers)


def _is_word_numbered_or_bulleted_paragraph(paragraph) -> bool:
    return _word_paragraph_has_tag(paragraph, {"w:numPr"})


def _is_word_table_paragraph(paragraph) -> bool:
    from docx.oxml.ns import qn

    parent = paragraph._p.getparent()
    while parent is not None:
        if parent.tag == qn("w:tc"):
            return True
        parent = parent.getparent()
    return False


def _is_lead_in_label_text(text: str) -> bool:
    """Detect short paragraph labels that should stay left-aligned."""
    cleaned = re.sub(r"[*_`]+", "", (text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned) > 90:
        return False
    if not cleaned.endswith(":"):
        return False
    if re.search(r"[.!?]\s*:$", cleaned):
        return False
    words = re.findall(r"\w+", cleaned, flags=re.UNICODE)
    if not words or len(words) > 12:
        return False
    return True


def _should_justify_word_paragraph(paragraph) -> bool:
    text = (paragraph.text or "").strip()
    if not text:
        return False
    if text in {"Danh mục hình", "List of Figures"}:
        return False
    if _is_lead_in_label_text(text):
        return False
    if _is_word_numbered_or_bulleted_paragraph(paragraph):
        return False
    if _is_word_table_paragraph(paragraph):
        return False

    style_id = getattr(getattr(paragraph, "style", None), "style_id", "") or ""
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    special_style_ids = {
        "Title",
        "Subtitle",
        "Caption",
        "TOCHeading",
        "TOC1",
        "TOC2",
        "TOC3",
        "TOC4",
        "TOC5",
    }
    if style_id in special_style_ids or style_id.startswith("Heading"):
        return False
    if style_name in {"Title", "Subtitle", "Caption"} or style_name.startswith("TOC"):
        return False
    if re.match(r"^(?:Hình|Figure)\s+\d+(?:\.\d+)*\s*:", text, re.IGNORECASE):
        return False
    if _is_word_code_paragraph(paragraph):
        return False
    if _word_paragraph_has_tag(
        paragraph,
        {"w:drawing", "w:fldChar", "m:oMath", "m:oMathPara"},
    ):
        return False
    return True


def _is_word_caption_paragraph(paragraph) -> bool:
    if _word_paragraph_has_tag(paragraph, {"w:fldChar"}):
        return False
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    if style_name == "Caption":
        return True
    text = (paragraph.text or "").strip()
    return bool(re.match(r"^(?:Hình|Figure)\s+\d+(?:\.\d+)*\s*:", text, re.IGNORECASE))


def _iter_word_body_paragraphs(doc):
    for paragraph in doc.paragraphs:
        yield paragraph
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    yield paragraph


def _justify_word_body_paragraphs(doc) -> int:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    count = 0
    for paragraph in _iter_word_body_paragraphs(doc):
        if not _should_justify_word_paragraph(paragraph):
            continue
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        count += 1
    return count


def _left_align_word_table_paragraphs(doc) -> int:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    count = 0
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    _set_paragraph_alignment_xml(paragraph._p, "left")
                    count += 1
    return count


def _patch_word_media_and_code_alignment(doc) -> tuple[int, int, int]:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    image_count = 0
    caption_count = 0
    code_count = 0
    for paragraph in _iter_word_body_paragraphs(doc):
        style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        if _word_paragraph_has_tag(paragraph, {"w:drawing"}):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            image_count += 1
        elif _is_word_caption_paragraph(paragraph):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption_count += 1
        elif _is_word_code_paragraph(paragraph):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            code_count += 1
    return image_count, caption_count, code_count


def _image_alt_text_from_paragraph_xml(paragraph_element) -> str:
    for element in paragraph_element.iter():
        if not str(element.tag).endswith("}docPr"):
            continue
        for attr in ("descr", "title", "name"):
            value = element.get(attr)
            if value and value.strip():
                return value.strip()
    return ""


def _new_word_caption_paragraph_xml(caption: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    paragraph = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr")
    pstyle = OxmlElement("w:pStyle")
    pstyle.set(qn("w:val"), "Caption")
    ppr.append(pstyle)
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), "center")
    ppr.append(jc)
    paragraph.append(ppr)

    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), _document_font())
    rpr.append(rfonts)
    run.append(rpr)
    text = OxmlElement("w:t")
    text.text = caption
    run.append(text)
    paragraph.append(run)
    return paragraph


def _insert_missing_word_image_captions(doc) -> int:
    from docx.oxml.ns import qn

    body = doc.element.body
    inserted = 0
    caption_re = re.compile(r"^(?:Hình|Figure)\s+\d+(?:\.\d+)*\s*:", re.IGNORECASE)

    for child in list(body):
        if child.tag != qn("w:p") or not any(
            element.tag == qn("w:drawing") for element in child.iter()
        ):
            continue

        caption = _image_alt_text_from_paragraph_xml(child)
        if not caption_re.match(caption):
            continue

        children = list(body)
        index = children.index(child)
        next_paragraph = None
        for candidate in children[index + 1:]:
            if candidate.tag != qn("w:p"):
                continue
            if not _paragraph_text_xml(candidate).strip() and not _word_paragraph_has_page_break_xml(candidate):
                continue
            next_paragraph = candidate
            break
        if next_paragraph is not None and caption_re.match(
            _paragraph_text_xml(next_paragraph).strip()
        ):
            continue

        body.insert(index + 1, _new_word_caption_paragraph_xml(caption))
        inserted += 1

    return inserted


def _patch_word_toc_heading(doc, toc_label: str) -> None:
    from docx.oxml.ns import qn

    for paragraph_element in doc.element.body.iter(qn("w:p")):
        ppr = paragraph_element.find(qn("w:pPr"))
        pstyle = ppr.find(qn("w:pStyle")) if ppr is not None else None
        style_val = pstyle.get(qn("w:val")) if pstyle is not None else ""
        text = _paragraph_text_xml(paragraph_element).strip()
        if style_val == "TOCHeading" or text == "Table of Contents":
            _replace_paragraph_text_xml(paragraph_element, toc_label)
            return


def _word_paragraph_has_page_break_xml(paragraph_element) -> bool:
    from docx.oxml.ns import qn

    for br in paragraph_element.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    return False


def _new_word_page_break_paragraph():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    paragraph = OxmlElement("w:p")
    run = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run.append(br)
    paragraph.append(run)
    return paragraph


def _is_toc_sdt_element(element) -> bool:
    from docx.oxml.ns import qn

    if element.tag != qn("w:sdt"):
        return False
    text = _paragraph_text_xml(element)
    if "Mục lục" in text or "Table of Contents" in text:
        return True
    return any("TOC" in (instr.text or "") for instr in element.iter(qn("w:instrText")))


def _is_figure_list_paragraph_xml(element) -> bool:
    from docx.oxml.ns import qn

    if element.tag != qn("w:p"):
        return False
    return _paragraph_text_xml(element).strip() in {"Danh mục hình", "List of Figures"}


def _is_body_start_paragraph_xml(element, start_heading: str | None) -> bool:
    from docx.oxml.ns import qn

    if element.tag != qn("w:p"):
        return False
    text = _paragraph_text_xml(element).strip()
    return bool(text and start_heading and text == start_heading)


def _ensure_page_break_after_body_child(body, element) -> bool:
    from docx.oxml.ns import qn

    children = list(body)
    try:
        index = children.index(element)
    except ValueError:
        return False
    next_element = children[index + 1] if index + 1 < len(children) else None
    if (
        next_element is not None
        and next_element.tag == qn("w:p")
        and _word_paragraph_has_page_break_xml(next_element)
    ):
        return False
    body.insert(index + 1, _new_word_page_break_paragraph())
    return True


def _is_blank_word_paragraph_xml(element) -> bool:
    from docx.oxml.ns import qn

    return element.tag == qn("w:p") and not _paragraph_text_xml(element).strip()


def _ensure_single_page_break_between_body_children(body, start_element, end_element) -> int:
    from docx.oxml.ns import qn

    children = list(body)
    try:
        start_index = children.index(start_element)
        end_index = children.index(end_element)
    except ValueError:
        return 0
    if start_index >= end_index:
        return 0

    changed = 0
    middle = children[start_index + 1:end_index]
    break_elements = [
        element
        for element in middle
        if element.tag == qn("w:p") and _word_paragraph_has_page_break_xml(element)
    ]

    if break_elements:
        keeper = break_elements[0]
        for element in middle:
            if element is keeper:
                continue
            if (
                element in break_elements
                or _is_blank_word_paragraph_xml(element)
            ):
                body.remove(element)
                changed += 1
        children = list(body)
        current_index = children.index(keeper)
        desired_index = children.index(start_element) + 1
        if current_index != desired_index:
            body.remove(keeper)
            body.insert(desired_index, keeper)
            changed += 1
        return changed

    insert_index = children.index(start_element) + 1
    body.insert(insert_index, _new_word_page_break_paragraph())
    return 1


def _ensure_word_front_matter_page_breaks(
    doc,
    *,
    page_start_heading: str | None = None,
) -> int:
    from docx.oxml.ns import qn

    body = doc.element.body
    children = list(body)
    changed = 0
    last_toc = None
    last_figure_list_entry = None
    body_start = None

    for child in children:
        if child.tag != qn("w:p"):
            if _is_toc_sdt_element(child):
                last_toc = child
            continue

        text = _paragraph_text_xml(child).strip()
        ppr = child.find(qn("w:pPr"))
        pstyle = ppr.find(qn("w:pStyle")) if ppr is not None else None
        style_val = pstyle.get(qn("w:val")) if pstyle is not None else ""

        if style_val == "Title":
            changed += int(_ensure_page_break_after_body_child(body, child))
        elif style_val == "TOCHeading" or text in {"Mục lục", "Table of Contents"}:
            last_toc = child
        elif _is_figure_list_paragraph_xml(child) or "PAGEREF fig_" in "".join(
            instr.text or "" for instr in child.iter(qn("w:instrText"))
        ):
            last_figure_list_entry = child
        elif page_start_heading and _is_body_start_paragraph_xml(child, page_start_heading):
            body_start = child

    if last_toc is not None:
        changed += int(_ensure_page_break_after_body_child(body, last_toc))
    if last_figure_list_entry is not None and body_start is not None:
        changed += _ensure_single_page_break_between_body_children(
            body,
            last_figure_list_entry,
            body_start,
        )
    elif last_figure_list_entry is not None:
        changed += int(_ensure_page_break_after_body_child(body, last_figure_list_entry))

    if page_start_heading and last_figure_list_entry is None:
        children = list(body)
        for child in children:
            if _is_body_start_paragraph_xml(child, page_start_heading):
                index = children.index(child)
                prev = children[index - 1] if index > 0 else None
                if not (
                    prev is not None
                    and prev.tag == qn("w:p")
                    and _word_paragraph_has_page_break_xml(prev)
                ):
                    body.insert(index, _new_word_page_break_paragraph())
                    changed += 1
                break

    return changed


def _remove_section_footer_refs(sect_pr) -> None:
    from docx.oxml.ns import qn

    for child in list(sect_pr):
        if child.tag == qn("w:footerReference"):
            sect_pr.remove(child)


def _set_section_page_number_start(sect_pr, start: int = 1) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    pg_num = sect_pr.find(qn("w:pgNumType"))
    if pg_num is None:
        pg_num = OxmlElement("w:pgNumType")
        sect_pr.append(pg_num)
    pg_num.set(qn("w:start"), str(start))


def _set_section_margins(sect_pr) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    pg_mar = sect_pr.find(qn("w:pgMar"))
    if pg_mar is None:
        pg_mar = OxmlElement("w:pgMar")
        sect_pr.append(pg_mar)
    pg_mar.set(qn("w:left"), _WORD_MARGIN_LEFT_RIGHT_TWIPS)
    pg_mar.set(qn("w:right"), _WORD_MARGIN_LEFT_RIGHT_TWIPS)
    pg_mar.set(qn("w:top"), _WORD_MARGIN_TOP_BOTTOM_TWIPS)
    pg_mar.set(qn("w:bottom"), _WORD_MARGIN_TOP_BOTTOM_TWIPS)


def _set_word_section_layout(doc) -> None:
    for section in doc.sections:
        _set_section_margins(section._sectPr)


def _set_section_vertical_alignment(sect_pr, alignment: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    v_align = sect_pr.find(qn("w:vAlign"))
    if v_align is None:
        v_align = OxmlElement("w:vAlign")
        sect_pr.append(v_align)
    v_align.set(qn("w:val"), alignment)


def _set_section_type(sect_pr, section_type: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sect_type = sect_pr.find(qn("w:type"))
    if sect_type is None:
        sect_type = OxmlElement("w:type")
        sect_pr.insert(0, sect_type)
    sect_type.set(qn("w:val"), section_type)


def _patch_word_title_page(doc) -> bool:
    """
    Give the Pandoc title block a dedicated vertically centered first page.

    Pandoc emits the YAML title as a paragraph with the Title style. Adding a
    section break to that paragraph lets the cover page have vertical centering
    without affecting the TOC, figure list, or body sections.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    body_sect_pr = doc.element.body.find(qn("w:sectPr"))
    if body_sect_pr is None:
        return False

    for paragraph in doc.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        style_id = getattr(getattr(paragraph, "style", None), "style_id", "") or ""
        style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        if style_id != "Title" and style_name != "Title":
            return False

        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_sect_pr = copy.deepcopy(body_sect_pr)
        _remove_section_footer_refs(title_sect_pr)
        _set_section_type(title_sect_pr, "nextPage")
        _set_section_vertical_alignment(title_sect_pr, "center")
        _set_section_margins(title_sect_pr)

        ppr = paragraph._p.get_or_add_pPr()
        existing = ppr.find(qn("w:sectPr"))
        if existing is not None:
            ppr.remove(existing)
        ppr.append(title_sect_pr)
        return True

    return False


def _center_word_heading1_paragraphs(doc) -> int:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    count = 0
    for paragraph in _iter_word_body_paragraphs(doc):
        style_id = getattr(getattr(paragraph, "style", None), "style_id", "") or ""
        if style_id == "Heading1":
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            count += 1
    return count


def _insert_body_section_break(doc, start_heading: str) -> bool:
    """
    Split front matter from body before the configured body start heading.

    The Markdown already inserts page breaks before the body. A continuous
    section break here avoids adding another blank page while allowing the
    body section to restart page numbers at 1 and own the footer.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    body = doc.element.body
    children = list(body)
    body_sect_pr = body.find(qn("w:sectPr"))
    if body_sect_pr is None:
        return False

    target_index = None
    for i, child in enumerate(children):
        if child.tag != qn("w:p"):
            continue
        text = _paragraph_text_xml(child).strip()
        ppr = child.find(qn("w:pPr"))
        pstyle = ppr.find(qn("w:pStyle")) if ppr is not None else None
        style_val = pstyle.get(qn("w:val")) if pstyle is not None else ""
        if text == start_heading and style_val in {"Heading1", ""}:
            target_index = i
            break

    if target_index is None or target_index == 0:
        return False

    previous_paragraph = None
    for child in reversed(children[:target_index]):
        if child.tag == qn("w:p"):
            previous_paragraph = child
            break
    if previous_paragraph is None:
        return False

    front_sect_pr = copy.deepcopy(body_sect_pr)
    _remove_section_footer_refs(front_sect_pr)
    pg_num = front_sect_pr.find(qn("w:pgNumType"))
    if pg_num is not None:
        front_sect_pr.remove(pg_num)

    _set_section_type(front_sect_pr, "continuous")
    _set_section_margins(front_sect_pr)

    ppr = previous_paragraph.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        previous_paragraph.insert(0, ppr)
    existing = ppr.find(qn("w:sectPr"))
    if existing is not None:
        ppr.remove(existing)
    ppr.append(front_sect_pr)
    return True


def _max_word_bookmark_id(doc) -> int:
    from docx.oxml.ns import qn

    max_id = -1
    for bookmark in doc.element.iter(qn("w:bookmarkStart")):
        raw = bookmark.get(qn("w:id"))
        if raw and raw.isdigit():
            max_id = max(max_id, int(raw))
    return max_id


def _add_bookmark_to_paragraph(paragraph_element, name: str, bookmark_id: int) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))

    ppr = paragraph_element.find(qn("w:pPr"))
    insert_at = 1 if ppr is not None else 0
    paragraph_element.insert(insert_at, start)
    paragraph_element.append(end)


def _new_text_run(text: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    if text.startswith(" ") or text.endswith(" "):
        t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    return run


def _new_pageref_run(bookmark_name: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = OxmlElement("w:r")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" PAGEREF {bookmark_name} \\h "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run.extend([begin, instr, separate, placeholder, end])
    return run


def _new_hyperlink_run(bookmark_name: str, display_text: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = OxmlElement("w:r")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' HYPERLINK \\l "{bookmark_name}" '
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = display_text
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run.extend([begin, instr, separate, text, end])
    return run


def _new_tab_run():
    from docx.oxml import OxmlElement

    run = OxmlElement("w:r")
    run.append(OxmlElement("w:tab"))
    return run


def _new_figure_list_ppr():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    ppr = OxmlElement("w:pPr")
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), "left")
    ppr.append(jc)
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "right")
    tab.set(qn("w:leader"), "dot")
    tab.set(qn("w:pos"), _WORD_FIGURE_LIST_TAB_POS_TWIPS)
    tabs.append(tab)
    ppr.append(tabs)
    return ppr


def _new_figure_list_paragraph(caption: str, bookmark_name: str):
    from docx.oxml import OxmlElement

    paragraph = OxmlElement("w:p")
    paragraph.append(_new_figure_list_ppr())
    paragraph.append(_new_hyperlink_run(bookmark_name, caption))
    paragraph.append(_new_tab_run())
    paragraph.append(_new_pageref_run(bookmark_name))
    return paragraph


def _style_word_figure_list_title(paragraph_element) -> bool:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    text = _paragraph_text_xml(paragraph_element).strip()
    if text not in {"Danh mục hình", "List of Figures"}:
        return False

    ppr = paragraph_element.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        paragraph_element.insert(0, ppr)

    pstyle = ppr.find(qn("w:pStyle"))
    if pstyle is not None:
        ppr.remove(pstyle)
    _set_ppr_alignment_xml(ppr, "center")

    for run in paragraph_element.findall(qn("w:r")):
        rpr = run.find(qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            run.insert(0, rpr)
        if rpr.find(qn("w:b")) is None:
            rpr.append(OxmlElement("w:b"))
        sz = rpr.find(qn("w:sz"))
        if sz is None:
            sz = OxmlElement("w:sz")
            rpr.append(sz)
        sz.set(qn("w:val"), "28")
        sz_cs = rpr.find(qn("w:szCs"))
        if sz_cs is None:
            sz_cs = OxmlElement("w:szCs")
            rpr.append(sz_cs)
        sz_cs.set(qn("w:val"), "28")
    return True


def _patch_word_figure_list_fields(doc) -> int:
    """
    Replace the Markdown marker with caption entries backed by PAGEREF fields.
    """
    marker_paragraph = None
    for paragraph in doc.paragraphs:
        if (paragraph.text or "").strip() == _WORD_FIGURE_LIST_MARKER:
            marker_paragraph = paragraph._p
            break
    if marker_paragraph is None:
        return 0

    body = doc.element.body
    children = list(body)
    marker_index = children.index(marker_paragraph)
    for child in reversed(children[:marker_index]):
        if child.tag.endswith("}p"):
            _style_word_figure_list_title(child)
            break

    caption_re = re.compile(r"^(?:Hình|Figure)\s+\d+(?:\.\d+)*\s*:", re.IGNORECASE)
    captions: list[tuple[str, object, str]] = []
    next_id = _max_word_bookmark_id(doc) + 1
    for paragraph in doc.paragraphs:
        text = (paragraph.text or "").strip()
        if not caption_re.match(text):
            continue
        bookmark_name = f"fig_{len(captions) + 1}"
        _add_bookmark_to_paragraph(paragraph._p, bookmark_name, next_id)
        captions.append((text, paragraph._p, bookmark_name))
        next_id += 1

    if captions:
        for caption, _paragraph_element, bookmark_name in captions:
            body.insert(
                body.index(marker_paragraph),
                _new_figure_list_paragraph(caption, bookmark_name),
            )

    body.remove(marker_paragraph)
    return len(captions)


def _mark_word_fields_for_update(doc) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    settings = doc.settings.element
    update_fields = settings.find(qn("w:updateFields"))
    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)
    update_fields.set(qn("w:val"), "true")

    for fld_char in doc.element.iter(qn("w:fldChar")):
        if fld_char.get(qn("w:fldCharType")) == "begin":
            fld_char.set(qn("w:dirty"), "true")
            if fld_char.get(qn("w:fldLock")) is not None:
                del fld_char.attrib[qn("w:fldLock")]


def _set_word_paragraph_keep_flags(
    paragraph,
    *,
    keep_next: bool = False,
    keep_lines: bool = True,
) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    ppr = paragraph._p.get_or_add_pPr()
    if keep_next and ppr.find(qn("w:keepNext")) is None:
        ppr.append(OxmlElement("w:keepNext"))
    if keep_lines and ppr.find(qn("w:keepLines")) is None:
        ppr.append(OxmlElement("w:keepLines"))


def _word_paragraph_has_numbering(paragraph) -> bool:
    from docx.oxml.ns import qn

    ppr = paragraph._p.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:numPr")) is not None


def _looks_like_word_formula_definition_paragraph(paragraph) -> bool:
    text = ((paragraph.text or "") or _paragraph_text_xml(paragraph._p)).strip()
    if not text:
        return False
    if text.startswith("$"):
        return True
    if re.match(r"^[A-Za-z](?:\s*,\s*[A-Za-z]){0,4}\s*[:：]", text):
        return True
    return _word_paragraph_has_numbering(paragraph)


def _patch_word_formula_definition_pagination(doc) -> int:
    paragraphs = list(_iter_word_body_paragraphs(doc))
    changed = 0
    intro_re = re.compile(r"^(?:Trong đó|Where)\s*:?\s*$", re.IGNORECASE)

    for index, paragraph in enumerate(paragraphs):
        if not intro_re.match((paragraph.text or "").strip()):
            continue

        block = [paragraph]
        for follower in paragraphs[index + 1:index + 9]:
            if _looks_like_word_formula_definition_paragraph(follower):
                block.append(follower)
                continue
            break

        if len(block) == 1:
            continue

        for block_index, item in enumerate(block):
            _set_word_paragraph_keep_flags(
                item,
                keep_next=block_index < len(block) - 1,
                keep_lines=True,
            )
            changed += 1

    return changed


def _add_centered_page_footer(doc, body_only: bool = False) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sections = list(doc.sections)
    if body_only and len(sections) > 1:
        for section in sections[:-1]:
            _remove_section_footer_refs(section._sectPr)
        sections = [sections[-1]]

    for section in sections:
        _set_section_page_number_start(section._sectPr, 1)
        footer = section.footer
        footer.is_linked_to_previous = False
        paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        paragraph.clear()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        run.font.name = _document_font()

        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = "PAGE"
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        text = OxmlElement("w:t")
        text.text = "1"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")

        run._r.extend([begin, instr, separate, text, end])


def finalize_word_docx(
    docx_path: Path,
    toc_label: str,
    page_start_heading: str | None = None,
) -> bool:
    """
    Best-effort Word finishing pass for Pandoc DOCX output.

    Applies presentation-only fixes: localized TOC heading, heading/TOC fonts,
    TOC heading alignment, justified body paragraphs, a body-only centered PAGE
    footer, and dirty field flags so Word refreshes TOC page numbers on open.
    It deliberately does not rewrite prose content, including em dash usage.
    """
    try:
        from docx import Document as DocxDocument

        doc = DocxDocument(docx_path)  # type: ignore
        _patch_word_document_styles(doc)
        _set_word_section_layout(doc)
        title_page_patched = _patch_word_title_page(doc)
        _patch_word_toc_heading(doc, toc_label)
        heading_count = _center_word_heading1_paragraphs(doc)
        inserted_caption_count = _insert_missing_word_image_captions(doc)
        figure_count = _patch_word_figure_list_fields(doc)
        front_break_count = _ensure_word_front_matter_page_breaks(
            doc,
            page_start_heading=page_start_heading,
        )
        image_count, caption_count, code_count = _patch_word_media_and_code_alignment(doc)
        table_paragraph_count = _left_align_word_table_paragraphs(doc)
        formula_keep_count = _patch_word_formula_definition_pagination(doc)
        justified_count = _justify_word_body_paragraphs(doc)
        has_body_section = False
        if page_start_heading:
            has_body_section = _insert_body_section_break(doc, page_start_heading)
        _set_word_section_layout(doc)
        _add_centered_page_footer(doc, body_only=has_body_section)
        _mark_word_fields_for_update(doc)
        doc.save(docx_path)  # type: ignore
        logger.info(
            "✓ Word finishing pass applied: %s "
            "(title=%s, %s h1 centered, %s figures, %s images, "
            "%s front breaks, %s captions, %s inserted captions, %s code blocks, "
            "%s table paragraphs left-aligned, %s formula paragraphs kept, "
            "%s body paragraphs justified)",
            docx_path,
            title_page_patched,
            heading_count,
            figure_count,
            image_count,
            front_break_count,
            caption_count,
            inserted_caption_count,
            code_count,
            table_paragraph_count,
            formula_keep_count,
            justified_count,
        )
        return True
    except Exception as e:
        logger.warning("Word finishing pass skipped for %s: %s", docx_path, e)
        return False
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
_DISPLAY_MATH_SIGNAL_RE = re.compile(
    r'(?:=|[<>]|\\(?:times|cdot|approx|leq|geq|sum|prod|int|frac|sqrt|lim)\b)'
)
_WORD_PAGEBREAK = (
    '```{=openxml}\n'
    '<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n'
    '```'
)
_WORD_FIGURE_LIST_MARKER = "[[WORD_FIGURE_LIST]]"
_WORD_FIGURE_LIST_TITLE_STYLE = "WordFigureListTitle"
_WORD_MARGIN_LEFT_RIGHT_TWIPS = "1417"  # 2.5 cm
_WORD_MARGIN_TOP_BOTTOM_TWIPS = "1134"  # 2.0 cm
_WORD_FIGURE_LIST_TAB_POS_TWIPS = "9360"


def _looks_like_display_math_expression(expr: str) -> bool:
    """Return True for equations that should remain block/display math."""
    expr = expr.strip()
    if not expr:
        return False
    return bool(_DISPLAY_MATH_SIGNAL_RE.search(expr))


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
        if _looks_like_display_math_expression(expr):
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
        r'(?<![A-Za-z0-9_\\)\]\}.,;:])\$(?!\$)([^$\n]{1,60}?)\n([^$\n]{1,60}?)\$(?!\$)',
        lambda m: '$' + m.group(1).rstrip() + ' ' + m.group(2).lstrip() + '$',
        content,
    )
    content = re.sub(r'\n\n(\$(?!\$)[^$\n]+\$(?!\$))\n\n', r'\n\1\n', content)
    return content


def _strip_vietnamese_accents_for_math(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_math_identifier_text(expr: str) -> str:
    expr = expr.replace("φ", r"\varphi")
    expr = re.sub(
        r'(?<!\\)\b(cos|sin|tan)\s*(\\varphi)',
        lambda m: "\\" + m.group(1) + m.group(2),
        expr,
    )
    expr = re.sub(
        r'([_^]\{)([^{}\n]*[^\x00-\x7F][^{}\n]*)(\})',
        lambda m: m.group(1) + _strip_vietnamese_accents_for_math(m.group(2)) + m.group(3),
        expr,
    )
    expr = re.sub(
        r'([_^])([A-Za-z]*[^\W\d_][\wÀ-ỹ]*)',
        lambda m: m.group(1) + _strip_vietnamese_accents_for_math(m.group(2)),
        expr,
    )
    return expr


def normalize_math_identifier_formatting(content: str) -> str:
    """Normalize small formula identifier artifacts without touching prose."""
    def transform(text: str) -> str:
        text = _convert_formula_backticks(text)
        text = re.sub(
            r'(?<!\$)\$\$(.*?)\$\$(?!\$)',
            lambda m: "$$\n" + _normalize_math_identifier_text(m.group(1)).strip() + "\n$$",
            text,
            flags=re.DOTALL,
        )
        text = re.sub(
            r'\b([A-Z])\$_([^$\n]+)\$',
            lambda m: f'${m.group(1)}_{{{_normalize_math_identifier_text(m.group(2).strip())}}}$',
            text,
        )

        def replace_inline(match: re.Match) -> str:
            expr = _normalize_math_identifier_text(match.group(1))
            return f'${expr}$'

        return re.sub(
            r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)',
            replace_inline,
            text,
        )

    return _apply_outside_fenced_blocks(content, transform)


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


_MATH_ENV_RE = re.compile(
    r"\\begin\{(?:aligned|align|cases|matrix|bmatrix|pmatrix|smallmatrix|array|split|gathered)\}",
    re.IGNORECASE,
)


def _is_markdown_boundary_inside_math(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "![", "|")):
        return True
    if re.match(r"^(?:[-+*]|\d+[.)]|[a-z]\))\s+\S", stripped, re.IGNORECASE):
        return True
    if _is_lead_in_label_text(stripped):
        return True
    return False


def _looks_like_bare_formula_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped in {"$$", "$"}:
        return False
    if stripped.startswith(("#", ">", "|", "![", "```")):
        return False
    if re.match(r"^(?:[-+*]|\d+[.)]|[a-z]\))\s+\S", stripped, re.IGNORECASE):
        return False
    if "$" in stripped or "`" in stripped:
        return False
    if len(stripped) > 220:
        return False
    if not re.search(r"[=<>]|\\(?:frac|sqrt|sum|prod|int|Phi|omega|Omega|Delta|cdot|times)\b", stripped):
        return False
    has_vietnamese = bool(re.search(r"[À-ỹ]", stripped))
    if has_vietnamese and not re.search(r"\\text\{|~|\\\s|[=<>]", stripped):
        return False
    math_signal_count = sum(
        bool(re.search(pattern, stripped))
        for pattern in (
            r"\\[A-Za-z]+",
            r"[_^]\{?[\w\\]+",
            r"\d",
            r"[=<>]",
            r"\\cdot|\\times|\\frac|\\sqrt",
        )
    )
    words = re.findall(r"[A-Za-zÀ-ỹ]{3,}", stripped)
    word_limit = 10 if has_vietnamese else 28
    return math_signal_count >= 2 and len(words) <= word_limit


def _display_math_block(lines: list[str]) -> list[str]:
    body = "\n".join(line.rstrip() for line in lines if line.strip()).strip()
    if not body:
        return []
    return ["$$", body, "$$"]


def repair_mixed_math_markdown_blocks(content: str) -> str:
    """Split display math blocks that accidentally swallowed Markdown prose/list lines."""

    def transform(text: str) -> str:
        lines = text.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip() != "$$":
                out.append(line)
                i += 1
                continue

            block: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != "$$":
                block.append(lines[j])
                j += 1
            if j >= len(lines):
                out.append(line)
                out.extend(block)
                i = j
                continue

            has_markdown = any(_is_markdown_boundary_inside_math(block_line) for block_line in block)
            if not has_markdown:
                out.append(line)
                out.extend(block)
                out.append(lines[j])
                i = j + 1
                continue

            formula_buf: list[str] = []
            repaired: list[str] = []
            for block_line in block:
                stripped = block_line.strip()
                if not stripped:
                    continue
                if _is_markdown_boundary_inside_math(block_line):
                    repaired.extend(_display_math_block(formula_buf))
                    formula_buf = []
                    repaired.append(block_line)
                elif _looks_like_bare_formula_line(block_line) or formula_buf:
                    formula_buf.append(stripped)
                else:
                    repaired.extend(_display_math_block(formula_buf))
                    formula_buf = []
                    repaired.append(block_line)
            repaired.extend(_display_math_block(formula_buf))
            out.extend(repaired)
            i = j + 1

        return "\n".join(out)

    normalized = _apply_outside_fenced_blocks(content, transform)
    return re.sub(r"\n{3,}", "\n\n", normalized)


def wrap_bare_formula_lines(content: str) -> str:
    """Wrap standalone formula-like lines that were emitted without delimiters."""

    def transform(text: str) -> str:
        lines = text.split("\n")
        out: list[str] = []
        in_math = False

        for line in lines:
            stripped = line.strip()
            if stripped == "$$":
                in_math = not in_math
                out.append(line)
                continue
            if in_math or not _looks_like_bare_formula_line(line):
                out.append(line)
                continue
            indent = re.match(r"\s*", line).group(0)  # type: ignore[union-attr]
            out.extend([f"{indent}$$", f"{indent}{stripped}", f"{indent}$$"])

        return "\n".join(out)

    normalized = _apply_outside_fenced_blocks(content, transform)
    return re.sub(r"\n{3,}", "\n\n", normalized)


def normalize_display_math_blocks(content: str) -> str:
    """
    Normalize display math delimiters before Pandoc/Typst conversion.

    This repairs malformed blocks such as "$$\nexpr$$" and wraps plain
    multiline equations that use LaTeX row breaks in an aligned environment.
    """

    def transform(text: str) -> str:
        def repl(match: re.Match) -> str:
            inner = match.group(1).strip()
            if not inner:
                return "$$\n\n$$"

            inner = re.sub(r"^[ \t]+|[ \t]+$", "", inner, flags=re.MULTILINE)
            has_row_breaks = r"\\" in inner
            has_known_env = bool(_MATH_ENV_RE.search(inner))
            if has_row_breaks and not has_known_env:
                inner = "\\begin{aligned}\n" + inner + "\n\\end{aligned}"

            return "$$\n" + inner.strip() + "\n$$"

        return re.sub(
            r"(?<!\$)\$\$(?!\$)(.*?)(?<!\$)\$\$(?!\$)",
            repl,
            text,
            flags=re.DOTALL,
        )

    return _apply_outside_fenced_blocks(content, transform)


def normalize_lead_in_labels(content: str) -> str:
    """
    Split short lead-in labels from following prose.

    Hard line breaks after labels such as "**Bài tập thực hành:**  " can be
    rendered as one justified paragraph, stretching the label across the line.
    """

    def is_protected_line(stripped: str) -> bool:
        return (
            not stripped
            or stripped.startswith(("#", "-", "+", "* ", ">", "|"))
            or stripped == "$$"
            or bool(re.fullmatch(r"[-*_]{3,}", stripped))
        )

    def transform(text: str) -> str:
        lines = text.split("\n")
        out: list[str] = []
        in_math = False

        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "$$":
                in_math = not in_math
                out.append(line)
                continue

            if in_math or is_protected_line(stripped):
                out.append(line)
                continue

            next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
            has_hard_break = bool(re.search(r" {2,}$", line))
            if (
                _is_lead_in_label_text(stripped)
                and has_hard_break
                and next_line
                and not is_protected_line(next_line)
            ):
                out.append(line.rstrip())
                out.append("")
                continue

            out.append(line)

        return "\n".join(out)

    normalized = _apply_outside_fenced_blocks(content, transform)
    return re.sub(r"\n{3,}", "\n\n", normalized)


def normalize_list_lead_in_labels(content: str) -> str:
    """Split list-item lead-in labels from their continuation paragraph."""

    item_re = re.compile(
        r"^(?P<indent>\s*)(?P<marker>(?:[-+*]|\d+[.)])\s+)(?P<label>(?:\*\*)?[^:\n]{2,90}:(?:\*\*)?)\s+(?P<body>\S.*)$"
    )

    def label_text(value: str) -> str:
        return re.sub(r"[*_`]+", "", value).strip()

    def transform(text: str) -> str:
        lines = text.split("\n")
        out: list[str] = []
        in_math = False

        for line in lines:
            stripped = line.strip()
            if stripped == "$$":
                in_math = not in_math
                out.append(line)
                continue
            if in_math:
                out.append(line)
                continue

            match = item_re.match(line)
            if not match or not _is_lead_in_label_text(label_text(match.group("label"))):
                out.append(line)
                continue

            continuation_indent = match.group("indent") + (" " * len(match.group("marker")))
            out.append(f'{match.group("indent")}{match.group("marker")}{match.group("label")}')
            out.append("")
            out.append(f'{continuation_indent}{match.group("body").strip()}')

        return "\n".join(out)

    normalized = _apply_outside_fenced_blocks(content, transform)
    return re.sub(r"\n{3,}", "\n\n", normalized)


def lint_math_export_risks(content: str) -> str:
    """Apply conservative final cleanup for known export-risk math artifacts."""

    def clean_math_text(value: str) -> str:
        value = re.sub(r"(?<=[A-Za-z0-9_}])\s*=\s*=\s*", " = ", value)
        value = re.sub(r"\s{2,}", " ", value)
        return value.strip()

    def transform(text: str) -> str:
        def display_repl(match: re.Match) -> str:
            body = match.group(1)
            return "$$\n" + "\n".join(
                clean_math_text(line) for line in body.split("\n") if line.strip()
            ) + "\n$$"

        text = re.sub(
            r"(?<!\$)\$\$(?!\$)(.*?)(?<!\$)\$\$(?!\$)",
            display_repl,
            text,
            flags=re.DOTALL,
        )
        lines = [
            clean_math_text(line) if _looks_like_bare_formula_line(line) else line
            for line in text.split("\n")
        ]
        return "\n".join(lines)

    normalized = _apply_outside_fenced_blocks(content, transform)
    normalized = repair_mixed_math_markdown_blocks(normalized)
    return re.sub(r"\n{3,}", "\n\n", normalized)


_FORMULA_TOKEN_RE = r'(?:\$[^$\n]{1,80}\$|`[^`\n]{1,80}`)'
_FORMULA_DEFINITION_START_RE = re.compile(
    rf'^{_FORMULA_TOKEN_RE}\s*(?::|(?:là|is|are)\b)',
    re.IGNORECASE,
)


def _looks_like_formula_symbol(expr: str) -> bool:
    expr = expr.strip()
    if not expr or not re.search(r'[A-Za-z]', expr):
        return False
    if re.search(r'["\'=\[\]()]', expr):
        return False
    if re.search(r'[_\\{}^]', expr):
        return True
    if re.fullmatch(r'[A-Z][A-Z0-9]{0,9}', expr):
        return True
    if re.fullmatch(r'[A-Za-z](?:\s*,\s*[A-Za-z])+', expr):
        return True
    if re.fullmatch(r'[A-Za-z]', expr):
        return True
    return False


def _looks_like_indexed_formula_symbol(expr: str) -> bool:
    expr = expr.strip()
    if not expr or len(expr) > 80:
        return False
    if re.search(r'["\']', expr):
        return False
    base = r'[A-Za-z](?:_\{?[A-Za-z0-9]+\}?)?'
    index = r'[A-Za-z0-9\s,+\-*/^_{}\\().]+'
    return bool(re.fullmatch(rf'{base}\[{index}\]', expr))


def _looks_like_formula_backtick_expression(expr: str) -> bool:
    expr = expr.strip()
    if _looks_like_formula_symbol(expr):
        return True
    if _looks_like_indexed_formula_symbol(expr):
        return True
    if "=" not in expr:
        return False
    if not re.search(r'[\\_^{}]', expr):
        return False
    if re.search(r'\b(?:if|for|while|return|import|class|def)\b', expr):
        return False
    return bool(re.search(r'[A-Za-z]', expr))


def _convert_formula_backticks(text: str) -> str:
    def repl(match: re.Match) -> str:
        expr = match.group(1).strip()
        if _looks_like_formula_backtick_expression(expr):
            return f'${_normalize_math_identifier_text(expr)}$'
        return match.group(0)

    return re.sub(r'`([^`\n]{1,80})`', repl, text)


def _looks_like_cleanable_formula_span(expr: str) -> bool:
    expr = expr.strip()
    if not expr or len(expr) > 80:
        return False
    if not re.search(r"[A-Za-z]", expr):
        return False
    if re.search(r"[^\w\s\\{}^,+\-*/=<>|().]", expr):
        return False
    if _looks_like_formula_symbol(expr):
        return True
    if "\\" in expr or "_" in expr or "^" in expr:
        return True
    if re.fullmatch(r"[A-Za-z0-9\\{}_^,+\-*/=<>|().\s]+", expr):
        return len(expr.split()) <= 8
    return False


def _cleanup_spaced_formula_delimiters(text: str) -> str:
    def repl(match: re.Match) -> str:
        expr = match.group(1).strip()
        if _looks_like_cleanable_formula_span(expr):
            return f"${expr}$"
        return match.group(0)

    text = re.sub(r"\$(?!\$)\s+([^$\n]{1,80}?)\s+\$(?!\$)", repl, text)
    text = re.sub(
        r"\$(?!\$)\s+([^$\n]{1,80}?)(?<!\s)\$(?!\$)",
        repl,
        text,
    )
    text = re.sub(
        r"\$(?!\$)(?!\s)([^$\n]{1,80}?)\s+\$(?!\$)",
        repl,
        text,
    )
    return text


def _fix_glued_inline_math(text: str) -> str:
    text = _cleanup_spaced_formula_delimiters(text)
    pieces: list[tuple[str, bool]] = []
    pos = 0
    length = len(text)

    while pos < length:
        start = text.find("$", pos)
        if start == -1:
            pieces.append((text[pos:], False))
            break
        if start + 1 < length and text[start + 1] == "$":
            pieces.append((text[pos:start + 2], False))
            pos = start + 2
            continue

        end = text.find("$", start + 1)
        while end != -1 and end + 1 < length and text[end + 1] == "$":
            end = text.find("$", end + 2)
        if end == -1 or "\n" in text[start + 1:end]:
            pieces.append((text[pos:start + 1], False))
            pos = start + 1
            continue

        pieces.append((text[pos:start], False))
        expr = text[start + 1:end].strip()
        if expr != text[start + 1:end] and _looks_like_cleanable_formula_span(expr):
            pieces.append((f"${expr}$", True))
        else:
            pieces.append((text[start:end + 1], True))
        pos = end + 1

    out: list[str] = []
    for idx, (piece, is_math) in enumerate(pieces):
        if not piece:
            continue
        unit_suffix_math = piece.startswith("$^") or piece.startswith("$_")
        if (
            is_math
            and not unit_suffix_math
            and out
            and re.search(r"(?:[^\W\d_]|[,;:=<>])$", out[-1])
        ):
            out.append(" ")
        out.append(piece)
        if is_math and idx + 1 < len(pieces):
            next_piece, _next_is_math = pieces[idx + 1]
            if next_piece and re.match(r"^(?:[^\W\d_]|[=<>])", next_piece):
                out.append(" ")
    return "".join(out)


def normalize_markdown_list_spacing(content: str) -> str:
    """Ensure Markdown lists are separated from prose so Pandoc parses them."""
    list_item_re = re.compile(r'^\s*(?:[-+*]\s+\S|\d+[.)]\s+\S)')
    formula_intro_re = re.compile(r'^\s*(?:Trong đó|Where)\b', re.IGNORECASE)

    def is_list_item(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if re.fullmatch(r'[-*_]{3,}', stripped):
            return False
        return bool(list_item_re.match(line))

    def transform(text: str) -> str:
        lines = text.split('\n')
        out: list[str] = []

        for line in lines:
            current_is_list = is_list_item(line)
            if out:
                prev = out[-1]
                prev_is_blank = not prev.strip()
                prev_is_list = is_list_item(prev)
                if current_is_list and not prev_is_blank and not prev_is_list:
                    out.append("")
                elif formula_intro_re.match(line) and prev_is_list and not prev_is_blank:
                    out.append("")
                elif (
                    not current_is_list
                    and line.strip()
                    and prev_is_list
                    and not re.match(r'^\s{2,}\S', line)
                ):
                    out.append("")
            out.append(line)

        return '\n'.join(out)

    normalized = _apply_outside_fenced_blocks(content, transform)
    return re.sub(r'\n{3,}', '\n\n', normalized)


def normalize_markdown_image_blocks(content: str) -> str:
    """Keep Markdown images as standalone blocks so Pandoc emits captions."""
    image_re = re.compile(r'!\[[^\]\n]*\]\([^\)\n]+\)(?:\{[^}\n]*\})?')

    def next_nonblank_is_image(lines: list[str], index: int) -> bool:
        for next_line in lines[index + 1:]:
            stripped = next_line.strip()
            if not stripped:
                continue
            return bool(image_re.fullmatch(stripped))
        return False

    def append_paragraph(out: list[str], text: str) -> None:
        text = text.strip()
        if not text:
            return
        if out and out[-1].strip():
            out.append("")
        out.append(text)

    def transform(text: str) -> str:
        lines = text.split('\n')
        out: list[str] = []
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == ">" and next_nonblank_is_image(lines, index):
                continue

            matches = list(image_re.finditer(line))
            if not matches:
                out.append(line)
                continue

            cursor = 0
            for match in matches:
                append_paragraph(out, line[cursor:match.start()])
                append_paragraph(out, match.group(0))
                out.append("")
                cursor = match.end()
            append_paragraph(out, line[cursor:])

        return '\n'.join(out)

    normalized = _apply_outside_fenced_blocks(content, transform)
    return re.sub(r'\n{3,}', '\n\n', normalized)


def _split_dash_definition_items(text: str) -> list[str]:
    body = re.sub(r'^\s*-\s*', '', text.strip())
    parts = [
        part.strip()
        for part in re.split(rf'\s*,?\s+-\s*(?={_FORMULA_TOKEN_RE})', body)
        if part.strip()
    ]
    if len(parts) <= 1:
        return [text.strip()]
    if sum(1 for part in parts if _FORMULA_DEFINITION_START_RE.match(part)) < 2:
        return [text.strip()]
    return parts


def _split_inline_definition_items(text: str) -> list[str]:
    body = text.strip()
    parts = [
        part.strip()
        for part in re.split(
            rf'\s*,\s+(?={_FORMULA_TOKEN_RE}\s*(?::|(?:là|is|are)\b))',
            body,
            flags=re.IGNORECASE,
        )
        if part.strip()
    ]
    if len(parts) <= 1:
        return [text.strip()]
    if not all(_FORMULA_DEFINITION_START_RE.match(part) for part in parts):
        return [text.strip()]
    return parts


def _format_formula_definition_item(item: str) -> str:
    item = re.sub(r'^\s*-\s*', '', item.strip()).rstrip(' ,;')
    item = _convert_formula_backticks(item)
    item = re.sub(
        r'^(\$[^$\n]+\$)\s+(?:là|is|are)\s+',
        r'\1: ',
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r'^(\$[^$\n]+\$)\s*[:：]\s*', r'\1: ', item)
    return f'- {item}'


def normalize_formula_explanations(content: str) -> str:
    """
    Normalize formula explanation blocks for clean Markdown/Pandoc rendering.

    The writer sometimes emits compact explanations such as
    "Trong đó: - $E$ là ..., - $R$ là ..." or uses backticks for formula
    symbols. This pass turns those into one bullet per variable.
    """
    intro_re = re.compile(r'^(?P<label>Trong đó|Where)\s*:?\s*(?P<body>.*)$', re.IGNORECASE)
    inline_intro_re = re.compile(r'\s+(?P<label>Trong đó|Where)\s*:?\s*(?P<body>.*)$', re.IGNORECASE)

    def transform(text: str) -> str:
        text = _fix_glued_inline_math(text)
        lines = text.split('\n')
        out: list[str] = []
        in_formula_definitions = False

        def emit_formula_intro(indent: str, label: str, body: str) -> bool:
            nonlocal in_formula_definitions
            body = body.strip()
            if not body:
                out.append(f'{indent}{label}:')
                in_formula_definitions = True
                return True

            items = (
                _split_dash_definition_items(body)
                if body.startswith('-')
                else _split_inline_definition_items(body)
            )
            if len(items) > 1 or _FORMULA_DEFINITION_START_RE.match(items[0]):
                out.append(f'{indent}{label}:')
                out.extend(
                    f'{indent}{_format_formula_definition_item(item)}'
                    for item in items
                )
                in_formula_definitions = True
                return True

            line = f'{indent}{label} {body}'
            line = _convert_formula_backticks(line)
            out.append(line)
            in_formula_definitions = False
            return True

        for line in lines:
            indent = re.match(r'\s*', line).group(0) #type: ignore
            stripped = line.strip()

            if not stripped:
                out.append(line)
                in_formula_definitions = False
                continue

            intro_match = intro_re.match(stripped)
            if intro_match:
                emit_formula_intro(
                    indent,
                    intro_match.group('label'),
                    intro_match.group('body'),
                )
                continue

            if stripped.startswith(('- ', '+ ', '* ')):
                inline_intro_match = inline_intro_re.search(line)
                if inline_intro_match and inline_intro_match.start() > line.find(stripped[0]) + 2:
                    before = line[:inline_intro_match.start()].rstrip()
                    if before:
                        out.append(before)
                        out.append("")
                    emit_formula_intro(
                        indent,
                        inline_intro_match.group('label'),
                        inline_intro_match.group('body'),
                    )
                    continue

            if in_formula_definitions and stripped.startswith('- '):
                items = _split_dash_definition_items(stripped)
                out.extend(
                    f'{indent}{_format_formula_definition_item(item)}'
                    for item in items
                )
                continue

            if not stripped.startswith('- '):
                in_formula_definitions = False

            if stripped.startswith('- '):
                line = re.sub(
                    r'(?<=[.!?])\s+-\s+(?=\S)',
                    f'\n{indent}- ',
                    line,
                )

            if (
                '`' in line
                and (
                    'trong đó' in line.lower()
                    or 'công thức' in line.lower()
                    or 'formula' in line.lower()
                    or 'with ' in line.lower()
                    or 'với ' in line.lower()
                    or re.search(r'\$[^$\n]*=[^$\n]*\$', line)
                )
            ):
                line = _convert_formula_backticks(line)

            out.append(line)

        return '\n'.join(out)

    return _apply_outside_fenced_blocks(content, transform)


def promote_standalone_inline_math(content: str) -> str:
    """Convert equation-only inline math lines into display math blocks."""
    def transform(text: str) -> str:
        lines = text.split('\n')
        out: list[str] = []
        for line in lines:
            match = re.match(r'^(\s*)\$(?!\$)([^$\n]+)\$(?!\$)\s*$', line)
            if match and _looks_like_display_math_expression(match.group(2)):
                indent = match.group(1)
                expr = match.group(2).strip()
                out.extend([f'{indent}$$', f'{indent}{expr}', f'{indent}$$'])
            else:
                out.append(line)
        return '\n'.join(out)

    return _apply_outside_fenced_blocks(content, transform)


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


def remove_markdown_horizontal_rules(content: str) -> str:
    """
    Remove standalone Markdown horizontal rules from generated body content.

    The publisher adds YAML front matter separately, so this pass is applied
    only to body Markdown before YAML assembly. Lines inside fenced code blocks
    are preserved because they may be teaching examples.
    """
    lines = content.split('\n')
    cleaned: list[str] = []
    in_fence = False

    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            cleaned.append(line)
            continue

        if not in_fence and re.fullmatch(r'\s*-{3,}\s*', line):
            continue

        cleaned.append(line)

    result = '\n'.join(cleaned)
    return re.sub(r'\n{3,}', '\n\n', result)


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
    Prefix image captions with chapter-scoped figure numbers.

    Tracks the current ``# CHƯƠNG N``/``# CHAPTER N`` heading as images are
    encountered and prefixes each caption with "Hình N.M:"/"Figure N.M:".

    Behaviour:
        - Existing figure-number prefixes are replaced, making the pass
          idempotent and normalizing legacy section-scoped numbers.
        - Images before the first chapter heading are left unchanged.
        - The counter is shared by all sections in a chapter and starts again
          at 1 for each new chapter.
    """
    lines = content.split('\n')
    result: list[str] = []
    current_chapter = ""
    chapter_img_count: dict[str, int] = {}
    profile = get_language_profile(language)
    chapter_heading_re = re.compile(
        rf'^#\s+{re.escape(profile.chapter_label)}\s+(\d+)\b',
        flags=re.IGNORECASE,
    )
    existing_number_re = re.compile(
        rf'^{re.escape(profile.figure_label)}\s+\d+(?:\.\d+)*\s*:\s*',
        flags=re.IGNORECASE,
    )

    for line in lines:
        chapter_match = chapter_heading_re.match(line)
        if chapter_match:
            current_chapter = chapter_match.group(1)
            result.append(line)
            continue

        img_match = re.match(r'^(!\[)([^\]]*?)(\]\()(.+?)(\))(\{.*?\})?$', line)
        if img_match and current_chapter:
            caption = existing_number_re.sub("", img_match.group(2), count=1)
            path    = img_match.group(4)
            attrs   = img_match.group(6) or ""

            chapter_img_count[current_chapter] = (
                chapter_img_count.get(current_chapter, 0) + 1
            )
            n = chapter_img_count[current_chapter]
            caption = f"{profile.figure_label} {current_chapter}.{n}: {caption}"
            line = f"![{caption}]({path}){attrs}"

        result.append(line)

    return '\n'.join(result)


def prepare_markdown_for_standalone_export(
    md_content: str,
    language: str = "vi",
    enable_images: bool = True,
) -> str:
    """
    Apply publisher-safe formatting passes to an existing Markdown file.

    This is used by preview CLIs that start from checkpoint/raw Markdown rather
    than from the full workflow state.
    """
    content = md_content.replace('\r\n', '\n').replace('\r', '\n')
    content = fix_unicode_math(content)
    content = fix_programming_inline_code(content)
    if language == "en":
        content = normalize_english_dashes(content)
    content = fix_markdown_headings(content)
    content = remove_markdown_horizontal_rules(content)
    content = repair_mixed_math_markdown_blocks(content)
    content = wrap_bare_formula_lines(content)
    content = normalize_display_math_blocks(content)
    content = fix_inline_display_math(content)
    content = fix_math_formatting(content)
    content = normalize_math_identifier_formatting(content)
    content = normalize_formula_explanations(content)
    content = normalize_lead_in_labels(content)
    content = normalize_list_lead_in_labels(content)
    content = normalize_markdown_list_spacing(content)
    content = lint_math_export_risks(content)
    content = normalize_markdown_list_spacing(content)
    content = normalize_markdown_image_blocks(content)
    content = promote_standalone_inline_math(content)
    content = fix_typst_deprecated_symbols(content)
    content = fix_chapter_pagebreaks(content, language=language)
    if enable_images:
        content = add_figure_numbers(content, language=language)
    return content


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
        - Figure list: inserted as a marker, then finalized with Word fields

    Pipeline:
        1. Strip YAML front matter
        2. Replace {=typst} #pagebreak() blocks → OpenXML page break
        3. Strip remaining {=typst} blocks
        4. Build figure list marker when image captions exist
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
    content = repair_mixed_math_markdown_blocks(content)
    content = wrap_bare_formula_lines(content)
    content = normalize_display_math_blocks(content)
    content = normalize_math_identifier_formatting(content)
    content = normalize_formula_explanations(content)
    content = normalize_lead_in_labels(content)
    content = normalize_list_lead_in_labels(content)
    content = normalize_markdown_list_spacing(content)
    content = lint_math_export_risks(content)
    content = normalize_markdown_list_spacing(content)
    content = normalize_markdown_image_blocks(content)

    # Step 4 — Detect captions already in MD.
    # Captions format: "Figure/Hình X.Y: Caption text" — set by add_figure_numbers()
    # No leading _WORD_PAGEBREAK — Step 5 manages page separation around this block.
    figure_list_md = ""
    if enable_images:
        captions = re.findall(
            rf'!\[({re.escape(profile.figure_label)} [\d.]+:[^\]]+)\]',
            content,
        )
        if captions:
            figure_list_md = f"{profile.figure_list_label}\n\n{_WORD_FIGURE_LIST_MARKER}"
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
    custom = BASE_DIR / "assets" / "reference.docx" #type: ignore
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

        # 2. Patch Word styles that Pandoc emits with explicit theme fonts.
        _patch_word_document_styles(ref_doc)

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
        12. add_figure_numbers()        — "Hình X.N:"
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
    timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
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
    full_content = remove_markdown_horizontal_rules(full_content)
    full_content = repair_mixed_math_markdown_blocks(full_content)
    full_content = wrap_bare_formula_lines(full_content)
    full_content = normalize_display_math_blocks(full_content)
    full_content = fix_inline_display_math(full_content)
    full_content = fix_math_formatting(full_content)
    full_content = normalize_math_identifier_formatting(full_content)
    full_content = normalize_formula_explanations(full_content)
    full_content = normalize_lead_in_labels(full_content)
    full_content = normalize_list_lead_in_labels(full_content)
    full_content = normalize_markdown_list_spacing(full_content)
    full_content = lint_math_export_risks(full_content)
    full_content = normalize_markdown_list_spacing(full_content)
    full_content = normalize_markdown_image_blocks(full_content)
    full_content = promote_standalone_inline_math(full_content)
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
                  show table.cell: it => {
                    set align(left)
                    set par(justify: false)
                    it
                  }
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
                    finalize_word_docx(
                        docx_filename,
                        profile.toc_label,
                        page_start_heading=profile.preface_heading,
                    )
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
