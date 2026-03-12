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
from src.config import LLM_MODEL_CHEAP

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
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0.1)

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
            ("system", """<role>
You are a strict academic quality gate. Your only output is a JSON object. No extra text.
</role>

<evaluation_criteria>
Step 1: Count the words in the content.
Step 2: Return needs_revision=true if ANY of the following is true:
1. Word count is less than 300.
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

        # Reviewer prompt — XML-structured for strict LLM compliance
        # NOTE: Variables use single braces {var}, LaTeX examples use double braces {{...}}
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
1. Chapter header — DO NOT add or modify any # (level-1) heading. The Writer node owns chapter headers exclusively. Your only job here is to ensure the ## section header is correctly formatted.
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

5. Length — if draft is under 200 words, expand using internal knowledge.
   Add definitions, explain the WHY and HOW, provide an example.
</phase>

<phase id="3" name="VISUALS">
PRESERVE all existing > [IMAGE SUGGESTION: ...] tags — do NOT remove them.

ADD new suggestions only where a visual would genuinely aid understanding AND is still missing:
- ADD when: architecture diagrams, flowcharts, process steps, scientific phenomena, data structures
- DO NOT ADD when: pure definition paragraphs, abstract concepts with no visual component, or if
  the surrounding text already conveys everything without a diagram

Quantity rules (mirror the Writer's policy):
- Summary or practice sections (inferable from title/description): max 1 total, prefer 0
- All other sections: up to 3 total, scaled to content complexity — don't pad with weak suggestions

Format: > [IMAGE SUGGESTION: Specific technical description of the required diagram]
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
        
        # Chapter header is owned exclusively by the Writer node (gated by chapter_header_written flag).
        # Reviewer must NOT re-inject it. Only verify it exists if this is the first subsection.
        chap_cmd_text = ""
        if display_sec_num.endswith(".1") and state.get("chapter_header_written", False):
            chap_cmd_text = (
                f"VERIFY ONLY (do NOT add): Confirm a '# CHƯƠNG {display_chap_num}' heading exists "
                f"at the very top of the draft. If missing, that is acceptable — do not add it."
            )
        
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