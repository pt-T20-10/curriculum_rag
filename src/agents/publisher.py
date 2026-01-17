import os
from pathlib import Path
from venv import logger
from src.graph.state import AgentState
from src.config import BASE_DIR

from src.log_config import setup_logger

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")

def publish_curriculum(state: AgentState):
    """
        Final node: Save all contents to Markdown file
    """
    logger.info("\n --- PUBLISHER: Saving Final Document ---")
    
    # Get contents
    full_content = state.get("final_content","")
    topic = state.get("request", "curriculum").replace(" ","_")
    
    if not full_content:
        return {"messages": ["Error: No content to publish"]}
    
    output_dir = BASE_DIR/ "outputs"
    output_dir.mkdir(exist_ok=True)
    
    filename = output_dir / f"{topic}_Textbook.md"
    
    with open(filename, "w", encoding="utf-8") as f:
            # Thêm tiêu đề lớn
            header = f"# GENERATED TEXTBOOK: {state['request']}\n\n"
            f.write(header + full_content)
            
    print(f"✅ BOOK SAVED TO: {filename}")
        
    return {"messages": [f"Published to {filename}"]}