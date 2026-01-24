import streamlit as st
import sys
import os
import time
from pathlib import Path

# Config path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.graph.workflow import create_workflow
from src.config import BASE_DIR

# --- CẤU HÌNH TRANG WEB ---
st.set_page_config(page_title="AI Textbook Generator", page_icon="📚", layout="wide")

# --- CSS ---
st.markdown("""
<style>
    .main-header {font-size: 2.5rem; color: #4F8BF9; text-align: center; margin-bottom: 1rem;}
    .success-box {padding: 1rem; border-radius: 10px; background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb;}
    .error-box {padding: 1rem; border-radius: 10px; background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;}
</style>
""", unsafe_allow_html=True)

# --- KHỞI TẠO SESSION STATE (Lưu trạng thái file) ---
if "generated_file_path" not in st.session_state:
    st.session_state.generated_file_path = None

# --- HEADER ---
st.markdown('<div class="main-header">📚 Hệ Thống Soạn Giáo Trình Tự Động (AI)</div>', unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Cấu hình")
    recursion_limit = st.slider("Giới hạn bước lặp", 50, 300, 150)
    if st.button("🧹 Xóa Cache & Reset"):
        st.session_state.clear()
        st.rerun()

# --- MAIN UI ---
col1, col2 = st.columns([3, 1])
with col1:
    topic = st.text_input("📌 Nhập chủ đề giáo trình:", placeholder="Ví dụ: Kỹ thuật trồng hoa lan...")
with col2:
    st.write("") 
    st.write("") 
    start_btn = st.button("🚀 Bắt đầu tạo sách", type="primary", use_container_width=True)

# --- XỬ LÝ WORKFLOW ---
if start_btn and topic:
    # Reset file cũ trước khi chạy mới
    st.session_state.generated_file_path = None
    
    app = create_workflow()
    
    initial_state = {
        "request": topic,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "revision_number": 0,
        "messages": [],
        "final_content": "",
        "current_content": ""
    }

    st.divider()
    status_text = st.empty()
    progress_bar = st.progress(0)
    log_container = st.expander("📜 Xem chi tiết (Logs)", expanded=True)
    
    try:
        step_count = 0
        total_estimated_steps = 30
        
        with log_container:
            for event in app.stream(initial_state, {"recursion_limit": recursion_limit}): # type: ignore
                for key, value in event.items():
                    step_count += 1
                    progress = min(step_count / total_estimated_steps, 0.95)
                    progress_bar.progress(progress)
                    
                    if key == "ingestion":
                        st.success(f"✅ **[Ingestion]** Xong dữ liệu: '{topic}'")
                    elif key == "planner":
                        plan = value.get("curriculum", {})
                        title = plan.get('topic', topic) if isinstance(plan, dict) else plan.topic
                        st.info(f"📘 **[Planner]** Dàn ý: **{title}**")
                    elif key == "writer":
                        st.markdown(f"✍️ **[Writer]** Đang viết...")
                    elif key == "publisher":
                        progress_bar.progress(1.0)
                        status_text.markdown(f"**Hoàn tất!** Đang kiểm tra file...")
                        
                        # --- DEBUG LOGGING ---
                        st.write("--- DEBUG PUBLISHER OUTPUT ---")
                        st.json(value) # In ra JSON để xem Publisher trả về cái gì
                        
                        raw_path = value.get("final_filepath")
                        
                        if raw_path:
                            # Chuẩn hóa đường dẫn (Tránh lỗi dấu \ hoặc /)
                            abs_md_path = os.path.abspath(raw_path)
                            abs_pdf_path = abs_md_path.replace(".md", ".pdf")
                            
                            st.write(f"Checking PDF path: `{abs_pdf_path}`")
                            
                            if os.path.exists(abs_pdf_path):
                                st.session_state.generated_file_path = abs_pdf_path
                                st.balloons()
                            elif os.path.exists(abs_md_path):
                                st.session_state.generated_file_path = abs_md_path
                                st.warning("⚠️ Chỉ tìm thấy file Markdown.")
                            else:
                                st.error(f"❌ File không tồn tại trên ổ cứng: {abs_pdf_path}")
                        else:
                            st.error("❌ Publisher không trả về 'final_filepath'.")

    except Exception as e:
        st.error(f"❌ Lỗi hệ thống: {e}")
        st.exception(e)

# --- HIỂN THỊ NÚT DOWNLOAD (DỰA VÀO SESSION STATE) ---
# Phần này nằm ngoài vòng lặp, luôn được render nếu session_state có dữ liệu
if st.session_state.generated_file_path:
    file_path = st.session_state.generated_file_path
    
    if os.path.exists(file_path):
        st.divider()
        st.markdown('<div class="success-box">🎉 Sách của bạn đã sẵn sàng!</div>', unsafe_allow_html=True)
        
        file_name = os.path.basename(file_path)
        mime_type = "application/pdf" if file_path.endswith(".pdf") else "text/markdown"
        
        col1, col2 = st.columns([1, 2])
        with col1:
            with open(file_path, "rb") as f:
                st.download_button(
                    label=f"⬇️ Tải xuống {file_name}",
                    data=f,
                    file_name=file_name,
                    mime=mime_type,
                    type="primary",
                    use_container_width=True
                )
        with col2:
            st.info(f"📂 Đường dẫn nội bộ: `{file_path}`")
    else:
        st.error("⚠️ File đã bị xóa hoặc di chuyển.")

elif start_btn and not st.session_state.generated_file_path:
    # Nếu bấm nút rồi mà cuối cùng vẫn không có file trong session
    st.write("") # Spacer