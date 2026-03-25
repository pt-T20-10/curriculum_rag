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

from src.log_config import setup_logger, setup_prompt_logger
from src.graph.state import (
    AgentState,
    Chapter,
    SubSection,
    get_chapter_and_subsection,
    clean_section_title,
)
from src.config import LLM_MODEL_CHEAP

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")

# Maximum number of revision cycles per subsection before forcing approval.
# Also imported by graph.py for the graph-level defense-in-depth ceiling.
MAX_REVISIONS = 2


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
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0.1)
        self.prompt_logger = setup_prompt_logger("reviewer")

    def should_revise(
        self,
        content: str,
        char_min: int = 300,
    ) -> tuple[bool, str]:
        """
        Quality gate: decide whether polished content meets minimum standards.

        Evaluation criteria (any single failure → needs_revision=True):
            1. Character count below char_min (content too short).
            2. Naked math — LaTeX symbols outside $ delimiters (e.g. a_x, \\frac).
            3. Wrong math delimiters — \\[ \\] or \\( \\) instead of $$ or $.
            4. Conversational or unprofessional tone in Vietnamese.
            5. Superficial content — missing definitions, examples, or core
               explanations; OR any ### sub-section with fewer than 3 paragraphs.
            6. Any Markdown heading not preceded by a blank line.

        The char_min parameter aligns the quality gate with the Writer's
        char_target, ensuring both agents enforce the same length floor rather
        than using independent thresholds.

        Args:
            content:  Polished content from review_content().
            char_min: Minimum character count floor (default 300 as safety net;
                      callers should pass the section's effective char_target[0]).

        Returns:
            (needs_revision, feedback) tuple.
            Falls back to (False, "") on any error to avoid blocking the workflow.
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """<role>
You are a strict academic quality gate. Your only output is a JSON object. No extra text.
</role>

<evaluation_criteria>
Step 1: Count the CHARACTERS (not words) in the content.
Step 2: Return needs_revision=true if ANY of the following is true:
1. Character count is less than {char_min}. If this criterion fails, your feedback
   MUST include: the exact character count found, the required minimum, and which
   specific ### sub-section is shortest and should be expanded first.
   Example: "Content is 2474/3000 chars. Section ### 1.1.2 has only 1 paragraph —
   expand with concrete examples and deeper analysis before other fixes."
2. Contains naked math — LaTeX symbols or variables written outside $ delimiters (e.g., a_x, \\frac outside $).
3. Contains wrong math delimiters: \\[ \\] or \\( \\) instead of $$ or $.
4. Uses conversational or unprofessional tone in Vietnamese.
5. Section is superficial — missing definitions, examples, or core explanations.
   OR any ### sub-section contains fewer than 3 paragraphs (shallow structure).
6. Any Markdown heading (`#`, `##`, `###`) is NOT preceded by a blank line — i.e., the line immediately before the `#` is non-empty text.
</evaluation_criteria>

<output_format>
Output a single JSON object, no markdown fences, no extra text:
{{"needs_revision": true, "feedback": "Actionable feedback for the writer"}}
or
{{"needs_revision": false, "feedback": ""}}
</output_format>"""),
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
    ) -> str:
        """
        Full editorial pass: sanitize, refine tone, fix structure, audit visuals.

        Runs four sequential editing phases (see reviewer_template below):
            Phase 1 — LATEX_SANITIZATION (CRITICAL, runs first)
            Phase 2 — CONTENT_REFINEMENT (tone, headers, length)
            Phase 3 — VISUALS (preserve existing tags, add missing ones)
            Phase 4 — FORMAT_CHECK (bold, code blocks, blank lines, depth)

        Args:
            course_topic:        Main textbook topic (e.g. "Học máy").
            chapter_num:         1-indexed chapter number as string.
            chapter_title:       Title of the current chapter.
            section_num:         Dot-notation section number (e.g. "2.3").
            section_title:       Title of the current section.
            section_description: What this section should cover (from curriculum).
            draft_content:       Raw content from the Writer node.
            chapter_cmd:         Typst-compatible directive for chapter header handling.
                                 Empty string when Reviewer should ignore the # heading.
                                 "VERIFY ONLY..." when first subsection of a chapter.

        Returns:
            Polished Markdown string.
            Returns the original draft unchanged on error (preserves workflow).
        """
        logger.info(f"Polishing: {section_num} {section_title}")

        if not draft_content or len(draft_content) < 50:
            logger.warning("Draft too short/empty — skipping review")
            return draft_content

        # ------------------------------------------------------------------
        # Reviewer prompt — XML-structured for strict LLM phase compliance.
        #
        # Variable interpolation note:
        #   Single braces {var}   → Python .format() substitution
        #   Double braces {{...}} → literal braces in the final prompt string
        #                           (e.g. LaTeX \text{{cuối}} examples)
        # ------------------------------------------------------------------
        reviewer_template = """<role>
