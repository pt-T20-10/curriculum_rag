"""
Reviewer Agent for AI Textbook Generator.

This agent reviews and polishes Writer-drafted content before it proceeds
to the Illustrator. It runs two sequential passes per subsection:

Pass 1 — review_content():
    Full editorial pass covering LaTeX/math sanitization, academic tone,
    structural consistency, and quality gating.
    Output is the polished Markdown sent back to the workflow.

Pass 2 — should_revise():
    Lightweight quality gate that decides whether the polished content
    meets minimum standards. If rejected and below MAX_REVISIONS, the
    workflow routes back to the Writer for a targeted rewrite.

PDF pipeline note: the document is compiled via Pandoc → Typst, not
directly via LaTeX/xelatex. Math sanitization targets Pandoc-compatible
$...$ and $$...$$ delimiters, which Typst's math renderer consumes.
"""

import json
import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.utils.log_config import setup_logger, setup_prompt_logger
from app.schemas.curriculum import (
    AgentState,
    Chapter,
    SubSection,
    get_chapter_and_subsection,
    clean_section_title,
)
from app.config import settings
from app.services.cost_profile import auxiliary_chat_model, use_balanced_cost
from app.services.api_rate_limiter import rate_limited_invoke
from app.services.runtime_config import get_api_key
from app.services.textbook.language import get_language_profile

LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
LLM_MODEL_PREMIUM =settings.LLM_MODEL_PREMIUM

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")


def _is_practice_mode(textbook_mode: str | None) -> bool:
    return str(textbook_mode or "standard").strip().lower() == "practice"

# Maximum number of revision cycles per subsection before forcing approval.
# Also imported by graph.py for the graph-level defense-in-depth ceiling.
MAX_REVISIONS = settings.REVIEWER_MAX_REVISIONS


def _quality_gate_model(advanced_config: dict | None = None) -> str:
    return auxiliary_chat_model(
        cheap_model=LLM_MODEL_CHEAP,
        premium_model=LLM_MODEL_PREMIUM,
        advanced_config=advanced_config,
    )


