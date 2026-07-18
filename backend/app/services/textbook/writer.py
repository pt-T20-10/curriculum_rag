"""
Writer Agent for AI Textbook Generator.

Components in this module:

    ContentWriter           — Generates academic Vietnamese prose using the
                              premium model (gpt-4o). Receives pre-enriched
                              context — no tool calls during writing.
                              Uses section summaries for continuity enforcement.

    WriterAgent             — Orchestrator: sequences ContentWriter and
                              deterministic post-processing.
                              deterministic post-processing.

    write_section_crag()    — LangGraph node for the CRAG pipeline. Merges
                              web_supplement_context and delegates to WriterAgent.

Context enrichment (EvaluatorAgent) lives in evaluator.py.
"""

import re

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings
from app.services.api_rate_limiter import rate_limited_invoke
from app.services.runtime_config import get_api_key, get_runtime_config
from app.services.textbook.language import get_language_profile

LLM_MODEL_PREMIUM = settings.LLM_MODEL_PREMIUM

from app.utils.log_config import setup_logger, setup_prompt_logger
from app.schemas.curriculum import (
    AgentState,
    Chapter,
    SubSection,
    get_chapter_and_subsection,
    get_section_location,
    get_char_target,
    clean_section_title,
)

logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")


def _is_practice_mode(textbook_mode: str | None) -> bool:
    return str(textbook_mode or "standard").strip().lower() == "practice"


# ============================================================================
# CONSTANTS
# ============================================================================

_SUMMARY_PREVIEW_CHARS: int = settings.WRITER_SUMMARY_PREVIEW_CHARS
_MAX_PRIOR_SUMMARIES:   int = settings.WRITER_MAX_PRIOR_SUMMARIES

# ============================================================================
# HK PEDAGOGY HINTS — System Alignment (Task 0)
# Source: Guiding Principles for Quality Textbooks, HKSAR EDB, June 2016.
# Strategy: B+C — dynamic per-section_type hint (≤6 lines) injected at the
# tail of [CRITERION]. Keeps token overhead minimal while targeting the
# principles most relevant to each depth level.
# ============================================================================

def _page_budget_mode(target_pages: int | None, char_target: tuple[int, int] | None = None) -> str:
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
    if char_target and char_target[1] <= 2600:
        return "compact"
    return "standard"


def _get_hk_hint(section_type: str, page_budget_mode: str = "standard") -> str:
    """
    Return a concise HK pedagogy nudge tailored to the section's depth level.

    Mapped principles (HK Guiding Principles, 2016):
        light   → L/T-5 CONNECT + S/O-3 orientation opening
        medium  → L/T-5 full CORE cycle + L-1 define-in-context
        deep    → L/T-2 higher-order thinking (analysis/evaluation/synthesis)
        applied → L/T-5 EXTEND + L/T-9 reflective closure

    Args:
        section_type: One of 'light' | 'medium' | 'deep' | 'applied'.

    Returns:
        A 2–6 line pedagogical hint string for prompt injection.
    """
    if page_budget_mode == "compact":
        return (
            "Pedagogy (COMPACT): Connect briefly, organise only the core ideas, "
            "and avoid padding. Prefer compact academic prose; use a short list "
            "only for a genuine enumeration, workflow, formula explanation, or "
            "comparison. Do not add reflection or real-world transfer unless it "
            "is clearly valuable for this exact section."
        )

    hints: dict[str, str] = {
        "light": (
            "Pedagogy (CONNECT + ORIENT): Open by activating prior knowledge "
            "(analogy or back-reference). First paragraph = 2–3 sentence orientation "
            "of what this section covers and why it matters here."
        ),
        "medium": (
            "Pedagogy (CORE cycle): "
            "CONNECT → open with prior-knowledge hook or analogy. "
            "ORGANISE → build new concepts incrementally on established ones. "
            "REFLECT → weave a key takeaway or compare/contrast insight into prose when useful. "
            "EXTEND → close by transferring knowledge to a real-world context. "
            "Define every new term in context on first use — never in isolation."
        ),
        "deep": (
            "Pedagogy (HIGHER-ORDER THINKING): Prohibit bare fact-listing. "
            "ANALYSE trade-offs and component differences explicitly. "
            "EVALUATE conditions under which the concept applies or fails. "
            "SYNTHESISE how multiple ideas combine — explain WHY and HOW, not just WHAT."
        ),
        "applied": (
            "Pedagogy (EXTEND + REFLECT): Each worked step must state its purpose "
            "(why this step, not just what to do). "
            "Close the section with a reflective synthesis paragraph — "
            "what the learner can now do and how this skill connects forward."
        ),
    }
    return hints.get(section_type, hints["medium"])

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
    page_budget_mode: str = "standard",
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
            f"- applied  (~{char_min}-{char_max} chars): "
            f"{blocks} ### blocks with {paras}"
        )
    else:
        calibration_line = (
            f"- {type_key:<8} (~{char_min}-{char_max} chars): "
            f"{blocks} ### blocks, with about {paras} cohesive paragraph groups; "
            f"most body paragraphs should fully develop an idea across {sents}+ sentences"
        )

    if page_budget_mode == "compact":
        return (
            f"RULE 2.5 — LENGTH TARGET (COMPACT PAGE BUDGET):\n"
            f"Target range: {char_min}-{char_max} characters. Reach the core ideas "
            f"without padding; aim for the lower-to-middle part of this range when "
            f"the section is conceptual or introductory.\n\n"
            f"Calibration for this compact section ({section_type} / {content_level}):\n"
            f"- Write directly under the ## section heading when possible.\n"
            f"- Do not create a lone ### block. Use no ### by default.\n"
            f"- Prefer cohesive prose over note-like fragments.\n"
            f"- Use bullets/tables only for true enumerations, workflows, variables, comparisons, or practice tasks.\n\n"
            f"If short: add one precise explanation or short example that improves learning.\n"
            f"If long: remove repeated framing, routine summaries, unnecessary real-world "
            f"applications, and reflective commentary before adding more content."
        )

    return (
        f"RULE 2.5 — LENGTH TARGET (NON-NEGOTIABLE FLOOR, SOFT CEILING):\n"
        f"Your output MUST contain at least {char_min} characters. "
        f"This is a hard floor — do NOT stop before reaching it.\n"
        f"Target ceiling: keep the section at or below {char_max} characters "
        f"unless a required example or explanation genuinely needs more space.\n\n"
        f"Calibration for this section ({section_type} / {content_level}):\n"
        f"{calibration_line}\n\n"
        f"CRITICAL — HOW to reach the character target:\n"
        f"Write DEEPER within each ### block — richer analysis, concrete examples,\n"
        f"worked illustrations, and fuller paragraphs. Do NOT add extra ### blocks.\n"
        f"Rule 6 sets the ### block ceiling. This rule sets the depth inside each block.\n"
        f"If short: expand the shallowest ### block by deepening existing paragraphs "
        f"or adding one substantial paragraph where the idea genuinely needs it.\n"
        f"If long: condense repetition, merge overlapping sentences, and keep the "
        f"same heading structure rather than deleting essential examples.\n\n"
        f"Self-check before finishing: mentally estimate flow and character count.\n"
        f"If you have not reached {char_min} characters, continue writing —\n"
        f"add more depth to existing blocks. If you are above {char_max}, tighten "
        f"wording and remove redundancy. Do NOT create many short paragraphs."
    )