You are a Senior Technical Editor and LaTeX Specialist for a Vietnamese university textbook publisher.
Edit the draft below. Your sole output is the final polished Markdown — no preamble, no explanations.
</role>

<task_context>
<book_topic>{course_topic}</book_topic>
<chapter num="{chapter_num}">{chapter_title}</chapter>
<section num="{section_num}">{section_title}</section>
<description>{section_description}</description>
</task_context>

<draft>
{draft}
</draft>

<editing_phases>

<phase id="1" name="LATEX_SANITIZATION" priority="CRITICAL">
Execute these fixes IN ORDER before any other edits.

1. Block math delimiters — replace ALL non-standard forms with $$ $$:
   ❌ \\[ F = ma \\]  →  ✅ $$ F = ma $$
   ❌ \\begin{{equation}} F = ma \\end{{equation}}  →  ✅ $$ F = ma $$

2. Inline math delimiters — replace ALL \\( \\) with $:
   ❌ \\( x = 5 \\)  →  ✅ $x = 5$
   CRITICAL: NO space after opening $ or before closing $. $ x $ is WRONG — Pandoc ignores it.

3. Naked math — wrap standalone variables, symbols, subscripts in $:
   ❌ Ta có gia toc a duoc tinh bang...  →  ✅ Ta có gia tốc $a$ được tính bằng...
   ❌ a_max = 5  →  ✅ $a_{{max}} = 5$

4. Vietnamese text inside math — MUST use \\text{{...}}:
   ❌ $$ v_{{cuoi}} = v_{{dau}} + at $$
   ✅ $$ v_{{\\text{{cuối}}}} = v_{{\\text{{đầu}}}} + at $$

5. Unicode subscripts/superscripts — convert ALL to math notation (may not render correctly):
   ❌ H₂O, CO₂, Na⁺, Cl⁻, 1s², H₂SO₄  (Unicode chars not in Times New Roman)
   ✅ H$_2$O, CO$_2$, Na$^+$, Cl$^-$, $1s^2$, H$_2$SO$_4$
   Rule: subscript digits (₀–₉) → $_n$, superscripts (⁺⁻⁰–⁹) → $^n$
</phase>

<phase id="2" name="CONTENT_REFINEMENT">
1. Chapter header — DO NOT add or modify any # (level-1) heading. The Writer node owns
   chapter headers exclusively. Your only job here is to ensure the ## section header
   is correctly formatted.
   {chap_cmd}

2. Section header must be exactly: ## {section_num} {section_title}
   - Remove colon: ## 1.1: Title  →  ## 1.1 Title
   - Remove double numbering: ## 1.1. Muc 1.1 Title  →  ## 1.1 {section_title}
   - Do NOT use # (Header 1) unless it is the chapter title line

3. Academic tone — eliminate conversational fillers:
   Remove: "Chung ta hay cung xem...", "Trong phan nay toi se..."
   Keep: direct, formal, Vietnamese academic prose

4. Technical terms — keep standard English terms as-is (DataFrame, CPU, API).
   Use standard Vietnamese translations for general terms.

5. Length — PRESERVE AND PROTECT content length.
   CRITICAL: Count the input draft characters before editing. Your output MUST
   contain AT LEAST as many characters as the input draft. If your editorial
   changes (tone, structure, math fixes) reduce the character count, you MUST
   immediately expand the shortest ### sub-section with additional explanation,
   examples, or analysis to compensate — do NOT submit output shorter than input.
   Removing content is only allowed when fixing exact duplicate passages, and any
   removal must be offset by equivalent expansion elsewhere in the same section.
</phase>

<phase id="3" name="VISUALS">
PRESERVE all existing > [IMAGE: ...] tags — do NOT remove them.

ADD new suggestions only where a visual would genuinely aid understanding AND is still missing.
Mirror the Writer's image policy based on the section type inferred from the description:

- light sections (orientation, recap, bridge): max 1 image total, prefer 0.
- applied sections (exercises, tasks, problems): max 2 images, only diagrams that
  directly illustrate a task or worked example.
- medium / deep sections: up to 3 images total, scaled to content complexity.
  ADD when: architecture diagrams, flowcharts, process steps, scientific phenomena, data structures.
  DO NOT ADD when: pure definition paragraphs or abstract concepts with no visual component.

Format: > [IMAGE: Short caption title | Detailed English description for image generation]
</phase>

<phase id="4" name="FORMAT_CHECK">
1. Bold audit — REMOVE excessive bold. Keep bold ONLY for the first formal definition of the
   section's primary technical term. Remove bold from: adjectives, general nouns, phrases
   longer than 4 words, any term that already appears in a Markdown header.
2. Code blocks must have a language identifier: ```python, ```bash, ```sql.
3. CRITICAL: Every heading (`#`, `##`, `###`) MUST have a blank line immediately BEFORE and AFTER it.
   Fix any heading that directly follows a paragraph with no blank line between them.
   ❌  ...end of paragraph.\n### 2.1.2 Title
   ✅  ...end of paragraph.\n\n### 2.1.2 Title\n\nNext paragraph...
