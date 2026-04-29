"""
Workflow runner - Bridge between Celery tasks and LangGraph orchestrator.

Responsibilities:
- Initialize AgentState from database parameters
- Execute LangGraph workflow (create_workflow)
- Export final content to PDF/DOCX
- Return file paths for database update

This module is the integration layer between:
- Backend (Celery, FastAPI, Database) → workflow_runner
- AI Layer (LangGraph, Agents, RAG) → orchestrator
"""

from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from app.config import settings
from app.schemas.curriculum import build_initial_state
from app.services.textbook.orchestrator import create_workflow
from app.utils.log_config import setup_logger

logger = setup_logger(name="WorkflowRunner", logfile="backend/logs/workflow_runner.log")


async def run_textbook_workflow(
    textbook_id: int,
    topic: str,
    num_chapters: int = 3,
    min_words_per_section: int = 300,
    enable_images: bool = False,
    content_type: str = "technical", 
    content_level: str = "Trung Bình",
    
    export_formats: list = None, #type: ignore
) -> Dict[str, Any]:
    """
    Execute complete textbook generation workflow.
    
    Workflow sequence (from orchestrator.create_workflow):
        1. Ingestion   - Web crawl and RAG indexing
        2. Planner     - Generate curriculum outline
        3. Researcher  - Retrieve context from RAG
        4. Writer      - Generate section content
        5. Reviewer    - Quality check and feedback
        6. Illustrator - Add images (if enabled)
        7. Publisher   - Export to PDF/DOCX
    
    Args:
        textbook_id:           Database ID for file naming
        topic:                 Textbook topic (e.g., "Python Basics")
        num_chapters:          Number of chapters to generate
        min_words_per_section: Minimum words per section (converted to chars)
        enable_images:         Whether to generate images
        content_level:         Length scale: 'Ngắn', 'Trung Bình', 'Dài', 'Rất Dài'
        export_formats:        List of formats: ['PDF', 'Word']
        
    Returns:
        dict with:
            - success: bool
            - title: str (AI-generated textbook title)
            - pdf_path: str (relative path)
            - docx_path: str | None
            - error: str (if failed)
    """
    
    try:
        logger.info(f"[Workflow] Starting generation for textbook_id={textbook_id}")
        logger.info(f"[Workflow] Topic: {topic}")
        logger.info(f"[Workflow] Chapters: {num_chapters}, Images: {enable_images}")
        
        # ===================================================================
        # STEP 1: Build initial AgentState
        # ===================================================================
        
        # Convert words to chars (Vietnamese: ~5 chars per word)
        min_chars_per_section = min_words_per_section * 5
        
        if export_formats is None:
            export_formats = ["PDF", "Word"]
        
        initial_state = build_initial_state(
            request=topic,
            num_chapters=num_chapters,
            enable_images=enable_images,
            min_chars_per_section=min_chars_per_section,
            max_subsections_per_chapter=5,  # Default from curriculum.py
            content_level=content_level,
            content_type=content_type,
            export_formats=export_formats,
        )
      
        logger.info(f"[Workflow] Initial state built: {len(initial_state)} fields")
        
        # ===================================================================
        # STEP 2: Execute LangGraph workflow
        # ===================================================================
        
        # create_workflow() returns full pipeline:
        # ingestion → planner → researcher → writer → reviewer → illustrator → publisher
        workflow = create_workflow()
        
        logger.info("[Workflow] Running LangGraph agents...")
        logger.info("[Workflow] This may take 5-15 minutes on first run (model download)")
        
        # Execute workflow - awaitable
        final_state = await workflow.ainvoke(initial_state)
        
        logger.info(f"[Workflow] Initial state built: {len(initial_state)} fields")
        logger.info(f"[Workflow] Using pre-validated content_type: {content_type}")
        
        # ===================================================================
        # STEP 3: Check validation and results
        # ===================================================================
        
        # Check if topic validation failed
        if final_state.get("validation_failed"):
            reason = final_state.get("validation_reason", "Topic không phù hợp")
            suggestion = final_state.get("validation_suggestion", "")
            logger.warning(f"[Workflow] Validation failed: {reason}")
            return {
                "success": False,
                "error": f"{reason}. Gợi ý: {suggestion}" if suggestion else reason
            }
        
        # Extract generated content
        final_content = final_state.get("final_content", "")
        textbook_title = final_state.get("textbook_title", topic)
        
        if not final_content:
            logger.error("[Workflow] No content generated")
            return {
                "success": False,
                "error": "Workflow hoàn thành nhưng không tạo được nội dung"
            }
        
        logger.info(f"[Workflow] Content generated: {len(final_content)} chars")
        logger.info(f"[Workflow] Title: {textbook_title}")
        
        # ===================================================================
        # STEP 4: Get file paths from publisher
        # ===================================================================
        
        # Publisher node already exported files and set paths in state
        pdf_path = final_state.get("final_filepath")
        docx_path = final_state.get("final_docx_filepath")
        
        if not pdf_path:
            logger.error("[Workflow] Publisher did not set final_filepath")
            return {
                "success": False,
                "error": "Publisher không tạo được file PDF"
            }
        
        # Convert absolute path to relative for database storage
        pdf_path_obj = Path(pdf_path)
        if pdf_path_obj.is_absolute():
            # Make relative to backend root
            try:
                pdf_path = str(pdf_path_obj.relative_to(settings.BASE_DIR))
            except ValueError:
                # If not under BASE_DIR, just use filename
                pdf_path = f"data/textbooks/{pdf_path_obj.name}"
        
        logger.info(f"[Workflow] PDF path: {pdf_path}")
        
        if docx_path:
            docx_path_obj = Path(docx_path)
            if docx_path_obj.is_absolute():
                try:
                    docx_path = str(docx_path_obj.relative_to(settings.BASE_DIR))
                except ValueError:
                    docx_path = f"data/textbooks/{docx_path_obj.name}"
            logger.info(f"[Workflow] DOCX path: {docx_path}")
        
        # ===================================================================
        # STEP 5: Return success result
        # ===================================================================
        
        logger.info(f"[Workflow] ✓ Textbook generation successful for ID {textbook_id}")
        
        return {
            "success": True,
            "title": textbook_title,
            "pdf_path": pdf_path,
            "docx_path": docx_path,
        }
        
    except Exception as e:
        logger.error(f"[Workflow] Exception in workflow execution: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Lỗi trong quá trình tạo giáo trình: {str(e)}"
        }

