"""
Streamlit UI for AI Textbook Generator.

Provides web interface with Google Gemini Deep Search style:
- Progressive workflow visualization
- Hierarchical curriculum display
- Real-time status updates
- Clean, modern design
"""

import os
import sys

from src.config import setup_directories
from src.graph.workflow import create_workflow

import streamlit as st

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)


setup_directories()
# Page configuration
st.set_page_config(
    page_title="AI Textbook Generator",
    page_icon="📚",
    layout="wide"
)

# Custom CSS - Deep Search Style
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #4F8BF9;
        text-align: center;
        margin-bottom: 1rem;
        font-weight: 600;
    }
    .success-box {
        padding: 1rem;
        border-radius: 10px;
        background-color: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
    }
    .error-box {
        padding: 1rem;
        border-radius: 10px;
        background-color: #f8d7da;
        color: #721c24;
        border: 1px solid #f5c6cb;
    }
    
    /* Deep Search Style Cards */
    .workflow-card {
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #4F8BF9;
        background-color: #f8f9fa;
        margin-bottom: 0.5rem;
    }
    .workflow-card.completed {
        border-left-color: #28a745;
        background-color: #f1f8f4;
    }
    .workflow-card.active {
        border-left-color: #ffc107;
        background-color: #fffbf0;
    }
    .workflow-card.pending {
        border-left-color: #e0e0e0;
        background-color: #fafafa;
        opacity: 0.7;
    }
    
    /* Curriculum Tree */
    .curriculum-tree {
        font-family: 'Courier New', monospace;
        background-color: #f5f5f5;
        padding: 1rem;
        border-radius: 8px;
        font-size: 0.9rem;
        line-height: 1.6;
    }
    .chapter-item {
        color: #1a73e8;
        font-weight: 600;
        margin-top: 0.5rem;
    }
    .section-item {
        color: #5f6368;
        padding-left: 1.5rem;
    }
    
    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 500;
    }
    .status-completed {
        background-color: #d4edda;
        color: #155724;
    }
    .status-active {
        background-color: #fff3cd;
        color: #856404;
    }
    .status-pending {
        background-color: #e9ecef;
        color: #6c757d;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "generated_file_path" not in st.session_state:
    st.session_state.generated_file_path = None
if "curriculum_structure" not in st.session_state:
    st.session_state.curriculum_structure = None
if "current_progress" not in st.session_state:
    st.session_state.current_progress = {
        "chapter": 0,
        "subsection": 0,
        "total_chapters": 0,
        "total_subsections": 0
    }

# Header
st.markdown(
    '<div class="main-header">📚 AI Textbook Generator</div>',
    unsafe_allow_html=True
)
st.markdown(
    '<p style="text-align: center; color: #6c757d; margin-bottom: 2rem;">Tạo giáo trình tự động với AI - Powered by LangGraph & RAG</p>',
    unsafe_allow_html=True
)

# Sidebar configuration
with st.sidebar:
    st.header("⚙️ Cấu hình")
    recursion_limit = st.slider("Giới hạn bước lặp", 50, 300, 150)
    
    st.divider()
    st.subheader("📊 Thống kê hệ thống")
    if st.session_state.curriculum_structure:
        st.metric("Số chương", st.session_state.current_progress['total_chapters'])
        st.metric("Tổng số mục", st.session_state.current_progress['total_subsections'])
    
    st.divider()
    if st.button("🧹 Xóa Cache & Reset"):
        st.session_state.clear()
        st.rerun()

# Main UI
col1, col2 = st.columns([3, 1])
with col1:
    topic = st.text_input(
        "📌 Nhập chủ đề giáo trình:",
        placeholder="Ví dụ: Công nghệ Blockchain, Kỹ thuật trồng hoa lan, Marketing cơ bản..."
    )
with col2:
    st.write("")
    st.write("")
    start_btn = st.button("🚀 Bắt đầu tạo", type="primary", use_container_width=True)


def render_curriculum_tree(curriculum):
    """Render curriculum structure as a tree (Deep Search style)."""
    tree_html = '<div class="curriculum-tree">'
    tree_html += f'<div style="color: #1a73e8; font-weight: 700; margin-bottom: 0.5rem;">📘 {curriculum.topic}</div>'
    
    for idx, chapter in enumerate(curriculum.chapters, 1):
        tree_html += f'<div class="chapter-item">├─ Chương {idx}: {chapter.title}</div>'
        
        for sub_idx, subsection in enumerate(chapter.subsections, 1):
            is_last = sub_idx == len(chapter.subsections)
            connector = "└─" if is_last else "├─"
            tree_html += f'<div class="section-item">│  {connector} {idx}.{sub_idx} {subsection.title}</div>'
    
    tree_html += '</div>'
    return tree_html


def render_workflow_status(stage, status, message):
    """Render workflow stage card (Deep Search style)."""
    status_class = {
        "completed": "completed",
        "active": "active",
        "pending": "pending"
    }
    
    icons = {
        "ingestion": "🔍",
        "planner": "📋",
        "researcher": "📚",
        "writer": "✍️",
        "reviewer": "👁️",
        "illustrator": "🎨",
        "publisher": "📦"
    }
    
    badge_class = {
        "completed": "status-completed",
        "active": "status-active",
        "pending": "status-pending"
    }
    
    badge_text = {
        "completed": "✓ Hoàn tất",
        "active": "⏳ Đang xử lý",
        "pending": "⏸️ Chờ xử lý"
    }
    
    icon = icons.get(stage, "📌")
    card_class = status_class.get(status, "pending")
    badge_style = badge_class.get(status, "status-pending")
    badge = badge_text.get(status, "Pending")
    
    html = f'''
    <div class="workflow-card {card_class}">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span style="font-size: 1.2rem; margin-right: 0.5rem;">{icon}</span>
                <p class="section-item"><strong>{message}</strong></p>
            </div>
            <span class="status-badge {badge_style}">{badge}</span>
        </div>
    </div>
    '''
    return html


# Workflow execution
if start_btn and topic:
    # Reset state
    st.session_state.generated_file_path = None
    st.session_state.curriculum_structure = None
    st.session_state.current_progress = {
        "chapter": 0,
        "subsection": 0,
        "total_chapters": 0,
        "total_subsections": 0
    }
    
    # Create workflow
    app = create_workflow()
    
    initial_state = {
        "request": topic,
        "rag_context": "", 
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "revision_number": 0,
        "messages": [],
        "final_content": "",
        "current_content": ""
    }

    st.divider()
    
    # Progress section
    progress_container = st.container()
    status_container = st.container()
    curriculum_container = st.container()
    
    # Workflow stages tracking
    workflow_stages = {
        "ingestion": {"status": "pending", "message": "Thu thập dữ liệu từ web"},
        "planner": {"status": "pending", "message": "Lập dàn ý giáo trình"},
        "content_generation": {"status": "pending", "message": "Sinh nội dung"},
        "publisher": {"status": "pending", "message": "Xuất bản tài liệu"}
    }
    
    try:
        with progress_container:
            progress_bar = st.progress(0)
            progress_text = st.empty()
        
        step_count = 0
        total_estimated_steps = 30
        content_started = False
        
        for event in app.stream(initial_state, {"recursion_limit": recursion_limit}):
            for key, value in event.items():
                step_count += 1
                progress = min(step_count / total_estimated_steps, 0.95)
                progress_bar.progress(progress)
                
                # === INGESTION ===
                if key == "ingestion":
                    workflow_stages["ingestion"]["status"] = "completed"
                    progress_text.markdown("**Bước 1/4:** Thu thập dữ liệu hoàn tất")
                    
                    with status_container:
                        st.markdown(render_workflow_status(
                            "ingestion", "completed",
                            f"Thu thập dữ liệu về '{topic}'"
                        ), unsafe_allow_html=True)
                
                # === PLANNER ===
                elif key == "planner":
                    workflow_stages["planner"]["status"] = "completed"
                    progress_text.markdown("**Bước 2/4:** Lập dàn ý hoàn tất")
                    
                    plan = value.get("curriculum")
                    if plan:
                        # Store curriculum structure
                        st.session_state.curriculum_structure = plan
                        
                        # Calculate totals
                        total_chapters = len(plan.chapters)
                        total_subsections = sum(len(ch.subsections) for ch in plan.chapters)
                        st.session_state.current_progress['total_chapters'] = total_chapters
                        st.session_state.current_progress['total_subsections'] = total_subsections
                        
                        with status_container:
                            st.markdown(render_workflow_status(
                                "planner", "completed",
                                f"Dàn ý: {plan.topic} ({total_chapters} chương, {total_subsections} mục)"
                            ), unsafe_allow_html=True)
                        
                        # Display curriculum tree
                        with curriculum_container:
                            st.markdown("### 📚 Cấu trúc giáo trình")
                            st.markdown(render_curriculum_tree(plan), unsafe_allow_html=True)
                
                # === CONTENT GENERATION (Writer/Reviewer/Illustrator) ===
                elif key in ["researcher", "writer", "reviewer", "illustrator"]:
                    if not content_started:
                        workflow_stages["content_generation"]["status"] = "active"
                        content_started = True
                    
                    # Get current position from state
                    current_state = value
                    chap_idx = current_state.get("current_chapter_index", 0)
                    sub_idx = current_state.get("current_subsection_index", 0)
                    
                    st.session_state.current_progress['chapter'] = chap_idx + 1
                    st.session_state.current_progress['subsection'] = sub_idx + 1
                    
                    progress_text.markdown(
                        f"**Bước 3/4:** Đang viết - "
                        f"Chương {chap_idx + 1}, Mục {sub_idx + 1}/"
                        f"{st.session_state.current_progress['total_subsections']}"
                    )
                
                # === CHECKPOINT NODES ===
                elif key in ["update_subsection", "update_chapter"]:
                    # Silent update - just track progress
                    pass
                
                # === PUBLISHER ===
                elif key == "publisher":
                    workflow_stages["content_generation"]["status"] = "completed"
                    workflow_stages["publisher"]["status"] = "active"
                    
                    progress_bar.progress(1.0)
                    progress_text.markdown("**Bước 4/4:** Xuất bản tài liệu...")
                    
                    raw_path = value.get("final_filepath")
                    
                    if raw_path:
                        abs_md_path = os.path.abspath(raw_path)
                        abs_pdf_path = abs_md_path.replace(".md", ".pdf")
                        
                        if os.path.exists(abs_pdf_path):
                            st.session_state.generated_file_path = abs_pdf_path
                            workflow_stages["publisher"]["status"] = "completed"
                            
                            with status_container:
                                st.markdown(render_workflow_status(
                                    "publisher", "completed",
                                    "Xuất bản PDF thành công"
                                ), unsafe_allow_html=True)
                            
                            st.balloons()
                            
                        elif os.path.exists(abs_md_path):
                            st.session_state.generated_file_path = abs_md_path
                            workflow_stages["publisher"]["status"] = "completed"
                            
                            with status_container:
                                st.markdown(render_workflow_status(
                                    "publisher", "completed",
                                    "Xuất bản Markdown (PDF generation failed)"
                                ), unsafe_allow_html=True)
                        else:
                            st.error(f"❌ File không tồn tại: {abs_pdf_path}")
                    else:
                        st.error("❌ Publisher không trả về file path")

    except Exception as e:
        st.error(f"❌ Lỗi hệ thống: {e}")
        with st.expander("Chi tiết lỗi"):
            st.exception(e)

# Download section (persistent across reruns)
if st.session_state.generated_file_path:
    file_path = st.session_state.generated_file_path
    
    if os.path.exists(file_path):
        st.divider()
        st.markdown(
            '<div class="success-box">🎉 <strong>Giáo trình của bạn đã sẵn sàng!</strong></div>',
            unsafe_allow_html=True
        )
        
        file_name = os.path.basename(file_path)
        mime_type = "application/pdf" if file_path.endswith(".pdf") else "text/markdown"
        file_size = os.path.getsize(file_path) / 1024  # KB
        
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            st.metric("📄 File", file_name.split('_')[0][:20] + "...")
        with col2:
            st.metric("📦 Kích thước", f"{file_size:.1f} KB")
        with col3:
            st.metric("📑 Format", "PDF" if file_path.endswith(".pdf") else "Markdown")
        
        st.divider()
        
        col_download, col_path = st.columns([1, 2])
        with col_download:
            with open(file_path, "rb") as f:
                st.download_button(
                    label=f"⬇️ Tải xuống {file_name}",
                    data=f,
                    file_name=file_name,
                    mime=mime_type,
                    type="primary",
                    use_container_width=True
                )
        with col_path:
            st.code(file_path, language=None)
    else:
        st.error("⚠️ File đã bị xóa hoặc di chuyển")

# Footer
st.divider()
st.markdown(
    '<p style="text-align: center; color: #adb5bd; font-size: 0.85rem;">Built with ❤️ using LangGraph, OpenAI & Streamlit</p>',
    unsafe_allow_html=True
)