def _build_expansion_rule(
    *,
    layout_profile: str | None,
    formula_density: str | None,
    expansion_strategy: str | None,
    target_pages: int | None,
    page_budget_mode: str = "standard",
    language: str,
) -> str:
    density = str(formula_density or "none")
    strategy = str(expansion_strategy or "")
    profile = str(layout_profile or "prose")
    page_note = (
        f"This section has a target of about {target_pages} content page(s)."
        if target_pages
        else "This section has a page-budget target."
    )
    lines = [
        "RULE 2.6 — PAGE-BUDGET EXPANSION STRATEGY:",
        page_note,
        f"Layout profile: {profile}. Expansion strategy: {strategy or 'structured academic support'}.",
        (
            "For compact sections, use only the structured element that genuinely helps; "
            "for longer sections, prefer relevant structured learning elements over simply stretching prose."
            if page_budget_mode == "compact"
            else "Prefer relevant structured learning elements over simply stretching prose."
        ),
    ]

    if density in {"contextual", "high"}:
        lines.extend([
            "Because formula/structured tools are preferred, include them when they genuinely fit the subject:",
            "- quantitative subjects: formulas, variables, derivations, and worked calculations;",
            "- technical or management subjects: metrics, simple models, rubrics, scoring tables, KPIs, or workflow measurements;",
            "- social/history/humanities subjects: timelines, comparison matrices, cause-effect frameworks, qualitative indicators, or evidence tables;",
            "- practical subjects: checklists, procedures, worked examples, exercises, and evaluation criteria.",
            "Do NOT invent artificial math for prose-only concepts; use the best domain-appropriate structured tool instead.",
        ])

    strategy_rules = {
        "quantitative_formula_examples": "Add formulas, symbol explanations, worked examples, and short interpretation paragraphs where appropriate.",
        "code_examples_debugging_tasks": "Use compact code examples, expected output, common mistakes, debugging notes, and short practice tasks only when this section is genuinely about programming, commands, configuration, APIs, SQL, or debugging.",
        "workflow_checklists_practice_steps": "Use workflow steps, checklists, decision points, quality gates, and practice tasks.",
        "case_studies_rubrics_metrics": "Use case studies, rubrics, metrics/KPIs, scoring criteria, and small decision tables.",
        "comparison_tables_timelines_frameworks": "Use comparison tables, timelines, classification criteria, cause-effect frameworks, and synthesis prompts.",
        "models_metrics_examples": "Use conceptual models, metrics, examples, tables, and practical interpretation.",
        "domain_structuring_tools": "Use the most appropriate domain tool: formula, model, rubric, timeline, table, checklist, or worked example.",
        "analytical_examples_structured_synthesis": (
            "Use analytical examples, structured synthesis, and comparison points."
            if page_budget_mode == "compact"
            else "Use analytical examples, structured synthesis, and comparison points."
        ),
    }
    selected_rule = strategy_rules.get(strategy, strategy_rules["analytical_examples_structured_synthesis"])
    lines.append(selected_rule)
    if target_pages and target_pages >= 4:
        lines.append(
            "For a large section target, include at least two structured learning elements across the section, not only long paragraphs."
        )
    if language == "vi":
        lines.append("Write all labels, tables, examples, and explanations in Vietnamese.")
    return "\n".join(lines)


