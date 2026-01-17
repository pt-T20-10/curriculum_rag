from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.config import LLM_MODEL_NAME
from src.graph.state import AgentState, CurriculumOutline
from src.log_config import setup_logger


#Create LLM
#temperature=0 make sure consistency, reduce hallucinations

llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0)
logger = setup_logger(name="PlannerAgent", logfile="logs/agents.log")
#Promt
system_prompt = """You are an expert curriculum developer capable of designing learning paths for any field (Sciences, Arts, Technology, Business, etc.).
Your goal is to create a detailed, step-by-step curriculum outline based on the user's request.

INSTRUCTIONS:
1. Analyze the user's topic and identify the specific domain.
2. Break it down into logical Chapters (ordered pedagogically from fundamental to advanced).
3. Each Chapter must have specific Subsections.
4. CRITICAL: For each Subsection, generate a 'search_query' optimized for a vector database search.
   - The query must be specific and keyword-rich.
   - Example (History): "Causes of World War I alliance systems"
   - Example (Coding): "Python list comprehension syntax and examples"
"""

planner_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Topic: {request}")       
])

#Create Chain
planner_chain = planner_prompt | llm.with_structured_output(CurriculumOutline)

def plan_curriculum(state: AgentState):
    """
    Node: Generates the curriculum outline base on user request.
    """
    logger.info("--- PLANNER: Generating Curriculum Outline ---")
    user_request = state.get("request", "")
    
    if not user_request:
        logger.error("Usser request is empty!")
        return {"messages": ["ERROR: Input request is missing."]}
    
    try:
        logger.info(f"Sending request to LLM: '{user_request}'")
        #Invoke AI
        curriculum = planner_chain.invoke({"request": user_request})
        
        if not curriculum:
            raise ValueError("LLM returned Empty/None result. Possible JSON parsing error.")
        
        
        #Debug
        logger.info(f"--> Created Plan for Topic: '{curriculum.topic}'")# type: ignore 
        logger.info(f"--> Total Chapters: {len(curriculum.chapters)}") # type: ignore
        for i, chap in enumerate(curriculum.chapters): # type: ignore
            logger.info(f"    [{i+1}] {chap.title} ({len(chap.subsections)} subsections)")
            
        return {
            "curriculum": curriculum,
            
            "final_content": "",  # Khởi tạo bản thảo rỗng
            "current_chapter_index": 0,
            "current_subsection_index": 0
        }
    
    except Exception as e:
        logger.error(f"PLANNER ERROR: {str(e)}")
        
        return {
            "curriculum": None,
            "messages": [f"Planner failed: {str(e)}"]
        }