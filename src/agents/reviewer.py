import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from src.log_config import setup_logger
from src.graph.state import AgentState
from src.config import LLM_MODEL_NAME

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")

class ReviewerAgent:
    """
    Reviewer Agent (The Editor):
    Task: Review Draft from Writer.
    Goal: Accurate, Academic, Flowing, and LaTeX Error-Free (for PDF).
    """
    def __init__(self):
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.1)

    def review_content(self, 
                       course_topic: str,
                       chapter_num: str, 
                       chapter_title: str, 
                       section_num: str, 
                       section_title: str, 
                       section_description: str,
                       draft_content: str) -> str:
        """
        Input: Draft content and Metadata.
        Output: Polished content.
        """
        logger.info(f"   🧐 Reviewer is polishing: '{section_title}'...")

        if not draft_content or len(draft_content) < 50:
            logger.warning("   ⚠️ Draft is too short/empty. Skipping review.")
            return draft_content

        # --- REVIEWER PROMPT (SAFE VERSION) ---
        # CRITICAL RULE: 
        # 1. Variables to replace: Use single braces -> {draft}
        # 2. LaTeX/Code examples: Use DOUBLE braces -> {{equation}}, a_{{max}}
        
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
        1.  **Enforce Delimiters (Pandoc Standard):**
            * **Block Math:** MUST use `$$ ... $$`. REPLACE all `\\[ ... \\]` or `\\begin{{equation}}...\\end{{equation}}` with `$$ ... $$`.
                * ❌ BAD: `\\[ F = ma \\]`
                * ✅ GOOD: `$$ F = ma $$`
            * **Inline Math:** MUST use single `$` ... `$`. REPLACE `\\( ... \\)` with `$ ... $`.
                * ❌ BAD: `\\( x = 5 \\)`
                * ✅ GOOD: `$ x = 5 $`

        2.  **Fix "Naked" Math (The "Missing $" Error):**
            * Scan text for orphan mathematical symbols, variables, or subscripts/superscripts.
            * **Constraint:** Variables like x, y, z, F, m, a MUST be italicized via math mode.
                * ❌ BAD: Ta có gia tốc a được tính bằng...
                * ✅ GOOD: Ta có gia tốc $a$ được tính bằng...
                * ❌ BAD: a_max = 5
                * ✅ GOOD: $a_{{max}} = 5$

        3.  **Handle Unicode/Vietnamese inside Math:**
            * LaTeX math mode does NOT support Vietnamese accents directly. You MUST wrap text inside `\\text{{...}}`.
                * ❌ BAD: `$$ v_{{cuối}} = v_{{đầu}} + at $$`  (This will crash LaTeX)
                * ✅ GOOD: `$$ v_{{\\text{{cuối}}}} = v_{{\\text{{đầu}}}} + at $$`

        4.  **Sanitize Environments:**
            * Do NOT use complex environments like `\\begin{{itemize}}`, `\\begin{{tabular}}` inside Markdown. Use standard Markdown lists `*` and Markdown tables `|...|` instead.

        ### PHASE 2: CONTENT & FLOW REFINEMENT
        1.  **Header Hierarchy Check:**
            * Ensure the draft starts with the correct Header 2: `## {section_num}. {section_title}`.
            * Ensure sub-points use Header 3 (`###`) or Header 4 (`####`). DO NOT use Header 1 (`#`).
            * **Fix Hanging Headers:** Never leave a Header without content below it.

        2.  **Academic Tone (Vietnamese):**
            * Ensure the language is **Formal Vietnamese** (Tiếng Việt học thuật).
            * Eliminate conversational fillers (e.g., "Chúng ta hãy cùng xem...", "Trong phần này tôi sẽ..."). Go straight to the point.
            * *Translation:* Ensure technical terms are handled consistently. Generally, keep standard English terms (like "DataFrame", "CPU", "Marketing Mix") if common, or use standard Vietnamese translations.

        3.  **Expansion & Filling:**
            * If the draft is too short (< 200 words) or superficial compared to the `{section_description}`, use your internal knowledge to **expand** it. Add definitions, explanations of "Why" and "How".

        ### PHASE 3: VISUAL PREPARATION (ILLUSTRATOR PREP)
        1.  **Image Tag Enforcement:**
            * Scan for `> [IMAGE SUGGESTION: ...]` tags.
            * If the section explains a complex concept (e.g., a biological process, a physics diagram, a code architecture) and NO image tag exists, **YOU MUST ADD ONE**.
            * Format: `> [IMAGE SUGGESTION: Detailed description of the image needed for {section_title}]`

        ### PHASE 4: FINAL FORMATTING CHECK
        * **Bold** key terms upon first mention.
        * Ensure Code Blocks have language identifiers (e.g., ```python, ```bash).

        ---
        **OUTPUT REQUIREMENT:**
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
                "draft": draft_content
            })
            logger.info("   ✅ Review complete.")
            return response.content # type: ignore
        except Exception as e:
            logger.error(f"Error in Reviewer: {e}")
            # Fallback: return draft if reviewer fails to preserve workflow
            return draft_content

# --- LANGGRAPH NODE FUNCTION ---
def review_section(state: AgentState):
    logger.info(f"---REVIEWER: Polishing Content ---")
    
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    try:
        if isinstance(curriculum, dict):
            current_chapter = curriculum['chapters'][chap_idx]
            
            # --- DEFENSIVE ACCESS ---
            if 'subsections' in current_chapter:
                items = current_chapter['subsections']
                is_complex = True
            elif 'sections' in current_chapter:
                items = current_chapter['sections']
                is_complex = False
            else:
                # Nếu không tìm thấy, giả lập dữ liệu để không crash
                items = ["Unknown Section"]
                is_complex = False
            
            current_item = items[sub_idx]
            chap_title = current_chapter.get('title', current_chapter.get('chapter_title', 'Unknown'))
            
            if is_complex:
                sec_title = current_item.get('title', 'Unknown') #type: ignore
                sec_desc = current_item.get('description', '')#type: ignore
            else:
                sec_title = current_item
                sec_desc = ''
        else:
            current_chapter = curriculum.chapters[chap_idx]
            current_item = current_chapter.subsections[sub_idx]
            chap_title = current_chapter.title
            sec_title = current_item.title
            sec_desc = current_item.description
            
        display_chap_num = str(chap_idx + 1)
        display_sec_num = f"{display_chap_num}.{sub_idx + 1}"
        
        draft = state.get("current_content", "")
        
        agent = ReviewerAgent()
        polished = agent.review_content(
            course_topic=state.get("request", "General Topic"),
            chapter_num=display_chap_num,
            chapter_title=chap_title,
            section_num=display_sec_num,
            section_title=sec_title,
            section_description=sec_desc,
            draft_content=draft
        )
        
        return {"current_content": polished}
        
    except Exception as e:
        logger.error(f"Reviewer Error: {e}")
        return {"current_content": state.get("current_content", "")} # Trả về bản gốc