"""
Reviewer Agent for AI Textbook Generator.

This agent reviews and polishes drafted content, with special focus on:
- LaTeX/Math sanitization for PDF compilation
- Academic tone and flow
- Structural consistency
- Quality gate with revision loop (max 2 revisions per section)
"""

import json

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from src.log_config import setup_logger
from src.graph.state import AgentState, CurriculumOutline, get_chapter_and_subsection
from src.config import LLM_MODEL_NAME

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")

MAX_REVISIONS = 2


class ReviewerAgent:
    """
    Reviewer Agent: Reviews and polishes drafted content.
    
    Responsibilities:
    - LaTeX/Math sanitization (prevent PDF compilation errors)
    - Academic tone enforcement
    - Structural consistency
    - Image placeholder validation
    - Quality gate: decide if content needs revision (max MAX_REVISIONS times)
    """
    
    def __init__(self) -> None:
        """Initialize LLM with low temperature for precise editing."""
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.1)

    def should_revise(self, content: str) -> tuple[bool, str]:
        """
        Quality gate: Decide if polished content still needs revision.
        
        Criteria for rejection:
        - Content < 300 words (too short)
        - Missing key concepts
        - Broken LaTeX (naked math symbols)
        - Unprofessional/conversational tone
        
        Args:
            content: Polished content from review_content()
            
        Returns:
            (needs_revision: bool, feedback: str)
            Falls back to (False, "") on any error to avoid blocking workflow.
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a strict academic editor.
Evaluate the content below and decide if it needs revision.

CRITERIA FOR REVISION (return needs_revision=true if ANY of these):
- Content is less than 300 words (too short)
- Missing key concepts described in section description
- Contains broken LaTeX (naked math symbols without $)
- Unprofessional or conversational tone

OUTPUT FORMAT (JSON only, no markdown):
{{"needs_revision": true/false, "feedback": "Specific feedback for writer"}}
"""),
            ("user", "Content to evaluate:\n\n{content}")
        ])
        
        try:
            chain = prompt | self.llm
            response = chain.invoke({"content": content})
            
            raw = response.content.strip()  # type: ignore
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].strip()
            
            result = json.loads(raw)
            needs_revision = result.get("needs_revision", False)
            feedback = result.get("feedback", "")
            
            logger.info(f"Quality gate: {'REJECT' if needs_revision else 'APPROVE'} — {feedback[:80]}")
            return needs_revision, feedback
        
        except json.JSONDecodeError as e:
            logger.error(f"Quality gate JSON parse error: {e}")
            return False, ""  # Fallback: approve nếu parse lỗi
        
        except Exception as e:
            logger.error(f"Quality gate unexpected error: {e}", exc_info=True)
            return False, ""  # Fallback: approve để không block workflow

    def review_content(
        self,
        course_topic: str,
        chapter_num: str,
        chapter_title: str,
        section_num: str,
        section_title: str,
        section_description: str,
        draft_content: str,
        chapter_cmd: str
    ) -> str:
        """
        Review and polish drafted content.
        
        Args:
            course_topic: Main topic
            chapter_num: Chapter number
            chapter_title: Chapter title
            section_num: Section number (e.g., "1.2")
            section_title: Section title
            section_description: What this section should cover
            draft_content: Content from Writer
            chapter_cmd: Special LaTeX instructions for chapter headers
            
        Returns:
            Polished content, or original draft on error.
        """
        logger.info(f"Polishing: {section_num} {section_title}")

        if not draft_content or len(draft_content) < 50:
            logger.warning("Draft too short/empty - skipping review")
            return draft_content

        # Reviewer prompt with LaTeX safety rules
        # NOTE: Variables use single braces {var}, LaTeX examples use double braces {{...}}
        reviewer_template = """You are a Senior Technical Editor and LaTeX Specialist for a university textbook publisher.
Your task is to review, polish, and "debug" a specific section drafted by a Writer Agent.
Your ultimate goal is to ensure the content is **Academic**, **Flowing**, and **Compilation-Ready** (Error-free for Pandoc/PDF).

--- CONTEXT & LOCATION ---
- **Book Topic**: {course_topic}
- **Current Chapter**: {chapter_num}. {chapter_title}
- **Current Section**: {section_num}. {section_title}
- **Section Description**: {section_description}

--- DRAFT CONTENT TO REVIEW ---
{draft}

--- EDITING INSTRUCTIONS (STRICT EXECUTION ORDER) ---

### PHASE 1: LATEX & MATH SANITIZATION (CRITICAL PRIORITY)
Your primary responsibility is to prevent PDF generation failures.

1. **Enforce Delimiters (Pandoc Standard)**:
   * **Block Math**: MUST use `$$ ... $$`. REPLACE all `\\[ ... \\]` or `\\begin{{equation}}...\\end{{equation}}` with `$$ ... $$`.
     - ❌ BAD: `\\[ F = ma \\]`
     - ✅ GOOD: `$$ F = ma $$`
   * **Inline Math**: MUST use single `$ ... $`. REPLACE `\\( ... \\)` with `$ ... $`.
     - ❌ BAD: `\\( x = 5 \\)`
     - ✅ GOOD: `$ x = 5 $`

2. **Fix "Naked" Math (The "Missing $" Error)**:
   * Scan text for orphan mathematical symbols, variables, or subscripts/superscripts.
   * **Constraint**: Variables like x, y, z, F, m, a MUST be italicized via math mode.
     - ❌ BAD: Ta có gia tốc a được tính bằng...
     - ✅ GOOD: Ta có gia tốc $a$ được tính bằng...
     - ❌ BAD: a_max = 5
     - ✅ GOOD: $a_{{max}} = 5$

3. **Handle Unicode/Vietnamese inside Math**:
   * LaTeX math mode does NOT support Vietnamese accents directly. You MUST wrap text inside `\\text{{...}}`.
     - ❌ BAD: `$$ v_{{cuối}} = v_{{đầu}} + at $$` (This will crash LaTeX)
     - ✅ GOOD: `$$ v_{{\\text{{cuối}}}} = v_{{\\text{{đầu}}}} + at $$`

4. **Sanitize Environments**:
   * Do NOT use complex environments like `\\begin{{itemize}}`, `\\begin{{tabular}}` inside Markdown. Use standard Markdown lists `*` and Markdown tables `|...|` instead.

### PHASE 2: CONTENT & FLOW REFINEMENT

1. **Structure & Header Hierarchy**:
   {chap_cmd}
   * **Standardization**: Ensure the section starts with Header 2: `## {section_num} {section_title}`.
   * **Hierarchy**: Use Header 3 (`###`) for sub-sections.
   * **Exception**: Do NOT use Header 1 (`#`) **UNLESS** it is the Chapter Title line (e.g., `# CHƯƠNG...`).
   * **Redundancy Check**: If you see patterns like `## 1.1. Mục 1.1...` or `## 1.1. Phần 1.1...`, DELETE the redundant word "Mục/Phần" and keep only `## 1.1 {section_title}`.
   * **Remove Colons**: If you see `## 1.1: Tiêu đề` → Change to `## 1.1 Tiêu đề`.
   * **Preserve LaTeX**: DO NOT remove `\\newpage`, `\\begin{{center}}` or `\\textbf` commands if present.

2. **Academic Tone (Vietnamese)**:
   * Ensure the language is **Formal Vietnamese** (Tiếng Việt học thuật).
   * Eliminate conversational fillers (e.g., "Chúng ta hãy cùng xem...", "Trong phần này tôi sẽ..."). Go straight to the point.
   * **Translation**: Ensure technical terms are handled consistently. Generally, keep standard English terms (like "DataFrame", "CPU", "Marketing Mix") if common, or use standard Vietnamese translations.

3. **Expansion & Filling**:
   * If the draft is too short (< 200 words) or superficial compared to the `{section_description}`, use your internal knowledge to **expand** it. Add definitions, explanations of "Why" and "How".

### PHASE 3: VISUAL PREPARATION (ILLUSTRATOR PREP)

1. **Image Tag Enforcement**:
   * Scan for `> [IMAGE SUGGESTION: ...]` tags.
   * If the section explains a complex concept (e.g., a biological process, a physics diagram, a code architecture) and NO image tag exists, **YOU MUST ADD ONE**.
   * Format: `> [IMAGE SUGGESTION: Detailed description of the image needed for {section_title}]`
**Image Suggestions (Use Sparingly)**:
- Only add `> [IMAGE SUGGESTION: ...]` for truly ESSENTIAL visuals
- Prioritize: diagrams, charts, technical illustrations
- Skip: decorative images, generic photos
- Limit: Maximum 1-2 image suggestions per section

### PHASE 4: FINAL FORMATTING CHECK

* **Bold** key terms upon first mention.
* Ensure Code Blocks have language identifiers (e.g., ```python, ```bash).

---
**OUTPUT REQUIREMENT**:
- Return **ONLY** the final polished Markdown string.
- **NO** conversational preamble (e.g., "Here is the fixed version...").
- **NO** markdown fences around the output (unless part of the content).
"""

        user_template = "Here is the draft to review:\n\n{draft}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", reviewer_template),
            ("user", user_template)
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
                "draft": draft_content,
                "chap_cmd": chapter_cmd
            })
            
            logger.info("✓ Review complete")
            return response.content  # type: ignore
            
        except Exception as e:
            logger.error(f"Error during review: {e}", exc_info=True)
            # Fallback: return original draft to preserve workflow
            return draft_content


