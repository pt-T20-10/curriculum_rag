"""
Writer Agent for AI Textbook Generator.

This agent synthesizes retrieved RAG context into high-quality academic content,
with standard Markdown formatting for PDF compilation via Typst.
"""

import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from src.log_config import setup_logger, setup_prompt_logger
from src.graph.state import AgentState, CurriculumOutline, Chapter, SubSection, get_chapter_and_subsection, get_char_target
from src.config import LLM_MODEL_CHEAP

logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")


class WriterAgent:
    """
    Writer Agent: Generates textbook content from RAG context.

    Specialized in:
    - Academic writing in Vietnamese
    - Markdown formatting for PDF compilation
    - Structured content with proper headers
    - Revision support: accepts feedback from Reviewer for re-drafting
    """

    def __init__(self) -> None:
        """Initialize LLM with balanced creativity."""
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0.4)
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
        enable_images: bool = True
    ) -> str:
        """
        Generate content for a specific section using RAG context.

        Args:
            course_topic: Main topic of the textbook
            chapter_num: Chapter number (1-indexed)
            chapter_title: Title of the current chapter
            section_num: Section number (e.g., "1.2")
            section_title: Title of the current section
            section_description: Description of what to cover
            context: Retrieved RAG context
            chapter_instruction: Explicit directive for chapter header handling.
                Non-empty with "# CHƯƠNG" → emit that heading first.
                Non-empty with "DO NOT" → explicitly prohibited from emitting any # heading.
            review_feedback: Feedback from Reviewer (non-empty means this is a revision)
            section_type: Content purpose — controls tone and depth expectations
            char_target: (min_chars, max_chars) tuple derived from section_type depth level

        Returns:
            Generated Markdown content, or error message on failure.
        """
        logger.info(f"Composing: {section_num} {section_title}")

        if review_feedback:
            logger.info(f"Revision mode — feedback: {review_feedback[:80]}")

        # Build visual rule based on enable_images flag and section type
        LOW_VISUAL_TYPES = ("summary", "practice")
        if not enable_images:
            visual_rule = "Do NOT add any image suggestions."
        elif section_type in LOW_VISUAL_TYPES:
            visual_rule = (
                "Insert an image suggestion only if a diagram is truly essential.\n"
                "Prefer 0 for this section type. Maximum: 1.\n"
                "Format: > [IMAGE: Short caption title | Detailed English description for image generation]"
            )
        else:
            visual_rule = (
                "Insert image suggestions where they genuinely enhance understanding.\n"
                "Aim for 1–3 images per section based on content complexity.\n\n"
                "WHEN to add:\n"
                "- System architecture, flowcharts, process steps, data structures\n"
                "- Scientific diagrams: circuits, biological processes, physics phenomena\n"
                "- Comparisons: before/after, A vs B visual contrast\n"
                "- Spatial structures: layouts, 3D models, hierarchies\n\n"
                "WHEN to skip:\n"
                "- Pure definition paragraphs with no visual component\n"
                "- If a diagram adds no information beyond the surrounding text\n\n"
                "Placement: insert the tag inline immediately AFTER the paragraph it illustrates.\n"
                "Format: > [IMAGE: Short caption title | Detailed English description for image generation]\n\n"
                "IMAGE FORMAT RULES:\n"
                "- TITLE: 3-6 words max, can be Vietnamese or English, used directly as caption in PDF.\n"
                "  Examples: 'Kiến trúc microservices', 'OSI Model layers', 'CI/CD pipeline flow'\n"
                "- DESCRIPTION: 1-3 sentences in English. Include: visual structure (shapes, layout),\n"
                "  key elements (number of components, connections), style (technical, clean, minimal).\n"
                "  For DRAW (abstract/conceptual): describe atmosphere, metaphor, and style.\n"
                "  For SEARCH (real entities): name the specific real-world subject clearly.\n"
                "  Examples:\n"
                "  > [IMAGE: Kiến trúc microservices | System architecture showing 5 independent service\n"
                "    boxes connected via REST arrows, API gateway on left, message queue in center,\n"
                "    each service has a database icon below, white background, clean technical style]\n"
                "  > [IMAGE: DevOps culture | Illustrative scene of collaborative software development\n"
                "    team working seamlessly across dev and ops, conveying speed and reliability]\n"
                "  > [IMAGE: Docker logo | Official Docker whale logo on white background]"
            )

        # Inject revision instruction if this is a re-draft
        revision_instruction = ""
        if review_feedback:
            revision_instruction = f"""<revision_required>
PREVIOUS DRAFT REJECTED. You MUST fix ALL issues below before writing.
FEEDBACK: {review_feedback}
ACTION: Rewrite from scratch. Do NOT repeat previous mistakes.
</revision_required>"""

        # System prompt — XML-structured for strict LLM compliance
        system_prompt = """<role>
You are an expert academic content writer specializing in Vietnamese university textbooks.
Your sole output is the final Markdown content — no preamble, no explanations, no meta-commentary.
</role>

<task_context>
<book_topic>{course_topic}</book_topic>
<chapter num="{chapter_num}">{chapter_title}</chapter>
<section num="{section_num}">{section_title}</section>
<description>{section_description}</description>
<section_type>{section_type}</section_type>
<char_target>{char_min}–{char_max} characters</char_target>
<research_material>
{context}
</research_material>
</task_context>

{revision_instruction}

<rules>

RULE 1 — LANGUAGE:
Write in formal Vietnamese (Tiếng Việt học thuật). Academic, precise, and accessible like a professor teaching.
Do NOT use conversational fillers: "Chúng ta hãy cùng xem...", "Trong phần này tôi sẽ...", "Hãy cùng khám phá...".

RULE 2 — DEPTH LEVEL BEHAVIOR:
Adapt writing depth and length based on the <section_type> value:
- light   → Orient or recap: light technical depth, accessible prose, no exhaustive detail
- medium  → Explain or demonstrate: clear definitions, worked examples, concrete illustrations
- deep    → Analyse or theorise: sustained argument, rigorous detail, explain WHY and HOW fully
- applied → Tasks or exercises: step-by-step guidance, problems with worked solutions
Each paragraph: 3–5 sentences. Output MUST reach the <char_target> minimum.

RULE 3 — CHAPTER HEADER (STRICTLY OBEY):
{chapter_instruction}

RULE 4 — DOCUMENT STRUCTURE (CRITICAL):
Header format rules — apply ALL of them:
- Section header: ## {section_num} {section_title}
- Sub-section header: ### {section_num}.N Title where N starts at 1 (e.g. for ## 1.2, sub-sections are ### 1.2.1 Tiêu đề, ### 1.2.2 Tiêu đề, ...)
- NEVER use unnumbered ### headers — always include the full dot-number prefix (e.g. ### 1.2.1 not ### Tiêu đề)
- NEVER use # (Header 1) unless RULE 3 above explicitly instructs you to output a # CHƯƠNG line
- NEVER double-number: ❌ ## 1.1. Mục 1.1 Tiêu đề → ✅ ## 1.1 Tiêu đề
- NEVER use colon: ❌ ## 1.1: Tiêu đề → ✅ ## 1.1 Tiêu đề

RULE 5 — SUB-SECTION DEPTH (CRITICAL):
Each ### sub-section MUST contain a MINIMUM of 3 substantial paragraphs (each 3–5 sentences).
DO NOT create a ### heading for content that fits in 1–2 paragraphs — fold it into the
preceding sub-section or expand it before promoting to a header.
PREFER FEWER, DEEPER ### blocks over MANY, SHALLOW ones.

Guideline by section_type:
- light   → 2–3 ### blocks max, each 3+ paragraphs
- medium  → 3–4 ### blocks, each 3–5 paragraphs
- deep    → 3–5 ### blocks, each 4–6 paragraphs with analysis, evidence, examples
- applied → 2–4 ### blocks, each containing full worked steps or complete problems

❌ WRONG: 5 sub-sections, each with 1–2 short paragraphs
✅ RIGHT:  3 sub-sections, each with 4–5 thorough paragraphs

CRITICAL — BLANK LINE RULE (PDF will break if you ignore this):
You MUST ALWAYS put a blank line immediately BEFORE and AFTER every heading.
Never write a heading on the line directly following a paragraph — always insert an empty line first.
❌  ...end of paragraph.\n### 2.1.2 Title   ← WRONG
✅  ...end of paragraph.\n\n### 2.1.2 Title   ← CORRECT
Mandatory blank lines — apply to EVERY occurrence:
- Blank line BEFORE every header
- Blank line AFTER every header
- Blank line BETWEEN every paragraph
- Blank line BEFORE and AFTER every list
- Blank line BEFORE and AFTER every code block
- Blank line BEFORE and AFTER every math block

RULE 6 — CONTENT REQUIREMENTS:
- Bold (**term**) — use SPARINGLY. Bold ONLY for the primary concept being formally defined for
  the FIRST time in this section. Do NOT bold: general descriptive words, repeated mentions,
  phrases longer than 4 words, or terms that already appear in a Markdown header.
- Provide at least one concrete, domain-relevant example
- Adapt tone: precise for IT/Engineering, narrative for History/Arts, rigorous for Science
- Code blocks MUST include a language identifier: ```python, ```bash, ```sql
- If research material is thin or irrelevant, use internal knowledge to fill gaps

RULE 7 — VISUALS:
{visual_rule}

</rules>

<output_format>
- Language: Vietnamese (Tiếng Việt)
- Format: raw Markdown — output content directly, NO outer markdown fences
- STRICTLY follow RULE 3 for your first line — no exceptions
- Sub-section headers: ### {section_num}.N Title (numbered sequentially from 1, e.g. ### 1.2.1 Title)
- CRITICAL: Blank line before AND after EVERY header (`#`, `##`, `###`) — no exceptions
- Blank line between EVERY paragraph
- Blank line before AND after EVERY math block ($$ ... $$)
- Character count MUST be within the <char_target> range — write until you reach {char_min} characters minimum
</output_format>"""

        user_prompt = f"Please write the content for section **{section_num}: {section_title}**."

        # Log prompt before invoking LLM
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
            chain = prompt | self.llm
            response = chain.invoke({
                "course_topic": course_topic,
                "chapter_num": chapter_num,
                "chapter_title": chapter_title,
                "section_num": section_num,
                "section_title": section_title,
                "section_description": section_description,
                "context": context,
                "chapter_instruction": chapter_instruction,
                "revision_instruction": revision_instruction,
                "section_type": section_type,
                "char_min": char_target[0],
                "char_max": char_target[1],
                "visual_rule": visual_rule
            })

            raw_content = response.content
            if not isinstance(raw_content, str):
                logger.error(f"LLM returned non-string content: {type(raw_content)}")
                return "(Error: Invalid content type from LLM)"

            content: str = raw_content

            # POST-PROCESSING: Ensure blank lines before headers
            content = re.sub(
                r'([^\n])\n(#{1,3} )',
                r'\1\n\n\2',
                content
            )

            # Ensure blank lines after headers
            content = re.sub(
                r'(^#{1,3} .+)$\n(?!\n)',
                r'\1\n\n',
                content,
                flags=re.MULTILINE
            )

            # Fix paragraphs without blank lines between them
            lines = content.split('\n')
            fixed_lines = []

            for i, line in enumerate(lines):
                fixed_lines.append(line)

                if i < len(lines) - 1:
                    current_line = line.rstrip()
                    next_line = lines[i + 1].strip()

                    if not current_line or not next_line:
                        continue

                    current_is_special = current_line.startswith(('#', '-', '*', '>', '```', '$$'))
                    next_is_special = next_line.startswith(('#', '-', '*', '>', '```', '$$'))

                    if current_is_special or next_is_special:
                        continue

                    if current_line and current_line[-1] in '.!?;:':
                        if next_line[0].isupper() or next_line[0].isdigit():
                            fixed_lines.append('')

            content = '\n'.join(fixed_lines)
            # Post-generation length enforcement
            actual_chars = len(content)
            if actual_chars < char_target[0] * 0.7:
                logger.warning(
                    f"⚠️  Content too short: {actual_chars} chars "
                    f"(target {char_target[0]}–{char_target[1]}) for {section_num} '{section_title}'. "
                    f"Reviewer quality gate will handle revision if needed."
                )
            else:
                logger.info(f"✓ Content length OK: {actual_chars} chars (target {char_target[0]}–{char_target[1]})")
            logger.info(f"✓ Content generated ({len(content)} chars)")
            return content

        except Exception as e:
            logger.error(f"Error generating content: {e}", exc_info=True)
            return "(Error: Unable to generate content for this section. Please check logs.)"


