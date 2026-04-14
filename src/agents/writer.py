"""
Writer Agent for AI Textbook Generator.

This agent synthesizes retrieved RAG context into high-quality academic content,
with standard Markdown formatting for PDF compilation via Typst.

Responsibilities:
- Draft new sections from RAG context + curriculum metadata
- Re-draft sections when Reviewer returns feedback (revision mode)
- Enforce chapter header ownership (emit / suppress # CHƯƠNG heading)
- Apply post-processing to guarantee blank-line compliance before returning content
"""

import re
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate


from src.log_config import setup_logger, setup_prompt_logger
from src.graph.state import (
    AgentState,
    Chapter,
    SubSection,
    get_chapter_and_subsection,
    get_char_target,
    clean_section_title,
)
from src.config import LLM_MODEL_PREMIUM, ANTHROPIC_API_KEY

logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")

# ============================================================================
# RULE 2.5 CALIBRATION DATA
#
# Per (section_type, content_level) → (block_range, para_range, sent_range)
# Used by _build_length_rule() to generate dynamic RULE 2.5 prompt text.
# Tuple: (blocks, paragraphs_per_block, sentences_per_paragraph)
# ============================================================================

_LENGTH_CALIBRATION: dict[str, dict[str, tuple[str, str, str]]] = {
    "light": {
        "Ngắn":       ("1–2", "2–3", "3"),
        "Trung Bình": ("2–3", "3–4", "4–5"),
        "Dài":        ("3",   "4–5", "5"),
        "Rất Dài":    ("4",   "5",   "6"),
    },
    "medium": {
        "Ngắn":       ("2–3", "3",   "3–4"),
        "Trung Bình": ("3–4", "4",   "5"),
        "Dài":        ("4–5", "5–6", "6"),
        "Rất Dài":    ("5–6", "6–7", "7"),
    },
    "deep": {
        "Ngắn":       ("3",   "3–4", "4"),
        "Trung Bình": ("4–5", "5",   "5–6"),
        "Dài":        ("5–6", "6",   "6–7"),
        "Rất Dài":    ("6–7", "7–8", "7–8"),
    },
    "applied": {
        "Ngắn":       ("2",   "brief worked steps",    ""),
        "Trung Bình": ("3",   "full worked steps",     ""),
        "Dài":        ("3–4", "detailed worked steps", ""),
        "Rất Dài":    ("4–5", "comprehensive worked examples with edge cases", ""),
    },
}


def _build_length_rule(
    section_type: str,
    content_level: str,
    char_min: int,
    char_max: int,
) -> str:
    """
    Build RULE 2.5 prompt text scaled to the user's chosen content_level.

    Generates concrete structural guidance (blocks × paragraphs × sentences)
    calibrated to the actual char_min so the LLM can self-check accurately.
    """
    level_key  = content_level if content_level in _LENGTH_CALIBRATION.get(
        section_type, {}
    ) else "Trung Bình"
    type_key   = section_type if section_type in _LENGTH_CALIBRATION else "medium"
    cal        = _LENGTH_CALIBRATION[type_key][level_key]
    blocks, paras, sents = cal

    if type_key == "applied":
        calibration_line = (
            f"- applied  (~{char_min} chars min): "
            f"{blocks} ### blocks with {paras}"
        )
    else:
        calibration_line = (
            f"- {type_key:<8} (~{char_min} chars min): "
            f"{blocks} ### blocks × {paras} paragraphs × {sents} sentences each"
        )

    return (
        f"RULE 2.5 — LENGTH ENFORCEMENT (NON-NEGOTIABLE):\n"
        f"Your output MUST contain at least {char_min} characters. "
        f"This is a hard floor — do NOT stop before reaching it.\n\n"
        f"Calibration for this section ({section_type} / {content_level}):\n"
        f"{calibration_line}\n\n"
        f"Self-check before finishing: mentally estimate your paragraph count.\n"
        f"If you have not reached {char_min} characters, continue writing —\n"
        f"add more explanation, a worked example, or deeper analysis. Do NOT stop early."
    )
