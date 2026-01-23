import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.log_config import setup_logger
from src.graph.state import AgentState
from src.config import LLM_MODEL_NAME

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")

class ReviewerAgent:
    """
    Reviewer Agent (The Editor):
    Nhiệm vụ: Đọc bản nháp (Draft) từ Writer và tinh chỉnh lại.
    Mục tiêu: Chính xác, Học thuật, Trình bày đẹp, Fix lỗi LaTeX.
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
        Input: Bản nháp thô và Metadata.
        Output: Bản thảo đã biên tập.
        """
        logger.info(f"   🧐 Reviewer is polishing: '{section_title}'...")

        if not draft_content or len(draft_content) < 50:
            logger.warning("   ⚠️ Draft is too short/empty. Skipping review.")
            return draft_content

        # --- REVIEWER PROMPT (ENHANCED VERSION) ---
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

        ### PHASE 2: CONTENT & FLOW REFINEMENT
        1.  **Header Hierarchy Check:** Ensure correct Header 2 (`##`) and Header 3 (`###`).
        2.  **Academic Tone:** Ensure formal Vietnamese.
        3.  **Expansion:** If draft is too short (< 200 words), expand it.

        ### PHASE 3: VISUAL PREPARATION
        1.  **Image Tag Enforcement:** Add `> [IMAGE SUGGESTION: ...]` if missing for complex concepts.

        ---
        **OUTPUT REQUIREMENT:**
        - Return **ONLY** the final polished Markdown string.
        """

        user_prompt = f"Please review and fix the following draft:\n\n{draft_content}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", reviewer_template),
            ("user", user_prompt)
        ])

        try:
            chain = prompt | self.llm
            # --- FIX: TRUYỀN ĐỦ BIẾN VÀO INVOKE ---
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
            return response.content #type: ignore
        except Exception as e:
            logger.error(f"Error in Reviewer: {e}")
            return draft_content

# --- LANGGRAPH NODE FUNCTION ---
# Hàm này dùng để gọi Reviewer trong LangGraph Workflow
def review_section(state: AgentState):
    logger.info(f"---REVIEWER: Polishing Content ---")
    
    # 1. Get Metadata from State
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    # Handle Dict vs Object (để tương thích cả cũ và mới)
    if isinstance(curriculum, dict):
        current_chapter = curriculum['chapters'][chap_idx]
        current_subsection = current_chapter['sections'][sub_idx] # string title
        
        chap_title = current_chapter['chapter_title']
        sec_title = current_subsection
        sec_desc = f"Review content for {sec_title}"
    else:
        current_chapter = curriculum.chapters[chap_idx] # type: ignore
        current_subsection = current_chapter.subsections[sub_idx]
        
        chap_title = current_chapter.title
        sec_title = current_subsection.title
        sec_desc = current_subsection.description
        
    display_chap_num = str(chap_idx + 1)
    display_sec_num = f"{display_chap_num}.{sub_idx + 1}"
    
    draft = state.get("current_content", "")
    
    # 2. Call Reviewer Agent
    agent = ReviewerAgent()
    
    # --- FIX: GỌI HÀM VỚI ĐỦ THAM SỐ ---
    polished_content = agent.review_content(
        course_topic=state.get("request", "General Topic"),
        chapter_num=display_chap_num,
        chapter_title=chap_title,
        section_num=display_sec_num,
        section_title=sec_title,
        section_description=sec_desc,
        draft_content=draft
    )
    
    return {"current_content": polished_content}