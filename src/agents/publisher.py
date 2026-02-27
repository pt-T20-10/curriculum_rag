"""
Publisher Agent for AI Textbook Generator.

This agent finalizes the generated content by:
1. Adding LaTeX/YAML headers for PDF compilation
2. Saving Markdown file
3. Converting to PDF via Pandoc
4. Cleaning up temporary resources
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
import re

try:
    import pypandoc
except ImportError:
    pypandoc = None

from src.graph.state import AgentState
from src.config import BASE_DIR
from src.log_config import setup_logger

logger = setup_logger(name="PublisherAgent", logfile="logs/agents.log")


def cleanup_temp_images() -> None:
    """Clean up temporary images directory."""
    image_dir = BASE_DIR / "outputs" / "images"
    if image_dir.exists():
        try:
            shutil.rmtree(image_dir)
            logger.info("Cleaned up temporary images")
        except Exception as e:
            logger.warning(f"Failed to cleanup images: {e}")


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """
    Sanitize user input for safe use as filename.
    
    - Remove all characters except alphanumeric, spaces, hyphens
    - Replace spaces with underscores
    - Truncate to max_length
    - Fallback to 'Textbook' if result is empty
    """
    # Chỉ giữ chữ cái, số, khoảng trắng, gạch ngang
    safe = re.sub(r'[^\w\s\-]', '', name)
    # Replace spaces
    safe = safe.strip().replace(' ', '_')
    # Truncate
    safe = safe[:max_length]
    # Fallback nếu rỗng sau khi sanitize
    return safe if safe else "Textbook"

def publish_curriculum(state: AgentState) -> dict:
    """
    Publisher node: Finalize and export document.
    
    Workflow integration:
    - Input: state["final_content"] (accumulated content)
    - Output: state["final_filepath"] (path to generated file)
    
    Pipeline:
    1. Add YAML/LaTeX headers
    2. Save Markdown file
    3. Convert to PDF (if pypandoc available)
    4. Cleanup temporary resources
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with file paths and status messages.
    """
    logger.info("=" * 60)
    logger.info("NODE: Publisher - Finalizing document")
    logger.info("=" * 60)
    
    # Get final content
    current = state.get("current_content", "")
    final = state.get("final_content", "")
    full_content = final + "\n\n" + current if (final and current) else (final or current)
    if not full_content:
        full_content = state.get("current_content", "")

    if not full_content:
        logger.error("No content found to publish")
        return {
            "messages": ["✗ Publisher failed: No content to publish"],
            "final_filepath": None
        }

    # Prepare output directory and filenames
    raw_topic = state.get("request", "Textbook")
    request_topic = sanitize_filename(raw_topic)
    
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base_name = f"{request_topic}_{timestamp}"
    md_filename = output_dir / f"{file_base_name}.md"
    pdf_filename = output_dir / f"{file_base_name}.pdf"
    
    # YAML header with LaTeX configuration for Vietnamese + Math support
    yaml_header = f"""---
title: "{state.get('request', 'Giáo trình')}"
subtitle: "Biên soạn bởi AI Agent System"
date: "{datetime.now().strftime('%d/%m/%Y')}"
geometry: "left=2.5cm,right=2.5cm,top=2cm,bottom=2cm"
mainfont: "Times New Roman"
header-includes:
  - \\usepackage{{amsmath}}
  - \\usepackage{{amssymb}}
  - \\usepackage{{hyperref}}
  - \\hypersetup{{colorlinks=true, linkcolor=blue, urlcolor=blue}}
  - \\usepackage{{indentfirst}}
  - \\usepackage{{float}}
  - \\usepackage[font=small,labelfont=bf]{{caption}}
  - \\captionsetup[figure]{{labelformat=empty}}
  - \\let\\origfigure\\figure
  - \\let\\endorigfigure\\endfigure
  - \\renewenvironment{{figure}}[1][2] {{\\expandafter\\origfigure\\expandafter[H]}} {{\\endorigfigure}}
---

"""

    final_document = yaml_header + full_content

    # Save Markdown file
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(final_document)
        logger.info(f"✓ Markdown saved: {md_filename}")
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}", exc_info=True)
        return {
            "messages": ["✗ Publisher failed: Could not save Markdown"],
            "final_filepath": None
        }

    # Convert to PDF if pypandoc available
    result_filepath = str(md_filename)  # Default to MD if PDF fails
    
    if pypandoc:
        try:
            logger.info("Converting to PDF (xelatex engine)...")
            pypandoc.convert_text(
                source=final_document,
                to='pdf',
                format='md',
                outputfile=str(pdf_filename),
                extra_args=[
                    '--pdf-engine=xelatex',
                    '-V', 'mainfont=Times New Roman',
                    '--toc',
                    '--extract-media=.',          
                    '-V', 'graphics=true',   
                ]
            )
            logger.info(f"✓ PDF saved: {pdf_filename}")
            result_filepath = str(pdf_filename)
            cleanup_temp_images()
        except Exception as e:
            logger.warning(f"PDF generation failed: {e}", exc_info=True)
            logger.info("Falling back to Markdown output only")
    else:
        logger.warning("pypandoc not installed - skipping PDF generation")

    return {
        "messages": [
            f"✓ Document finalized: {os.path.basename(result_filepath)}"
        ],
        "final_filepath": result_filepath
    }
