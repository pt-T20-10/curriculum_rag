"""
Writer Agent for AI Textbook Generator.

This agent synthesizes retrieved RAG context into high-quality academic content,
with special attention to LaTeX-safe Markdown formatting for PDF compilation.
"""

import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from src.log_config import setup_logger
from src.graph.state import AgentState, CurriculumOutline, Chapter, SubSection, get_chapter_and_subsection, get_word_target
from src.config import LLM_MODEL_PREMIUM, PDF_CHAPTER_FONTSIZE

logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")


class WriterAgent:
    """
    Writer Agent: Generates textbook content from RAG context.
    
    Specialized in:
    - Academic writing in Vietnamese
    - LaTeX-safe Markdown formatting
    - Structured content with proper headers
    - Revision support: accepts feedback from Reviewer for re-drafting
    """
    
    def __init__(self) -> None:
        """Initialize LLM with balanced creativity (temperature=0.4)."""
        self.llm = ChatOpenAI(model=LLM_MODEL_PREMIUM, temperature=0.4)

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
        section_type: str = "concept",
        word_target: tuple[int, int] = (800, 1000)
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
            chapter_instruction: Special LaTeX instructions for chapter headers
            review_feedback: Feedback from Reviewer (non-empty means this is a revision)
            section_type: Content purpose — controls tone and depth expectations
            word_target: (min_words, max_words) tuple derived from section_type + user config
            
        Returns:
            Generated Markdown content, or error message on failure.
        """
        logger.info(f"Composing: {section_num} {section_title}")
        
        if review_feedback:
            logger.info(f"Revision mode — feedback: {review_feedback[:80]}")

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
<word_target>{word_min}–{word_max} words</word_target>
<research_material>
{context}
</research_material>
</task_context>

{revision_instruction}

<rules>

RULE 1 — LANGUAGE:
Write in formal Vietnamese (Tiếng Việt học thuật). Academic, precise, and accessible like a professor teaching.
Do NOT use conversational fillers: "Chúng ta hãy cùng xem...", "Trong phần này tôi sẽ...", "Hãy cùng khám phá...".

RULE 2 — SECTION TYPE BEHAVIOR:
Adapt writing based on the <section_type> value:
- intro    → Engaging overview, motivate the reader, light technical depth
- concept  → Deep theory, definitions, principles — explain WHY and HOW
- example  → Worked examples, case studies, step-by-step walkthroughs
- practice → Exercises and hands-on tasks with guidance
- summary  → Concise recap of key points, bridge to next section
Each paragraph: 3–5 sentences. Hit the <word_target> range.

RULE 3 — CHAPTER HEADER (CRITICAL — execute BEFORE section header when chapter_instruction is non-empty):
{chapter_instruction}

RULE 4 — DOCUMENT STRUCTURE (CRITICAL):
Header format rules — apply ALL of them:
- Section header: ## {section_num} {section_title}
- Sub-section header: ### {section_num}.N Title where N starts at 1 (e.g. for ## 1.2, sub-sections are ### 1.2.1 Tiêu đề, ### 1.2.2 Tiêu đề, ...)
- NEVER use unnumbered ### headers — always include the full dot-number prefix (e.g. ### 1.2.1 not ### Tiêu đề)
- NEVER use # (Header 1) unless it is the chapter title line
- NEVER double-number: ❌ ## 1.1. Mục 1.1 Tiêu đề → ✅ ## 1.1 Tiêu đề
- NEVER use colon: ❌ ## 1.1: Tiêu đề → ✅ ## 1.1 Tiêu đề
Mandatory blank lines — apply to EVERY occurrence:
- Blank line BEFORE every header
- Blank line AFTER every header
- Blank line BETWEEN every paragraph
- Blank line BEFORE and AFTER every list
- Blank line BEFORE and AFTER every code block
- Blank line BEFORE and AFTER every math block

RULE 5 — MATH AND LATEX (CRITICAL):
Block math — use $$ on its own line, with blank lines around it:
  ✅ CORRECT:
  (blank line)
  $$ E = mc^2 $$
  (blank line)
  ❌ WRONG: \\[ E = mc^2 \\]
  ❌ WRONG: \\begin{{equation}} E = mc^2 \\end{{equation}}

Inline math — single $ delimiter:
  ✅ The force is $F$ where $F = ma$.
  ❌ The force is F where F = ma.

Naked math — NEVER write LaTeX commands or math symbols without $:
  ✅ $a_x = 5$     ❌ a_x = 5
  ✅ $\\frac{{d}}{{t}}$   ❌ \\frac{{d}}{{t}}

Intervals and sets — wrap entirely in $, NO space after opening $:
  ✅ $[0, \\frac{{a}}{{2}}]$
  ❌ $ [0, \\frac{{a}}{{2}}]$

Vietnamese text inside math — MUST use \\text{{...}}:
  ✅ $v_{{\\text{{cuối}}}}$
  ❌ $v_{{cuối}}$

Chemical formulas and electron configs — NEVER use Unicode subscript/superscript characters:
  ❌ H₂O, CO₂, Na⁺, Cl⁻, 1s²2s²2p⁴  (these render as □ boxes in PDF)
  ✅ H$_2$O, CO$_2$, Na$^+$, Cl$^-$, $1s^2 2s^2 2p^4$

Complex environments — do NOT use \\begin{{equation}}, \\begin{{itemize}}, \\begin{{tabular}}.

RULE 6 — CONTENT REQUIREMENTS:
- Bold (**term**) — use SPARINGLY. Bold ONLY for the primary concept being formally defined for
  the FIRST time in this section. Do NOT bold: general descriptive words, repeated mentions,
  phrases longer than 4 words, or terms that already appear in a Markdown header.
- Provide at least one concrete, domain-relevant example
- Adapt tone: precise for IT/Engineering, narrative for History/Arts, rigorous for Science
- Code blocks MUST include a language identifier: ```python, ```bash, ```sql
- If research material is thin or irrelevant, use internal knowledge to fill gaps

RULE 7 — VISUALS:
Default: write ZERO image suggestions.
Only add one if the concept absolutely cannot be understood without a diagram
(e.g., system architecture, biological process, physics circuit).
Format: > [IMAGE SUGGESTION: Specific technical description of the required diagram]
Maximum: 1 per section. Prefer 0.

</rules>

<output_format>
- Language: Vietnamese (Tiếng Việt)
- Format: raw Markdown — output content directly, NO outer markdown fences
- If RULE 3 chapter_instruction is non-empty: output the full LaTeX chapter block first (\\newpage, \\begin{{center}}, etc.), then ## {section_num} {section_title} on the next line
- If RULE 3 chapter_instruction is empty: first line is ## {section_num} {section_title}
- Sub-section headers: ### {section_num}.N Title (numbered sequentially from 1, e.g. ### 1.2.1 Title)
- Blank line before AND after EVERY header
- Blank line between EVERY paragraph
- Blank line before AND after EVERY math block ($$ ... $$)
- Word count MUST be within the <word_target> range
</output_format>"""

        user_prompt = f"Please write the content for section **{section_num}: {section_title}**."

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
                "word_min": word_target[0],
                "word_max": word_target[1]
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
        sec_type = subsection.section_type if isinstance(subsection, SubSection) else subsection.get('section_type', 'concept')
        
        # Compute word target: start from section_type defaults, then apply user min floor
        min_words_floor = state.get("min_words_per_section", 0)   # type: ignore[call-overload]
        base_min, base_max = get_word_target(sec_type)
        effective_min = max(base_min, min_words_floor)
        effective_max = max(base_max, effective_min + 100)  # ensure max > min
        word_target = (effective_min, effective_max)
        
        logger.info(f"Section type: '{sec_type}' → word target: {effective_min}–{effective_max} words")
        
        # Clean section title
        if ":" in sec_title and any(prefix in sec_title for prefix in ["Mục", "Phần", "Bài"]):
            sec_title = sec_title.split(":", 1)[1].strip()
        
        display_chap = str(chap_idx + 1)
        display_sec = f"{display_chap}.{sub_idx + 1}"
        
        # Generate chapter header instruction for first subsection only
        chapter_instruction_text = ""
        if display_sec.endswith(".1"):
            chapter_instruction_text = f"""
**SPECIAL INSTRUCTION (NEW CHAPTER)**:
- This is the start of Chapter {display_chap}.
- Insert these RAW LaTeX commands at the very top (with blank lines around):

(blank line)
\\newpage
\\begin{{center}}
\\{PDF_CHAPTER_FONTSIZE} \\textbf{{CHƯƠNG {display_chap}: {chap_title.upper()}}}
\\end{{center}}
\\vspace{{1cm}}
(blank line)
"""
        
        # Get RAG context from dedicated field (not messages)
        context = state.get("rag_context", "") or "No specific context available."
        
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
            word_target=word_target
        )
        
        return {"current_content": content}

    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {"current_content": "(Error: Invalid curriculum index)"}
    
    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {"current_content": "(Error: Malformed curriculum structure)"}
    
    except Exception as e:
        logger.error(f"Unexpected error in Writer: {e}", exc_info=True)
        return {"current_content": "(Error: Content generation failed)"}