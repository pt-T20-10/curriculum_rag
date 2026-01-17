from re import sub
import stat
from turtle import update
from typing import final
from src.log_config import setup_logger
from langgraph.graph import StateGraph, END
from src.graph.state import AgentState

# Import các Agent đã viết
from src.agents.planner import plan_curriculum
from src.agents.researcher import perform_research
from src.agents.writer import write_section
from src.agents.publisher import publish_curriculum

logger = setup_logger(name="WorkFlowBuilder", logfile="logs/workflow.log")

def create_workflow():
    """
    Create Graph connect Agents
    """
    
    # 1. Create State Graph with AgentState
    builder = StateGraph(AgentState)
    
    # 2. Define Nodes 
    builder.add_node("planner", plan_curriculum)
    builder.add_node("researcher", perform_research)
    builder.add_node("writer", write_section)
    builder.add_node("publisher", publish_curriculum)
    
    def check_next_step(state: AgentState):
        curriculum = state["curriculum"]
        
        chapter_idx = state["current_chapter_index"]
        sub_idx = state["current_subsection_index"]
        
        current_chapter = curriculum.chapters[chapter_idx] # type: ignore 
        
        #Check if any subsection in current chapter left
        if sub_idx < len(current_chapter.subsections) -1:
            return "continue_subsection"
        #No subsection left check remain chapter
        elif chapter_idx < len(curriculum.chapters) -1: # type: ignore
            return "next_chapter"
        else:
            return "finished"
        
    # Temp node update index
  
        return {
            "current_chapter_index": state["current_chapter_index"] + 1,
            "current_subsection_index": 0
        }
        
    def append_and_update_subsection(state):
        new_content = state.get("current_content", "")
        
        updated_doc = state.get("final_content", "") + "\n\n" + new_content
        
        new_index = state["current_subsection_index"] + 1
        
        logger.info(f"\n Saved section. Moving to subsection {new_index}")
        
        return {
            "current_subsection_index": new_index,
            "final_content": updated_doc,
            "current_content": ""
        }
    def append_and_update_chapter(state):
        new_content = state.get("current_content", "")
        updated_doc = state.get("final_content", "") + "\n\n" + new_content
        
        new_chap = state["current_chapter_index"] + 1
        print(f"\n[SYSTEM] Chapter finished. Moving to Chapter {new_chap}")
        
        return {
            "current_chapter_index": new_chap,
            "current_subsection_index": 0,
            "final_content": updated_doc,
            "current_content": ""
        }
         # 3. Define Entry Point
    builder.set_entry_point("planner")
    
    # 4. Define Edges
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "writer")   
  
        
    builder.add_node("update_subsection", append_and_update_subsection)
    builder.add_node("update_chapter", append_and_update_chapter)
    
    builder.add_conditional_edges(
        "writer",
        check_next_step,
        {
            "continue_subsection":"update_subsection",
            "next_chapter": "update_chapter",
            "finished": "publisher"
        }
    )
    
    builder.add_edge("update_subsection", "researcher")
    builder.add_edge("update_chapter", "researcher")
    
    
    builder.add_edge("publisher", END)
    
    # 6. Compile
    graph = builder.compile()
    return graph
    