class WriterAgent:
    """
    Writer Agent: Generates textbook section content from RAG context.

    Specialized in:
    - Academic writing in Vietnamese (văn phong học thuật)
    - Markdown formatting compatible with Pandoc → Typst → PDF pipeline
    - Structured content with numbered headers (## X.Y, ### X.Y.Z)
    - Revision support: accepts Reviewer feedback and rewrites from scratch

    LLM is initialized once in __init__ and reused across all write_section calls
    within the same agent lifetime.
    """
    llm: BaseChatModel
    def __init__(self) -> None:
        """
        Initialize LLM with temperature=0.4 (balanced creativity vs consistency).

        temperature=0.4 is chosen to:
        - Allow natural variation in prose across sections
        - Avoid excessive creativity that breaks structural rules
        - Remain deterministic enough for consistent formatting compliance
        """
        self.llm = ChatAnthropic(
            model_name=LLM_MODEL_PREMIUM,
            api_key=ANTHROPIC_API_KEY,        # type: ignore[arg-type]
            temperature=0.4,
            max_tokens_to_sample=16000,
        )
        # ── INACTIVE: OpenAI GPT (uncomment to switch back) ─────────────────────
        # from langchain_openai import ChatOpenAI
        # from src.config import OPENAI_API_KEY
        # self.llm = ChatOpenAI(
        #     model=LLM_MODEL_PREMIUM,   # e.g. "gpt-4o"
        #     api_key=OPENAI_API_KEY,
        #     temperature=0.4,
        # )

        self.prompt_logger = setup_prompt_logger("writer")

    def write_section(
        self,
        course_topic: str,
        chapter_num: int,
        chapter_title: str,
        section_num: str,
        section_title: str,
        section_description: str,
        context: str,
        chapter_instruction: str,
        review_feedback: str = "",
        section_type: str = "medium",
        char_target: tuple[int, int] = (3000, 4500),
        enable_images: bool = True,
        content_level: str = "Trung Bình",
    ) -> str:
        """
        Generate or revise content for a single textbook section.

        This method builds the full system prompt, invokes the LLM, then applies
        deterministic post-processing to enforce blank-line rules that the LLM
        sometimes violates under token pressure.

        Args:
            course_topic:        Main topic of the textbook (e.g. "Học máy").
            chapter_num:         1-indexed chapter number.
            chapter_title:       Title of the current chapter.
            section_num:         Dot-notation section number (e.g. "2.3").
            section_title:       Title of the current section.
            section_description: 1-2 sentence description of what to cover.
            context:             RAG-retrieved text chunks relevant to this section.
            chapter_instruction: Directive controlling # CHƯƠNG header behaviour.
                                 Two forms:
                                   - "Output EXACTLY this line ... # CHƯƠNG N"
                                     → LLM must emit the chapter heading first.
                                   - "DO NOT output any # (level-1) heading"
                                     → LLM is explicitly prohibited from emitting one.
            review_feedback:     Non-empty string → revision mode; LLM rewrites from
                                 scratch addressing the listed issues.
            section_type:        Depth level controlling prose density and structure.
                                 One of: "light" | "medium" | "deep" | "applied".
            char_target:         (min_chars, max_chars) derived from section_type.
                                 The LLM is instructed to reach min_chars before stopping.
            enable_images:       When False, all image suggestion rules are suppressed.

        Returns:
            Generated Markdown string ready for the Reviewer node.
            Returns an error sentinel string on LLM or formatting failure.
        """
        logger.info(f"Composing: {section_num} {section_title}")

        if review_feedback:
            logger.info(f"Revision mode — feedback: {review_feedback[:80]}")

        # ------------------------------------------------------------------
        # Visual rule — controls image tag injection in the LLM output.
        #
        # Mapped directly to the 4 valid section_type values:
        #   light   → minimal (orientation/recap sections don't benefit from images)
        #   applied → moderate (diagrams that illustrate exercises are welcome)
        #   medium / deep → full guidance (1–3 images based on content complexity)
        #
        # Previously used LOW_VISUAL_TYPES = ("summary", "practice") which never
        # matched any valid section_type and caused the branch to be dead code.
        # ------------------------------------------------------------------
        if not enable_images:
            visual_rule = "Do NOT add any image suggestions."

        elif section_type == "light":
            visual_rule = (
                "This is an orientation or recap section — 1 image is appropriate\n"
                "if it sets the scene or establishes the visual context for the chapter.\n"
                "Insert exactly 1 image suggestion if a diagram or photo would orient\n"
                "the reader. Prefer a real-world photo or overview diagram.\n"
                "Format: > [IMAGE: Short caption title | Detailed English description]\n"
                "DESCRIPTION: 1-2 sentences in English describing what to depict visually.\n"
                "CRITICAL: Do NOT mention text, labels, captions, or written words as visual\n"
                "elements — they will be rendered literally and appear garbled in the image."
            )

        elif section_type == "applied":
            visual_rule = (
                "This is a hands-on section — diagrams and photos that illustrate\n"
                "the task, tool, material, or expected result are strongly encouraged.\n"
                "Insert 2–3 image suggestions: one near the start to show the goal or\n"
                "setup, and one after each major worked step that has a visual output.\n"
                "Format: > [IMAGE: Short caption title | Detailed English description]\n"
                "DESCRIPTION: 1-2 sentences showing the task, tool, or result visually.\n"
                "Describe steps as actions and shapes — NOT as numbered labels or text overlays.\n"
                "CRITICAL: Do NOT mention text, labels, captions, or written words as visual\n"
                "elements — they will be rendered literally and appear garbled in the image."
            )

        else:
            # medium / deep — full visual guidance for richer sections
             visual_rule = (
                "Images are EXPECTED in this section — the default is to ADD, not skip.\n"
                "Target: at least 2 images per section, up to 4 for complex content.\n\n"
                "ADD an image after any paragraph that involves:\n"
                "- A process, sequence, or workflow (flowchart or step diagram)\n"
                "- A system, architecture, or structure with multiple components\n"
                "- A scientific or physical phenomenon (diagram or photo)\n"
                "- A real-world object, person, place, or artifact being discussed\n"
                "- A comparison, contrast, or before/after scenario\n"
                "- A concept that is easier to grasp visually than in prose\n\n"
                "SKIP only when the paragraph is a pure abstract definition with zero\n"
                "visual component — e.g. a philosophical statement or a list of dates.\n"
                "If in doubt, ADD the image.\n\n"
                "Placement: insert the tag immediately AFTER the paragraph it illustrates.\n"
                "Format: > [IMAGE: Short caption title | Detailed English description]\n\n"
                "IMAGE FORMAT RULES:\n"
                "- TITLE: 3-6 words max, Vietnamese or English, used directly as PDF caption.\n"
                "  Examples: 'Kiến trúc microservices', 'OSI Model layers', 'CI/CD pipeline flow'\n"
               "- DESCRIPTION: 2-3 sentences in English. Describe what to depict visually:\n"
                "  shapes, composition, key elements, mood, colors, and atmosphere.\n"
                "  For abstract/conceptual: describe the metaphor, mood, and visual composition.\n"
                "  For real entities: name the specific subject clearly and describe the scene.\n"
                "  CRITICAL: Do NOT mention text, labels, captions, or written words as visual\n"
                "  elements — they will be rendered literally and appear garbled in the image.\n"
                "  Do NOT over-constrain style (avoid forcing 'white background', 'clean technical').\n"
                "  Examples:\n"
                "  > [IMAGE: Kiến trúc microservices | Five independent service nodes connected by\n"
                "    arrows flowing through a central gateway, each node paired with a small database\n"
                "    cylinder below, message queue shown as a horizontal pipeline in the center]\n"
                "  > [IMAGE: Vụ nổ Big Bang | A brilliant point of light exploding outward into\n"
                "    swirling colourful matter and energy against a deep dark space background,\n"
                "    dramatic cosmic atmosphere with warm and cool colour contrast]\n"
                "  > [IMAGE: Kính viễn vọng Hubble | The Hubble Space Telescope floating in orbit\n"
                "    above Earth, golden solar panels extended, blue curved Earth below, star-filled\n"
                "    space backdrop]"
            )
        # ------------------------------------------------------------------
        # Revision instruction block — injected into system prompt only when
        # the Reviewer has rejected the previous draft. Placed prominently so
        # the LLM addresses all feedback items before writing new content.
        # ------------------------------------------------------------------
        revision_instruction = ""
        if review_feedback:
            revision_instruction = (
                "<revision_required>\n"
                "PREVIOUS DRAFT REJECTED. You MUST fix ALL issues below before writing.\n"
                f"FEEDBACK: {review_feedback}\n"
                "ACTION: Rewrite from scratch. Do NOT repeat previous mistakes.\n"
                "</revision_required>"
            )
        length_rule = _build_length_rule(
            section_type, content_level, char_target[0], char_target[1]
        )
        # ------------------------------------------------------------------
        # System prompt — XML-structured for strict LLM rule compliance.
        #
        # Rule ordering is intentional:
        #   RULE 1  Language & tone
        #   RULE 2  Depth level behaviour (structure guidance)
        #   RULE 2.5 Length enforcement — placed immediately after depth guide
        #            so the LLM has calibration context when reading the floor
        #   RULE 3  Chapter header (critical — must come before RULE 4)
        #   RULE 4  Document structure (headers, numbering)
        #   RULE 5  Sub-section depth
        #   RULE 6  Content requirements (bold, examples, tone)
        #   RULE 7  Visual guidance
        # ------------------------------------------------------------------
        system_prompt = """
[CONTEXT]
You are a neutral academic writing specialist producing content for an educational
platform that covers all learning domains — university academics, technical skills,
practical crafts, and lifestyle topics. You adapt tone and depth to the subject
domain rather than applying a fixed academic register to every topic.
Your sole output is the final Markdown content — no preamble, no explanations,
no meta-commentary.
[/CONTEXT]

[TASK]
Write the content for the following textbook section.

<book_topic>{course_topic}</book_topic>
<chapter num="{chapter_num}">{chapter_title}</chapter>
<section num="{section_num}">{section_title}</section>
<description>{section_description}</description>
<section_type>{section_type}</section_type>
<char_target>{char_min}–{char_max} characters</char_target>
<research_material>
{context}
</research_material>
[/TASK]

{revision_instruction}

[CRITERION]
Adapt writing depth and length based on section_type:
- light   → Orient or recap: accessible prose, light technical depth, no exhaustive detail
- medium  → Explain or demonstrate: clear definitions, worked examples, concrete illustrations
- deep    → Analyse or theorise: sustained argument, rigorous detail, explain WHY and HOW fully
- applied → Tasks or exercises: step-by-step guidance, problems with worked solutions

Each paragraph: 3–5 sentences. Output MUST reach the char_target minimum.

{length_rule}

Sub-section depth standards:
- Each ### block MUST contain a MINIMUM of 3 substantial paragraphs (each 3–5 sentences).
- PREFER FEWER, DEEPER ### blocks over MANY, SHALLOW ones.
  - light   → 2–3 ### blocks max, each 3+ paragraphs
  - medium  → 3–4 ### blocks, each 4–5 paragraphs
  - deep    → 3–5 ### blocks, each 5–6 paragraphs with analysis, evidence, examples
  - applied → 2–4 ### blocks, each containing full worked steps or complete problems

Content quality standards:
- Write in formal Vietnamese (Tiếng Việt học thuật). Academic, precise, and accessible.
  Do NOT use conversational fillers: "Chúng ta hãy cùng xem...", "Trong phần này tôi sẽ...".
- Adapt tone to domain: precise for IT/Engineering, narrative for History/Arts, rigorous for Science.
- Bold (**term**) — use SPARINGLY. Bold ONLY for the primary concept being formally defined
  for the FIRST time in this section. Do NOT bold: general descriptive words, repeated mentions,
  phrases longer than 4 words, or terms already in a Markdown header.
- Provide at least one concrete, domain-relevant example.
- Code blocks MUST include a language identifier: ```python, ```bash, ```sql
- If research material is thin or irrelevant, use internal knowledge to fill gaps.
[/CRITERION]

[CONSTRAINT]
Rule 1 — CHAPTER HEADER (STRICTLY OBEY — non-negotiable, binary compliance):
{chapter_instruction}

Rule 2 — DOCUMENT STRUCTURE (all sub-rules are hard requirements):
- Section header: ## {section_num} {section_title}
- Sub-section header: ### {section_num}.N Title where N starts at 1
  (e.g. for ## 1.2: ### 1.2.1 Tiêu đề, ### 1.2.2 Tiêu đề, ...)
- NEVER use unnumbered ### headers — always include full dot-number prefix
- NEVER use # (Header 1) unless Rule 1 explicitly instructs a # CHƯƠNG line
- NEVER double-number: ❌ ## 1.1. Mục 1.1 Tiêu đề → ✅ ## 1.1 Tiêu đề
- NEVER use colon after header number: ❌ ## 1.1: Tiêu đề → ✅ ## 1.1 Tiêu đề

Rule 3 — BLANK LINE (PDF will break if violated — zero exceptions):
ALWAYS put a blank line immediately BEFORE and AFTER every heading.
❌  ...end of paragraph.\n### 2.1.2 Title   ← WRONG
✅  ...end of paragraph.\n\n### 2.1.2 Title  ← CORRECT
Apply to EVERY occurrence:
- Blank line BEFORE and AFTER every header (#, ##, ###)
- Blank line BETWEEN every paragraph
- Blank line BEFORE and AFTER every list
- Blank line BEFORE and AFTER every code block
- Blank line BEFORE and AFTER every math block ($$)

Rule 4 — DO NOT create a ### heading for content that fits in 1–2 paragraphs.
Fold it into the preceding sub-section or expand it first.
[/CONSTRAINT]

[EXEMPLAR]
WRONG sub-section structure (too shallow):
  ### 1.2.1 Khái niệm
  One paragraph.
  ### 1.2.2 Ứng dụng
  One paragraph.

CORRECT sub-section structure (deep enough):
  ### 1.2.1 Khái niệm và Nền tảng Lý thuyết
  Four to five paragraphs with definition, context, and analysis.

WRONG header format:
  ## 1.1: Tiêu đề   or   ## 1.1. Mục 1.1 Tiêu đề

CORRECT header format:
  ## 1.1 Tiêu đề
[/EXEMPLAR]

[FORMAT]
- Language: Vietnamese (Tiếng Việt)
- Output: raw Markdown — NO outer markdown fences wrapping the entire response
- STRICTLY follow Rule 1 (CHAPTER HEADER) for your first line — no exceptions
- Sub-section headers: ### {section_num}.N Title (numbered sequentially from 1)
- Blank line before AND after EVERY header — no exceptions
- Blank line between EVERY paragraph
- Blank line before AND after EVERY math block ($$ ... $$)
- Character count MUST reach {char_min} minimum before stopping

{visual_rule}
[/FORMAT]"""

        user_prompt = f"Please write the content for section **{section_num}: {section_title}**."

        # ------------------------------------------------------------------
        # Prompt logging — logs a preview (context truncated to 500 chars)
        # to avoid bloating the prompt log file with full RAG context.
        # Falls back to the unformatted template string on format error.
        # ------------------------------------------------------------------
        try:
            context_preview = context[:500] + "...[truncated]" if len(context) > 500 else context
            formatted_system = system_prompt.format(
                course_topic=course_topic,
                chapter_num=chapter_num,
                chapter_title=chapter_title,
                section_num=section_num,
                section_title=section_title,
                section_description=section_description,
                context=context_preview,
                chapter_instruction=chapter_instruction,
                revision_instruction=revision_instruction,
                section_type=section_type,
                char_min=char_target[0],
                char_max=char_target[1],
                visual_rule=visual_rule,
                length_rule=length_rule,
            )
        except Exception:
            formatted_system = system_prompt

        mode = "REVISION" if review_feedback else "DRAFT"
        self.prompt_logger.log(
            system_prompt=formatted_system,
            user_prompt=user_prompt,
            context_label=f"{section_num} {section_title} [{mode}]",
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", user_prompt)
        ])

        try:
            safe_context = ''.join(
                c for c in context
                if c >= ' ' or c in '\n\t\r'
            )
            chain = prompt | self.llm
            response = chain.invoke({
                "course_topic": course_topic,
                "chapter_num": chapter_num,
                "chapter_title": chapter_title,
                "section_num": section_num,
                "section_title": section_title,
                "section_description": section_description,
                "context": safe_context,
                "chapter_instruction": chapter_instruction,
                "revision_instruction": revision_instruction,
                "section_type": section_type,
                "char_min": char_target[0],
                "char_max": char_target[1],
                "visual_rule": visual_rule,
                "length_rule": length_rule, 
            })

            raw_content = response.content
            if not isinstance(raw_content, str):
                logger.error(f"LLM returned non-string content: {type(raw_content)}")
                return "(Error: Invalid content type from LLM)"

            content: str = raw_content

            # ------------------------------------------------------------------
            # Post-processing — deterministic fixups applied after every LLM call.
            #
            # These are safety nets for known LLM formatting failures:
            #   Pass 1: Missing blank line BEFORE a heading
            #           Pattern: any non-newline char followed immediately by \n##
            #   Pass 2: Missing blank line AFTER a heading
            #           Pattern: heading line followed by non-empty line with no gap
            #   Pass 3: Missing blank line BETWEEN prose paragraphs
            #           Heuristic: sentence-ending punctuation + next line starts
            #           with uppercase or digit. Skips lines that start with
            #           special Markdown tokens to avoid false positives on lists,
            #           blockquotes, code blocks, and math blocks.
            # ------------------------------------------------------------------

            # Pass 1 — blank line before headings
            content = re.sub(
                r'([^\n])\n(#{1,3} )',
                r'\1\n\n\2',
                content,
            )

            # Pass 2 — blank line after headings
            content = re.sub(
                r'(^#{1,3} .+)$\n(?!\n)',
                r'\1\n\n',
                content,
                flags=re.MULTILINE,
            )

            # Pass 3 — blank line between prose paragraphs
            lines = content.split('\n')
            fixed_lines: list[str] = []

            for i, line in enumerate(lines):
                fixed_lines.append(line)

                if i >= len(lines) - 1:
                    continue

                current_line = line.rstrip()
                next_line    = lines[i + 1].strip()

                # Skip if either line is already blank — gap already present
                if not current_line or not next_line:
                    continue

                # Skip lines that start with Markdown special tokens — inserting
                # a blank line inside a list, blockquote, or code block would
                # break the structure.
                SPECIAL_PREFIXES = ('#', '-', '*', '>', '```', '$$')
                if current_line.startswith(SPECIAL_PREFIXES):
                    continue
                if next_line.startswith(SPECIAL_PREFIXES):
                    continue

                # Insert blank line when current line ends a sentence and next
                # line begins a new one (uppercase or digit start).
                if current_line[-1] in '.!?;:':
                    if next_line[0].isupper() or next_line[0].isdigit():
                        fixed_lines.append('')

            content = '\n'.join(fixed_lines)

            # ------------------------------------------------------------------
            # Length check — warn if output is significantly below target.
            # The Reviewer quality gate will request a revision if needed;
            # this log line gives early visibility in the pipeline logs.
            # ------------------------------------------------------------------
            actual_chars = len(content)
            if actual_chars < char_target[0] * 0.95:
                logger.warning(
                    f"⚠️  Content too short: {actual_chars} chars "
                    f"(target {char_target[0]}–{char_target[1]}) "
                    f"for {section_num} '{section_title}'. "
                    f"Reviewer quality gate will handle revision if needed."
                )
            else:
                logger.info(
                    f"✓ Content length OK: {actual_chars} chars "
                    f"(target {char_target[0]}–{char_target[1]})"
                )

            logger.info(f"✓ Content generated ({len(content)} chars)")
            return content

        except Exception as e:
            logger.error(f"Error generating content: {e}", exc_info=True)
            return "(Error: Unable to generate content for this section. Please check logs.)"


