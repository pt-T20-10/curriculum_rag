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
    """
    logger.info("\n --- PUBLISHER: Finalizing Document ---")
    
    # 1. KHỞI TẠO KẾT QUẢ TRẢ VỀ MẶC ĐỊNH (Quan trọng!)
    # Đảm bảo key 'final_filepath' luôn tồn tại ngay từ đầu
    result_output = {
        "messages": [],
        "final_filepath": None 
    }
    
    # 2. Lấy dữ liệu nội dung
    full_content = state.get("final_content", "")
    if not full_content:
        full_content = state.get("current_content", "")

    if not full_content:
        logger.error("❌ No content found to publish!")
        result_output["messages"].append("Error: No content to publish")
        return result_output

    # 3. Chuẩn bị đường dẫn
    request_topic = state.get("request", "Textbook").replace(" ", "_")
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_base_name = f"{request_topic}_{timestamp}"
    md_filename = output_dir / f"{file_base_name}.md"
    pdf_filename = output_dir / f"{file_base_name}.pdf"
    
    # 4. Metadata và Nội dung
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
---

"""
    final_document = yaml_header + full_content

    # 5. Xuất file Markdown
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(final_document)
        
        logger.info(f"✅ MARKDOWN SAVED: {md_filename}")
        result_output["messages"].append(f"Markdown file: {md_filename}")
        
        # --- GÁN GIÁ TRỊ QUAN TRỌNG NHẤT ---
        # Ngay khi có file MD, ta đã có thể gán đường dẫn để download (phòng hờ PDF lỗi)
        result_output["final_filepath"] = str(md_filename)
        
    except Exception as e:
        logger.error(f"Failed to save Markdown: {e}")
        result_output["messages"].append(f"Error saving MD: {e}")
        return result_output # Dừng nếu không lưu được file gốc

    # 6. Xuất file PDF (Nếu có công cụ)
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
                    # '--number-sections' # Đã tắt theo yêu cầu trước
                ]
            )
            logger.info(f"✅ PDF SAVED: {pdf_filename}")
            result_output["messages"].append(f"PDF file: {pdf_filename}")
            
            # --- CẬP NHẬT ĐƯỜNG DẪN ƯU TIÊN ---
            # Nếu tạo PDF thành công, đổi đường dẫn download sang PDF
            result_output["final_filepath"] = str(pdf_filename)
            
        except Exception as e:
            logger.warning(f"⚠️ PDF Generation failed: {e}")
            result_output["messages"].append("PDF generation failed (using MD instead).")
            # Không cần reset final_filepath vì nó đã trỏ tới file MD ở bước trên
    else:
        logger.warning("⚠️ pypandoc not installed. Skipping PDF generation.")
        result_output["messages"].append("PDF skipped (pypandoc missing).")

    # 7. TRẢ VỀ KẾT QUẢ CUỐI CÙNG
    return result_output