def review_section(state: AgentState) -> dict:
    """
    Reviewer node: Polish content then run quality gate.
    
    Workflow integration:
    - Input: state["current_content"] (draft from Writer)
    - Output:
        * If approved: state["current_content"] (polished), review_feedback=""
        * If rejected: state["current_content"] (polished), review_feedback=<feedback>,
                       revision_number incremented → workflow routes back to Writer
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with polished content and review decision.
    """
    logger.info("=" * 60)
    logger.info("NODE: Reviewer - Polishing content")
    logger.info("=" * 60)
    
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    revision_number = state.get("revision_number", 0)
    
    try:
        # Unified curriculum access (Pydantic or dict)
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)
        
        chap_title = chapter.title if hasattr(chapter, 'title') else chapter.get('title', 'Unknown Chapter')
        sec_title = subsection.title if hasattr(subsection, 'title') else subsection.get('title', 'Unknown Section')
        sec_desc = subsection.description if hasattr(subsection, 'description') else subsection.get('description', '')
        
        # Clean section title
        if ":" in sec_title and any(prefix in sec_title for prefix in ["Mục", "Phần", "Bài"]):
            sec_title = sec_title.split(":", 1)[1].strip()
        
        display_chap_num = str(chap_idx + 1)
        display_sec_num = f"{display_chap_num}.{sub_idx + 1}"
        
        # Generate chapter header instruction for first subsection
        chap_cmd_text = ""
        if display_sec_num.endswith(".1"):
            chap_cmd_text = f"""
- **CHECK CHAPTER HEADER**: This is the start of Chapter {display_chap_num}.
- Ensure raw LaTeX commands exist at the top:
  \\newpage
  \\begin{{center}}
  \\Huge \\textbf{{CHƯƠNG {display_chap_num}: {chap_title.upper()}}}
  \\end{{center}}
  \\vspace{{1cm}}
- If they are wrapped in code blocks, UNWRAP them.
"""
        
        draft = state.get("current_content", "")
        
        # Step 1: Polish content
        agent = ReviewerAgent()
        polished = agent.review_content(
            course_topic=state.get("request", "General Topic"),
            chapter_num=display_chap_num,
            chapter_title=chap_title,
            section_num=display_sec_num,
            section_title=sec_title,
            section_description=sec_desc,
            draft_content=draft,
            chapter_cmd=chap_cmd_text
        )
        
        # Step 2: Quality gate — chỉ check nếu chưa vượt quá max revisions
        if revision_number < MAX_REVISIONS:
            needs_revision, feedback = agent.should_revise(polished)
            
            if needs_revision:
                logger.info(
                    f"Revision requested "
                    f"(attempt {revision_number + 1}/{MAX_REVISIONS}): {feedback[:80]}"
                )
                return {
                    "current_content": polished,
                    "review_feedback": feedback,
                    "revision_number": revision_number + 1,
                    "messages": [
                        f"↺ Revision {revision_number + 1}/{MAX_REVISIONS}: {feedback[:80]}"
                    ]
                }
        else:
            logger.warning(
                f"Max revisions ({MAX_REVISIONS}) reached for {display_sec_num} — forcing approval"
            )
        
        # Step 3: Approved (or max revisions reached)
        logger.info(f"✓ Content approved: {display_sec_num} {sec_title}")
        return {
            "current_content": polished,
            "review_feedback": "",   # Clear feedback — signals "approved" to workflow router
            "revision_number": 0,    # Reset cho subsection tiếp theo
            "messages": [
                f"✓ Approved: {display_sec_num} {sec_title} "
                f"(after {revision_number} revision(s))"
            ]
        }
        
    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {
            "current_content": state.get("current_content", ""),
            "review_feedback": "",
            "revision_number": 0,
        }
    
    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {
            "current_content": state.get("current_content", ""),
            "review_feedback": "",
            "revision_number": 0,
        }
    
    except Exception as e:
        logger.error(f"Unexpected error in Reviewer: {e}", exc_info=True)
        return {
            "current_content": state.get("current_content", ""),
            "review_feedback": "",
            "revision_number": 0,
        }