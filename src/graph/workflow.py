"""
LangGraph workflow orchestration for AI Textbook Generator.

This module constructs the complete workflow graph connecting all agents:
- Ingestion: Load documents into vector DB
- Planning: Generate curriculum outline
- Content Loop: Research → Write → Review → Illustrate (per subsection)
- Publishing: Generate final document

The workflow uses conditional routing to iterate through all chapters and
subsections defined in the curriculum outline.
"""

from enum import Enum

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph  # ← CORRECT IMPORT PATH

from src.graph.state import AgentState
from src.log_config import setup_logger

# Import agent nodes
from src.agents.ingester import perform_ingestion
from src.agents.planner import plan_curriculum
from src.agents.researcher import perform_research
from src.agents.writer import write_section
from src.agents.reviewer import review_section
from src.agents.illustrator import illustrate_section
from src.agents.publisher import publish_curriculum

# Setup logger
logger = setup_logger(name="WorkflowBuilder", logfile="logs/workflow.log")


class WorkflowDecision(str, Enum):
    """Enum for conditional edge routing decisions."""
    CONTINUE_SUBSECTION = "continue_subsection"
    NEXT_CHAPTER = "next_chapter"
    FINISHED = "finished"
    REVISE = "revise"
    APPROVE = "approve"


def route_after_review(state: AgentState) -> str:
    """
    Decision function for conditional routing after review.

    Logic:
    - If review_feedback is non-empty → content was rejected → route back to writer
    - Otherwise → content approved → proceed to illustrator

    Returns:
        WorkflowDecision.REVISE or WorkflowDecision.APPROVE
    """
    feedback = state.get("review_feedback", "")
    if feedback:
        logger.info(f"Review decision: REVISE — feedback: {feedback[:80]}")
        return WorkflowDecision.REVISE
    logger.info("Review decision: APPROVE — proceeding to illustrator")
    return WorkflowDecision.APPROVE


def _accumulate_content(state: AgentState) -> dict:
    """
    Helper function to accumulate current subsection content into final document.
    
    Returns:
        Partial state update with accumulated content and cleared buffer.
    """
    current = state.get("current_content", "")
    final = state.get("final_content", "")
    
    # Only append if there's content to add
    if current:
        accumulated = final + "\n\n" + current if final else current
    else:
        accumulated = final
    
    return {
        "final_content": accumulated,
        "current_content": "",
    }


def append_and_update_subsection(state: AgentState) -> dict:
    """
    Checkpoint node: Save completed subsection and advance to next subsection.
    
    State Changes:
    - Accumulate current_content into final_content
    - Increment current_subsection_index
    - Clear current_content buffer
    - Log milestone
    
    Returns:
        Partial state update for subsection progression.
    """
    current_chapter = state["current_chapter_index"]
    current_subsection = state["current_subsection_index"]
    new_subsection = current_subsection + 1
    
    logger.info(
        f"Checkpoint: Completed Chapter {current_chapter + 1}, "
        f"Subsection {current_subsection + 1} → Moving to Subsection {new_subsection + 1}"
    )
    
    content_update = _accumulate_content(state)
    
    return {
        **content_update,
        "current_subsection_index": new_subsection,
        "messages": [
            f"✓ Completed: Chapter {current_chapter + 1}, Subsection {current_subsection + 1}"
        ]
    }


def append_and_update_chapter(state: AgentState) -> dict:
    """
    Checkpoint node: Save completed chapter and advance to next chapter.
    
    State Changes:
    - Accumulate current_content into final_content
    - Increment current_chapter_index
    - Reset current_subsection_index to 0
    - Clear current_content buffer
    - Log milestone
    
    Returns:
        Partial state update for chapter progression.
    """
    current_chapter = state["current_chapter_index"]
    new_chapter = current_chapter + 1
    
    logger.info(
        f"Checkpoint: Completed Chapter {current_chapter + 1} → "
        f"Moving to Chapter {new_chapter + 1}"
    )
    
    content_update = _accumulate_content(state)
    
    return {
        **content_update,
        "current_chapter_index": new_chapter,
        "current_subsection_index": 0,  # Reset to first subsection of new chapter
        "messages": [
            f"✓ Completed: Chapter {current_chapter + 1} (all subsections)"
        ]
    }


