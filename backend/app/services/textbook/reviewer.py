"""
Reviewer Agent for AI Textbook Generator.

This agent reviews and polishes Writer-drafted content before it proceeds
to the Illustrator. It runs two sequential passes per subsection:

Pass 1 — review_content():
    Full editorial pass covering LaTeX/math sanitization, academic tone,
    structural consistency, and image placeholder preservation.
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
from app.services.runtime_config import get_api_key
from app.services.textbook.language import get_language_profile

LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")

# Maximum number of revision cycles per subsection before forcing approval.
# Also imported by graph.py for the graph-level defense-in-depth ceiling.
MAX_REVISIONS = settings.REVIEWER_MAX_REVISIONS


class ReviewerAgent:
    """
    Reviewer Agent: Editorial pass + quality gate for each drafted section.

    Responsibilities:
    - LaTeX/math sanitization (Pandoc → Typst pipeline compatibility)
    - Academic tone enforcement (remove conversational fillers)
    - Structural consistency (header format, blank lines, sub-section depth)
    - Image placeholder preservation and optional new suggestions
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
            model=LLM_MODEL_CHEAP,
            api_key=get_api_key("OPENAI_API_KEY"), # type: ignore[arg-type]
            temperature=0.1,
        )
        self.prompt_logger = setup_prompt_logger("reviewer")

    def should_revise(
        self,
        content: str,
        char_min: int = 300,
        language: str = "vi",
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

        Returns:
            (needs_revision, feedback) tuple.
            Falls back to (False, "") on any error to avoid blocking the workflow.
        """
    # Fast Python pre-check — if content is already long enough,
    # skip the LLM call entirely. LLM character counting is unreliable
    # (underestimates by 30-40%) and wastes an API call when content
    # clearly meets the floor.
        if len(content) >= char_min * 1.2:
            # 20% headroom accounts for LLM undercounting tendency
            logger.info(
                f"Quality gate: APPROVE (pre-check) — "
                f"{len(content)} chars ≥ {char_min * 1.2:.0f} (floor {char_min} × 1.2)"
            )
            return False, ""
        profile = get_language_profile(language)
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

    Rule 2 — NAKED MATH: Contains LaTeX symbols or variables written outside
    $ delimiters (e.g., a_x, \\frac outside $).

    Rule 3 — WRONG MATH DELIMITERS: Contains \\[ \\] or \\( \\) instead of $$ or $.

    Rule 4 — TONE: Uses conversational or unprofessional tone in {profile.prompt_name}.
    Expected tone: {profile.tone_rule}

    Rule 5 — DEPTH: Section is superficial — missing definitions, examples, or
    core explanations. OR any ### sub-section contains fewer than 3 paragraphs.

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
                f"[QUALITY GATE — char_min={char_min} — "
                "see reviewer_prompts.log for full criteria]"
            ),
            user_prompt=f"Content to evaluate (first 300 chars):\n{content[:300]}...",
            context_label="QUALITY GATE",
        )

        try:
            chain = prompt | self.llm
            response = chain.invoke({"content": content, "char_min": char_min})

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

Rule 9 — Code blocks: must have a language identifier.
  ``` →  ```python  (or ```bash, ```sql, ```json depending on content)

Rule 10 — Inline programming code:
  Programming identifiers, keywords, function names, method names, operators,
  and code expressions MUST use Markdown backticks, not $...$ math.
  Fix: $student\\_scores["Alice"]$ → `student_scores["Alice"]`
  Fix: $del student\\_scores["Bob"]$ → `del student_scores["Bob"]`
  Fix: `keys()$ → `keys()`
  Do NOT wrap Python keywords, variables, string literals, list/dict indexing,
  or methods in math delimiters.

Rule 11 — Language-specific punctuation:
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
                model=LLM_MODEL_CHEAP,
                api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
                temperature=0.0,
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", format_system),
                ("user", "Apply format rules to this draft:\n\n{draft}"),
            ])
            chain = prompt | llm_format
            response = chain.invoke({
                "section_num":   section_num,
                "section_title": section_title,
                "chap_cmd":      chapter_cmd,
                "language_math_rule": language_math_rule,
                "format_style_rule": format_style_rule,
                "draft":         draft,
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
    ) -> str:
        """
        Pass B: Content quality — academic tone, depth, and visuals.

        Receives the format-clean output of _format_pass(). This pass focuses
        exclusively on content quality. LaTeX and structural rules are intentionally
        absent — Pass A already handled them, and their presence in this pass caused
        the LLM to trim content to comply with format rules instead of expanding it.

        Permitted changes:
          - Remove conversational fillers (Chúng ta hãy..., etc.)
          - Enforce academic Vietnamese tone
          - Expand shallow ### blocks (fewer than 3 paragraphs) using domain knowledge
          - Preserve and add > [IMAGE: ...] placeholders

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
        content_style_rule = (
            "Do NOT use em dash or en dash characters (—, –) in English output. "
            "Use commas, parentheses, semicolons, or ASCII hyphen-minus (-) instead."
            if profile.code == "en"
            else "Use natural Vietnamese punctuation."
        )
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

--- DEPTH ---
If any ### sub-section block contains fewer than 3 substantial paragraphs:
  Option A: MERGE it with the adjacent ### block into one richer section.
  Option B: EXPAND it to at least 3 paragraphs (4–5 sentences each) using
            domain knowledge consistent with the section description.
Prefer Option B when the block covers a distinct sub-topic worth preserving.

Bold audit: remove excessive bold. Keep bold ONLY for the primary concept
defined for the first time in the section. Remove bold from adjectives, general
nouns, phrases over 4 words, and any term already in a heading.

--- VISUALS ---
PRESERVE all existing > [IMAGE: ...] tags — do NOT remove or modify them.
ADD new image suggestions only where a visual genuinely aids comprehension:
  medium/deep sections → up to 3 images; light sections → max 1; applied → max 2.
  ADD: architecture diagrams, process flows, data structures, comparisons.
  SKIP: pure definition paragraphs, abstract theory, transition paragraphs.
Format: > [IMAGE: Short caption title | Detailed English description for image search]
[/CRITERION]

[FORMAT]
MANDATORY CHARACTER COUNT CHECK — execute before submitting:

Step 1: Mentally estimate the character count of the draft you received.
Step 2: Write your edited content.
Step 3: Estimate the character count of your output.

If your output is less than 95% of the draft's character count:
  → You have over-edited. Do NOT submit yet.
  → Identify the shortest ### block in your output.
  → Add 2–3 substantial paragraphs of domain-relevant analysis to that block.
  → Re-estimate. Repeat until output ≥ draft length.

This check is MANDATORY. Submitting shorter content than received is a failure.

Output rules:
  - Return ONLY the final polished Markdown
  - NO conversational preamble or meta-commentary
  - NO outer markdown fences wrapping the entire output
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
                )
            except Exception:
                logged_system = content_system

            self.prompt_logger.log(
                system_prompt=logged_system,
                user_prompt=f"Draft to improve (first 200 chars):\n{draft[:200]}...",
                context_label=f"{section_num} {section_title} [CONTENT-PASS-B]",
            )

            llm_content = ChatOpenAI(
                model=LLM_MODEL_CHEAP,
                api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
                temperature=0.2,
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", content_system),
                ("user", "Here is the draft to improve:\n\n{draft}"),
            ])
            chain = prompt | llm_content
            response = chain.invoke({
                "course_topic":        course_topic,
                "chapter_num":         chapter_num,
                "chapter_title":       chapter_title,
                "section_num":         section_num,
                "section_title":       section_title,
                "section_description": section_description,
                "filler_examples":     profile.filler_examples,
                "tone_rule":           profile.tone_rule,
                "content_style_rule":  content_style_rule,
                "draft":               draft,
            })
            return str(response.content)

        except Exception as e:
            logger.error(
                f"Pass B (_content_pass) error — returning format-fixed draft: {e}",
                exc_info=True,
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

        # --- Pass A: Mechanical format fixes ---
        logger.info(f"  Pass A (format): {section_num} {section_title}")
        format_fixed = self._format_pass(
            draft=safe_draft,
            section_num=section_num,
            section_title=section_title,
            chapter_cmd=chapter_cmd,
            language=language,
        )
        pass_a_len = len(format_fixed)
        logger.info(f"  Pass A complete: {len(safe_draft)} → {pass_a_len} chars")

        # --- Pass B: Content quality ---
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
        )
        pass_b_len = len(polished)
        logger.info(
            f"  Pass B complete: {pass_a_len} → {pass_b_len} chars "
            f"({'▼' if pass_b_len < pass_a_len else '▲'}"
            f"{abs(pass_b_len - pass_a_len)} chars)"
        )

        # Apply deterministic heading level fix (existing logic — keep unchanged).
        polished = self._fix_heading_levels(polished, section_num, section_title)

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
    profile = get_language_profile(language)

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

        

        # ------------------------------------------------------------------
        # Step 1 — Polish content.
        # Always runs; returns original draft on LLM error.
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

        # ------------------------------------------------------------------
        # Step 2 — Quality gate.
        #
        # Pass char_min from section_type so the gate enforces the same floor
        # the Writer targeted, rather than a fixed word-count threshold.
        # Skip the gate entirely once MAX_REVISIONS is reached.
        # ------------------------------------------------------------------
        from app.schemas.curriculum import get_char_target
        char_min, _ = get_char_target(sec_type, state.get("content_level", "Trung Bình"))

        if revision_number < MAX_REVISIONS:
            needs_revision, feedback = agent.should_revise(
                polished,
                char_min=char_min,
                language=language,
            )

            if needs_revision:
                logger.info(
                    f"Revision requested "
                    f"(attempt {revision_number + 1}/{MAX_REVISIONS}): {feedback[:80]}"
                )
                rejection = agent.classify_rejection_type(feedback)
                return {
                    "current_content":  polished,
                    "review_feedback":  feedback,
                    "revision_number":  revision_number + 1,
                    "rejection_type":   rejection,
                    "messages": [
                        f"↺ Revision {revision_number + 1}/{MAX_REVISIONS} "
                        f"[{rejection}]: {feedback[:80]}"
                    ],
                }
        else:
            logger.warning(
                f"Max revisions ({MAX_REVISIONS}) reached for "
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
