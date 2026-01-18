import os
from pathlib import Path
try:
    import pypandoc
except ImportError:
    pypandoc = None

from src.graph.state import AgentState
from src.config import BASE_DIR
from src.log_config import setup_logger

logger = setup_logger(name="PublisherAgent", logfile="logs/agents.log")

def publish_curriculum(state: AgentState):
    """
    Final node: Save 'final_content' to Markdown file AND generated PDF.
    """
    logger.info("\n --- PUBLISHER: Saving Final Document ---")
    
    # 1. Get full content
    full_content = state.get("final_content", "")
    topic = state.get("request", "curriculum").replace(" ", "_")
    
    if not full_content:
        logger.error("No content found in 'final_content'!")
        return {"messages": ["Error: No content to publish"]}
    
    # 2. Setup dir
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    md_filename = output_dir / f"{topic}_Textbook.md"
    pdf_filename = output_dir / f"{topic}_Textbook.pdf"
    
    # 3. Add Metadata 
    final_markdown = f"""---
title: "{state.get('request', 'Generated Textbook')}"
subtitle: "AI-Generated Curriculum"
author: "AI Agent System"
date: "\\today"
geometry: "margin=1in"
output: pdf_document
---

{full_content}
"""

    messages = []

    # 4. Save
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(final_markdown)
        logger.info(f"✅ MARKDOWN SAVED: {md_filename}")
        messages.append(f"Markdown saved to {md_filename}")
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}")
        return {"messages": [f"Error saving MD: {e}"]}

    # 5. Export PDF (Pandoc)
    if pypandoc:
        try:
            logger.info("⏳ Converting to PDF (this may take a moment)...")
            # Nếu máy chưa cài LaTeX, có thể thử đổi to='html' để test pypandoc trước
            pypandoc.convert_text(
                source=final_markdown,
                to='pdf',
                format='md',
                outputfile=str(pdf_filename),
                extra_args=['--pdf-engine=pdflatex'] # Cần cài MikTeX hoặc TeX Live
            )
            logger.info(f"✅ PDF SAVED: {pdf_filename}")
            messages.append(f"PDF saved to {pdf_filename}")
        except Exception as e:
            logger.error(f"⚠️ PDF Generation Failed: {e}")
            messages.append("PDF generation failed (Check logs/Install Latex)")
    else:
        logger.warning("pypandoc module not found. Skipping PDF generation.")
        
    return {"messages": messages}