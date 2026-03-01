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
from src.config import LLM_MODEL_NAME

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
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.4)

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
            revision_instruction = f"""
--- REVISION REQUIRED ---
Your previous draft was reviewed and rejected. You MUST address ALL points below:

REVIEWER FEEDBACK:
{review_feedback}

ACTION: Rewrite the section from scratch, fixing all issues mentioned above.
Do NOT repeat the same mistakes from the previous draft.
--- END REVISION INSTRUCTION ---
"""

        # System prompt with LaTeX safety rules + STRICT formatting rules
        system_prompt = """You are an expert educational content creator, capable of writing high-quality textbook material for any subject (Science, History, Technology, Arts, etc.).

--- CONTEXT AND LOCATION ---
You are currently writing:
- **Book Topic**: {course_topic}
- **Chapter {chapter_num}**: {chapter_title}
- **Section {section_num}**: {section_title}
- **Description**: {section_description}

RESEARCH CONTEXT (From Vector DB):
{context}

{revision_instruction}

--- WRITING RULES (STRICT) ---

1. ADAPT YOUR TONE:
   - For IT/Engineering: Be precise, practical. Use code blocks for examples.
   - For History/Arts: Be narrative, engaging. Use dates and cultural context.
   - For Science: Be rigorous, explanatory. Use formulas if needed (LaTeX).

2. FORMATTING (CRITICAL - READ CAREFULLY):
   - Write in clear, academic but accessible Markdown.
   - Use bolding for key terms.
   - Use lists/bullet points for readability.
   - **CRITICAL**: ALWAYS add blank lines between paragraphs and sections.
   - **CRITICAL**: Headers MUST have blank lines before AND after.

3. CONTENT:
   - Explain the concept clearly.
   - Provide relevant examples based on the domain.
   - If the context provided is empty/irrelevant, use your general knowledge but mention that specific textbook references were missing.

4. STRUCTURE & NUMBERING (CRITICAL):
   **Header Formatting (STRICT):**
   {chapter_instruction}
   
   - **Section Header**: Start with Header 2 on its OWN line with blank lines around it:
   
   CORRECT FORMAT:
```
   (blank line)
   ## 1.1 Section Title
   (blank line)
   First paragraph starts here...
   (blank line)
   Second paragraph...
```
   
   - **Sub-headers**: Use Header 3 with blank lines:
```
   (blank line)
   ### 1.1.1 Subsection Title
   (blank line)
   Content starts here...
```
   
   - **WRONG FORMATS** (will cause rendering errors):
     ❌ `## 1.1 Title Text continues on same line...` (NO blank line after header)
     ❌ `## 1.1 Title\\nText` (No blank line, text immediately after)
     ✅ `## 1.1 Title\\n\\nText starts here` (Correct with blank line)
   
   - **Clean Titles**: 
     - ❌ BAD: `## 1.1. Mục 1.1 Khái niệm` (Double numbering)
     - ❌ BAD: `## 1.1: Khái niệm` (Colon)
     - ✅ GOOD: `## 1.1 Khái niệm`
   
   - **IMPORTANT**: Use a SPACE between number and title, NO colons or extra dots.

5. **Content Depth (CRITICAL)**:
   - **Section Type**: This is a **{section_type}** section — adapt accordingly:
     - "intro"    : Engaging overview, set the scene, motivate the reader. Light depth.
     - "concept"  : Deep explanation of theory, definitions, principles. The "Why" and "How".
     - "example"  : Worked examples, case studies, step-by-step walkthroughs.
     - "practice" : Exercises, problems, hands-on tasks with guidance.
     - "summary"  : Concise recap of key points, takeaways, bridge to next section.
   - **Target Length**: Write approximately **{word_min}–{word_max} words** for this section type.
   - **No Fluff**: Every sentence must add value. Do not pad or repeat unnecessarily.
   - **Academic Tone**: Formal, precise, but accessible (like a professor teaching).
   - **Paragraph Structure**: Each paragraph should be 3-5 sentences. Add blank line between paragraphs.

6. **Required Elements**:
   - **Key Terminology**: Bold important terms.
   - **Examples**: Provide concrete, real-world examples.
   - **Math & LaTeX Rules (CRITICAL FOR PDF GENERATION)**:
     - **Block Math**: ALWAYS use double dollar signs `$$ ... $$` on NEW lines with blank lines:
```
       (blank line)
       $$ E = mc^2 $$
       (blank line)
```
       - ❌ BAD: `\\[ E = mc^2 \\]`
       - ✅ GOOD: Blank line + `$$ E = mc^2 $$` + Blank line
     
     - **Inline Math**: Use single dollar signs `$ ... $` within text.
       - ✅ GOOD: The force is $F$ where $F = ma$.
     
     - **No Naked Math**: NEVER use LaTeX commands without `$`.
       - ❌ BAD: a_x = 5
       - ✅ GOOD: $a_x = 5$
       - ❌ BAD: \\frac{{d}}{{t}}
       - ✅ GOOD: $\\frac{{d}}{{t}}$
     
     - **Avoid Complex Environments**: Do not use `\\begin{{equation}}`. Stick to `$$ ... $$`.

**Visuals (RARELY USE)**:
   - **ONLY add image suggestion for ESSENTIAL technical diagrams/charts**
   - Skip images for: concepts that can be explained in text, generic examples, decorative purposes
   - Maximum 0-1 image per section (prefer 0)
   - Format:
```
     > [IMAGE SUGGESTION: Specific technical description]
```

7. **Missing Info**:
   - If the Research Material is thin, use your internal expert knowledge to fill gaps.
   - Connect this section to the broader Chapter theme.

8. **LINE BREAKS (CRITICAL)**:
   - ALWAYS add blank line after headers
   - ALWAYS add blank line between paragraphs
   - ALWAYS add blank line before/after lists
   - ALWAYS add blank line before/after code blocks
   - ALWAYS add blank line before/after math blocks

OUTPUT LANGUAGE: VIETNAMESE (Tiếng Việt).

**FINAL CHECK BEFORE OUTPUTTING**:
- Every header has blank line before AND after
- Every paragraph separated by blank line
- No text immediately after headers on same line
"""

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
            
            # POST-PROCESSING: Ensure blank lines after headers
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
\\Huge \\textbf{{CHƯƠNG {display_chap}: {chap_title.upper()}}}
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