from langgraph.graph import StateGraph, END
from src.graph.state import AgentState
from src.log_config import setup_logger

# Import các Agent cũ
from src.agents.planner import plan_curriculum
from src.agents.researcher import perform_research
from src.agents.writer import write_section
from src.agents.publisher import publish_curriculum
from src.agents.reviewer import review_section
from src.agents.illustrator import illustrate_section

# --- IMPORT NODE MỚI ---
from src.agents.ingestion_agent import perform_ingestion

logger = setup_logger(name="WorkFlowBuilder", logfile="logs/workflow.log")

def create_workflow():
    """
    Create Graph connect Agents (Full Flow: Ingest -> Plan -> Write -> Publish)
    """
    
    # 1. Create State Graph
    builder = StateGraph(AgentState)
    
    # 2. Define Nodes 
    builder.add_node("ingestion", perform_ingestion) # <--- NODE MỚI
    builder.add_node("planner", plan_curriculum)
    builder.add_node("researcher", perform_research)
    builder.add_node("writer", write_section)
    builder.add_node("reviewer", review_section)
    builder.add_node("illustrator", illustrate_section)
    builder.add_node("publisher", publish_curriculum)
    
    # Logic cập nhật trạng thái (giữ nguyên)
    def append_and_update_subsection(state):
        new_content = state.get("current_content", "")
        updated_doc = state.get("final_content", "") + "\n\n" + new_content
        new_index = state["current_subsection_index"] + 1
        logger.info(f"\n Saved section. Moving to subsection {new_index}")
        return {
            "current_subsection_index": new_index,
            "final_content": updated_doc,
            "current_content": "",
            "messages": [] # Clear context cũ
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
            "current_content": "",
            "messages": []
        }

    builder.add_node("update_subsection", append_and_update_subsection)
    builder.add_node("update_chapter", append_and_update_chapter)
    
    # 3. Define Entry Point
    # --- THAY ĐỔI QUAN TRỌNG: BẮT ĐẦU TỪ INGESTION ---
    builder.set_entry_point("ingestion")
    
    # 4. Define Edges (Luồng đi)
    builder.add_edge("ingestion", "planner")    # Ingest xong -> Plan
    builder.add_edge("planner", "researcher")   # Plan xong -> Research
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_edge("reviewer", "illustrator")
    # 5. Conditional Edges (Giữ nguyên)
    def check_next_step(state: AgentState):
        curriculum = state["curriculum"]
        chap_idx = state["current_chapter_index"]
        sub_idx = state["current_subsection_index"]
        
        try:
            if isinstance(curriculum, dict):
                chapters = curriculum['chapters']
                current_chap = chapters[chap_idx]
                
                # --- DEFENSIVE CHECK ---
                if 'subsections' in current_chap:
                    items = current_chap['subsections']
                elif 'sections' in current_chap:
                    items = current_chap['sections']
                else:
                    items = []
                
                total_chaps = len(chapters)
            else:
                chapters = curriculum.chapters
                current_chap = chapters[chap_idx]
                items = current_chap.subsections
                total_chaps = len(chapters)

            if sub_idx < len(items) - 1:
                return "continue_subsection"
            elif chap_idx < total_chaps - 1:
                return "next_chapter"
            else:
                return "finished"
        except Exception as e:
            logger.error(f"Workflow Logic Error: {e}")
            return "finished" # Dừng an toàn
        
    builder.add_conditional_edges(
        "illustrator",
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

