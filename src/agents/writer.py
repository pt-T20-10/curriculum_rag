import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.log_config import setup_logger
from src.graph.state import AgentState
from src.config import LLM_MODEL_NAME

logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")

class WriterAgent:
    """
    Writer Agent:
    Responsible for synthesizing retrieved context into high-quality textbook content.
    Specialized in producing Markdown that compiles safely to PDF via LaTeX.
    """
    def __init__(self):
        # Temperature = 0.4: Cân bằng giữa sự sáng tạo và tính chính xác
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.4)

    def write_section(self, course_topic: str, chapter_num: int, chapter_title: str, 
                      section_num: str, section_title: str, section_description: str, context: str) -> str:
        """
        Generate content for a specific section using RAG context.
        """
        logger.info(f"   ✍️  Writer is composing: '{section_title}'...")

        # --- WRITER PROMPT (LATEX SAFE VERSION) ---
        # LƯU Ý KỸ THUẬT: 
        # 1. Các biến cần thay thế dùng 1 dấu ngoặc nhọn: {context}
        # 2. Các ví dụ về code/latex trong prompt phải dùng 2 dấu ngoặc nhọn để escape: {{ }}
        
        system_prompt = """You are an expert educational content creator, capable of writing high-quality textbook material for any subject (Science, History, Technology, Arts, etc.).

---CONTEXT AND LOCATION---
You are currently writing:
- **Book Topic**: {course_topic}
- **Chapter {chapter_num}: ** {chapter_title}
- **Section {section_num}: ** {section_title}
- **Description:** {section_description}

RESEARCH CONTEXT: (From Vector DB)
{context}

--- WRITING RULES (STRICT)---
1. ADAPT YOUR TONE:
   - For IT/Engineering: Be precise, practical. Use code blocks for examples.
   - For History/Arts: Be narrative, engaging. Use dates and cultural context.
   - For Science: Be rigorous, explanatory. Use formulas if needed (LaTeX).

2. FORMATTING:
   - Write in clear, academic but accessible Markdown.
   - Use bolding for key terms.
   - Use lists/bullet points for readability.

3. CONTENT:
   - Explain the concept clearly.
   - Provide relevant examples based on the domain.
   - If the context provided is empty/irrelevant, use your general knowledge but mention that specific textbook references were missing.

4. STRUCTURE & NUMBERING:
   - Start immediately with a level 2 Header: `## {section_num}. {section_title}`
   - Use level 3 Headers (`###`) for sub-points.
   - DO NOT output Chapter Title (it is handled elsewhere)

5. **Content Depth (CRITICAL):**
   - **Target Length:** Write approximately **800-1000 words** (Comprehensive coverage).
   - **No Fluff:** Do not summarize. Explain concepts in depth (The "Why" and "How").
   - **Academic Tone:** Formal, precise, but accessible (like a professor teaching).

6. **Required Elements:**
   - **Key Terminology:** Bold important terms.
   - **Examples:** Provide concrete, real-world examples.
   - **Math & LaTeX Rules (CRITICAL FOR PDF GENERATION):**
     - **Block Math:** ALWAYS use double dollar signs `$$ ... $$` on new lines.
       - ❌ BAD: `\\[ E = mc^2 \\]`
       - ✅ GOOD: `$$ E = mc^2 $$`
     - **Inline Math:** Use single dollar signs `$ ... $`.
       - ✅ GOOD: The force is $F$.
     - **No Naked Math:** NEVER use LaTeX commands (like `_`, `^`, `\\frac`) without `$`.
       - ❌ BAD: a_x = 5
       - ✅ GOOD: $a_x = 5$
       - ❌ BAD: \\frac{{d}}{{t}}  <-- (Writer note: avoid raw latex commands outside dollars)
       - ✅ GOOD: $\\frac{{d}}{{t}}$
     - **Avoid Complex Environments:** Do not use `\\begin{{equation}}` or `\\usepackage`. Stick to standard math mode.

   - **Visuals:** Add a placeholder for diagrams: `> [IMAGE SUGGESTION: Describe the image needed here]`

7. **Missing Info:**
   - If the Research Material is thin, use your internal expert knowledge to fill gaps.
   - Connect this section to the broader Chapter theme.
   
OUTPUT LANGUAGE: VIETNAMESE (Tiếng Việt).
"""

        # USER PROMPT
        user_prompt = f"""
        Please write the content for section **{section_num}: {section_title}**.
        """

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", user_prompt)
        ])

        try:
            # Truyền đúng các biến vào template
            chain = prompt | self.llm
            response = chain.invoke({
                "course_topic": course_topic,
                "chapter_num": chapter_num,
                "chapter_title": chapter_title,
                "section_num": section_num,
                "section_title": section_title,
                "section_description": section_description,
                "context": context
            })
            return response.content #type: ignore
        except Exception as e:
            logger.error(f"Error in Writer: {e}")
            return "(Lỗi: Không thể tạo nội dung cho phần này. Vui lòng kiểm tra Log.)"

# --- LANGGRAPH NODE FUNCTION ---
def write_section(state: AgentState):
    logger.info("--- WRITER NODE: Drafting Content ---")
    
    # 1. Lấy thông tin vị trí từ State
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    # Xử lý tương thích cả Dict và Object
    if isinstance(curriculum, dict):
        current_chapter = curriculum['chapters'][chap_idx]
        current_subsection = current_chapter['sections'][sub_idx] # Đây là string tiêu đề
        
        chap_title = current_chapter['chapter_title']
        sec_title = current_subsection
        sec_desc = f"Learn about {sec_title}" # Dict từ Planner không có desc, tự generate
    else:
        # Nếu dùng Pydantic Model (Future proof)
        current_chapter = curriculum.chapters[chap_idx] # type: ignore
        current_subsection = current_chapter.subsections[sub_idx]
        
        chap_title = current_chapter.title
        sec_title = current_subsection.title
        sec_desc = current_subsection.description

    # Số thứ tự hiển thị
    display_chap_num = chap_idx + 1
    display_sec_num = f"{display_chap_num}.{sub_idx + 1}"

    # 2. Lấy Context từ Researcher
    messages = state["messages"]
    context = messages[-1] if messages else "No context found."

    # 3. Gọi Agent
    agent = WriterAgent()
    content = agent.write_section(
        course_topic=state.get("request", "General Topic"),
        chapter_num=display_chap_num,
        chapter_title=chap_title,
        section_num=display_sec_num,
        section_title=sec_title,
        section_description=sec_desc,
        context=context
    )
    
    # 4. Trả về
    return {"current_content": content}