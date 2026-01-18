from email import message
from os import write

from sympy import content
from src.log_config import setup_logger
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.graph.state import AgentState
from src.config import LLM_MODEL_NAME


logger = setup_logger(name="WriterAgent", logfile="logs/agents.log")

# 1. Initialize LLM
# Writer needs creativity, so we can increase temperature slightly if desired.
llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.4)

# 2. Define Prompt
writer_template = """You are an expert educational content creator, capable of writing high-quality textbook material for any subject (Science, History, Technology, Arts, etc.).

---CONTEXT AND LOCATION---
You are currently writing:
- **Book Topic***: {course_topic}
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
   - **Target Length:** Write at least **800-1000 words**.
   - **No Fluff:** Do not summarize. Explain concepts in depth (The "Why" and "How").
   - **Academic Tone:** Formal, precise, but accessible (like a professor teaching).

6. **Required Elements:**
   - **Key Terminology:** Bold important terms.
   - **Examples:** Provide concrete, real-world examples.
   - **Code/Math:** If the topic involves coding/math, use code blocks or LaTeX ($E=mc^2$).
   - **Visuals:** Add a placeholder for diagrams: `> [IMAGE SUGGESTION: Describe the image needed here]`

7. **Missing Info:**
   - If the Research Material is thin, use your internal expert knowledge to fill gaps. 
   - Connect this section to the broader Chapter theme.
"""

writer_prompt = ChatPromptTemplate.from_messages([
    ("system", writer_template),
    ("human", "Write the section content now.")
])
writer_chain = writer_prompt | llm | StrOutputParser()

def write_section(state: AgentState):
    """
        Node: Synthesizes research and writes the section 
    """
    logger.info("---WRITTER: Drafting Content (Deep Mode)---")
    # 1. Get Metadata
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    current_chapter = curriculum.chapters[chap_idx] # type: ignore
    current_subsection = current_chapter.subsections[sub_idx] # type: ignore
    
    #Calculate number indexes 
    display_chap_num = chap_idx + 1
    display_sec_num = f"{display_chap_num}.{sub_idx +1 }"
    
    # 2. Get Research Context
    messages = state["messages"]
    
    if messages:
        latest_message = messages[-1]
    else:
        latest_message = "No research context provided."
        
    # 3. Invoke LLM
    try:
        logger.info(f"Writing Section {display_chap_num}: {current_subsection.title}...")
        content = writer_chain.invoke({
            "course_topic": state.get("request", "General Knowledge"),
            "chapter_num": display_chap_num,
            "chapter_title": current_chapter.title,
            "section_num": display_sec_num,
            "section_title": current_subsection.title,
            "section_description": current_subsection.description,
            "context": latest_message
        })
        logger.info(f"Drafted {len(content)} charcters for '{current_subsection.title}'")
        
        return {"current_content": content}
    
    except Exception as e:
        logger.error(f"Writting failed: {e}")
        return {"current_content":f"## {display_sec_num}. {current_subsection.title}\n\nError generating content."}