def _is_code_heavy_context(layout_profile: str | None, expansion_strategy: str | None) -> bool:
    return (
        str(layout_profile or "").strip().lower() == "code"
        or str(expansion_strategy or "").strip().lower() == "code_examples_debugging_tasks"
    )


def _build_code_style_rule(
    layout_profile: str | None,
    expansion_strategy: str | None,
) -> str:
    if _is_code_heavy_context(layout_profile, expansion_strategy):
        return (
            "- Code blocks are allowed when they directly teach programming, SQL/API usage, "
            "configuration, command-line work, debugging, or lab implementation. Every code "
            "block must include a language identifier such as ```python, ```bash, or ```sql."
        )
    return (
        "- Do NOT use fenced code blocks in concept/basic sections. For networking, operating "
        "systems, computer architecture, and other conceptual technical topics, prefer prose, "
        "comparison tables, conceptual models, diagrams/images, or scenario examples. Use a "
        "code/config/command block only when the section title or description explicitly asks "
        "for programming, commands, configuration, SQL/API usage, debugging, or a hands-on lab."
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
    - Use prior section summaries for continuity (no repetition).
    - No tool calls — receives fully prepared context from ContextEvaluator.

    Premium model is used here exclusively because output quality directly
    determines the textbook content quality.
    """

    def __init__(self) -> None:
        self.model = str(get_runtime_config("LLM_MODEL_PREMIUM", required=False) or LLM_MODEL_PREMIUM)
        self._llm = ChatOpenAI(
            model=self.model, #type: ignore
            api_key=get_api_key("OPENAI_API_KEY"), #type: ignore
            temperature=0.4,
        )
        self._prompt_logger = setup_prompt_logger("writer")

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
        language: str = "vi",
        textbook_mode: str = "standard",
        formula_policy: str = "auto",
        formula_need: str = "none",
        target_pages: int | None = None,
        layout_profile: str | None = None,
        formula_density: str | None = None,
        expansion_strategy: str | None = None,
        page_fill_bias: float | None = None,
        planned_child_sections: list[dict] | None = None,
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
            enable_images:       Kept for workflow compatibility; image planning
                                 is handled by the downstream Illustrator node.
            review_feedback:     Non-empty → revision mode.
            section_summaries:   Summaries of previously written sections.

        Returns:
            Generated Markdown string without image placeholders.
        """
        char_min, char_max = char_target
        profile = get_language_profile(language)
        page_budget_mode = _page_budget_mode(target_pages, char_target)
        length_rule   = _build_length_rule(
            section_type,
            content_level,
            char_min,
            char_max,
            page_budget_mode,
        )
        expansion_rule = _build_expansion_rule(
            layout_profile=layout_profile,
            formula_density=formula_density,
            expansion_strategy=expansion_strategy,
            target_pages=target_pages,
            page_budget_mode=page_budget_mode,
            language=language,
        )
        code_style_rule = _build_code_style_rule(layout_profile, expansion_strategy)
        prior_block   = _build_prior_summary_block(section_summaries)
        hk_hint       = _get_hk_hint(section_type, page_budget_mode)
        back_reference = (
            'When writing in Vietnamese, reference prior concepts with a natural '
            'phrase such as "như đã trình bày ở mục X.Y" when relevant.'
            if language == "vi"
            else 'When writing in English, reference prior concepts with a natural '
            'phrase such as "as discussed in Section X.Y" when relevant.'
        )
        planned_child_sections = planned_child_sections or []
        planned_child_heading_lines = [
            f"### {child.get('number')} {child.get('title')}"
            for child in planned_child_sections
            if child.get("number") and child.get("title")
        ]
        planned_child_block = "\n".join(planned_child_heading_lines)
        is_controlled_level2_parent = bool(planned_child_heading_lines)
        is_planned_level2_leaf = section_num.count(".") >= 2
        section_heading_marker = "###" if is_planned_level2_leaf else "##"
        double_number_example = (
            f"NEVER double-number: ❌ {section_heading_marker} {section_num}. Mục {section_num} → ✅ {section_heading_marker} {section_num} Tiêu đề"
            if language == "vi"
            else f"NEVER double-number: ❌ {section_heading_marker} {section_num}. Section {section_num} → ✅ {section_heading_marker} {section_num} Title"
        )
        style_rule = (
            "English punctuation: do NOT use em dash or en dash characters "
            "(—, –). Use commas, parentheses, semicolons, or ASCII hyphen-minus (-) instead."
            if language == "en"
            else (
                "Vietnamese punctuation: do NOT use the em dash character (—). "
                "ASCII hyphen-minus (-) is allowed when it is genuinely part of "
                "a term/acronym explanation, e.g. (ALU - Arithmetic and Logic Unit). "
                "For prose explanation or assertion, rewrite naturally with "
                "\"đây là\", \"là\", \"điều này cho thấy\", a comma, or a separate sentence."
            )
        )
        if is_controlled_level2_parent:
            subsection_depth_rule = (
                "Controlled level-2 parent discipline:\n"
                f"- This writer unit is the full parent section ## {section_num} {section_title}.\n"
                "- You MUST write exactly the planned ### child headings below, in order:\n"
                f"{planned_child_block}\n"
                "- Do NOT create any extra ### headings. Do NOT omit, rename, renumber, or reorder planned child headings.\n"
                "- Inside each planned child, prefer cohesive prose. Use bullets, tables, code, or math only when they genuinely fit the content."
            )
            subsection_count_rule = (
                "Rule 5 — CONTROLLED LEVEL-2 STRUCTURE:\n"
                "- The only ### headings allowed are the planned child headings listed above.\n"
                "- Missing planned child heading = failure. Extra unplanned ### heading = failure."
            )
            paragraph_flow_rule = (
                "Paragraph rhythm: write cohesive prose in the target language under each "
                "planned child; use lists/tables only when they improve scanning."
            )
            pedagogy_line = (
                "Apply the planned level-2 outline precisely; deepen each approved child "
                "rather than inventing additional heading levels."
            )
            example_rule = "Use concrete, domain-relevant examples when they improve understanding."
        elif is_planned_level2_leaf:
            subsection_depth_rule = (
                "Controlled level-2 leaf discipline:\n"
                f"- This writer unit is already a planned ### section: {section_num}.\n"
                "- Do NOT create any additional ### headings inside it.\n"
                "- Organise internal parts with cohesive paragraphs first; use lists/tables/steps only for true enumerations, workflows, or comparisons."
            )
            subsection_count_rule = (
                "Rule 5 — CONTROLLED LEVEL-2 STRUCTURE:\n"
                "- Output exactly one planned ### heading for this section.\n"
                "- Do not create extra ### headings. Use inline lead-ins sparingly and keep the explanation in the same paragraph."
            )
            paragraph_flow_rule = (
                "Paragraph rhythm: write cohesive prose in the target language and use "
                "lists/tables only when they improve scanning."
            )
            pedagogy_line = (
                "Apply the planned level-2 scope precisely; deepen the approved leaf "
                "rather than creating more heading levels."
            )
            example_rule = "Use concrete, domain-relevant examples when they improve understanding."
        elif page_budget_mode == "compact":
            paragraph_flow_rule = (
                "Paragraph rhythm: prefer concise academic prose over note-like fragments. "
                "Use bullets only for true enumerations, workflows, variables, comparisons, "
                "or practice tasks. Avoid reflective wrap-ups and repeated application framing."
            )
            pedagogy_line = (
                "Use a compact teaching pattern: connect briefly, organise the core "
                "ideas, and stop when the section has enough learning value. Do not "
                "force reflection, application, or summary paragraphs into short sections."
            )
            example_rule = (
                "Use at most one short concrete example when it clarifies the concept; "
                "omit examples that only repeat the prose."
            )
            subsection_depth_rule = (
                "Compact sub-section discipline:\n"
                "- Default: no ### blocks; write directly under the ## section heading.\n"
                "- Create ### only for real second-level subsections such as "
                f"### {section_num}.1 and only if there are at least two genuinely "
                "distinct child groups.\n"
                "- Never create one lone ### block; continue with prose, a compact table, or a true list instead."
            )
            subsection_count_rule = (
                "Rule 5 — SUB-SECTION COUNT FOR COMPACT MODE:\n"
                "- Default: 0 ### blocks.\n"
                "- If real child groups are necessary: use at least 2 numbered ### blocks, "
                "never a single ### block.\n"
                "- Absolute ceiling: 2 ### blocks for compact sections."
            )
        else:
            paragraph_flow_rule = (
                "Paragraph rhythm: write cohesive prose in the target language, "
                "not note-like fragments. Most body paragraphs should develop one "
                "idea across 4-7 sentences. Use a short 2-3 sentence paragraph only "
                "for orientation, transition, or emphasis. If adjacent short "
                "paragraphs continue the same idea, merge them into one stronger paragraph."
            )
            pedagogy_line = (
                "Apply the CORE model per section: Connect to prior knowledge → Organise new "
                "content incrementally → weave synthesis or comparison into prose when useful → "
                "Extend to a real-world context only when it adds clear value."
            )
            example_rule = "Use concrete, domain-relevant examples when they improve understanding."
            subsection_depth_rule = (
                "Sub-section depth:\n"
                "- Each ### block: use fewer, fuller paragraphs rather than many short ones.\n"
                "- Paragraphs may vary by depth and content; avoid a repeated pattern of 2–3 sentence paragraphs.\n"
                "- light → 1–2 ### blocks; medium → 2–3; deep → 3–4; applied → 2–3.\n"
                "- PREFER fewer, deeper blocks over many shallow ones.\n"
                f"- {paragraph_flow_rule}"
            )
            subsection_count_rule = (
                "Rule 5 — SUB-SECTION COUNT PER DEPTH LEVEL (STRICT CEILING):\n"
                "- light   → maximum 2 ### blocks\n"
                "- medium  → maximum 3 ### blocks\n"
                "- deep    → maximum 4 ### blocks\n"
                "- applied → maximum 3 ### blocks"
            )
        practice_mode = _is_practice_mode(textbook_mode)
        practice_criterion = ""
        practice_constraint = ""
        if practice_mode:
            practice_criterion = f"""
Practice-course content standards:
- Treat this as a university practice textbook section, not a theory chapter.
- Prioritize what the learner must do, produce, check, modify, and submit.
- Each section must include guided hands-on steps, a similar exercise, and
  a slightly advanced exercise/challenge.
- Use examples or worked steps only when they directly support doing the task.
- Avoid long conceptual exposition; give only the minimum operational context
  needed to complete the task.
"""
            practice_constraint = """
Rule 8 — PRACTICE COURSE MODE:
- Do NOT create headings named 'Lý thuyết', 'Khái niệm', 'Tổng quan',
  'Tổng kết', 'Kết luận', 'Theory', 'Concepts', 'Overview', 'Summary',
  or 'Conclusion'.
- Do NOT write a theory-first explanation, concept catalogue, or summary block.
- Include concrete action steps the learner can follow.
- Include at least one similar exercise and one slightly advanced exercise.
- Keep all existing heading, numbering, blank-line, code, and math rules.
"""

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
You are a pedagogical architect producing learner-focused academic content.
{pedagogy_line}
Prioritise analysis and evaluation over fact-listing.
Adapt tone to the subject domain. Output only final Markdown — no preamble.
[/CONTEXT]

[TASK]
Write content for the following textbook section.

<book_topic>{course_topic}</book_topic>
<chapter num="{chapter_num}">{chapter_title}</chapter>
<section num="{section_num}">{section_title}</section>
<description>{section_description}</description>
<section_type>{section_type}</section_type>
<page_budget_mode>{page_budget_mode}</page_budget_mode>
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
- {back_reference}
- Assume the reader has read all prior sections.

Adapt depth to section_type:
- light   → Orient/recap: accessible prose, light technical depth
- medium  → Explain/demonstrate: definitions, worked examples
- deep    → Analyse/theorise: sustained argument, rigorous detail
- applied → Tasks/exercises: step-by-step guidance, worked solutions

{length_rule}

{expansion_rule}

{subsection_depth_rule}

Content standards:
- {profile.tone_rule} No conversational fillers.
- Adapt tone: precise for IT/Engineering, narrative for History/Arts.
- Bold (**term**) ONLY for the primary concept defined for the first time.
- {example_rule}
{code_style_rule}
- Inline code rule: programming identifiers, keywords, function names, method
  names, operators, and code expressions MUST use backticks, not $...$ math.
  Correct: `student_scores["Alice"]`, `keys()`, `if`, `for`, `str()`.
  Incorrect: $student_scores["Alice"]$, $keys()$, $if$, $str()$.
- Use $...$ only for real mathematical notation. Do not use $...$ for Python
  keywords, variable names, string literals, dictionary/list indexing, or methods.
- Formula explanations must be formatted as one variable per bullet:
  Trong đó:
  - $C_{{total}}$: ...
  - $C_{{dev}}$: ...
  Never write "Trong đó: - ..." on one line, and never use backticks for
  mathematical symbols.
- In numbered/bulleted calculation steps, each step label must stay outside
  math. Put only that step's formula inside its own $$...$$ block. Never open
  one $$ block that spans multiple numbered/bulleted steps or prose labels.
- Colon rule: keep prose explanations on the same line/paragraph after ":".
  Correct: "Ví dụ thực tiễn: ..." and "Điểm khác biệt là: ...".
  Start a new list after ":" only for a true list, table, formula explanation,
  workflow, or "Trong đó:" variable block.
- Do not create empty label bullets such as "- Chia sẻ tài nguyên:" followed by
  the explanation in the next paragraph. Write "- Chia sẻ tài nguyên: ..." or
  use a normal prose sentence instead.
- Do not write labels named "Checkpoint", "Checkpoint phản tư",
  "Checkpoint thực hành", "synthesis checkpoint", or similar checkpoint markers.
- {style_rule}

{hk_hint}
{practice_criterion}
[/CRITERION]

[CONSTRAINT]
Rule 1 — CHAPTER HEADER (non-negotiable):
{chapter_instruction}

Rule 2 — DOCUMENT STRUCTURE:
- Section header: {section_heading_marker} {section_num} {section_title}
- Sub-section: {"use exactly the planned child headings listed in the criterion above" if is_controlled_level2_parent else f"### {section_num}.N Title (N starts at 1) only when this writer unit is a ## section."}
- ### is only for real planned/necessary second-level subsections such as {section_num}.1.
- NEVER use unnumbered ### headers such as "### Đặc điểm kỹ thuật",
  "### Ví dụ thực tiễn", "### Bảng so sánh nhanh", or "### Quy trình thực hiện".
  Use a normal prose sentence or a short inline lead-in instead.
- NEVER use # unless Rule 1 explicitly instructs it
- {double_number_example}
- NEVER use colon after number: ❌ {section_heading_marker} {section_num}: → ✅ {section_heading_marker} {section_num}

Rule 3 — BLANK LINES (PDF will break if violated):
Blank line BEFORE and AFTER: every heading, every paragraph, every list,
every code block, every math block. Zero exceptions.

Rule 3.5 — NO HORIZONTAL RULES:
Do NOT output standalone separator lines such as --- or ---- anywhere.
Use headings and blank lines only to separate sections.

Rule 4 — DEPTH AND CLOSURE:
- Do NOT create a ### heading for content that fits in 1–2 paragraphs.
- Do NOT create a '### Kết luận' or '### Conclusion' subsection.
- Do NOT create sections named "Phản tư", "Suy ngẫm", or "Mở rộng thực tiễn".
- Do NOT end every section with routine "Sinh viên có thể..." statements.
Concluding thoughts, when genuinely needed, must be woven into the last body paragraph.

{subsection_count_rule}

Rule 6 — MERGE OVER SPLIT:
If you have more sub-topics than the ceiling, merge related topics into the
same ### block. Prefer fewer, deeper blocks with substantial paragraphs over
many thin blocks or long sequences of short paragraphs.
{practice_constraint}
[/CONSTRAINT]

[FORMAT]
- Language: {profile.prompt_name}
- Output: raw Markdown — NO outer fences
- First line: strictly follow Rule 1
- Character count target: {char_min}-{char_max}; respect page_budget_mode={page_budget_mode}
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

        response = rate_limited_invoke(
            self._llm,
            messages,
            bucket="chat",
            metadata={
                "agent": "ContentWriter",
                "node": "content_writer",
                "model": LLM_MODEL_PREMIUM,
            },
        )
        return str(response.content)


# ============================================================================
# ORCHESTRATOR — Writer Agent
# ============================================================================

class WriterAgent:
    """
    Orchestrator that sequences the three writing components.

    Pipeline per section:
        1. ContextEvaluator       — enrich RAG context with optional tools
        2. ContentWriter          — generate prose    (LLM_MODEL_PREMIUM)
    Also applies deterministic post-processing (blank line enforcement,
    chapter header compliance) after content generation.
    """

    def __init__(self) -> None:
        self._writer = ContentWriter()

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
        language: str = "vi",
        textbook_mode: str = "standard",
        formula_policy: str = "auto",
        formula_need: str = "none",
        writer_call_count: int = 1,
        target_pages: int | None = None,
        layout_profile: str | None = None,
        formula_density: str | None = None,
        expansion_strategy: str | None = None,
        page_fill_bias: float | None = None,
        planned_child_sections: list[dict] | None = None,
        
    ) -> str:
        """
        Generate or revise content for a single textbook section.

        Sequences ContextEvaluator-prepared context → ContentWriter,
        then applies post-processing.

        Args:
            course_topic:        Main textbook topic.
            chapter_num:         1-indexed chapter number.
            chapter_title:       Title of the current chapter.
            section_num:         Dot-notation section number (e.g. "1.2").
            section_title:       Title of the current section.
            section_description: What this section should cover.
            context:             Prepared RAG context from Retriever/ContextEvaluator.
            chapter_instruction: # CHƯƠNG header emit/suppress directive.
            section_type:        Depth level.
            char_target:         (min_chars, max_chars) tuple.
            content_level:       User-configured length level.
            enable_images:       Kept for page-budget compatibility; the
                                 downstream Illustrator handles images.
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
        # Step 2: Generate content (premium model, no tools). Very large page
        # budgets are split into a small number of internal writer calls so a
        # single prompt does not become too hard to satisfy.
        # ------------------------------------------------------------------
        try:
            safe_call_count = max(1, min(int(writer_call_count or 1), 5))
        except (TypeError, ValueError):
            safe_call_count = 1

        if safe_call_count == 1:
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
                language=language,
                textbook_mode=textbook_mode,
                formula_policy=formula_policy,
                formula_need=formula_need,
                target_pages=target_pages,
                layout_profile=layout_profile,
                formula_density=formula_density,
                expansion_strategy=expansion_strategy,
                page_fill_bias=page_fill_bias,
                planned_child_sections=planned_child_sections,
            )
        else:
            logger.info(
                "Splitting long section %s into %s writer calls",
                section_num,
                safe_call_count,
            )
            pieces: list[str] = []
            part_min = max(1200, int(char_target[0] / safe_call_count))
            part_max = max(part_min + 250, int(char_target[1] / safe_call_count))
            for part_idx in range(safe_call_count):
                is_first_part = part_idx == 0
                part_instruction = (
                    chapter_instruction
                    if is_first_part
                    else (
                        f"Continue the same section {section_num} {section_title}. "
                        "Do NOT output any #, ##, or ### heading. Continue with body prose, "
                        "lists, tables, and examples only when they genuinely improve learning."
                    )
                )
                part_description = (
                    f"{section_description}\n\n"
                    f"Internal page-budget split: write part {part_idx + 1} of "
                    f"{safe_call_count}. Keep continuity with earlier parts and avoid "
                    "repeating definitions already written in this section."
                )
                piece = self._writer.generate(
                    course_topic=course_topic,
                    chapter_num=chapter_num,
                    chapter_title=chapter_title,
                    section_num=section_num,
                    section_title=section_title,
                    section_description=part_description,
                    enriched_context=enriched_context,
                    chapter_instruction=part_instruction,
                    section_type=section_type,
                    char_target=(part_min, part_max),
                    content_level=content_level,
                    enable_images=enable_images,
                    review_feedback=review_feedback if is_first_part else "",
                    section_summaries=list(section_summaries) + pieces[-1:],
                    language=language,
                    textbook_mode=textbook_mode,
                    formula_policy=formula_policy,
                    formula_need=formula_need,
                    target_pages=target_pages,
                    layout_profile=layout_profile,
                    formula_density=formula_density,
                    expansion_strategy=expansion_strategy,
                    page_fill_bias=page_fill_bias,
                    planned_child_sections=planned_child_sections if is_first_part else [],
                )
                if not is_first_part:
                    piece = re.sub(r'^# [^\n]*\n?', '', piece, flags=re.MULTILINE).lstrip()
                    piece = re.sub(
                        rf'^##\s+{re.escape(section_num)}\s+{re.escape(section_title)}\s*\n?',
                        '',
                        piece,
                        flags=re.MULTILINE,
                    ).lstrip()
                    piece = re.sub(
                        rf'^###\s+{re.escape(section_num)}\s+{re.escape(section_title)}\s*\n?',
                        '',
                        piece,
                        flags=re.MULTILINE,
                    ).lstrip()
                pieces.append(piece.strip())
            content = "\n\n".join(piece for piece in pieces if piece)

        if not isinstance(content, str):
            logger.error(f"Writer returned non-string: {type(content)}")
            return "(Error: Invalid content type from LLM)"

        # ------------------------------------------------------------------
        # Post-processing: deterministic blank line enforcement
        # ------------------------------------------------------------------
        content = self._fix_blank_lines(content)

        # Length check
        actual_chars = len(content)
        formula_count = len(re.findall(r'\$\$.*?\$\$|\$[^$\n]+\$', content, flags=re.DOTALL))
        image_marker_count = content.count("[IMAGE:") + content.count("![")
        logger.info(
            "Page-budget telemetry %s: target_pages=%s layout=%s strategy=%s "
            "fill_bias=%s target_chars=%s-%s actual_chars=%s formulas=%s images=%s",
            section_num,
            target_pages,
            layout_profile,
            expansion_strategy,
            page_fill_bias,
            char_target[0],
            char_target[1],
            actual_chars,
            formula_count,
            image_marker_count,
        )
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
    language: str = "vi",
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
        Summary string: "Mục/Section X.Y 'Title': <prose preview>..."
    """
    profile = get_language_profile(language)
    prose_lines = [
        line.strip()
        for line in content.split('\n')
        if line.strip() and not line.startswith('#') and not line.startswith('>')
    ]
    preview = ' '.join(prose_lines)[:_SUMMARY_PREVIEW_CHARS]
    return f"{profile.prior_section_label} {section_num} '{section_title}': {preview}..."




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
    language          = state.get("language", "vi")
    textbook_mode     = state.get("textbook_mode", "standard")
    formula_policy    = state.get("formula_policy", "auto")
    formula_need      = state.get("formula_need", "none")
    profile           = get_language_profile(language)

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
        location = get_section_location(curriculum, chap_idx, sub_idx)
        chapter = location["chapter"]
        subsection = location["subsection"]
        parent_section = location["parent"]
        child_sections = location.get("children") or []

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
        base_min, base_max = get_char_target(
            sec_type,
            content_level,
            state.get("advanced_config", {}),
            language=language,
        )
        page_target_min = (
            getattr(subsection, "target_chars_min", None)
            if isinstance(subsection, SubSection)
            else subsection.get("target_chars_min")
        )
        page_target_max = (
            getattr(subsection, "target_chars_max", None)
            if isinstance(subsection, SubSection)
            else subsection.get("target_chars_max")
        )
        if page_target_min and page_target_max:
            try:
                base_min = max(250, int(page_target_min))
                base_max = max(base_min + 250, int(page_target_max))
                logger.info(
                    "Using page-budget char target for %s: %s-%s",
                    sec_title,
                    base_min,
                    base_max,
                )
            except (TypeError, ValueError):
                logger.warning("Invalid page-budget char target; falling back to content level")
        min_chars_floor = state.get("min_chars_per_section", 0)
        effective_min   = max(base_min, min_chars_floor)
        effective_max   = max(base_max, effective_min + 250)
        char_target     = (effective_min, effective_max)
        used_queries    = state.get("used_rag_queries", [])

        sec_title    = clean_section_title(sec_title)
        display_chap = location["display_chapter"]
        display_sec  = location["display_number"]
        parent_number = location["parent_number"]
        is_child_leaf = bool(location["is_child"])
        planned_child_sections: list[dict] = []
        for child_idx, child in enumerate(child_sections):
            child_title = (
                child.title if isinstance(child, SubSection)
                else child.get("title", "")
            )
            child_desc = (
                child.description if isinstance(child, SubSection)
                else child.get("description", "")
            )
            child_type = (
                child.section_type if isinstance(child, SubSection)
                else child.get("section_type", "medium")
            )
            child_title = clean_section_title(str(child_title or ""))
            if not child_title:
                continue
            planned_child_sections.append({
                "number": f"{display_sec}.{child_idx + 1}",
                "title": child_title,
                "description": str(child_desc or ""),
                "section_type": str(child_type or "medium"),
            })
        if planned_child_sections:
            child_scope = "\n".join(
                f"- {child['number']} {child['title']}: {child.get('description') or 'Cover this planned child subsection.'}"
                for child in planned_child_sections
            )
            sec_desc = (
                f"{sec_desc}\n\nControlled level-2 child subsections to cover exactly:\n"
                f"{child_scope}"
            ).strip()
        parent_title = ""
        if parent_section is not None:
            parent_title = (
                parent_section.title if isinstance(parent_section, SubSection)
                else parent_section.get("title", "")
            )
            parent_title = clean_section_title(parent_title)

        is_chapter_open        = bool(location["is_first_in_chapter"])
        is_parent_open         = bool(location["is_first_in_parent"])
        header_already_written = state.get("chapter_header_written", False)

        if is_chapter_open and not header_already_written:
            expected_heading = f"# {profile.chapter_label} {display_chap}: {chap_title.upper()}"
            section_heading = (
                f"## {display_sec} {sec_title}\n\n" + "\n\n".join(
                    f"### {child['number']} {child['title']}"
                    for child in planned_child_sections
                )
                if planned_child_sections
                else
                f"## {parent_number} {parent_title}\n\n### {display_sec} {sec_title}"
                if is_child_leaf and is_parent_open
                else f"### {display_sec} {sec_title}" if is_child_leaf
                else f"## {display_sec} {sec_title}"
            )
            chapter_instruction_text = (
                f"This is the opening section of Chapter {display_chap}.\n"
                f"Output EXACTLY this line as the very first line "
                f"(before the ## section header):\n"
                f"{expected_heading}\n\n"
                f"Then write exactly this planned section heading block:\n"
                f"{section_heading}"
            )
            emit_header = True
        else:
            section_heading = (
                f"## {display_sec} {sec_title}\n\n" + "\n\n".join(
                    f"### {child['number']} {child['title']}"
                    for child in planned_child_sections
                )
                if planned_child_sections
                else
                f"## {parent_number} {parent_title}\n\n### {display_sec} {sec_title}"
                if is_child_leaf and is_parent_open
                else f"### {display_sec} {sec_title}" if is_child_leaf
                else f"## {display_sec} {sec_title}"
            )
            chapter_instruction_text = (
                f"This section is NOT the start of a new chapter.\n"
                f"DO NOT output any # (level-1) heading under ANY circumstances.\n"
                f"Your very first line(s) MUST be exactly this planned heading block:\n"
                f"{section_heading}"
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
        writer_call_count = (
            getattr(subsection, "writer_call_count", None)
            if isinstance(subsection, SubSection)
            else subsection.get("writer_call_count")
        )
        section_target_pages = (
            getattr(subsection, "target_pages", None)
            if isinstance(subsection, SubSection)
            else subsection.get("target_pages")
        )
        layout_profile = (
            getattr(subsection, "layout_profile", None)
            if isinstance(subsection, SubSection)
            else subsection.get("layout_profile")
        )
        formula_density = (
            getattr(subsection, "formula_density", None)
            if isinstance(subsection, SubSection)
            else subsection.get("formula_density")
        )
        expansion_strategy = (
            getattr(subsection, "expansion_strategy", None)
            if isinstance(subsection, SubSection)
            else subsection.get("expansion_strategy")
        )
        page_fill_bias = (
            getattr(subsection, "page_fill_bias", None)
            if isinstance(subsection, SubSection)
            else subsection.get("page_fill_bias")
        )

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
            language=language,
            textbook_mode=textbook_mode,
            formula_policy=formula_policy,
            formula_need=formula_need,
            writer_call_count=writer_call_count or 1,
            target_pages=section_target_pages,
            layout_profile=layout_profile,
            formula_density=formula_density,
            expansion_strategy=expansion_strategy,
            page_fill_bias=page_fill_bias,
            planned_child_sections=planned_child_sections,
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

        # Layer 2b — Enforce missing chapter heading
        chapter_heading_re = rf'^# {re.escape(profile.chapter_label)}'
        if emit_header and not re.search(chapter_heading_re, content, flags=re.MULTILINE):
            expected = f"# {profile.chapter_label} {display_chap}: {chap_title.upper()}"
            content  = expected + "\n\n" + content.lstrip('\n')
            logger.warning(f"⚠️  Prepended missing chapter heading: '{expected}'")

        # Layer 2c — Normalize chapter title text to uppercase
        if emit_header:
            content = re.sub(
                rf'^(# {re.escape(profile.chapter_label)} [^:]+: )(.+)$',
                lambda m: m.group(1) + m.group(2).upper(),
                content,
                flags=re.MULTILINE,
                count=1,
            )

        def _has_heading(markdown: str, heading: str) -> bool:
            return bool(re.search(rf'^{re.escape(heading)}\s*$', markdown, flags=re.MULTILINE))

        def _prepend_after_chapter_or_start(markdown: str, heading_block: str) -> str:
            if emit_header:
                chapter_line = rf'^(# {re.escape(profile.chapter_label)} {display_chap}: .+)$'
                if re.search(chapter_line, markdown, flags=re.MULTILINE):
                    return re.sub(
                        chapter_line,
                        lambda m: f"{m.group(1)}\n\n{heading_block}",
                        markdown,
                        flags=re.MULTILINE,
                        count=1,
                    )
            return f"{heading_block}\n\n{markdown.lstrip()}"

        # Layer 2d — Enforce planned section headings after LLM output.
        if planned_child_sections:
            parent_heading = f"## {display_sec} {sec_title}"
            if not _has_heading(content, parent_heading):
                content = _prepend_after_chapter_or_start(
                    content,
                    parent_heading,
                )
        elif is_child_leaf:
            parent_heading = f"## {parent_number} {parent_title}"
            child_heading = f"### {display_sec} {sec_title}"
            has_parent = _has_heading(content, parent_heading)
            has_child = _has_heading(content, child_heading)
            if is_parent_open and not has_parent and has_child:
                content = re.sub(
                    rf'^{re.escape(child_heading)}\s*$',
                    f"{parent_heading}\n\n{child_heading}",
                    content,
                    flags=re.MULTILINE,
                    count=1,
                )
                has_parent = True
            if is_parent_open and (not has_parent or not has_child):
                heading_block = "\n\n".join(
                    heading
                    for heading, present in (
                        (parent_heading, has_parent),
                        (child_heading, has_child),
                    )
                    if not present
                )
                if heading_block:
                    content = _prepend_after_chapter_or_start(content, heading_block)
            elif not has_child:
                content = _prepend_after_chapter_or_start(content, child_heading)
        else:
            expected_section_heading = f"## {display_sec} {sec_title}"
            if not _has_heading(content, expected_section_heading):
                content = _prepend_after_chapter_or_start(content, expected_section_heading)

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
