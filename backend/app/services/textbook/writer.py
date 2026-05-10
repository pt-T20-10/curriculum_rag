"""
Writer Agent for AI Textbook Generator.

Components in this module:

    ContentWriter           — Generates academic Vietnamese prose using the
                              premium model (gpt-4o). Receives pre-enriched
                              context — no tool calls during writing.
                              Uses section summaries for continuity enforcement.

    ImageDescriptionGenerator — Post-processes written content by replacing
                                [IMAGE_NEEDED: hint] placeholders with fully
                                formatted [IMAGE: Title | Description] tags
                                using gpt-4o-mini in a single batch call.

    WriterAgent             — Orchestrator: sequences ContentWriter and
                              ImageDescriptionGenerator, then applies
                              deterministic post-processing.

    write_section_crag()    — LangGraph node for the CRAG pipeline. Merges
                              web_supplement_context and delegates to WriterAgent.

Context enrichment (EvaluatorAgent) lives in evaluator.py.
"""

import re

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings

OPENAI_API_KEY = settings.OPENAI_API_KEY
LLM_MODEL_PREMIUM = settings.LLM_MODEL_PREMIUM
LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
from app.utils.log_config import setup_logger, setup_prompt_logger
from app.schemas.curriculum import (
    AgentState,
    Chapter,
    SubSection,
    get_chapter_and_subsection,
    get_char_target,
    clean_section_title,
)

logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")


# ============================================================================
# CONSTANTS
# ============================================================================

_SUMMARY_PREVIEW_CHARS: int = settings.WRITER_SUMMARY_PREVIEW_CHARS
_MAX_PRIOR_SUMMARIES:   int = settings.WRITER_MAX_PRIOR_SUMMARIES