4. Sub-section depth audit — if any ### block contains fewer than 3 paragraphs:
   - MERGE it into the adjacent ### block, OR
   - EXPAND it to at least 3 paragraphs using domain knowledge.
   A ### heading with only 1–2 paragraphs beneath it is a structural defect — fix it.
</phase>

</editing_phases>

<output_format>
- Return ONLY the final polished Markdown
- NO conversational preamble ("Here is the revised version...", "I have fixed...")
- NO outer markdown fences wrapping the entire output
</output_format>"""

        user_template = "Here is the draft to review:\n\n{draft}"

        # Log a preview of the formatted prompt (context truncated to avoid
        # bloating the prompt log file with full draft content).
        try:
            draft_preview = (
                draft_content[:500] + "...[truncated]"
                if len(draft_content) > 500
                else draft_content
            )
            formatted_reviewer = reviewer_template.format(
                course_topic=course_topic,
                chapter_num=chapter_num,
                chapter_title=chapter_title,
                section_num=section_num,
                section_title=section_title,
                section_description=section_description,
                draft=draft_preview,
                chap_cmd=chapter_cmd,
            )
        except Exception:
            formatted_reviewer = reviewer_template

        self.prompt_logger.log(
            system_prompt=formatted_reviewer,
            user_prompt=user_template.format(
                draft=draft_content[:200] + "...[truncated]"
            ),
            context_label=f"{section_num} {section_title} [POLISH]",
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", reviewer_template),
            ("user", user_template),
        ])

        try:
            # Strip control characters that break JSON serialization.
            # Keep only printable chars + standard whitespace (\n \t \r).
            # These accumulate after multiple Writer→Reviewer revision cycles
            # and cause OpenAI API to return 400 invalid_request_error.
            safe_draft = ''.join(
                c for c in draft_content
                if c >= ' ' or c in '\n\t\r'
            )

            chain = prompt | self.llm
            response = chain.invoke({
                "course_topic":        course_topic,
                "chapter_num":         chapter_num,
                "chapter_title":       chapter_title,
                "section_num":         section_num,
                "section_title":       section_title,
                "section_description": section_description,
                "draft":               safe_draft,
                "chap_cmd":            chapter_cmd,
            })

            logger.info("✓ Review complete")
            return response.content  # type: ignore

        except Exception as e:
            logger.error(f"Error during review: {e}", exc_info=True)
            # Return original draft to keep the workflow moving — the quality
            # gate in should_revise() will catch remaining issues on next pass.
            return draft_content


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
        # The Writer owns # CHƯƠNG headers exclusively. The Reviewer must never
        # add one. For the first subsection (sub_idx == 0), we ask the Reviewer
        # to verify the header exists — but NOT to add it if missing.
        #
        # sub_idx == 0 is used instead of display_sec_num.endswith(".1") to
        # avoid false matches on section numbers like "1.11" or "2.21".
        # ------------------------------------------------------------------
        chap_cmd_text = ""
        if sub_idx == 0 and state.get("chapter_header_written", False):
            chap_cmd_text = (
                f"VERIFY ONLY (do NOT add): Confirm a '# CHƯƠNG {display_chap_num}' "
                f"heading exists at the very top of the draft. "
                f"If missing, that is acceptable — do not add it."
            )

        draft = state.get("current_content", "")

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
        )

        # ------------------------------------------------------------------
        # Guard: restore # CHƯƠNG heading if Reviewer LLM stripped it.
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
            if not re.search(r'^# CHƯƠNG', polished, flags=re.MULTILINE):
                expected_heading = (
                    f"# CHƯƠNG {display_chap_num}: {chap_title.upper()}"
                )
                polished = expected_heading + "\n\n" + polished.lstrip('\n')
                logger.warning(
                    f"⚠️  Reviewer stripped # CHƯƠNG heading — restored: "
                    f"'{expected_heading}'"
                )

        # ------------------------------------------------------------------
        # Step 2 — Quality gate.
        #
        # Pass char_min from section_type so the gate enforces the same floor
        # the Writer targeted, rather than a fixed word-count threshold.
        # Skip the gate entirely once MAX_REVISIONS is reached.
        # ------------------------------------------------------------------
        from src.graph.state import get_char_target
        char_min, _ = get_char_target(sec_type, state.get("content_level", "Trung Bình"))

        if revision_number < MAX_REVISIONS:
            needs_revision, feedback = agent.should_revise(polished, char_min=char_min)

            if needs_revision:
                logger.info(
                    f"Revision requested "
                    f"(attempt {revision_number + 1}/{MAX_REVISIONS}): {feedback[:80]}"
                )
                return {
                    "current_content":  polished,
                    "review_feedback":  feedback,
                    "revision_number":  revision_number + 1,
                    "messages": [
                        f"↺ Revision {revision_number + 1}/{MAX_REVISIONS}: {feedback[:80]}"
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