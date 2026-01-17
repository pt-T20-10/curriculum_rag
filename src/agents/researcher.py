from re import search
from src.log_config import setup_logger

from yarl import Query
from src.graph.state import AgentState
from src.tools.search_tool import search_knowlege_base

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")

def perform_research(state: AgentState):
    """
    Node: Executes the search query defined by the Planner for current subsection.
    """
    
    logger.info("---RESEARCHER: Searching Knowledge Base ---")
    
    #1. Identify "Where are we?"
    
    curriculum = state["curriculum"]
    
    chap_idx = state["current_chapter_index"]
    
    sub_idx = state["current_subsection_index"]
    
    #Get the specific subsection object
    current_chapter = curriculum.chapters[chap_idx] # type: ignore
    current_subsections = current_chapter.subsections[sub_idx] #type: ignore
    
    query = current_subsections.search_query
    topic = current_subsections.title 
    
    logger.info(f"Targer: Chapter {chap_idx+1}, Subsection {sub_idx+1}: '{topic}")
    logger.info(f"Query: '{query}'")
    
    #2. Execute Search (Use tool)
    #Since search_knowledge_base is a LangChain tool, we use .invoke()
    
    try:
        search_results= search_knowlege_base.invoke(query)
    except Exception as e:
            logger.error(f"Search failed: {e}")
            search_results = "Error: Could not retrieve information"
            
    # 3. Pass results for the next node (Writer)
    # Append a message formatted specifically for the Writer to read
    research_note = f"""
    --- RESEARCH MATERIAL FOR: {topic}---
    QUERY USED: {query}
    
    CONTEXT FROM DATABASE:
    {search_results}
    """
    
    return {"messages": [research_note]}