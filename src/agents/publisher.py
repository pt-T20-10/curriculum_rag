import os
import logging
import shutil # <--- Import mới để xóa thư mục
from datetime import datetime
from pathlib import Path

try:
    import pypandoc
except ImportError:
    pypandoc = None

from src.graph.state import AgentState
from src.config import BASE_DIR
from src.log_config import setup_logger

logger = setup_logger(name="PublisherAgent", logfile="logs/agents.log")

def cleanup_temp_images():
    """Hàm dọn dẹp thư mục ảnh tạm"""
    image_dir = BASE_DIR / "outputs" / "images"
    if image_dir.exists():
        try:
            shutil.rmtree(image_dir) # Xóa sạch thư mục images
            logger.info("🧹 Cleaned up temporary images.")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cleanup images: {e}")

def publish_curriculum(state: AgentState):
    logger.info("\n --- PUBLISHER: Finalizing Document ---")
    
    result_output = {
        "messages": [],
        "final_filepath": None 
    }
    
    full_content = state.get("final_content", "")
    if not full_content:
        full_content = state.get("current_content", "")

    if not full_content:
        logger.error("❌ No content found to publish!")
        result_output["messages"].append("Error: No content to publish")
        return result_output

    request_topic = state.get("request", "Textbook").replace(" ", "_")
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base_name = f"{request_topic}_{timestamp}"
    md_filename = output_dir / f"{file_base_name}.md"
    pdf_filename = output_dir / f"{file_base_name}.pdf"
    
    # --- CẤU HÌNH LATEX ĐỂ FIX LỖI CAPTION ---
    # 1. \usepackage{caption}: Thư viện quản lý chú thích
    # 2. \captionsetup[figure]{labelformat=empty}: Tắt tự động điền "Figure 1:"
    #    Để ta có thể tự viết "Hình 1.1.1: ..." từ Markdown.
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

    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(final_document)
        logger.info(f"✅ MARKDOWN SAVED: {md_filename}")
        result_output["messages"].append(f"Markdown file: {md_filename}")
        result_output["final_filepath"] = str(md_filename)
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}")
        return result_output

    if pypandoc:
        try:
            logger.info("⏳ Converting to PDF (Using xelatex engine)...")
            pypandoc.convert_text(
                source=final_document,
                to='pdf',
                format='md',
                outputfile=str(pdf_filename),
                extra_args=[
                    '--pdf-engine=xelatex',
                    '-V', 'mainfont=Times New Roman',
                    '--toc'
                ]
            )
            logger.info(f"✅ PDF SAVED: {pdf_filename}")
            result_output["messages"].append(f"PDF file: {pdf_filename}")
            result_output["final_filepath"] = str(pdf_filename)
            cleanup_temp_images()
        except Exception as e:
            logger.warning(f"⚠️ PDF Generation failed: {e}")
            result_output["messages"].append("PDF generation failed.")
    else:
        logger.warning("⚠️ pypandoc not installed.")

    # cleanup_temp_images()
    return result_output