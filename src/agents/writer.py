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
                      section_num: str, section_title: str, section_description: str, context: str, chapter_instruction: str) -> str:
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
    **Header Formatting (STRICT):**
           {chapter_instruction}
           - **Section Header:** Start immediately with Header 2: `## {section_num} {section_title}`
           - **Clean Titles:** - ❌ BAD: `## 1.1. Mục 1.1 Khái niệm` (Double numbering/Redundant text)
             - ❌ BAD: `## 1.1. 1.1. Khái niệm`
             - ✅ GOOD: `## 1.1. Khái niệm`
             - **IMPORTANT:** Use a SPACE between the number and title. DO NOT use colons (`:`) or extra dots.
            - ❌ WRONG: `## 1.1: Khái niệm`, `## 1.1. Khái niệm`
            - ✅ RIGHT: `## 1.1 Khái niệm`
           - **Sub-points:** Use Header 3 (`###`). Never use Header 1 (`#`) inside the section body.

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
                "context": context,
                "chapter_instruction": chapter_instruction
            })
            return response.content #type: ignore
        except Exception as e:
            logger.error(f"Error in Writer: {e}")
            return "(Lỗi: Không thể tạo nội dung cho phần này. Vui lòng kiểm tra Log.)"

# --- LANGGRAPH NODE FUNCTION ---
def write_section(state: AgentState):
    logger.info("--- WRITER NODE: Drafting Content ---")
    
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    try:
        if isinstance(curriculum, dict):
            current_chapter = curriculum['chapters'][chap_idx]
            
            # --- DEFENSIVE ACCESS (Hỗ trợ cả 2 key) ---
            if 'subsections' in current_chapter:
                items = current_chapter['subsections']
                is_complex = True
            elif 'sections' in current_chapter:
                items = current_chapter['sections']
                is_complex = False
            else:
                raise KeyError("Missing sections key")
            
            current_item = items[sub_idx]
            
            chap_title = current_chapter.get('title', current_chapter.get('chapter_title', 'Unknown Chapter'))
            
            if is_complex:
                raw_sec_title = current_item.get('title', 'Unknown')
                sec_desc = current_item.get('description', '')
            else:
                raw_sec_title = current_item
                sec_desc = f"Write about {raw_sec_title}"
                
        else:
            current_chapter = curriculum.chapters[chap_idx]
            current_item = current_chapter.subsections[sub_idx]
            chap_title = current_chapter.title
            raw_sec_title = current_item.title
            sec_desc = current_item.description
        
        if ":" in raw_sec_title and any(x in raw_sec_title for x in ["Mục", "Phần", "Bài"]):
             sec_title_clean = raw_sec_title.split(":", 1)[1].strip()
        else:
             sec_title_clean = raw_sec_title
        
        display_chap = str(chap_idx + 1)
        display_sec = f"{display_chap}.{sub_idx + 1}"
        
        # 3. --- LOGIC TẠO INSTRUCTION (TẠO CHUỖI TẠI ĐÂY) ---
        is_first_sub = display_sec.endswith(".1")
        chapter_instruction_text = "" # Mặc định rỗng
        
        if is_first_sub:
            # Điền luôn giá trị vào chuỗi Python này trước khi gửi cho LangChain
            chapter_instruction_text = f"""
            **SPECIAL INSTRUCTION (NEW CHAPTER):**
            - This is the start of Chapter {display_chap}.
            - Insert these RAW LaTeX commands at the very top (DO NOT use markdown code blocks):
            
            \\newpage
            \\begin{{center}}
            \\Huge \\textbf{{CHƯƠNG {display_chap}: {chap_title.upper()}}}
            \\end{{center}}
            \\vspace{{1cm}}
            """

        messages = state["messages"]
        context = messages[-1] if messages else ""
        
        agent = WriterAgent()
        content = agent.write_section(
            course_topic=state.get("request", "Topic"),
            chapter_num=display_chap, # type: ignore
            chapter_title=chap_title,
            section_num=display_sec,
            section_title=sec_title_clean,
            section_description=sec_desc,
            context=context,
            chapter_instruction=chapter_instruction_text 
        )
        
        return {"current_content": content}

    except Exception as e:
        logger.error(f"Error in Writer Node: {e}")
        return {"current_content": ""}