_IMAGE_MARKER_LINE_RE = re.compile(
    r"^\s*>?\s*\[(?:IMAGE|IMAGE_NEEDED):.*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
_UNICODE_SUB_SUP_RE = re.compile(r"[₀₁₂₃₄₅₆₇₈₉⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹]")


def strip_image_markers_when_disabled(content: str) -> str:
    """Remove image placeholders/tags when the run explicitly disabled images."""
    cleaned = _IMAGE_MARKER_LINE_RE.sub("", content or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() if cleaned.strip() else cleaned


def _code_fence_without_language(content: str) -> bool:
    inside = False
    for line in (content or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("```"):
            continue
        if not inside:
            if stripped == "```":
                return True
            inside = True
        else:
            inside = False
    return False


def _has_heading_blank_line_issue(content: str) -> bool:
    lines = (content or "").splitlines()
    for idx, line in enumerate(lines):
        if not re.match(r"^#{1,3}\s+\S", line):
            continue
        if idx > 0 and lines[idx - 1].strip():
            return True
        if idx + 1 < len(lines) and lines[idx + 1].strip():
            return True
    return False


def _is_numbered_h3(line: str) -> bool:
    return bool(re.match(r"^###\s+\d+\.\d+\.\d+\s+\S", line.strip()))


def _normalize_unnumbered_h3_to_bold(content: str) -> str:
    """Convert display-label ### headings into bold lead-ins."""
    lines: list[str] = []
    for line in (content or "").splitlines():
        match = re.match(r"^###\s+(.+?)\s*$", line)
        if match and not _is_numbered_h3(line):
            title = match.group(1).strip().rstrip(":")
            lines.append(f"**{title}:**")
        else:
            lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _page_budget_mode(target_pages: int | None, char_max: int | None = None) -> str:
    try:
        pages = int(target_pages) if target_pages is not None else None
    except (TypeError, ValueError):
        pages = None
    if pages is not None:
        if pages <= 2:
            return "compact"
        if pages <= 4:
            return "standard"
        return "expanded"
    if char_max is not None and char_max <= 2600:
        return "compact"
    return "standard"


def _has_format_issues(
    content: str,
    section_num: str,
    section_title: str,
    language: str = "vi",
) -> bool:
    expected_section = rf"^##\s+{re.escape(section_num)}\s+{re.escape(section_title)}\s*$"
    has_expected_section = bool(re.search(expected_section, content or "", re.MULTILINE))
    if not has_expected_section:
        return True
    if re.search(r"^#{4,}\s+", content or "", re.MULTILINE):
        return True
    if re.search(r"^###\s+(?!\d+\.\d+\.\d+\s+).+", content or "", re.MULTILINE):
        return True
    if re.search(rf"^##\s+{re.escape(section_num)}:", content or "", re.MULTILINE):
        return True
    if re.search(r"^\s*-{3,}\s*$", content or "", re.MULTILINE):
        return True
    if "\\[" in content or "\\]" in content or "\\(" in content or "\\)" in content:
        return True
    if "\\begin{equation}" in content or "\\end{equation}" in content:
        return True
    if _UNICODE_SUB_SUP_RE.search(content or ""):
        return True
    if _has_heading_blank_line_issue(content):
        return True
    if _code_fence_without_language(content):
        return True
    if "—" in (content or "") or (language == "en" and "–" in (content or "")):
        return True
    return False


def _subsection_blocks(content: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^###\s+(.+)$", content or "", flags=re.MULTILINE))
    blocks: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content or "")
        blocks.append((match.group(1).strip(), (content or "")[start:end].strip()))
    return blocks


def _substantial_paragraph_count(text: str) -> int:
    paragraphs = [
        part.strip()
        for part in re.split(r"\n\s*\n", text or "")
        if part.strip()
    ]
    return sum(
        1
        for paragraph in paragraphs
        if not paragraph.lstrip().startswith(("#", ">", "-", "*", "```"))
        and len(re.sub(r"\s+", " ", paragraph)) >= 120
    )


def _has_content_issues(
    content: str,
    char_min: int,
    review_feedback: str = "",
    page_budget_mode: str = "standard",
) -> bool:
    text = content or ""
    feedback = (review_feedback or "").lower()
    if len(text) < char_min:
        return True
    if re.search(r"\b(chúng ta hãy|hãy cùng|cùng tìm hiểu|let's|we will now)\b", text, re.IGNORECASE):
        return True
    if len(re.findall(r"\*\*[^*\n]{1,80}\*\*", text)) > 10:
        return True
    blocks = _subsection_blocks(text)
    if page_budget_mode == "compact":
        if len(blocks) == 1:
            return True
        depth_signals = (
            "wrong focus", "sai trọng tâm", "thiếu nội dung cốt lõi",
            "missing core", "too long", "quá dài",
        )
        return any(signal in feedback for signal in depth_signals)
    if not blocks:
        return True
    for _heading, body in blocks:
        if _substantial_paragraph_count(body) < 2:
            return True
    depth_signals = (
        "depth", "deeper", "superficial", "paragraph", "expand",
        "thiếu chiều sâu", "nông cạn", "mở rộng", "thêm ví dụ",
    )
    return any(signal in feedback for signal in depth_signals)


def deterministic_quality_gate_passes(
    content: str,
    *,
    char_min: int,
    char_max: int | None,
    section_num: str,
    section_title: str,
    section_type: str,
    language: str,
    page_budget_mode: str = "standard",
) -> bool:
    """Conservative no-LLM approval gate for balanced_cost."""
    if len(content or "") < char_min:
        return False
    if _has_format_issues(content, section_num, section_title, language):
        return False
    if _has_content_issues(content, char_min, page_budget_mode=page_budget_mode):
        return False
    max_blocks = {
        "light": 2,
        "medium": 3,
        "deep": 4,
        "applied": 3,
    }.get(section_type, 3)
    blocks = _subsection_blocks(content)
    if page_budget_mode == "compact" and len(blocks) == 1:
        return False
    return len(blocks) <= max_blocks


def _structured_learning_element_count(content: str) -> int:
    text = content or ""
    lower = text.lower()
    count = 0
    count += len(re.findall(r'\$\$.*?\$\$|\$[^$\n]+\$', text, flags=re.DOTALL))
    count += len(re.findall(r'^\s*\|.+\|\s*$', text, flags=re.MULTILINE))
    count += len(re.findall(r'```', text)) // 2
    count += len(re.findall(r'^\s*(?:[-*]|\d+\.)\s+', text, flags=re.MULTILINE))
    structured_terms = (
        "ví dụ", "example", "bài tập", "exercise", "case study", "tình huống",
        "checklist", "rubric", "kpi", "metric", "chỉ số", "chi so",
        "timeline", "dòng thời gian", "bang so sánh", "bảng so sánh",
        "công thức", "formula", "mô hình", "model", "trong đó",
        "where:", "tiêu chí", "criteria",
    )
    count += sum(1 for term in structured_terms if term in lower)
    return count


def _structured_expansion_feedback(
    content: str,
    *,
    target_pages: int | None,
    formula_density: str | None,
    expansion_strategy: str | None,
    language: str,
) -> str:
    try:
        pages = int(target_pages) if target_pages is not None else None
    except (TypeError, ValueError):
        pages = None
    needs_structured = (
        (pages is not None and pages >= 4)
        or str(formula_density or "none") in {"contextual", "high"}
    )
    if not needs_structured:
        return ""
    required = 2 if pages is not None and pages >= 8 else 1
    if _structured_learning_element_count(content) >= required:
        return ""
    if language == "vi":
        return (
            "Mục này có ngân sách trang lớn hoặc ưu tiên công thức/cấu trúc nhưng "
            "đang gần như chỉ là văn xuôi. Hãy bổ sung thành phần học thuật có cấu trúc "
            f"phù hợp với chiến lược '{expansion_strategy or 'general'}': công thức/mô hình, "
            "bảng tiêu chí, rubric, checklist, timeline, case study, ví dụ tính toán, "
            "bài tập hoặc bảng so sánh. Không kéo dài prose đơn thuần."
        )
    return (
        "This section has a large page budget or formula/structured-tool preference "
        "but is mostly continuous prose. Add domain-appropriate structured learning "
        f"elements for strategy '{expansion_strategy or 'general'}': formula/model, "
        "criteria table, rubric, checklist, timeline, case study, worked example, "
        "exercise, or comparison table. Do not merely stretch prose."
    )


def _balanced_rejection_kind(feedback: str) -> str:
    feedback_lower = (feedback or "").lower()
    if any(term in feedback_lower for term in (
        "source", "rag", "context", "nguồn", "ngữ cảnh",
        "missing definition", "thiếu định nghĩa",
    )):
        return "missing_context"
    if any(term in feedback_lower for term in (
        "too short", "quá ngắn", "chars", "ký tự", "paragraph",
        "expand", "mở rộng", "superficial", "nông cạn", "depth", "chiều sâu",
        "example", "ví dụ",
    )):
        return "length_depth"
    return "formatting_error"


def _math_format_gate_feedback(content: str) -> str:
    """Return actionable feedback for severe Markdown/math export risks."""
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if text.count("$$") % 2:
        return (
            "Math formatting error: a display math block is not closed. "
            "Rewrite formulas so every calculation step uses its own $$...$$ block."
        )
    if re.search(r"\\\[|\\\]|\\\(|\\\)", text):
        return (
            "Math formatting error: non-standard math delimiters found. "
            "Use $$...$$ for display formulas and $...$ for inline formulas."
        )
    if re.search(r"(?<=[A-Za-z0-9_}])\s*=\s*=\s*", text):
        return (
            "Math formatting error: malformed '= =' expression found. "
            "Rewrite the affected formula completely with a valid left side, one equals sign, and a result."
        )

    display_re = re.compile(r"(?<!\$)\$\$(?!\$)(.*?)(?<!\$)\$\$(?!\$)", re.DOTALL)
    spans: list[tuple[int, int]] = []
    for match in display_re.finditer(text):
        spans.append(match.span())
        body = match.group(1)
        if re.search(r"(?m)^\s*(?:[-+*]|\d+[.)]|[a-z]\))\s+\S", body):
            return (
                "Math formatting error: a $$...$$ block contains Markdown list items. "
                "Close the math block before the next numbered/bulleted step; each calculation step needs its own formula block."
            )
        if re.search(r"(?m)^\s*#{1,6}\s+\S", body):
            return (
                "Math formatting error: a $$...$$ block contains a Markdown heading. "
                "Move headings outside math blocks."
            )
        if re.search(r"(?m)^\s*(?:Trong đó|Where|Hướng dẫn giải|Ví dụ|Bài tập)[^$]{0,80}:\s*$", body, re.IGNORECASE):
            return (
                "Math formatting error: explanatory prose is inside a $$...$$ block. "
                "Keep prose outside math blocks and put only formulas between $$ delimiters."
            )

    def in_display_math(position: int) -> bool:
        return any(start <= position < end for start, end in spans)

    bare_formula_re = re.compile(
        r"(?m)^(?!\s*(?:[-+*]|\d+[.)]|[a-z]\)|#|\||>|```))\s*"
        r"(?=[^$\n]*(?:\\(?:frac|sqrt|Phi|omega|Omega|Delta|cdot|times)|[_^]\{?[\w\\]+))"
        r"(?=[^$\n]*[=<>])[^$\n]{8,220}$"
    )
    for match in bare_formula_re.finditer(text):
        if not in_display_math(match.start()):
            return (
                "Math formatting error: a standalone formula line is outside $$ delimiters. "
                "Wrap every standalone calculation line in its own $$...$$ block."
            )
    return ""


class ReviewerAgent:
    """
    Reviewer Agent: Editorial pass + quality gate for each drafted section.

    Responsibilities:
    - LaTeX/math sanitization (Pandoc → Typst pipeline compatibility)
    - Academic tone enforcement (remove conversational fillers)
    - Structural consistency (header format, blank lines, sub-section depth)
    - Quality gate: approve or reject polished content (max MAX_REVISIONS times)

    LLM is initialized once in __init__ and reused across calls within the
    same agent lifetime — no per-call instantiation overhead.
    """

    def __init__(self) -> None:
        """
        Initialize LLM with temperature=0.1 for precise, deterministic editing.

        Low temperature is intentional: the Reviewer performs rule-based fixes
        (delimiter replacement, header normalization) where creativity is
        undesirable and consistency is critical.
        """

        self.llm = ChatOpenAI(
            model=LLM_MODEL_PREMIUM,
            api_key=get_api_key("OPENAI_API_KEY"), # type: ignore[arg-type]
            temperature=0.1,
        )
        self.prompt_logger = setup_prompt_logger("reviewer")

    def should_revise(
        self,
        content: str,
        char_min: int = 300,
        char_max: int | None = None,
        language: str = "vi",
        advanced_config: dict | None = None,
        textbook_mode: str = "standard",
    ) -> tuple[bool, str]:
        """
        Quality gate: decide whether polished content meets minimum standards.

        Evaluation criteria (any single failure → needs_revision=True):
            1. Character count below char_min (content too short).
            2. Naked math — LaTeX symbols outside $ delimiters (e.g. a_x, \\frac).
            3. Wrong math delimiters — \\[ \\] or \\( \\) instead of $$ or $.
            4. Conversational or unprofessional tone in the target language.
            5. Superficial content — missing definitions, examples, or core
            explanations; OR any ### sub-section with fewer than 3 paragraphs.
            6. Any Markdown heading not preceded by a blank line.

        Uses ISE-structured prompt: [CONTEXT] → [TASK] → [CONSTRAINT] → [FORMAT].
        [CONSTRAINT] lists hard rejection rules; model approves only when none fire.

        Args:
            content:  Polished content from review_content().
            char_min: Minimum character count floor (default 300 as safety net;
                    callers should pass the section's effective char_target[0]).
            char_max: Soft target retained for logging/telemetry only. Reviewer
                    must not request rewrites only because content exceeds it;
                    longer-than-target content is acceptable if quality and the
                    minimum floor pass.

        Returns:
            (needs_revision, feedback) tuple.
            Falls back to (False, "") on any error to avoid blocking the workflow.
        """
        practice_mode = _is_practice_mode(textbook_mode)
        # Fast Python pre-check. LLM character counting is unreliable
        # (underestimates by 30-40%), so deterministic length checks handle
        # obvious below-floor cases before the LLM quality gate. There is no
        # upper-length rejection: longer-than-target content is preferable to
        # spending another call to condense acceptable material.
        math_feedback = _math_format_gate_feedback(content)
        if math_feedback:
            logger.info("Quality gate: REJECT — deterministic math format gate")
            return True, math_feedback

        actual_chars = len(content)
        if not practice_mode and actual_chars >= char_min * 1.2:
            # 20% headroom accounts for LLM undercounting tendency.
            logger.info(
                f"Quality gate: APPROVE (pre-check) — "
                f"{actual_chars} chars ≥ {char_min * 1.2:.0f} (floor {char_min} × 1.2)"
            )
            return False, ""
        profile = get_language_profile(language)
        depth_rule = (
            """
    Rule 5 — PRACTICE COMPLETENESS: Section is unacceptable if it lacks any
    of these required practice elements:
    - concrete hands-on action steps the learner can follow;
    - at least one similar exercise or practice task;
    - at least one slightly advanced exercise/challenge.
    Do NOT reject merely because definitions or conceptual theory are absent.

    Rule 5.5 — NO THEORY SECTIONS: Return needs_revision=true if the content
    contains dedicated headings or blocks focused on "Lý thuyết", "Khái niệm",
    "Tổng quan", "Tổng kết", "Kết luận", "Theory", "Concepts", "Overview",
    "Summary", or "Conclusion".
    """
            if practice_mode
            else """
    Rule 5 — DEPTH: Section is superficial — missing definitions, examples, or
    core explanations. OR any ### sub-section contains fewer than 3 paragraphs.
    """
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""
    [CONTEXT]
    You are a neutral academic quality evaluator. Your only output is a JSON object.
    No extra text, no explanation, no preamble.
    [/CONTEXT]

    [TASK]
    Evaluate the content provided by the user.
    Determine whether it meets all quality standards by checking each rule in [CONSTRAINT].
    Return needs_revision=true if ANY single rule fails.
    [/TASK]

    [CONSTRAINT]
    Step 1: Count the CHARACTERS (not words) in the content.
    Return needs_revision=true if ANY of the following rules is violated:

    Rule 1 — LENGTH: Character count is less than {char_min}.
    If this rule fails, feedback MUST include: exact character count found,
    required minimum, and which specific ### sub-section is shortest and
    should be expanded first.
    Example: "Content is 2474/3000 chars. Section ### 1.1.2 has only 1 paragraph —
    expand with concrete examples and deeper analysis before other fixes."
    Do NOT reject content only because it is longer than a target or expected
    maximum. Longer-than-target content is acceptable when it is relevant,
    structured, and meets the minimum floor.

    Rule 2 — NAKED MATH: Contains LaTeX symbols or variables written outside
    $ delimiters (e.g., a_x, \\frac outside $).

    Rule 3 — WRONG MATH DELIMITERS: Contains \\[ \\] or \\( \\) instead of $$ or $.

    Rule 4 — TONE: Uses conversational or unprofessional tone in {profile.prompt_name}.
    Expected tone: {profile.tone_rule}

{depth_rule}

    Rule 6 — BLANK LINES: Any Markdown heading (`#`, `##`, `###`) is NOT preceded
    by a blank line — i.e., the line immediately before the `#` is non-empty text.
    [/CONSTRAINT]

        [FORMAT]
        Output a single JSON object. No markdown fences, no extra text.
        {{{{"needs_revision": true, "feedback": "Actionable feedback for the writer"}}}}
        or
        {{{{"needs_revision": false, "feedback": ""}}}}
        [/FORMAT]"""),
            ("user", "Content to evaluate:\n\n{content}")
        ])

        self.prompt_logger.log(
            system_prompt=(
                f"[QUALITY GATE — char_min={char_min}, char_max={char_max} — "
                "see reviewer_prompts.log for full criteria]"
            ),
            user_prompt=f"Content to evaluate (first 300 chars):\n{content[:300]}...",
            context_label="QUALITY GATE",
        )

        try:
            gate_model = _quality_gate_model(advanced_config)
            gate_llm = (
                self.llm
                if gate_model == LLM_MODEL_PREMIUM
                else ChatOpenAI(
                    model=gate_model,
                    api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
                    temperature=0.1,
                )
            )
            chain = prompt | gate_llm
            response = rate_limited_invoke(
                chain,
                {"content": content, "char_min": char_min, "char_max": char_max},
                bucket="chat",
                metadata={
                    "agent": "Reviewer",
                    "node": "reviewer",
                    "model": gate_model,
                    "operation": "quality_gate",
                },
            )

            raw = response.content.strip()  # type: ignore
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].strip()

            result = json.loads(raw)
            needs_revision = result.get("needs_revision", False)
            feedback       = result.get("feedback", "")

            logger.info(
                f"Quality gate: {'REJECT' if needs_revision else 'APPROVE'} "
                f"— {feedback[:80]}"
            )
            return needs_revision, feedback

        except json.JSONDecodeError as e:
            # Approve on parse error — a malformed JSON response from the quality
            # gate should not block the workflow; the content has already been polished.
            logger.error(f"Quality gate JSON parse error: {e}")
            return False, ""

        except Exception as e:
            # Approve on unexpected error for the same reason.
            logger.error(f"Quality gate unexpected error: {e}", exc_info=True)
            return False, ""

    @staticmethod
    def _fix_heading_levels(content: str, section_num: str, section_title: str) -> str:
        """
        Deterministic post-processing to fix heading level violations.

        The LLM occasionally outputs #### instead of ### for sub-sections,
        or strips numeric prefixes from ## and ### headings.
        This method enforces correct levels without touching heading text.

        Rules applied:
        - Any #### (or deeper) heading → downgrade to ###
        - Ensure exactly one ## {section_num} {section_title} exists at the top
        """
        lines = content.split('\n')
        fixed_lines = []
        section_header_found = False
        expected_section = f"## {section_num} {section_title}"

        for line in lines:
            # Downgrade #### (and deeper) to ### — sub-sections are always level 3.
            if re.match(r'^#{4,} ', line):
                line = re.sub(r'^#{4,} ', '### ', line)

            # Detect if the correct ## section header is present.
            if line.strip().startswith('## ') and section_num in line:
                section_header_found = True

            fixed_lines.append(line)

        result = '\n'.join(fixed_lines)
        result = _normalize_unnumbered_h3_to_bold(result)

        # If ## section header is missing or stripped, inject it after a level-1 chapter line.
        if not section_header_found:
            # Find insertion point: after level-1 chapter line if present, else at start.
            chap_match = re.search(r'^# .+$', result, flags=re.MULTILINE)
            if chap_match:
                insert_pos = chap_match.end()
                result = (
                    result[:insert_pos]
                    + f"\n\n{expected_section}\n"
                    + result[insert_pos:]
                )
            else:
                # No chapter header — prepend section header at top.
                result = f"{expected_section}\n\n" + result.lstrip('\n')

        return result

    def _format_pass(
        self,
        draft: str,
        section_num: str,
        section_title: str,
        chapter_cmd: str,
        language: str = "vi",
    ) -> str:
        """
        Pass A: Mechanical format fixes — LaTeX, headings, blank lines.

        This pass is ONLY permitted to make substitution-level changes:
          - Math delimiter replacements (\\[ → $$, \\( → $)
          - Unicode subscript/superscript → math notation (H₂O → H$_2$O)
          - Heading level corrections (#### → ###)
          - Blank lines before/after headings
          - Code block language identifiers

        It is FORBIDDEN from rephrasing, summarizing, expanding, or reordering prose.
        Every line that does not violate a format rule must be copied verbatim.

        Temperature: 0.0 — deterministic substitution, zero creativity.

        Args:
            draft:         Raw content from the Writer node.
            section_num:   Dot-notation section number (e.g. "1.1").
            section_title: Section title (e.g. "Giới thiệu về Python").
            chapter_cmd:   Chapter header directive (passed through from review_content).

        Returns:
            Format-fixed Markdown. Returns original draft unchanged on error.
        """
        profile = get_language_profile(language)
        language_math_rule = (
            "Vietnamese inside math blocks: use \\\\text{{...}}:\n"
            "  $v_{{cuoi}}$  →  $v_{{\\\\text{{cuối}}}}$"
            if profile.code == "vi"
            else "Language-specific words inside math blocks: use \\\\text{{...}} only when ordinary words appear inside math."
        )
        format_style_rule = (
            "English output: replace em dash/en dash characters (—, –) with "
            "commas, parentheses, semicolons, or ASCII hyphen-minus (-)."
            if profile.code == "en"
            else "No language-specific dash replacement required."
        )
        format_system = """
[CONTEXT]
You are a format compliance engine, not an editor.
Your output is the input with FORMAT VIOLATIONS fixed — nothing else.
[/CONTEXT]

[TASK]
Apply ONLY the format rules below to the draft. Every line that violates no rule
MUST be copied to the output verbatim — word-for-word, character-for-character.
[/TASK]

[CONSTRAINT]
These are the ONLY permitted changes. Make no others.

--- MATH FIXES ---

Rule 1 — Block math delimiters: replace ALL non-standard forms with $$ $$:
  \\[ F = ma \\]                           → $$ F = ma $$
  \\begin{{equation}} F = ma \\end{{equation}} → $$ F = ma $$

Rule 2 — Inline math delimiters: replace \\( \\) with $ $:
  \\( x = 5 \\)  →  $x = 5$
  No space after opening $ or before closing $.

Rule 3 — Naked math: wrap standalone variables/subscripts in $:
  a_max = 5  →  $a_{{max}} = 5$
  Only fix CLEAR mathematical notation — do NOT wrap ordinary text in $.

Rule 4 — {language_math_rule}

Rule 5 — Unicode subscripts/superscripts → math notation:
  H₂O → H$_2$O  |  CO₂ → CO$_2$  |  Na⁺ → Na$^+$  |  Cl⁻ → Cl$^-$
  subscript digits (₀₁₂₃₄₅₆₇₈₉) → $_n$
  superscripts (⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹) → $^n$

Rule 5.5 — Formula explanations:
  Use one bullet per variable after "Trong đó:" / "Where:".
  Fix: Trong đó: - $E$ là ..., - $R$ là ...
    → Trong đó:
      - $E$: ...
      - $R$: ...
  Mathematical symbols must use $...$, not backticks.

--- STRUCTURE FIXES ---

Rule 6 — Chapter header: {chap_cmd}
  DO NOT add, remove, or alter any # (level-1) heading under any circumstance.

Rule 7 — Heading format:
  Section header must be exactly: ## {section_num} {section_title}
  Sub-sections must follow: ### {section_num}.N Title
  Convert any #### (or deeper) heading to ###.
  NEVER strip numeric prefixes from headings.
  Fix: ## {section_num}: Title → ## {section_num} Title  (remove colon only)

Rule 8 — Blank lines: every #, ##, ### heading MUST have a blank line immediately
  BEFORE it AND immediately AFTER it.
  Fix missing blank lines — do NOT add blank lines elsewhere.

Rule 9 — Horizontal rules:
  Remove standalone separator lines such as --- or ----.
  Do NOT add horizontal rules anywhere; headings and blank lines are sufficient.

Rule 10 — Code blocks: must have a language identifier.
  ``` →  ```python  (or ```bash, ```sql, ```json depending on content)

Rule 11 — Inline programming code:
  Programming identifiers, keywords, function names, method names, operators,
  and code expressions MUST use Markdown backticks, not $...$ math.
  Fix: $student\\_scores["Alice"]$ → `student_scores["Alice"]`
  Fix: $del student\\_scores["Bob"]$ → `del student_scores["Bob"]`
  Fix: `keys()$ → `keys()`
  Do NOT wrap Python keywords, variables, string literals, list/dict indexing,
  or methods in math delimiters.

Rule 12 — Language-specific punctuation:
  {format_style_rule}

--- ABSOLUTE PROHIBITION ---

You MUST NOT:
  - Rephrase, reword, or paraphrase any sentence or paragraph
  - Summarize or shorten any content
  - Add new explanatory text, analysis, or commentary
  - Reorder paragraphs or sections
  - Remove any content except exact duplicate lines

If a line has no format violation → copy it CHARACTER FOR CHARACTER.
[/CONSTRAINT]

[FORMAT]
Return raw Markdown only.
No fences, no preamble, no explanation.
[/FORMAT]
"""

        try:
            try:
                logged_system = format_system.format(
                    section_num=section_num,
                    section_title=section_title,
                    chap_cmd=chapter_cmd,
                    language_math_rule=language_math_rule,
                    format_style_rule=format_style_rule,
                )
            except Exception:
                logged_system = format_system

            self.prompt_logger.log(
                system_prompt=logged_system,
                user_prompt=f"Apply format rules to draft (first 200 chars):\n{draft[:200]}...",
                context_label=f"{section_num} {section_title} [FORMAT-PASS-A]",
            )

            llm_format = ChatOpenAI(
                model=LLM_MODEL_PREMIUM,
                api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
                temperature=0.0,
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", format_system),
                ("user", "Apply format rules to this draft:\n\n{draft}"),
            ])
            chain = prompt | llm_format
            response = rate_limited_invoke(chain, {
                "section_num":   section_num,
                "section_title": section_title,
                "chap_cmd":      chapter_cmd,
                "language_math_rule": language_math_rule,
                "format_style_rule": format_style_rule,
                "draft":         draft,
            }, bucket="chat", metadata={
                "agent": "Reviewer",
                "node": "reviewer",
                "model": LLM_MODEL_PREMIUM,
                "operation": "format_pass",
            })
            return str(response.content)

        except Exception as e:
            logger.warning(f"Pass A (_format_pass) error — returning original draft: {e}")
            return draft

    def _content_pass(
        self,
        draft: str,
        course_topic: str,
        chapter_num: str,
        chapter_title: str,
        section_num: str,
        section_title: str,
        section_description: str,
        language: str = "vi",
        enable_images: bool = True,
        textbook_mode: str = "standard",
        target_pages: int | None = None,
        page_budget_mode: str = "standard",
    ) -> str:
        """
        Pass B: Content quality — academic tone and depth.

        Receives the format-clean output of _format_pass(). This pass focuses
        exclusively on content quality. LaTeX and structural rules are intentionally
        absent — Pass A already handled them, and their presence in this pass caused
        the LLM to trim content to comply with format rules instead of expanding it.

        Permitted changes:
          - Remove conversational fillers (Chúng ta hãy..., etc.)
          - Enforce academic Vietnamese tone
          - Expand shallow ### blocks (fewer than 3 paragraphs) using domain knowledge
        CRITICAL: content LENGTH must not decrease. The pre-submit self-check
        enforces this explicitly — the LLM must count characters before submitting.

        Temperature: 0.2 — needs light creativity for expanding shallow subsections.

        Args:
            draft:               Format-clean output from _format_pass().
            course_topic:        Main textbook topic.
            chapter_num:         1-indexed chapter number as string.
            chapter_title:       Current chapter title.
            section_num:         Dot-notation section number.
            section_title:       Current section title.
            section_description: What this section covers (from curriculum).

        Returns:
            Content-polished Markdown. Returns draft unchanged on error.
        """
        profile = get_language_profile(language)
        practice_mode = _is_practice_mode(textbook_mode)
        practice_criterion = (
            """
--- PRACTICE COURSE MODE ---
Preserve the section as hands-on practice material. Do not add theory-first
explanations, concept catalogues, summaries, or conclusion blocks. If a hands-on
section lacks action steps, a similar exercise, or a slightly advanced exercise,
add those elements while preserving the existing Markdown structure.
"""
            if practice_mode
            else ""
        )
        content_style_rule = (
            "Do NOT use em dash or en dash characters (—, –) in English output. "
            "Use commas, parentheses, semicolons, or ASCII hyphen-minus (-) instead."
            if profile.code == "en"
            else (
                "Do NOT leave the em dash character (—) in Vietnamese output. "
                "Choose the replacement by context: use ASCII hyphen-minus (-) "
                "inside acronym/term explanations such as (ALU - Arithmetic and Logic Unit); "
                "rewrite prose explanations with natural Vietnamese connectors such as "
                "\"đây là\", \"là\", \"điều này cho thấy\", a comma, or a separate sentence."
            )
        )
        if page_budget_mode == "compact":
            depth_rule = """
--- COMPACT DEPTH ---
This section has a small page budget. Do not expand merely because it has no
### blocks. Approve a direct ## section when the core concept is clear.
If there is exactly one unnumbered or weak ### label, convert it to a bold
lead-in. Use concise bullets for definitions, features, and components.
Remove routine reflection, "students can..." endings, and unnecessary real-world
application paragraphs unless they add clear value.
"""
            length_rule = (
                "Rule 4 — LENGTH: Keep the content within the compact page budget. "
                "Do not expand the draft unless it is missing core content."
            )
            count_check = (
                "Compact check: core idea covered, no lone ### remains, redundant "
                "reflection/application prose removed, and no padding added."
            )
        else:
            depth_rule = """
--- DEPTH ---
If any ### sub-section block contains fewer than 3 substantial paragraphs:
  Option A: MERGE it with the adjacent ### block into one richer section.
  Option B: EXPAND it to at least 3 paragraphs (4–5 sentences each) using
            domain knowledge consistent with the section description.
Prefer Option B when the block covers a distinct sub-topic worth preserving.
"""
            length_rule = (
                "Rule 4 — LENGTH: Do not shorten the content; the output must remain at least\n"
                "95% of the draft length."
            )
            count_check = """
Step 1: Mentally estimate the character count of the draft you received.
Step 2: Write your edited content.
Step 3: Estimate the character count of your output.

If your output is less than 95% of the draft's character count:
  → You have over-edited. Do NOT submit yet.
  → Identify the shortest ### block in your output.
  → Add 2–3 substantial paragraphs of domain-relevant analysis to that block.
  → Re-estimate. Repeat until output ≥ draft length.

This check is MANDATORY. Submitting shorter content than received is a failure.
"""
        content_system = """
[CONTEXT]
You are a neutral academic writing editor for an educational platform covering
all learning domains — university academics, technical skills, practical crafts,
and lifestyle topics. Adapt tone to the subject domain.
Edit the draft below. Your sole output is the final polished Markdown —
no preamble, no explanations, no meta-commentary.
[/CONTEXT]

[TASK]
Apply content quality improvements to the draft for:

<book_topic>{course_topic}</book_topic>
<chapter num="{chapter_num}">{chapter_title}</chapter>
<section num="{section_num}">{section_title}</section>
<description>{section_description}</description>

The draft has already been format-corrected (LaTeX, headings, blank lines).
Do NOT modify any math notation or heading structure — those are already correct.
Focus ONLY on the content quality improvements below.
[/TASK]

[CRITERION]
--- TONE ---
Remove conversational fillers. Examples to eliminate:
  {filler_examples}
Keep: direct, {tone_rule}
Adapt register to domain: precise for sciences/engineering, narrative for history/arts.
Technical terms in English: keep as-is (DataFrame, API, CPU, LaTeX).
Punctuation: {content_style_rule}
Inline programming code: preserve Markdown backticks for variables, methods,
keywords, and code expressions. Never convert programming code into $...$ math.

{depth_rule}

Bold audit: remove excessive bold. Keep bold ONLY for the primary concept
defined for the first time in the section. Remove bold from adjectives, general
nouns, phrases over 4 words, and any term already in a heading.

{practice_criterion}
[/CRITERION]

[CONSTRAINT]
Rule 1 — PRESERVE STRUCTURE: Do not change ## or ### numbering, chapter headers,
math notation, code fences, or paragraph order unless needed to fix
content quality.
Rule 2 — NO WRAPPERS: Do not add preambles, explanations, meta-commentary, or
outer markdown fences.
Rule 3 — NO SEPARATORS: Do not output standalone separator lines such as --- or ----.
{length_rule}
[/CONSTRAINT]

[FORMAT]
MANDATORY CHARACTER COUNT CHECK — execute before submitting:

{count_check}

Output rules:
  - Return ONLY the final polished Markdown
  - NO conversational preamble or meta-commentary
  - NO outer markdown fences wrapping the entire output
  - NO standalone separator lines such as --- or ----
[/FORMAT]
"""

        try:
            try:
                logged_system = content_system.format(
                    course_topic=course_topic,
                    chapter_num=chapter_num,
                    chapter_title=chapter_title,
                    section_num=section_num,
                    section_title=section_title,
                    section_description=section_description,
                    filler_examples=profile.filler_examples,
                    tone_rule=profile.tone_rule,
                    content_style_rule=content_style_rule,
                    practice_criterion=practice_criterion,
                    depth_rule=depth_rule,
                    length_rule=length_rule,
                    count_check=count_check,
                )
            except Exception:
                logged_system = content_system

            self.prompt_logger.log(
                system_prompt=logged_system,
                user_prompt=f"Draft to improve (first 200 chars):\n{draft[:200]}...",
                context_label=f"{section_num} {section_title} [CONTENT-PASS-B]",
            )

            llm_content = ChatOpenAI(
                model=LLM_MODEL_PREMIUM,
                api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
                temperature=0.2,
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", content_system),
                ("user", "Here is the draft to improve:\n\n{draft}"),
            ])
            chain = prompt | llm_content
            response = rate_limited_invoke(chain, {
                "course_topic":        course_topic,
                "chapter_num":         chapter_num,
                "chapter_title":       chapter_title,
                "section_num":         section_num,
                "section_title":       section_title,
                "section_description": section_description,
                "filler_examples":     profile.filler_examples,
                "tone_rule":           profile.tone_rule,
                "content_style_rule":  content_style_rule,
                "practice_criterion":  practice_criterion,
                "depth_rule":           depth_rule,
                "length_rule":          length_rule,
                "count_check":          count_check,
                "target_pages":         target_pages,
                "page_budget_mode":     page_budget_mode,
                "draft":               draft,
            }, bucket="chat", metadata={
                "agent": "Reviewer",
                "node": "reviewer",
                "model": LLM_MODEL_PREMIUM,
                "operation": "content_pass",
            })
            result = str(response.content)
            return result if enable_images else strip_image_markers_when_disabled(result)

        except Exception as e:
            logger.error(
                f"Pass B (_content_pass) error — returning format-fixed draft: {e}",
                exc_info=True,
            )
            return draft

    @staticmethod
    def _needs_em_dash_cleanup(content: str, language: str = "vi") -> bool:
        """Return True when a Vietnamese section still needs contextual dash cleanup."""
        return get_language_profile(language).code == "vi" and "—" in content

    def _em_dash_cleanup_pass(
        self,
        draft: str,
        section_num: str,
        section_title: str,
        language: str = "vi",
    ) -> str:
        """
        Contextual cleanup pass for Vietnamese em dashes.

        This intentionally uses the LLM instead of a regex because an em dash may
        need either a plain hyphen inside acronym explanations or a Vietnamese
        connective phrase in ordinary prose.
        """
        if not self._needs_em_dash_cleanup(draft, language):
            return draft

        cleanup_system = """
[CONTEXT]
You are a Vietnamese academic copy editor. Your only task is to remove the
em dash character (—) from the draft while preserving meaning and structure.
[/CONTEXT]

[TASK]
Edit the draft so the final output contains ZERO em dash characters (—).
Do not rewrite anything unrelated to em dash cleanup.
[/TASK]

[CONSTRAINT]
- Preserve all Markdown headings, heading numbers, math notation, code blocks,
  lists, and paragraph order.
- If the em dash appears inside an acronym or term explanation, replace it with
  ASCII hyphen-minus (-). Example: (ALU — Arithmetic and Logic Unit) becomes
  (ALU - Arithmetic and Logic Unit).
- If the em dash introduces an explanation or assertion in prose, rewrite the
  sentence naturally with Vietnamese connectors such as "đây là", "là",
  "điều này cho thấy", a comma, or a separate sentence.
- Do NOT use en dash (–) as a substitute.
- The final output must not contain the character —.
[/CONSTRAINT]

[FORMAT]
Return raw Markdown only. No preamble, no explanation, no fences.
[/FORMAT]
"""

        try:
            self.prompt_logger.log(
                system_prompt=cleanup_system,
                user_prompt=f"Clean em dashes in draft (first 200 chars):\n{draft[:200]}...",
                context_label=f"{section_num} {section_title} [EM-DASH-CLEANUP]",
            )
            llm_cleanup = ChatOpenAI(
                model=LLM_MODEL_PREMIUM,
                api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
                temperature=0.0,
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", cleanup_system),
                ("user", "Clean em dashes in this draft:\n\n{draft}"),
            ])
            response = rate_limited_invoke(
                prompt | llm_cleanup,
                {"draft": draft},
                bucket="chat",
                metadata={
                    "agent": "Reviewer",
                    "node": "reviewer",
                    "model": LLM_MODEL_PREMIUM,
                    "operation": "em_dash_cleanup",
                },
            )
            cleaned = str(response.content)
            if "—" in cleaned:
                logger.warning(
                    "Em dash cleanup pass left em dash characters in %s %s",
                    section_num,
                    section_title,
                )
            return cleaned
        except Exception as e:
            logger.warning(
                "Em dash cleanup pass failed for %s %s — returning prior draft: %s",
                section_num,
                section_title,
                e,
            )
            return draft

    def review_content(
        self,
        course_topic: str,
        chapter_num: str,
        chapter_title: str,
        section_num: str,
        section_title: str,
        section_description: str,
        draft_content: str,
        chapter_cmd: str,
        language: str = "vi",
        enable_images: bool = True,
        advanced_config: dict | None = None,
        char_min: int = 300,
        review_feedback: str = "",
        textbook_mode: str = "standard",
        target_pages: int | None = None,
        page_budget_mode: str = "standard",
    ) -> str:
        """
        Full editorial pass: sanitize, refine tone, fix structure, audit visuals.

        Two-pass pipeline:
            Pass A — _format_pass(): mechanical substitutions only
                     (LaTeX, headings, blank lines, code blocks).
                     Temperature 0.0. Content is never shortened.
            Pass B — _content_pass(): content quality only
                     (tone, depth, visuals).
                     Temperature 0.2. Explicit character count self-check.

        Separation rationale: combining mechanical and editorial tasks in one
        call caused the LLM to trade-off length against format compliance,
        shrinking content by 40-50% per pass. Separation eliminates the conflict.

        Args:
            course_topic:        Main textbook topic (e.g. "Học máy").
            chapter_num:         1-indexed chapter number as string.
            chapter_title:       Title of the current chapter.
            section_num:         Dot-notation section number (e.g. "2.3").
            section_title:       Title of the current section.
            section_description: What this section should cover (from curriculum).
            draft_content:       Raw content from the Writer node.
            chapter_cmd:         Directive for chapter header handling.
                                Empty string → Reviewer ignores # heading.
                                "PRESERVE: ..." → first subsection of a chapter.

        Returns:
            Polished Markdown string.
            Returns the original draft unchanged on error (preserves workflow).
        """
        logger.info(f"Polishing: {section_num} {section_title}")

        if not draft_content or len(draft_content) < 50:
            logger.warning("Draft too short/empty — skipping review")
            return draft_content

        # Strip control characters that break JSON serialization.
        # Keep only printable chars + standard whitespace (\n \t \r).
        # These accumulate after multiple Writer→Reviewer revision cycles
        # and cause OpenAI API to return 400 invalid_request_error.
        safe_draft = ''.join(
            c for c in draft_content
            if c >= ' ' or c in '\n\t\r'
        )

        balanced = use_balanced_cost(advanced_config)
        safe_draft = _normalize_unnumbered_h3_to_bold(safe_draft)

        needs_format_pass = (
            not balanced
            or _has_format_issues(safe_draft, section_num, section_title, language)
        )

        # --- Pass A: Mechanical format fixes ---
        if needs_format_pass:
            logger.info(f"  Pass A (format): {section_num} {section_title}")
            format_fixed = self._format_pass(
                draft=safe_draft,
                section_num=section_num,
                section_title=section_title,
                chapter_cmd=chapter_cmd,
                language=language,
            )
        else:
            logger.info("  Pass A skipped: deterministic format checks passed")
            format_fixed = safe_draft
        pass_a_len = len(format_fixed)
        logger.info(f"  Pass A complete: {len(safe_draft)} → {pass_a_len} chars")

        needs_content_pass = (
            not balanced
            or (
                review_feedback
                and _balanced_rejection_kind(review_feedback) != "formatting_error"
            )
            or _has_content_issues(
                format_fixed,
                char_min,
                review_feedback,
                page_budget_mode=page_budget_mode,
            )
        )

        # --- Pass B: Content quality ---
        if needs_content_pass:
            logger.info(f"  Pass B (content): {section_num} {section_title}")
            polished = self._content_pass(
                draft=format_fixed,
                course_topic=course_topic,
                chapter_num=chapter_num,
                chapter_title=chapter_title,
                section_num=section_num,
                section_title=section_title,
                section_description=section_description,
                language=language,
                enable_images=enable_images,
                textbook_mode=textbook_mode,
                target_pages=target_pages,
                page_budget_mode=page_budget_mode,
            )
        else:
            logger.info("  Pass B skipped: deterministic content checks passed")
            polished = format_fixed
        pass_b_len = len(polished)
        logger.info(
            f"  Pass B complete: {pass_a_len} → {pass_b_len} chars "
            f"({'▼' if pass_b_len < pass_a_len else '▲'}"
            f"{abs(pass_b_len - pass_a_len)} chars)"
        )

        # Apply deterministic heading level fix (existing logic — keep unchanged).
        polished = self._fix_heading_levels(polished, section_num, section_title)
        if not enable_images:
            polished = strip_image_markers_when_disabled(polished)
        if self._needs_em_dash_cleanup(polished, language):
            logger.info("  Em dash cleanup required: %s %s", section_num, section_title)
            cleaned = self._em_dash_cleanup_pass(
                draft=polished,
                section_num=section_num,
                section_title=section_title,
                language=language,
            )
            polished = self._fix_heading_levels(cleaned, section_num, section_title)
            if not enable_images:
                polished = strip_image_markers_when_disabled(polished)

        logger.info("✓ Review complete")
        return polished

    def classify_rejection_type(self, feedback: str) -> str:
        """
        Classify the rejection reason into a routing category.

        Used by route_after_review() in orchestrator.py to select the correct
        remediation path in the True Dynamic Routing implementation (Target 2).

        Classification rules (keyword-based, no extra LLM call):
            'missing_context'  — feedback mentions length failure, missing definitions,
                                 superficial content, or lack of examples/depth.
                                 These indicate the Writer lacked sufficient source material.
            'formatting_error' — feedback mentions heading format, blank lines,
                                 LaTeX delimiters, math notation, or tone issues.
                                 These indicate structural/format problems, not content gaps.

        Defaults to 'formatting_error' when signals are ambiguous — it is safer
        to route to ContentWriter directly than to trigger a full re-retrieval cycle.

        Args:
            feedback: Rejection feedback string from should_revise().

        Returns:
            'missing_context' or 'formatting_error'
        """
        if not feedback:
            return "formatting_error"

        feedback_lower = feedback.lower()

        # Signals indicating the Writer lacked sufficient source material
        missing_context_signals = (
        "thiếu ví dụ", "missing example",
        "thiếu định nghĩa", "missing definition", "superficial",
        "không đủ", "insufficient",
        "thiếu nội dung",
        "no examples", "lacks depth",
            )

        formatting_error_signals = (
            # Structural/format issues (original)
            "heading", "blank line", "dòng trống", "latex", "math",
            "delimiter", "\\[", "\\(", "naked", "unicode",
            "subscript", "superscript", "tone", "conversational",
            "chương", "section header", "### ", "## ",
            # Length/depth issues (moved from missing_context)
            # Rationale: short content = writer needs to write MORE with existing context,
            # not fetch new context. ContextEvaluator already gates for truly sparse context.
            "quá ngắn", "too short",
            "chars", "ký tự",
            "paragraph",
            "expand", "mở rộng", "thêm",
            "superficial", "nông cạn", "thiếu chiều sâu",
            )

        missing_score    = sum(1 for s in missing_context_signals   if s in feedback_lower)
        formatting_score = sum(1 for s in formatting_error_signals  if s in feedback_lower)

        rejection = "missing_context" if missing_score > formatting_score else "formatting_error"
        logger.info(
            f"Rejection classified: '{rejection}' "
            f"(missing_signals={missing_score}, format_signals={formatting_score})"
        )
        return rejection




def review_section(state: AgentState) -> dict:
    """
    Reviewer node: polish the current subsection then run the quality gate.

    Two-step pipeline:
        Step 1 — review_content():
            Full editorial pass (LaTeX fix, tone, structure, visuals).
            Always runs regardless of revision count.

        Step 2 — should_revise():
            Quality gate using char_min from the subsection's section_type.
            Only runs when revision_number < MAX_REVISIONS.
            When MAX_REVISIONS is reached, content is force-approved so the
            workflow is never permanently blocked by a single section.

    Workflow integration:
        Input:  state["current_content"]  — draft from Writer node
        Output (approved):
                state["current_content"]  — polished Markdown
                state["review_feedback"]  = ""  (signals approval to router)
                state["revision_number"]  = 0   (reset for next subsection)
        Output (rejected):
                state["current_content"]  — polished Markdown (partial improvements kept)
                state["review_feedback"]  = "<feedback>"  (routes back to Writer)
                state["revision_number"]  += 1

    Notes:
        - sec_title is cleaned via clean_section_title() (shared helper from state.py)
          to strip structured prefixes like "Mục 1.2: Title" → "Title".
        - chapter_header ownership check uses sub_idx == 0 (not endswith(".1"))
          to avoid false matches on section numbers like "1.11" or "2.21".

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict.
    """
    logger.info("=" * 60)
    logger.info("NODE: Reviewer - Polishing content")
    logger.info("=" * 60)

    curriculum      = state["curriculum"]
    chap_idx        = state["current_chapter_index"]
    sub_idx         = state["current_subsection_index"]
    revision_number = state.get("revision_number", 0)
    language = state.get("language", "vi")
    textbook_mode = state.get("textbook_mode", "standard")
    profile = get_language_profile(language)
    advanced_config = state.get("advanced_config", {}) or {}
    balanced = use_balanced_cost(advanced_config)
    enable_images = bool(state.get("enable_images", True))

    try:
        # Unified curriculum access — handles Pydantic and dict formats.
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

        # Use isinstance for explicit type discrimination (consistent with Writer).
        chap_title = (
            chapter.title if isinstance(chapter, Chapter)
            else chapter.get('title', 'Unknown Chapter')
        )
        sec_title = (
            subsection.title if isinstance(subsection, SubSection)
            else subsection.get('title', 'Unknown Section')
        )
        sec_desc = (
            subsection.description if isinstance(subsection, SubSection)
            else subsection.get('description', '')
        )
        sec_type = (
            subsection.section_type if isinstance(subsection, SubSection)
            else subsection.get('section_type', 'medium')
        )

        # Use shared helper (BUG-10 fix) — strips "Mục 1.2: " prefixes safely
        # without falsely stripping mid-sentence colons like "Bài toán tối ưu:".
        sec_title = clean_section_title(sec_title)

        display_chap_num = str(chap_idx + 1)
        display_sec_num  = f"{display_chap_num}.{sub_idx + 1}"

        # ------------------------------------------------------------------
        # Chapter header directive for the Reviewer.
        #
        # The Writer owns level-1 chapter headers exclusively. The Reviewer must never
        # add one. For the first subsection (sub_idx == 0), we ask the Reviewer
        # to verify the header exists — but NOT to add it if missing.
        #
        # sub_idx == 0 is used instead of display_sec_num.endswith(".1") to
        # avoid false matches on section numbers like "1.11" or "2.21".
        # ------------------------------------------------------------------
        draft = state.get("current_content", "")
        correct_heading  = f"# {profile.chapter_label} {display_chap_num}: {chap_title.upper()}"
        chap_cmd_text    = ""
        draft_has_header = draft.lstrip().startswith(f"# {profile.chapter_label}")

        if sub_idx == 0 and state.get("chapter_header_written", False):
            if draft_has_header:
                # First write: draft has header — instruct reviewer to preserve it verbatim.
                chap_cmd_text = (
                    f"PRESERVE: The draft begins with '{correct_heading}'. "
                    f"This line MUST appear as the very first line of your output — "
                    f"copy it verbatim. Do NOT remove, modify, or rewrite it under any circumstance."
                )
            else:
                # Revision: draft has no chapter header (Writer does not re-emit it).
                # Do NOT instruct reviewer to add or preserve any level-1 heading —
                # the deterministic guard below will re-inject the correct heading.
                chap_cmd_text = (
                    "DO NOT add any # (level-1) heading. "
                    "The draft does not contain a chapter header — do not add one."
                )

        from app.schemas.curriculum import get_char_target
        char_min, char_max = get_char_target(
            sec_type,
            state.get("content_level", "Trung Bình"),
            advanced_config,
            language=language,
        )
        page_target_min = (
            subsection.target_chars_min if isinstance(subsection, SubSection)
            else subsection.get("target_chars_min")
        )
        page_target_max = (
            subsection.target_chars_max if isinstance(subsection, SubSection)
            else subsection.get("target_chars_max")
        )
        section_target_pages = (
            subsection.target_pages if isinstance(subsection, SubSection)
            else subsection.get("target_pages")
        )
        section_page_budget_mode = (
            subsection.page_budget_mode if isinstance(subsection, SubSection)
            else subsection.get("page_budget_mode")
        )
        formula_density = (
            subsection.formula_density if isinstance(subsection, SubSection)
            else subsection.get("formula_density")
        )
        expansion_strategy = (
            subsection.expansion_strategy if isinstance(subsection, SubSection)
            else subsection.get("expansion_strategy")
        )
        if page_target_min and page_target_max:
            try:
                char_min = max(250, int(page_target_min))
                char_max = max(char_min + 250, int(page_target_max))
                logger.info(
                    "Reviewer using page-budget char target for %s: %s-%s",
                    sec_title,
                    char_min,
                    char_max,
                )
            except (TypeError, ValueError):
                logger.warning("Invalid reviewer page-budget char target; falling back")
        min_chars_floor = state.get("min_chars_per_section", 0)
        char_min = max(char_min, min_chars_floor)
        char_max = max(char_max, char_min + 250)
        if not section_page_budget_mode:
            section_page_budget_mode = _page_budget_mode(section_target_pages, char_max)
        section_page_budget_mode = str(section_page_budget_mode or "standard")

        source_audit = state.get("rag_source_audit", {}) or {}
        source_context_quality = source_audit.get("context_quality")
        if source_context_quality == "insufficient":
            feedback = (
                "RAG source audit is insufficient for this section; "
                "retrieve more relevant external sources before approving."
            )
            logger.warning(feedback)
            return {
                "current_content":  draft,
                "review_feedback":  feedback,
                "revision_number":  revision_number + 1,
                "rejection_type":   "missing_context",
                "messages": [
                    f"↺ Revision {revision_number + 1}/{MAX_REVISIONS} "
                    "[missing_context]: source audit insufficient"
                ],
            }
        if source_context_quality == "best_effort":
            logger.warning(
                "RAG source audit is best_effort for this section; reviewer will "
                "continue and preserve source-faithful wording."
            )

        # ------------------------------------------------------------------
        # Step 1 — Polish content.
        # In balanced_cost this can skip expensive passes when detectors pass.
        # ------------------------------------------------------------------
        agent    = ReviewerAgent()
        polished = agent.review_content(
            course_topic=state.get("request", "General Topic"),
            chapter_num=display_chap_num,
            chapter_title=chap_title,
            section_num=display_sec_num,
            section_title=sec_title,
            section_description=sec_desc,
            draft_content=draft,
            chapter_cmd=chap_cmd_text,
            language=language,
            enable_images=enable_images,
            advanced_config=advanced_config,
            char_min=char_min,
            review_feedback=state.get("review_feedback", ""),
            textbook_mode=textbook_mode,
            target_pages=section_target_pages,
            page_budget_mode=section_page_budget_mode,
        )

        # ------------------------------------------------------------------
        # Guard: restore chapter heading if Reviewer LLM stripped it.
        #
        # Reviewer rewrites content from scratch, which causes it to drop the
        # level-1 chapter heading even when instructed to preserve it. This
        # deterministic check re-injects the heading from known values rather
        # than relying on LLM compliance.
        #
        # Condition: only sub_idx==0 sections ever carry a # CHƯƠNG heading,
        # and only when chapter_header_written=True (meaning Writer did emit it).
        # ------------------------------------------------------------------
        if sub_idx == 0 and state.get("chapter_header_written", False):
            expected_heading = f"# {profile.chapter_label} {display_chap_num}: {chap_title.upper()}"
            existing = re.search(
                rf'^# {re.escape(profile.chapter_label)}.*$',
                polished,
                flags=re.MULTILINE,
            )

            if existing:
                found_text = existing.group(0).strip()
                if found_text != expected_heading:
                    # Malformed heading found (e.g. '# CHAPTER 1: ...' with literal
                    # ellipsis placeholder, or wrong casing). Replace deterministically.
                    polished = (
                        polished[:existing.start()]
                        + expected_heading
                        + polished[existing.end():]
                    )
                    logger.warning(
                        f"⚠️  Malformed chapter heading replaced: "
                        f"'{found_text}' → '{expected_heading}'"
                    )
            else:
                # Heading entirely absent — inject at top.
                polished = expected_heading + "\n\n" + polished.lstrip('\n')
                logger.warning(
                    f"⚠️  Chapter heading absent — injected: '{expected_heading}'"
                )
        if not enable_images:
            polished = strip_image_markers_when_disabled(polished)

        structured_feedback = _structured_expansion_feedback(
            polished,
            target_pages=section_target_pages,
            formula_density=formula_density,
            expansion_strategy=expansion_strategy,
            language=language,
        )
        if structured_feedback and revision_number < (1 if balanced else MAX_REVISIONS):
            logger.info("Structured expansion requested: %s", structured_feedback[:120])
            return {
                "current_content": polished,
                "review_feedback": structured_feedback,
                "revision_number": revision_number + 1,
                "rejection_type": "length_depth",
                "messages": [
                    f"↺ Revision {revision_number + 1}/"
                    f"{1 if balanced else MAX_REVISIONS} [structured_expansion]: "
                    f"{structured_feedback[:80]}"
                ],
            }

        # ------------------------------------------------------------------
        # Step 2 — Quality gate.
        #
        # Pass char_min from section_type so the gate enforces the same floor
        # the Writer targeted, rather than a fixed word-count threshold.
        # Skip the gate entirely once MAX_REVISIONS is reached.
        # ------------------------------------------------------------------
        effective_max_revisions = 1 if balanced else MAX_REVISIONS
        if (
            balanced
            and not _is_practice_mode(textbook_mode)
            and deterministic_quality_gate_passes(
            polished,
            char_min=char_min,
            char_max=char_max,
            section_num=display_sec_num,
            section_title=sec_title,
            section_type=sec_type,
            language=language,
            page_budget_mode=section_page_budget_mode,
            )
        ):
            logger.info("Balanced deterministic gate: APPROVE — skipped LLM quality gate")
            return {
                "current_content":  polished,
                "review_feedback":  "",
                "revision_number":  0,
                "rejection_type":   None,
                "messages": [
                    f"✓ Approved: {display_sec_num} {sec_title} "
                    "(deterministic balanced gate)"
                ],
            }

        if revision_number < effective_max_revisions:
            needs_revision, feedback = agent.should_revise(
                polished,
                char_min=char_min,
                char_max=char_max,
                language=language,
                advanced_config=advanced_config,
                textbook_mode=textbook_mode,
            )

            if needs_revision:
                logger.info(
                    f"Revision requested "
                    f"(attempt {revision_number + 1}/{effective_max_revisions}): {feedback[:80]}"
                )
                if balanced:
                    rejection_kind = _balanced_rejection_kind(feedback)
                    if rejection_kind == "missing_context":
                        return {
                            "current_content":  polished,
                            "review_feedback":  feedback,
                            "revision_number":  revision_number + 1,
                            "rejection_type":   "missing_context",
                            "messages": [
                                f"↺ Revision {revision_number + 1}/{effective_max_revisions} "
                                f"[missing_context]: {feedback[:80]}"
                            ],
                        }

                    if rejection_kind == "formatting_error":
                        repaired = agent._format_pass(
                            draft=polished,
                            section_num=display_sec_num,
                            section_title=sec_title,
                            chapter_cmd=chap_cmd_text,
                            language=language,
                        )
                        repaired = agent._fix_heading_levels(
                            repaired,
                            display_sec_num,
                            sec_title,
                        )
                        if not enable_images:
                            repaired = strip_image_markers_when_disabled(repaired)
                        repaired = _normalize_unnumbered_h3_to_bold(repaired)
                        logger.info("Balanced reviewer self-repair: formatting fixed without Writer rewrite")
                        return {
                            "current_content":  repaired,
                            "review_feedback":  "",
                            "revision_number":  0,
                            "rejection_type":   None,
                            "messages": [
                                f"✓ Approved: {display_sec_num} {sec_title} "
                                "(reviewer format self-repair)"
                            ],
                        }

                    repaired = agent._content_pass(
                        draft=polished,
                        course_topic=state.get("request", "General Topic"),
                        chapter_num=display_chap_num,
                        chapter_title=chap_title,
                        section_num=display_sec_num,
                        section_title=sec_title,
                        section_description=f"{sec_desc}\nReviewer feedback: {feedback}",
                        language=language,
                        enable_images=enable_images,
                        textbook_mode=textbook_mode,
                        target_pages=section_target_pages,
                        page_budget_mode=section_page_budget_mode,
                    )
                    repaired = agent._fix_heading_levels(repaired, display_sec_num, sec_title)
                    if not enable_images:
                        repaired = strip_image_markers_when_disabled(repaired)
                    if len(repaired) >= char_min:
                        logger.info("Balanced reviewer self-repair: depth/length fixed without Writer rewrite")
                        return {
                            "current_content":  repaired,
                            "review_feedback":  "",
                            "revision_number":  0,
                            "rejection_type":   None,
                            "messages": [
                                f"✓ Approved: {display_sec_num} {sec_title} "
                                "(reviewer depth self-repair)"
                            ],
                        }
                    logger.info("Balanced reviewer self-repair still below hard minimum; Writer rewrite required")
                    return {
                        "current_content":  repaired,
                        "review_feedback":  feedback,
                        "revision_number":  revision_number + 1,
                        "rejection_type":   "formatting_error",
                        "messages": [
                            f"↺ Revision {revision_number + 1}/{effective_max_revisions} "
                            f"[length_depth]: {feedback[:80]}"
                        ],
                    }

                rejection = agent.classify_rejection_type(feedback)
                return {
                    "current_content":  polished,
                    "review_feedback":  feedback,
                    "revision_number":  revision_number + 1,
                    "rejection_type":   rejection,
                    "messages": [
                        f"↺ Revision {revision_number + 1}/{effective_max_revisions} "
                        f"[{rejection}]: {feedback[:80]}"
                    ],
                }
        else:
            logger.warning(
                f"Max revisions ({effective_max_revisions}) reached for "
                f"{display_sec_num} — forcing approval"
            )

        # ------------------------------------------------------------------
        # Step 3 — Approved (quality gate passed or MAX_REVISIONS reached).
        # Clear review_feedback to signal approval to route_after_review().
        # Reset revision_number to 0 for the next subsection.
        # ------------------------------------------------------------------
        logger.info(f"✓ Content approved: {display_sec_num} {sec_title}")
        return {
            "current_content":  polished,
            "review_feedback":  "",   # empty string → approved in route_after_review()
            "revision_number":  0,    # reset for next subsection
            "rejection_type":   None, # reset on approval
            "messages": [
                f"✓ Approved: {display_sec_num} {sec_title} "
                f"(after {revision_number} revision(s))"
            ],
        }

    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {
            "current_content":  state.get("current_content", ""),
            "review_feedback":  "",
            "revision_number":  0,
        }

    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {
            "current_content":  state.get("current_content", ""),
            "review_feedback":  "",
            "revision_number":  0,
        }

    except Exception as e:
        logger.error(f"Unexpected error in Reviewer: {e}", exc_info=True)
        return {
            "current_content":  state.get("current_content", ""),
            "review_feedback":  "",
            "revision_number":  0,
        }
