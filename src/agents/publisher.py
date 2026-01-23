import os
import logging
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

def publish_curriculum(state: AgentState):
    """
    Node: Publisher
    Nhiệm vụ: Tổng hợp nội dung, thêm Metadata, xuất ra Markdown và PDF.
    Đặc biệt tối ưu cho Tiếng Việt và Toán học (LaTeX).
    """
    logger.info("\n --- PUBLISHER: Finalizing Document ---")
    
    # 1. Lấy dữ liệu từ State
    # Lưu ý: 'final_content' là nơi tích lũy toàn bộ nội dung sách qua các vòng lặp
    full_content = state.get("final_content", "")
    
    # Fallback: Nếu final_content rỗng (do chạy test lẻ), thử lấy current_content
    if not full_content:
        full_content = state.get("current_content", "")

    request_topic = state.get("request", "Textbook").replace(" ", "_")
    
    if not full_content:
        logger.error("❌ No content found to publish!")
        return {"messages": ["Error: No content to publish"]}
    
    # 2. Tạo thư mục output
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Tên file (Thêm timestamp để không bị ghi đè khi test nhiều lần)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base_name = f"{request_topic}_{timestamp}"
    md_filename = output_dir / f"{file_base_name}.md"
    pdf_filename = output_dir / f"{file_base_name}.pdf"
    
    # 3. Chuẩn bị Metadata (YAML Header cho Pandoc)
    # Đây là bí quyết để PDF đẹp và hỗ trợ Tiếng Việt tốt
    yaml_header = f"""---
title: "{state.get('request', 'Giáo trình AI Generative')}"
subtitle: "Biên soạn tự động bởi AI System"
author: "AI Curriculum Agent"
date: "{datetime.now().strftime('%d/%m/%Y')}"
geometry: "left=2.5cm,right=2.5cm,top=2cm,bottom=2cm"
mainfont: "Times New Roman"
header-includes:
  - \\usepackage{{amsmath}}
  - \\usepackage{{amssymb}}
  - \\usepackage{{hyperref}}
  - \\hypersetup{{colorlinks=true, linkcolor=blue, urlcolor=blue}}
  - \\usepackage{{indentfirst}}
---

"""
    # Ghép Metadata + Nội dung
    final_document = yaml_header + full_content

    messages = []

    # 4. Xuất file Markdown (Luôn thành công)
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(final_document)
        logger.info(f"✅ MARKDOWN SAVED: {md_filename}")
        messages.append(f"Markdown file: {md_filename}")
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}")
        return {"messages": [f"Error saving MD: {e}"]}

    # 5. Xuất file PDF (Cần cài đặt Pandoc và MikTeX/TeXLive)
    if pypandoc:
        try:
            logger.info("⏳ Converting to PDF (Using xelatex engine)...")
            
            # Kiểm tra xem máy có cài xelatex không (thường đi kèm MikTeX/TeXLive)
            # xelatex hỗ trợ Unicode (Tiếng Việt) tốt hơn pdflatex
            pypandoc.convert_text(
                source=final_document,
                to='pdf',
                format='md',
                outputfile=str(pdf_filename),
                extra_args=[
                    '--pdf-engine=xelatex',   # QUAN TRỌNG: Dùng engine này để không lỗi font Việt
                    '-V', 'mainfont=Times New Roman', # Yêu cầu máy có font này
                    '--toc',                  # Tự động tạo Mục lục (Table of Contents)
                    '--number-sections'       # Tự động đánh số đề mục (1, 1.1, 1.1.1)
                ]
            )
            logger.info(f"✅ PDF SAVED: {pdf_filename}")
            messages.append(f"PDF file: {pdf_filename}")
        except Exception as e:
            logger.warning(f"⚠️ PDF Generation failed: {e}")
            logger.warning("Tip: Make sure Pandoc and MikTeX (with xelatex) are installed.")
            messages.append("PDF generation failed (Check logs).")
    else:
        logger.warning("⚠️ pypandoc not installed. Skipping PDF generation.")
        messages.append("PDF skipped (pypandoc missing).")

    return {"messages": messages, "final_filepath": str(md_filename)}