def write_section(state: AgentState) -> dict:
    """
    Writer node: Generate or revise content for the current subsection.

    Reads curriculum position from state indexes, constructs the full context
    for the WriterAgent, then applies two additional deterministic layers:

    Layer 1 — Prompt instruction:
        Controls whether the LLM emits a # CHƯƠNG heading.
        Only the first subsection of each chapter (sub_idx == 0) that has not
        yet written its chapter header is instructed to emit it.
        All other subsections receive an explicit prohibition.

    Layer 2 — Post-processing strip:
        If the LLM emitted a level-1 heading despite the prohibition (hallucination
        under token pressure), all `# ...` lines are stripped from the output.

    Layer 3 — State flag:
        Returns chapter_header_written=True only when the header was actually
        emitted. The flag is never reset here — that is owned by the checkpoint
        nodes (append_and_update_chapter).

    Workflow integration:
        Input:  state["curriculum"], state["current_chapter_index"],
                state["current_subsection_index"], state["rag_context"],
                state["review_feedback"]
        Output: state["current_content"] with generated Markdown content
                state["chapter_header_written"] = True  (only on first subsection)

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict with "current_content" and optionally
        "chapter_header_written".
    """
    logger.info("=" * 60)
    logger.info("NODE: Writer - Drafting content")
    logger.info("=" * 60)

    curriculum      = state["curriculum"]
    chap_idx        = state["current_chapter_index"]
    sub_idx         = state["current_subsection_index"]
    review_feedback = state.get("review_feedback", "")

    if review_feedback:
        logger.info(f"Revision requested by Reviewer: '{review_feedback[:80]}...'")

    try:
        # Unified curriculum access — handles both Pydantic CurriculumOutline
        # and plain dict formats for testing/compatibility.
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

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

        # ------------------------------------------------------------------
        # Char target computation:
        #   1. Get (min, max) from section_type defaults via get_char_target()
        #   2. Apply user-configured global floor (min_chars_per_section)
        #   3. Ensure max > min with a meaningful gap (at least +500)
        # ------------------------------------------------------------------
        content_level = state.get("content_level", "Trung Bình")
        base_min, base_max = get_char_target(sec_type, content_level)
        min_chars_floor = state.get("min_chars_per_section", 0)   # type: ignore[call-overload]
        effective_min = max(base_min, min_chars_floor)
        effective_max = max(base_max, effective_min + 500)
        char_target   = (effective_min, effective_max)

        logger.info(
            f"Section type: '{sec_type}' → char target: {effective_min}–{effective_max} chars"
        )

        # Clean section title — strips structured prefixes like "Mục 1.2: ..."
        # using the shared helper from state.py to avoid duplicating the regex.
        sec_title = clean_section_title(sec_title)

        display_chap = str(chap_idx + 1)
        display_sec  = f"{display_chap}.{sub_idx + 1}"

        # ------------------------------------------------------------------
        # Chapter header ownership logic.
        #
        # Uses sub_idx == 0 (integer) instead of display_sec.endswith(".1")
        # to avoid false matches on section numbers like "1.11" or "2.21".
        #
        # emit_header=True  → LLM is instructed to output # CHƯƠNG N as first line
        # emit_header=False → LLM is explicitly prohibited from any # heading
        # ------------------------------------------------------------------
        is_chapter_open      = (sub_idx == 0)
        header_already_written = state.get("chapter_header_written", False)

        if is_chapter_open and not header_already_written:
            chapter_instruction_text = (
                f"This is the opening section of Chapter {display_chap}.\n"
                f"Output EXACTLY this line as the very first line of your response "
                f"(before the ## section header):\n"
                f"# CHƯƠNG {display_chap}: {chap_title.upper()}\n\n"
                f"Then on the next line write: ## {display_sec} {sec_title}"
            )
            emit_header = True
        else:
            chapter_instruction_text = (
                f"This section is NOT the start of a new chapter.\n"
                f"DO NOT output any # (level-1) heading under ANY circumstances.\n"
                f"Your very first line MUST be the ## section header: "
                f"## {display_sec} {sec_title}"
            )
            emit_header = False

        logger.info(
            f"Chapter header: {'EMIT' if emit_header else 'PROHIBITED'} "
            f"(sub_idx={sub_idx}, header_already_written={header_already_written})"
        )

        # RAG context is stored in a dedicated state field (not messages list)
        # to keep it cleanly separated from workflow log messages.
        context      = state.get("rag_context", "") or "No specific context available."
        enable_images = state.get("enable_images", True)   # type: ignore[call-overload]

        agent   = WriterAgent()
        content = agent.write_section(
            course_topic=state.get("request", "General Topic"),
            chapter_num=int(display_chap),
            chapter_title=chap_title,
            section_num=display_sec,
            section_title=sec_title,
            section_description=sec_desc,
            context=context,
            chapter_instruction=chapter_instruction_text,
            review_feedback=review_feedback,
            section_type=sec_type,
            char_target=char_target,
            enable_images=enable_images,
            content_level=content_level,
            
        )

        # ------------------------------------------------------------------
        # Layer 2 — Deterministic hallucination guard (suppress direction).
        #
        # If the LLM was prohibited from emitting a level-1 heading but did so
        # anyway (rare but observed under high token pressure), strip all lines
        # matching `# ...` from the output. This is a safety net — the prompt
        # prohibition in chapter_instruction_text is the primary control.
        # ------------------------------------------------------------------
        if not emit_header:
            before  = content
            content = re.sub(r'^# [^\n]*\n?', '', content, flags=re.MULTILINE)
            content = content.lstrip('\n')
            if content != before:
                logger.warning(
                    f"⚠️  Stripped spurious level-1 heading(s) from {display_sec} "
                    f"— LLM ignored prohibition instruction"
                )

        # ------------------------------------------------------------------
        # Layer 2b — Deterministic chapter heading enforcement (emit direction).
        #
        # Mirror của Layer 2: nếu LLM được instructed emit # CHƯƠNG nhưng bỏ
        # qua (non-compliance dưới token pressure), prepend heading từ các giá
        # trị đã có sẵn — không cần LLM call, không tốn thêm token.
        #
        # Detection dùng re.MULTILINE thay vì startswith() vì LLM đôi khi emit
        # blank line hoặc ký tự lạ trước heading, gây false negative với
        # startswith check.
        # ------------------------------------------------------------------
        if emit_header:
            if not re.search(r'^# CHƯƠNG', content, flags=re.MULTILINE):
                expected_heading = (
                    f"# CHƯƠNG {display_chap}: {chap_title.upper()}"
                )
                content = expected_heading + "\n\n" + content.lstrip('\n')
                logger.warning(
                    f"⚠️  LLM omitted # CHƯƠNG heading — prepended deterministically: "
                    f"'{expected_heading}'"
                )

        # ------------------------------------------------------------------
        # Layer 3 — State flag update.
        #
        # Only set chapter_header_written=True when this call actually emitted
        # the header. Never set it to False here — the checkpoint nodes
        # (append_and_update_chapter) own the reset responsibility.
        # ------------------------------------------------------------------
        result: dict = {"current_content": content}
        if emit_header:
            result["chapter_header_written"] = True

        return result

    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {"current_content": "(Error: Invalid curriculum index)"}

    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {"current_content": "(Error: Malformed curriculum structure)"}

    except Exception as e:
        logger.error(f"Unexpected error in Writer: {e}", exc_info=True)
        return {"current_content": "(Error: Content generation failed)"}