# ============================================================================
# LENGTH CALIBRATION
# ============================================================================
_LENGTH_CALIBRATION: dict[str, dict[str, tuple[str, str, str]]] = {
    "light": {
        "Ngắn":       ("1–2", "2–3", "3"),
        "Trung Bình": ("2–3", "3–4", "4–5"),
        "Dài":        ("3",   "4–5", "5"),
        "Rất Dài":    ("3",   "5",   "6"),    # cap at 3 — Rule 6 max for light
    },
    "medium": {
        "Ngắn":       ("2–3", "3",   "3–4"),
        "Trung Bình": ("3–4", "4",   "5"),
        "Dài":        ("3–4", "5–6", "6"),    # was "4–5" — cap at 4, Rule 6 max
        "Rất Dài":    ("4",   "6–7", "7"),    # was "5–6" — cap at 4
    },
    "deep": {
        "Ngắn":       ("3",   "3–4", "4"),
        "Trung Bình": ("3–4", "5",   "5–6"),
        "Dài":        ("4–5", "6",   "6–7"),  # was "5–6" — cap at 5, Rule 6 max
        "Rất Dài":    ("5",   "7–8", "7–8"),  # was "6–7" — cap at 5
    },
    "applied": {                               # unchanged
        "Ngắn":       ("2",   "brief worked steps",                        ""),
        "Trung Bình": ("3",   "full worked steps",                         ""),
        "Dài":        ("3–4", "detailed worked steps",                     ""),
        "Rất Dài":    ("4",   "comprehensive worked examples with edge cases", ""),
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

    Args:
        section_type:  One of 'light' | 'medium' | 'deep' | 'applied'.
        content_level: One of 'Ngắn' | 'Trung Bình' | 'Dài' | 'Rất Dài'.
        char_min:      Minimum character target for this section.
        char_max:      Maximum character target for this section.

    Returns:
        Formatted RULE 2.5 string for injection into system prompt.
    """
    level_key = content_level if content_level in _LENGTH_CALIBRATION.get(
        section_type, {}
    ) else "Trung Bình"
    type_key  = section_type if section_type in _LENGTH_CALIBRATION else "medium"
    blocks, paras, sents = _LENGTH_CALIBRATION[type_key][level_key]

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
        f"CRITICAL — HOW to reach the character target:\n"
        f"Write DEEPER within each ### block — more paragraphs, richer analysis,\n"
        f"concrete examples, worked illustrations. Do NOT add extra ### blocks.\n"
        f"Rule 6 sets the ### block ceiling. This rule sets the depth inside each block.\n"
        f"If short: expand the shallowest ### block with additional explanation or example.\n\n"
        f"Self-check before finishing: mentally estimate your paragraph count.\n"
        f"If you have not reached {char_min} characters, continue writing —\n"
        f"add more depth to existing blocks. Do NOT stop early."
    )


def _build_prior_summary_block(
    section_summaries: list[str],
    max_entries: int = _MAX_PRIOR_SUMMARIES,
) -> str:
    """
    Build a formatted prior-content summary block for prompt injection.

    Limits entries to `max_entries` most recent summaries to avoid
    token bloat on long textbooks.

    Args:
        section_summaries: Ordered list of completed section summaries.
        max_entries:       Maximum number of summaries to include.

    Returns:
        Formatted string for injection, or "" if no history exists.
    """
    if not section_summaries:
        return ""

    recent = section_summaries[-max_entries:]
    lines  = ["[PRIOR SECTIONS — do not repeat these topics]"]
    lines += [f"- {s}" for s in recent]
    lines += ["[/PRIOR SECTIONS]"]
    return "\n".join(lines)


# ============================================================================
# COMPONENT 1 — Content Writer
# ============================================================================

class ContentWriter:
    """
    Academic content generation component using the premium LLM.

    Responsibilities:
    - Generate Vietnamese academic prose from pre-enriched context.
    - Enforce structural rules (headers, blank lines, section depth).
    - Inject [IMAGE_NEEDED: hint] placeholders where images are appropriate.
    - Use prior section summaries for continuity (no repetition).
    - No tool calls — receives fully prepared context from ContextRetrievalAgent.

    Premium model is used here exclusively because output quality directly
    determines the textbook content quality.
    """

    _VISUAL_RULES: dict[str, str] = {
    "disabled": "Do NOT add any image suggestions.",

    "light": (
        "This is an orientation or recap section.\n"
        "Insert AT MOST 1 image placeholder, only if it significantly aids understanding.\n"
        "Format: > [IMAGE_NEEDED: <1-line Vietnamese hint>]\n"
        "Do NOT write English descriptions here."
    ),

    "applied": (
        "This is a hands-on section with step-by-step instructions.\n"
        "Insert 1 image placeholder per major step that has a visible physical outcome.\n"
        "Maximum 3 placeholders total — prefer fewer, higher-quality images over many generic ones.\n"
        "Format: > [IMAGE_NEEDED: <1-line Vietnamese hint>]\n"
        "Do NOT write English descriptions here."
    ),

    "default": (
        "Insert image placeholders where they genuinely aid understanding.\n"
        "QUALITY OVER QUANTITY — follow these rules strictly:\n\n"
        "INSERT after a paragraph when:\n"
        "- A physical process, pose, or technique is described step-by-step\n"
        "- A real-world object or entity is introduced for the first time\n"
        "- A comparison or before/after scenario is discussed\n"
        "- A system or structure with multiple components is explained\n\n"
        "DO NOT INSERT when:\n"
        "- The paragraph is abstract theory or pure definition\n"
        "- The same subject was already illustrated in a previous image\n"
        "- The paragraph is a summary or transition\n\n"
        "Target: 2–3 images per section. Never exceed 4.\n"
        "Format: > [IMAGE_NEEDED: <1-line Vietnamese hint>]\n"
        "Do NOT write English descriptions here."
    ),
}

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            model=LLM_MODEL_PREMIUM,
            api_key=OPENAI_API_KEY, #type: ignore
            temperature=0.4,
        )
        self._prompt_logger = setup_prompt_logger("writer")

    def _get_visual_rule(self, section_type: str, enable_images: bool) -> str:
        """Return the appropriate visual placeholder rule for this section."""
        if not enable_images:
            return self._VISUAL_RULES["disabled"]
        if section_type == "light":
            return self._VISUAL_RULES["light"]
        if section_type == "applied":
            return self._VISUAL_RULES["applied"]
        return self._VISUAL_RULES["default"]

    def generate(
        self,
        course_topic: str,
        chapter_num: int,
        chapter_title: str,
        section_num: str,
        section_title: str,
        section_description: str,
        enriched_context: str,
        chapter_instruction: str,
        section_type: str,
        char_target: tuple[int, int],
        content_level: str,
        enable_images: bool,
        review_feedback: str,
        section_summaries: list[str],
    ) -> str:
        """
        Generate academic content for a single textbook section.

        Args:
            course_topic:        Main textbook topic.
            chapter_num:         1-indexed chapter number.
            chapter_title:       Title of the current chapter.
            section_num:         Dot-notation section number (e.g. "2.3").
            section_title:       Title of the current section.
            section_description: What this section should cover.
            enriched_context:    Pre-fetched and enriched RAG context.
            chapter_instruction: # CHƯƠNG header emit/suppress directive.
            section_type:        Depth level ('light'|'medium'|'deep'|'applied').
            char_target:         (min_chars, max_chars) tuple.
            content_level:       User-configured length level.
            enable_images:       Whether to insert image placeholders.
            review_feedback:     Non-empty → revision mode.
            section_summaries:   Summaries of previously written sections.

        Returns:
            Generated Markdown string with [IMAGE_NEEDED: ...] placeholders.
        """
        char_min, char_max = char_target
        length_rule   = _build_length_rule(section_type, content_level, char_min, char_max)
        visual_rule   = self._get_visual_rule(section_type, enable_images)
        prior_block   = _build_prior_summary_block(section_summaries)

        revision_block = ""
        if review_feedback:
            revision_block = (
                "<revision_required>\n"
                "PREVIOUS DRAFT REJECTED. Fix ALL issues below before writing.\n"
                f"FEEDBACK: {review_feedback}\n"
                "ACTION: Rewrite from scratch. Do NOT repeat previous mistakes.\n"
                "</revision_required>"
            )

        system_prompt = f"""
[CONTEXT]
You are a neutral academic writing specialist producing content for an educational
platform covering all learning domains. Adapt tone to subject domain.
Output only the final Markdown content — no preamble, no explanations.
[/CONTEXT]

[TASK]
Write content for the following textbook section.

<book_topic>{course_topic}</book_topic>
<chapter num="{chapter_num}">{chapter_title}</chapter>
<section num="{section_num}">{section_title}</section>
<description>{section_description}</description>
<section_type>{section_type}</section_type>
<char_target>{char_min}–{char_max} characters</char_target>
<research_material>
{enriched_context}
</research_material>

{prior_block}
[/TASK]

{revision_block}

[CRITERION]
CONTINUITY — build on prior sections:
- Do NOT re-introduce or redefine concepts already covered in [PRIOR SECTIONS].
- Reference prior concepts with "như đã trình bày ở mục X.Y" when relevant.
- Assume the reader has read all prior sections.

Adapt depth to section_type:
- light   → Orient/recap: accessible prose, light technical depth
- medium  → Explain/demonstrate: definitions, worked examples
- deep    → Analyse/theorise: sustained argument, rigorous detail
- applied → Tasks/exercises: step-by-step guidance, worked solutions

{length_rule}

Sub-section depth:
- Each ### block: minimum 4–6 substantial paragraphs (4–6 sentences each).
- light → 1–2 ### blocks; medium → 2–3; deep → 3–4; applied → 2–3.
- PREFER fewer, deeper blocks over many shallow ones.

Content standards:
- Formal Vietnamese (Tiếng Việt học thuật). No conversational fillers.
- Adapt tone: precise for IT/Engineering, narrative for History/Arts.
- Bold (**term**) ONLY for the primary concept defined for the first time.
- At least one concrete, domain-relevant example per section.
- Code blocks must include language identifier: ```python, ```bash, etc.
[/CRITERION]

[CONSTRAINT]
Rule 1 — CHAPTER HEADER (non-negotiable):
{chapter_instruction}

Rule 2 — DOCUMENT STRUCTURE:
- Section header: ## {section_num} {section_title}
- Sub-section: ### {section_num}.N Title (N starts at 1)
- NEVER use unnumbered ### headers
- NEVER use # unless Rule 1 explicitly instructs it
- NEVER double-number: ❌ ## 1.1. Mục 1.1 → ✅ ## 1.1 Tiêu đề
- NEVER use colon after number: ❌ ## 1.1: → ✅ ## 1.1

Rule 3 — BLANK LINES (PDF will break if violated):
Blank line BEFORE and AFTER: every heading, every paragraph, every list,
every code block, every math block. Zero exceptions.

Rule 4 — No ### heading for content that fits in 1–2 paragraphs.

Rule 5 — Do NOT create a '### Kết luận' or '### Conclusion' subsection.\n"
Concluding thoughts must be woven into the last paragraph of the final ### block.\n"
A dedicated conclusion sub-heading is redundant and breaks academic prose flow."

Rule 6 — SUB-SECTION COUNT PER DEPTH LEVEL (STRICT CEILING):
- light   → maximum 2 ### blocks
- medium  → maximum 3 ### blocks
- deep    → maximum 4 ### blocks
- applied → maximum 3 ### blocks

CRITICAL — MERGE OVER SPLIT:
If you have more sub-topics than the limit above, MERGE related topics
into the same ### block. Write DEEPER within each block — more paragraphs,
richer analysis, concrete examples — instead of creating more ### headings.

Each ### block must contain at least 4–6 substantial paragraphs.
Do NOT create a ### heading for content shorter than 4 paragraphs.

PREFER: Fewer ### blocks with rich, flowing prose inside each block.
AVOID: Many ### blocks with thin content (1-2 paragraphs each).

Rule 7 — EXAMPLE STRUCTURE:
GOOD (medium section with 2 ### blocks):
  ### 1.1.1 Định nghĩa và nguồn gốc
  [5-6 paragraphs of deep explanation with examples]
  
  ### 1.1.2 Ứng dụng trong thực tế
  [5-6 paragraphs of practical analysis]

BAD (medium section with 4 ### blocks):
  ### 1.1.1 Định nghĩa
  [2 paragraphs — TOO THIN]
  
  ### 1.1.2 Nguồn gốc
  [2 paragraphs — TOO THIN]
  
  ### 1.1.3 Đặc điểm
  [2 paragraphs — TOO THIN]
  
  ### 1.1.4 Ứng dụng
  [2 paragraphs — TOO THIN]

The BAD example splits content unnecessarily. Merge 1.1.1 + 1.1.2 into one
rich ### block, merge 1.1.3 + 1.1.4 into another.
[/CONSTRAINT]

[FORMAT]
- Language: Vietnamese
- Output: raw Markdown — NO outer fences
- First line: strictly follow Rule 1
- Character count MUST reach {char_min} minimum

{visual_rule}
[/FORMAT]"""

        user_prompt = f"Write section **{section_num}: {section_title}**."

        # Log prompt (context truncated to avoid bloat)
        try:
            self._prompt_logger.log(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_label=f"{section_num} {section_title} "
                              f"[{'REVISION' if review_feedback else 'DRAFT'}]",
            )
        except Exception as e:
            logger.warning(f"Prompt logging failed: {e}")

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = self._llm.invoke(messages)
        return str(response.content)


# ============================================================================
# COMPONENT 3 — Image Description Generator
# ============================================================================

class ImageDescriptionGenerator:
    """
    Post-processing component that replaces image placeholders with
    fully formatted image tags containing English descriptions.

    Responsibilities:
    - Find all [IMAGE_NEEDED: hint] placeholders in generated content.
    - Batch-generate English visual descriptions using gpt-4o-mini.
    - Replace placeholders with [IMAGE: Title | Description] tags.

    Uses gpt-4o-mini because description generation is a focused,
    low-complexity task that does not require premium model capability.
    Processes ALL placeholders in a section in a single API call to
    minimise latency and cost.
    """

    _SYSTEM_PROMPT = """You are a visual art director writing image generation prompts
for an educational textbook.

For each Vietnamese hint provided, write a fully formatted image tag.

Output format (one per line, same order as input):
[IMAGE: <Vietnamese title 3-6 words> | <English description 2-3 sentences>]

English description rules:
- Describe shapes, composition, key visual elements, mood, and atmosphere.
- Be specific: "five service nodes connected by arrows" not "a diagram".
- For abstract concepts: describe the metaphor and visual composition.
- For real entities: name the subject and describe the scene clearly.
- CRITICAL: Do NOT mention text, labels, captions, or written words as
  visual elements — they render literally and appear garbled in images.
- Do NOT over-constrain style (avoid "white background", "clean technical").

Return ONLY the formatted [IMAGE: ...] tags, one per line. No commentary."""

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            model=LLM_MODEL_CHEAP,
            api_key=OPENAI_API_KEY, #type: ignore
            temperature=0.3,
        )

    def process(self, content: str, course_topic: str, section_title: str) -> str:
        """
        Replace all [IMAGE_NEEDED: hint] placeholders with formatted image tags.

        If no placeholders are present, returns content unchanged.
        On any LLM error, returns content with placeholders left as-is
        rather than failing the entire section.

        Args:
            content:       Section Markdown containing [IMAGE_NEEDED: ...] tags.
            course_topic:  Textbook topic — provides visual context.
            section_title: Current section title — provides visual context.

        Returns:
            Content with all placeholders replaced by [IMAGE: ...] tags.
        """
        placeholders = re.findall(r'\[IMAGE_NEEDED: ([^\]]+)\]', content)
        if not placeholders:
            return content

        hints_text = "\n".join(
            f"{i + 1}. {hint}" for i, hint in enumerate(placeholders)
        )
        user_prompt = (
            f"Textbook topic: {course_topic}\n"
            f"Section: {section_title}\n\n"
            f"Hints:\n{hints_text}"
        )

        try:
            response = self._llm.invoke([
                SystemMessage(content=self._SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])

            generated_tags = [
                line.strip()
                for line in str(response.content).split('\n')
                if line.strip().startswith('[IMAGE:')
            ]

            result = content
            for i, hint in enumerate(placeholders):
                if i < len(generated_tags):
                    result = result.replace(
                        f'[IMAGE_NEEDED: {hint}]',
                        f'> {generated_tags[i]}',
                        1,
                    )
                else:
                    logger.warning(
                        f"Missing image tag for placeholder {i + 1}: '{hint[:50]}'"
                    )

            logger.info(f"✓ Image descriptions generated: {len(generated_tags)} tags")
            return result

        except Exception as e:
            logger.error(f"Image description generation failed: {e}", exc_info=True)
            return content  # Graceful fallback — placeholders remain


# ============================================================================
# ORCHESTRATOR — Writer Agent
# ============================================================================

class WriterAgent:
    """
    Orchestrator that sequences the three writing components.

    Pipeline per section:
        1. ContextRetrievalAgent  — enrich RAG context (gpt-4o-mini + tools)
        2. ContentWriter          — generate prose    (gpt-5.4-mini / gpt-4o)
        3. ImageDescriptionGenerator — fill image tags (gpt-4o-mini, if images enabled)

    Also applies deterministic post-processing (blank line enforcement,
    chapter header compliance) after content generation.
    """

    def __init__(self) -> None:
        self._writer      = ContentWriter()
        self._illustrator = ImageDescriptionGenerator()

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
        section_type: str       = "medium",
        char_target: tuple[int, int] = (3000, 4500),
        content_level: str      = "Trung Bình",
        enable_images: bool     = True,
        review_feedback: str    = "",
        section_summaries: list[str] = (), #type: ignore
        used_queries: list[str]  = [], #type: ignore
        
    ) -> str:
        """
        Generate or revise content for a single textbook section.

        Sequences ContextRetrievalAgent → ContentWriter →
        ImageDescriptionGenerator, then applies post-processing.

        Args:
            course_topic:        Main textbook topic.
            chapter_num:         1-indexed chapter number.
            chapter_title:       Title of the current chapter.
            section_num:         Dot-notation section number (e.g. "1.2").
            section_title:       Title of the current section.
            section_description: What this section should cover.
            context:             Initial RAG context from Researcher node.
            chapter_instruction: # CHƯƠNG header emit/suppress directive.
            section_type:        Depth level.
            char_target:         (min_chars, max_chars) tuple.
            content_level:       User-configured length level.
            enable_images:       Whether to insert image placeholders.
            review_feedback:     Non-empty → revision mode.
            section_summaries:   Summaries of previously written sections.

        Returns:
            Post-processed Markdown string ready for the Reviewer node.
        """
        logger.info(f"Composing: {section_num} {section_title}")
        if review_feedback:
            logger.info(f"Revision mode — feedback: {review_feedback[:80]}")

        # ------------------------------------------------------------------
        # Step 1: Context already enriched by ContextEvaluator upstream (CRAG)
        # ------------------------------------------------------------------
        enriched_context = context

        # ------------------------------------------------------------------
        # Step 2: Generate content (premium model, no tools)
        # ------------------------------------------------------------------
        content = self._writer.generate(
            course_topic=course_topic,
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            section_num=section_num,
            section_title=section_title,
            section_description=section_description,
            enriched_context=enriched_context,
            chapter_instruction=chapter_instruction,
            section_type=section_type,
            char_target=char_target,
            content_level=content_level,
            enable_images=enable_images,
            review_feedback=review_feedback,
            section_summaries=list(section_summaries),
        )

        if not isinstance(content, str):
            logger.error(f"Writer returned non-string: {type(content)}")
            return "(Error: Invalid content type from LLM)"

        # ------------------------------------------------------------------
        # Step 3: Generate image descriptions (cheap model, if enabled)
        # ------------------------------------------------------------------
        if enable_images and "[IMAGE_NEEDED:" in content:
            content = self._illustrator.process(
                content=content,
                course_topic=course_topic,
                section_title=section_title,
            )

        # ------------------------------------------------------------------
        # Post-processing: deterministic blank line enforcement
        # ------------------------------------------------------------------
        content = self._fix_blank_lines(content)

        # Length check
        actual_chars = len(content)
        if actual_chars < char_target[0] * 0.95:
            logger.warning(
                f"⚠️  Content short: {actual_chars} chars "
                f"(target {char_target[0]}–{char_target[1]}) — "
                f"Reviewer gate will handle revision if needed."
            )
        else:
            logger.info(
                f"✓ Content length OK: {actual_chars} chars "
                f"(target {char_target[0]}–{char_target[1]})"
            )

        return content

    @staticmethod
    def _fix_blank_lines(content: str) -> str:
        """
        Deterministic post-processing: enforce blank lines around Markdown
        structural elements that the LLM sometimes violates under token pressure.

        Pass 1: Blank line before headings.
        Pass 2: Blank line after headings.
        Pass 3: Blank line between prose paragraphs.

        Args:
            content: Raw LLM-generated Markdown string.

        Returns:
            Content with blank line compliance enforced.
        """
        # Pass 1 — blank line before headings
        content = re.sub(r'([^\n])\n(#{1,3} )', r'\1\n\n\2', content)

        # Pass 2 — blank line after headings
        content = re.sub(
            r'(^#{1,3} .+)$\n(?!\n)',
            r'\1\n\n',
            content,
            flags=re.MULTILINE,
        )

        # Pass 3 — blank line between prose paragraphs
        _SPECIAL = ('#', '-', '*', '>', '```', '$$')
        lines      = content.split('\n')
        fixed: list[str] = []

        for i, line in enumerate(lines):
            fixed.append(line)
            if i >= len(lines) - 1:
                continue

            cur  = line.rstrip()
            nxt  = lines[i + 1].strip()

            if not cur or not nxt:
                continue
            if cur.startswith(_SPECIAL) or nxt.startswith(_SPECIAL):
                continue
            if cur[-1] in '.!?;:' and (nxt[0].isupper() or nxt[0].isdigit()):
                fixed.append('')

        return '\n'.join(fixed)


# ============================================================================
# HELPERS
# ============================================================================

def extract_section_summary(
    content: str,
    section_num: str,
    section_title: str,
) -> str:
    """
    Extract a one-line summary from a completed section for continuity tracking.

    Strips Markdown headers and takes the first meaningful prose sentence
    as a compact summary. Stored in state.section_summaries.

    Args:
        content:       Approved Markdown content for the section.
        section_num:   Dot-notation section number (e.g. "1.2").
        section_title: Section title.

    Returns:
        Summary string: "Mục X.Y 'Title': <prose preview>..."
    """
    prose_lines = [
        line.strip()
        for line in content.split('\n')
        if line.strip() and not line.startswith('#') and not line.startswith('>')
    ]
    preview = ' '.join(prose_lines)[:_SUMMARY_PREVIEW_CHARS]
    return f"Mục {section_num} '{section_title}': {preview}..."


# ============================================================================
# CRAG Node — write_section_crag
# ============================================================================

def write_section_crag(state: AgentState) -> dict:
    """
    ContentWriter CRAG node: generate section content using pre-enriched context.

    Context has already been retrieved and enriched by the upstream CRAG nodes
    (RetrieverNode + ContextEvaluator). This node's sole responsibility is to
    call WriterAgent with the final merged context and handle CRAG-specific
    state fields (web_supplement_context, rejection_type).

    CRAG-specific additions vs the legacy write_section() node:
        1. Merges state["web_supplement_context"] into rag_context before writing.
        2. Injects [FORMATTING FIX REQUIRED] prefix when rejection_type == 'formatting_error'
           so WriterAgent focuses on structure, not on fetching new content.

    Args:
        state: Current LangGraph workflow state.

    Returns:
        Partial state update dict.
    """
    logger.info("=" * 60)
    logger.info("NODE: ContentWriter (CRAG) - Drafting content")
    logger.info("=" * 60)

    curriculum        = state["curriculum"]
    chap_idx          = state["current_chapter_index"]
    sub_idx           = state["current_subsection_index"]
    review_feedback   = state.get("review_feedback", "")
    section_summaries = state.get("section_summaries", [])

    # ------------------------------------------------------------------
    # CRAG addition: inject formatting-fix prefix on formatting_error
    # ------------------------------------------------------------------
    rejection_type = state.get("rejection_type", None)
    if rejection_type == "formatting_error" and review_feedback:
        review_feedback = (
            "[FORMATTING FIX REQUIRED — content knowledge is correct, "
            "fix structure/format only]\n" + review_feedback
        )
        logger.info("Revision requested (formatting fix): injecting prefix")
    elif review_feedback:
        logger.info(f"Revision requested: '{review_feedback[:80]}...'")

    try:
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

        content_level   = state.get("content_level", "Trung Bình")
        base_min, base_max = get_char_target(sec_type, content_level)
        min_chars_floor = state.get("min_chars_per_section", 0)
        effective_min   = max(base_min, min_chars_floor)
        effective_max   = max(base_max, effective_min + 500)
        char_target     = (effective_min, effective_max)
        used_queries    = state.get("used_rag_queries", [])

        sec_title    = clean_section_title(sec_title)
        display_chap = str(chap_idx + 1)
        display_sec  = f"{display_chap}.{sub_idx + 1}"

        is_chapter_open        = (sub_idx == 0)
        header_already_written = state.get("chapter_header_written", False)

        if is_chapter_open and not header_already_written:
            chapter_instruction_text = (
                f"This is the opening section of Chapter {display_chap}.\n"
                f"Output EXACTLY this line as the very first line "
                f"(before the ## section header):\n"
                f"# CHƯƠNG {display_chap}: {chap_title.upper()}\n\n"
                f"Then on the next line write: ## {display_sec} {sec_title}"
            )
            emit_header = True
        else:
            chapter_instruction_text = (
                f"This section is NOT the start of a new chapter.\n"
                f"DO NOT output any # (level-1) heading under ANY circumstances.\n"
                f"Your very first line MUST be: ## {display_sec} {sec_title}"
            )
            emit_header = False

        logger.info(
            f"Chapter header: {'EMIT' if emit_header else 'PROHIBITED'} "
            f"(sub_idx={sub_idx}, header_written={header_already_written})"
        )

        # ------------------------------------------------------------------
        # CRAG addition: merge web supplement context
        # ------------------------------------------------------------------
        context    = state.get("rag_context", "") or "No specific context available."
        supplement = state.get("web_supplement_context", "")
        if supplement:
            context = context + "\n\n---\n\n" + supplement

        enable_images = state.get("enable_images", True)

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
            section_type=sec_type,
            char_target=char_target,
            content_level=content_level,
            enable_images=enable_images,
            review_feedback=review_feedback,
            section_summaries=section_summaries,
            used_queries=used_queries,
        )

        # Layer 2 — Suppress spurious level-1 headings
        if not emit_header:
            before  = content
            content = re.sub(r'^# [^\n]*\n?', '', content, flags=re.MULTILINE)
            content = content.lstrip('\n')
            if content != before:
                logger.warning(
                    f"⚠️  Stripped spurious # heading from {display_sec}"
                )

        # Layer 2b — Enforce missing # CHƯƠNG heading
        if emit_header and not re.search(r'^# CHƯƠNG', content, flags=re.MULTILINE):
            expected = f"# CHƯƠNG {display_chap}: {chap_title.upper()}"
            content  = expected + "\n\n" + content.lstrip('\n')
            logger.warning(f"⚠️  Prepended missing # CHƯƠNG: '{expected}'")

        # Layer 2c — Normalize chapter title text to uppercase
        if emit_header:
            content = re.sub(
                r'^(# CHƯƠNG [^:]+: )(.+)$',
                lambda m: m.group(1) + m.group(2).upper(),
                content,
                flags=re.MULTILINE,
                count=1,
            )

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
        logger.error(f"Unexpected error in ContentWriter: {e}", exc_info=True)
        return {"current_content": "(Error: Content generation failed)"}