def write_section(state: AgentState) -> dict:
    """
    Writer node: Generate content for current subsection.

    Workflow integration:
    - Input: state["curriculum"], indexes, rag_context, review_feedback
    - Output: state["current_content"] with generated content

    If review_feedback is non-empty, this is a revision pass —
    the Writer will address Reviewer's feedback in the new draft.

    Args:
        state: Current workflow state

    Returns:
        Partial state update with generated content.
    """
    logger.info("=" * 60)
    logger.info("NODE: Writer - Drafting content")
    logger.info("=" * 60)

    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    review_feedback = state.get("review_feedback", "")

    if review_feedback:
        logger.info(f"Revision requested by Reviewer: '{review_feedback[:80]}...'")

    try:
        # Unified curriculum access (Pydantic or dict) via DRY helper
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

        chap_title = chapter.title if isinstance(chapter, Chapter) else chapter.get('title', 'Unknown Chapter')
        sec_title = subsection.title if isinstance(subsection, SubSection) else subsection.get('title', 'Unknown Section')
        sec_desc = subsection.description if isinstance(subsection, SubSection) else subsection.get('description', '')
        sec_type = subsection.section_type if isinstance(subsection, SubSection) else subsection.get('section_type', 'medium')

        # Compute char target: start from section_type defaults, then apply user min floor
        min_chars_floor = state.get("min_chars_per_section", 0)   # type: ignore[call-overload]
        base_min, base_max = get_char_target(sec_type)
        effective_min = max(base_min, min_chars_floor)
        effective_max = max(base_max, effective_min + 500)  # ensure max > min with meaningful gap
        char_target = (effective_min, effective_max)

        logger.info(f"Section type: '{sec_type}' → char target: {effective_min}–{effective_max} chars")

        # Clean section title
        if ":" in sec_title and any(prefix in sec_title for prefix in ["Mục", "Phần", "Bài"]):
            sec_title = sec_title.split(":", 1)[1].strip()

        display_chap = str(chap_idx + 1)
        display_sec = f"{display_chap}.{sub_idx + 1}"

        # Determine whether this subsection is the chapter-open position.
        # Use sub_idx == 0 (integer comparison) instead of string endswith(".1")
        # to avoid false matches on section numbers like "1.11", "2.21", etc.
        is_chapter_open = (sub_idx == 0)
        header_already_written = state.get("chapter_header_written", False)

        # --- LAYER 1: Prompt instruction (tells LLM what to do) ---
        if is_chapter_open and not header_already_written:
            # Positive instruction: emit the chapter heading
            chapter_instruction_text = (
                f"This is the opening section of Chapter {display_chap}.\n"
                f"Output EXACTLY this line as the very first line of your response "
                f"(before the ## section header):\n"
                f"# CHƯƠNG {display_chap}: {chap_title.upper()}\n\n"
                f"Then on the next line write: ## {display_sec} {sec_title}"
            )
            emit_header = True
        else:
            # Explicit prohibition: LLM must not emit any level-1 heading
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

        # Get RAG context from dedicated field (not messages)
        context = state.get("rag_context", "") or "No specific context available."
        enable_images = state.get("enable_images", True)   # type: ignore[call-overload]

        # Generate content (with optional revision feedback)
        agent = WriterAgent()
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
            enable_images=enable_images
        )

        # --- LAYER 2: Deterministic post-processing strip ---
        # If the LLM was prohibited from emitting a level-1 header but did so anyway
        # (hallucination under load), strip ALL `# ` lines from the output.
        if not emit_header:
            before = content
            content = re.sub(r'^# [^\n]*\n?', '', content, flags=re.MULTILINE)
            content = content.lstrip('\n')
            if content != before:
                logger.warning(
                    f"⚠️  Stripped spurious level-1 heading(s) from {display_sec} "
                    f"— LLM ignored prohibition instruction"
                )

        # --- LAYER 3: State flag (gates future subsections in same chapter) ---
        # Only return chapter_header_written=True when we actually emitted the header.
        # Never return False here — let the checkpoint nodes own the reset.
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