def check_next_step(state: AgentState) -> str:
    """
    Decision function for conditional routing after illustration.
    
    Logic:
    1. If more subsections in current chapter → continue_subsection
    2. Else if more chapters remaining → next_chapter
    3. Else → finished (publish)
    
    Args:
        state: Current workflow state
        
    Returns:
        WorkflowDecision enum value for routing
        
    Raises:
        Falls back to 'finished' on any error for safe termination
    """
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    try:
        # Access curriculum structure (should be CurriculumOutline Pydantic object)
        # Fallback to dict access for compatibility
        if hasattr(curriculum, 'chapters'):
            # Pydantic CurriculumOutline object
            chapters = curriculum.chapters
            current_chapter = chapters[chap_idx]
            subsections = current_chapter.subsections
        else:
            # Dict format (fallback for testing/compatibility)
            chapters = curriculum["chapters"]
            current_chapter = chapters[chap_idx]
            subsections = current_chapter["subsections"]
        
        total_chapters = len(chapters)
        total_subsections = len(subsections)
        
        # Decision logic
        if sub_idx < total_subsections - 1:
            logger.info(
                f"Decision: Continue subsection "
                f"(current: {sub_idx + 1}/{total_subsections})"
            )
            return WorkflowDecision.CONTINUE_SUBSECTION
        
        elif chap_idx < total_chapters - 1:
            logger.info(
                f"Decision: Next chapter "
                f"(current: {chap_idx + 1}/{total_chapters})"
            )
            return WorkflowDecision.NEXT_CHAPTER
        
        else:
            logger.info("Decision: Finished (all chapters and subsections completed)")
            return WorkflowDecision.FINISHED
    
    except IndexError as e:
        logger.error(
            f"Invalid curriculum index access: "
            f"chapter={chap_idx}, subsection={sub_idx}. Error: {e}"
        )
        return WorkflowDecision.FINISHED
    
    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum structure: {e}")
        return WorkflowDecision.FINISHED
    
    except Exception as e:
        logger.error(f"Unexpected error in workflow decision logic: {e}", exc_info=True)
        return WorkflowDecision.FINISHED


def _register_nodes(builder: StateGraph) -> None:
    """
    Register all workflow nodes (agents + utility functions).
    
    Node Types:
    - Agent nodes: External agent functions (planner, writer, etc.)
    - Utility nodes: Internal checkpoint functions (update_subsection, etc.)
    """
    # Agent nodes
    builder.add_node("ingestion", perform_ingestion)
    builder.add_node("planner", plan_curriculum)
    builder.add_node("researcher", perform_research)
    builder.add_node("writer", write_section)
    builder.add_node("reviewer", review_section)
    builder.add_node("illustrator", illustrate_section)
    builder.add_node("publisher", publish_curriculum)
    
    # Utility nodes
    builder.add_node("update_subsection", append_and_update_subsection)
    builder.add_node("update_chapter", append_and_update_chapter)
    
    logger.debug("Registered 9 nodes in workflow graph")


def _define_edges(builder: StateGraph) -> None:
    """
    Define all edges (unconditional and conditional routing).
    
    Edge Types:
    - Unconditional: Always follow fixed path (A → B)
    - Conditional: Decision-based routing (A → B or C or D)
    """
    # Main linear flow
    builder.add_edge("ingestion", "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", "reviewer")

    # Conditional routing after review: reject → writer, approve → illustrator
    builder.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            WorkflowDecision.REVISE: "writer",
            WorkflowDecision.APPROVE: "illustrator",
        }
    )
    
    # Conditional routing after illustration
    builder.add_conditional_edges(
        "illustrator",
        check_next_step,
        {
            WorkflowDecision.CONTINUE_SUBSECTION: "update_subsection",
            WorkflowDecision.NEXT_CHAPTER: "update_chapter",
            WorkflowDecision.FINISHED: "publisher"
        }
    )
    
    # Loop edges (back to researcher for next subsection/chapter)
    builder.add_edge("update_subsection", "researcher")
    builder.add_edge("update_chapter", "researcher")
    
    # Terminal edge
    builder.add_edge("publisher", END)
    
    logger.debug("Defined 11 edges in workflow graph")


def create_workflow() -> CompiledStateGraph:  # ← FIXED RETURN TYPE
    """
    Construct the complete LangGraph workflow connecting all agents.
    
    Workflow Structure:
    1. Ingestion: Load user-uploaded documents into vector DB
    2. Planner: Generate curriculum outline
    3. Loop (per subsection):
       - Researcher: Retrieve RAG context
       - Writer: Generate content
       - Reviewer: Validate quality
       - Illustrator: Add visuals
    4. Publisher: Generate final document
    
    Returns:
        Compiled StateGraph ready for execution.
    """
    logger.info("Building workflow graph...")
    
    # Step 1: Initialize StateGraph with schema
    builder = StateGraph(AgentState)
    
    # Step 2: Register all nodes
    _register_nodes(builder)
    
    # Step 3: Define edges (routing)
    _define_edges(builder)
    
    # Step 4: Set entry point
    builder.set_entry_point("ingestion")
    
    # Step 5: Compile and validate
    graph = builder.compile()
    logger.info("✓ Workflow graph compiled successfully")
    
    return graph