import logging
import stat
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.log_config import setup_logger
from src.graph.state import AgentState
from src.config import LLM_MODEL_NAME

logger = setup_logger(name="ReviewerAgent", logfile="logs/agents.log")

# Reviewer needs high accuracy, low temperature
llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.1)

# --- REVIEWER PROMPT ---
# LƯU Ý: Các ví dụ LaTeX bên dưới đã được escape bằng {{ }}
# --- REVIEWER PROMPT (FINAL FIXED VERSION) ---
# LƯU Ý: Đã dùng {{ }} để escape dấu ngoặc nhọn, tránh lỗi LangChain Missing Variable
reviewer_template = """You are a Senior Technical Editor for a university textbook publisher. Your task is to review and polish a specific section drafted by a Writer Agent. Your goal is to ensure the content is perfect for PDF publication via LaTeX/Pandoc.

--- CONTEXT & LOCATION ---
- **Book topic**: {course_topic}
- **Current Chapter**: {chapter_num}. {chapter_title}
- **Current Section**: {section_num}. {section_title}
- **Section Description**: {section_description}

--- DRAFT CONTENT TO REVIEW ---
{draft}

--- EDITING INSTRUCTIONS ---

1. **LATEX SAFETY & STANDARDIZATION (CRITICAL PRIORITY):**
   - **Rule A: Enforce Delimiters (Pandoc Friendly):**
     - **Block Math:** You MUST use `$$ ... $$` for standalone equations. REPLACE all `\\[ ... \\]` with `$$ ... $$`.
       - ❌ BAD: `\\[ F = ma \\]`
       - ✅ GOOD: `$$ F = ma $$`
     - **Inline Math:** Use single `$` ... `$`.
       - ❌ BAD: `\\( x = 5 \\)`
       - ✅ GOOD: `$ x = 5 $`

   - **Rule B: Fix "Naked" Math (The "Missing $" Error):**
     - Scan specifically for subscript (`_`), superscript (`^`), and commands (`\\frac`, `\\cdot`, `\\sum`, `\\Delta`).
     - If they appear outside of `$`, **YOU MUST WRAP THEM**.
       - ❌ BAD: The value of a_x is calculated by...
       - ✅ GOOD: The value of $a_x$ is calculated by...
       - ❌ BAD: F_{{net}} = m \\cdot a
       - ✅ GOOD: $F_{{net}} = m \\cdot a$

   - **Rule C: Remove Redundant Wrappers:**
     - Do not combine text parentheses with LaTeX escapes.
       - ❌ BAD: `\\($E=mc^2$)`  <-- This crashes PDF generation.
       - ✅ GOOD: `($E=mc^2$)`   <-- Standard text parentheses around math.
       - ❌ BAD: `$$\\[ F=ma \\]$$`
       - ✅ GOOD: `$$ F=ma $$`

2. **Verify Context Alignment:**
    - Ensure the content ACTUALLY addresses the section title: "{section_title}".
    - Check if the Header Numbering in the draft matches the Source of Truth ({section_num}). If not, FIX IT.

3. **Protect Technical Integrity:**
    - **DO NOT** remove valid math logic.
    - **DO NOT** change the logic of code blocks.
    - Ensure key terms defined in the text are **bolded**.
    - Ensure text inside math equations uses `\\text{{...}}` (e.g., $v_{{\\text{{final}}}}$).
    
4. **Tone & Flow:**
    - The tone must be **Academic but Accessible**.
    - Fix choppy sentences. Ensure logical transitions between paragraphs.
    - If the content is too short or shallow relative to the description, expand it using your internal knowledge.
    
5. **Formatting:**
    - Ensure the output is valid Markdown.
    - Check for the existence of `[IMAGE SUGGESTION: ...]` tags.
    
OUTPUT: 
    - Return ONLY the **FINAL POLISHED MARKDOWN**. 
    - DO NOT add comments like "Here is the reviewed version".
"""
reviewer_prompt = ChatPromptTemplate.from_messages([
    ("system", reviewer_template),
    ("human", "Review and polish this draft.")
])

reviewer_chain = reviewer_prompt | llm | StrOutputParser()

def review_section(state: AgentState):
    """
    Node: Reviewer (Editor) reads the draft and returns the polished version.
    """
    logger.info(f"---REVIEWER: Polishing Content ---")
    # 1. Getting medatadas (syn writer)
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    current_chapter = curriculum.chapters[chap_idx] # type: ignore
    current_subsection = current_chapter.subsections[sub_idx] 
    
    display_chap_num = chap_idx + 1
    display_sec_num = f"{display_chap_num}.{sub_idx + 1}"
    
    draft = state.get("current_content", "") # type: ignore
    
    #Safety check
    if not draft:
        logger.warning("Reviewer received empty draft.")
        return {"current_content": ""}
    
    #2. Call Editor with full context
    try:
        polished_content = reviewer_chain.invoke({
            "course_topic": state.get("request", "General Knowledge"),
            "chapter_num": display_chap_num,
            "chapter_title": current_chapter.title,
            "section_num": display_sec_num,
            "section_title": current_subsection.title,
            "section_description": current_subsection.description,
            "draft": draft
        })
        
        logger.info(f"Polished content length: {len(polished_content)} chars")
        
        return {"current_content": polished_content}
    
    except Exception as e:
        logger.error(f"Reviewer error: {e}")
        return {"current_content": draft}