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
import threading
import queue as _queue

from src.config import setup_directories
from src.graph.workflow import create_workflow
from src.log_config import setup_logger
from src import stop_signal

logger = setup_logger(name="App", logfile="logs/app.log")

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
    .status-completed { background-color: #d4edda; color: #155724; }
    .status-active    { background-color: #fff3cd; color: #856404; }
    .status-pending   { background-color: #e9ecef; color: #6c757d; }

    /* Config panel */
    .config-info {
        font-size: 0.82rem;
        color: #6c757d;
        margin-top: 0.2rem;
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
if "stop_event" not in st.session_state:
    st.session_state.stop_event = threading.Event()
if "is_running" not in st.session_state:
    st.session_state.is_running = False

# Header
st.markdown(
    '<div class="main-header">📚 AI Textbook Generator</div>',
    unsafe_allow_html=True
)
st.markdown(
    '<p style="text-align: center; color: #6c757d; margin-bottom: 2rem;">'
    'Tạo giáo trình tự động với AI - Powered by LangGraph & RAG</p>',
    unsafe_allow_html=True
)

# ============================================================================
# SIDEBAR - Configuration
# ============================================================================
with st.sidebar:
    st.header("⚙️ Cấu hình")

    # --- Nội dung ---
    st.subheader("📖 Nội dung")

    num_chapters = st.slider(
        "Số chương",
        min_value=1,
        max_value=20,
        value=3,
        help="Số lượng chương trong giáo trình. Nhiều chương hơn → thời gian tạo lâu hơn."
    )

    # Độ dài nội dung — radio thay thế slider min_words.
    # Mỗi level scale char targets của tất cả section_type theo CONTENT_LEVEL_SCALES
    # trong state.py. Ước tính số từ dựa trên section type "medium" (phổ biến nhất):
    #   base chars: 3000 min – 4500 max  |  4.8 chars/từ (tiếng Việt đơn âm tiết)
    #   Ngắn:       3000×0.55/4.8 ≈ 344  →  4500×0.55/4.8 ≈ 516   → ~350–500 từ
    #   Trung Bình: 3000×1.0 /4.8 ≈ 625  →  4500×1.0 /4.8 ≈ 938   → ~600–950 từ
    #   Dài:        3000×1.6 /4.8 ≈ 1000 →  4500×1.6 /4.8 ≈ 1500  → ~1000–1500 từ
    #   Rất Dài:    3000×2.3 /4.8 ≈ 1438 →  4500×2.3 /4.8 ≈ 2156  → ~1400–2200 từ
    _level_desc = {
        "Ngắn":       "~350–500 từ/mục · Trình bày cốt lõi, súc tích",
        "Trung Bình": "~600–950 từ/mục · Cân bằng lý thuyết và ví dụ",
        "Dài":        "~1000–1500 từ/mục · Phân tích sâu, nhiều ví dụ",
        "Rất Dài":    "~1400–2200 từ/mục · Toàn diện, mức học thuật",
    }

    content_level = st.radio(
        "Độ dài nội dung",
        options=["Ngắn", "Trung Bình", "Dài", "Rất Dài"],
        index=1,   # default: Trung Bình
        horizontal=True,
        help=(
            "Kiểm soát độ dài và độ sâu của mỗi mục. "
            "Áp dụng đồng nhất cho tất cả section types (light / medium / deep / applied)."
        )
    )
    st.markdown(
        f'<div class="config-info">{_level_desc[content_level]}</div>',
        unsafe_allow_html=True
    )

    max_subsections = st.slider(
        "Số mục tối đa / chương",
        min_value=2,
        max_value=10,
        value=3,
        help=(
            "Giới hạn số mục con trong mỗi chương. "
            "Planner sẽ chọn cấu trúc phù hợp với chủ đề trong giới hạn này."
        )
    )

    st.divider()

    # --- Hình ảnh ---
    st.subheader("🖼️ Hình ảnh")

    enable_images = st.toggle(
        "Chèn hình ảnh minh họa",
        value=True,
        help="Tìm và chèn hình ảnh từ Google Images vào giáo trình. Yêu cầu SERPER_API_KEY."
    )

    if enable_images:
        st.markdown(
            '<div class="config-info">✓ Hình ảnh sẽ được tải về, resize và chèn tự động.</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="config-info">✗ Bỏ qua bước tìm hình — giáo trình chỉ có text.</div>',
            unsafe_allow_html=True
        )

    st.divider()

    # --- Hệ thống ---
    st.subheader("🔧 Hệ thống")

    # recursion_limit tính động trước khi có curriculum thực tế.
    # Công thức: ingestion(1) + planner(1) + subsections × steps + publisher(1) + buffer(25%)
    # 9 steps/sub (with images) = researcher + writer + reviewer(×2 max) + illustrator +
    #                             route_after_review + check_next_step + update_sub/chapter
    _est_subs      = num_chapters * max_subsections
    _steps_per_sub = 9 if enable_images else 8   # worst case với MAX_REVISIONS=2
    _auto_limit    = int((3 + _est_subs * _steps_per_sub) * 1.25)

    st.markdown(
        f'<div class="config-info">Recursion limit tự động: <b>{_auto_limit}</b> '
        f'(dựa trên ~{_est_subs} mục × {_steps_per_sub} steps + 25% buffer)</div>',
        unsafe_allow_html=True
    )
    st.divider()
    st.subheader("📊 Thống kê")
    if st.session_state.curriculum_structure:
        st.metric("Số chương", st.session_state.current_progress['total_chapters'])
        st.metric("Tổng số mục", st.session_state.current_progress['total_subsections'])

    st.divider()
    if st.button("🧹 Xóa Cache & Reset"):
        st.session_state.clear()
        st.rerun()


# ============================================================================
# MAIN UI - Topic input
# ============================================================================
col1, col2 = st.columns([3, 1])
with col1:
    topic = st.text_input(
        "📌 Nhập chủ đề giáo trình:",
        placeholder="Ví dụ: Công nghệ Blockchain, Kỹ thuật trồng hoa lan, Marketing cơ bản..."
    )
with col2:
    st.write("")
    st.write("")
    start_btn = st.button(
        "🚀 Bắt đầu tạo", type="primary", use_container_width=True,
        disabled=st.session_state.is_running
    )
    if st.session_state.is_running:
        if st.button("⛔ Dừng lại", type="secondary", use_container_width=True):
            st.session_state.stop_event.set()
            stop_signal.request_stop()
            st.session_state.is_running = False
            st.rerun()

# Config summary caption below topic input
if topic:
    img_label = "✓ Có hình ảnh" if enable_images else "✗ Không có hình"
    st.caption(
        f"Cấu hình: **{num_chapters} chương** · "
        f"**≤{max_subsections} mục/chương** · "
        f"**{content_level}** ({_level_desc[content_level].split('·')[0].strip()}) · "
        f"**{img_label}**"
    )


# ============================================================================
# HELPERS
# ============================================================================
def render_curriculum_tree(curriculum):
    """Render curriculum structure as a tree (Deep Search style)."""
    tree_html = '<div class="curriculum-tree">'
    tree_html += (
        f'<div style="color: #1a73e8; font-weight: 700; margin-bottom: 0.5rem;">'
        f'📘 {curriculum.topic}</div>'
    )

    for idx, chapter in enumerate(curriculum.chapters, 1):
        tree_html += f'<div class="chapter-item">├─ Chương {idx}: {chapter.title}</div>'

        for sub_idx, subsection in enumerate(chapter.subsections, 1):
            is_last    = sub_idx == len(chapter.subsections)
            connector  = "└─" if is_last else "├─"
            stype      = getattr(subsection, 'section_type', '')
            type_badge = (
                f' <span style="color:#aaa;font-size:0.8em">[{stype}]</span>'
                if stype else ''
            )
            tree_html += (
                f'<div class="section-item">'
                f'│  {connector} {idx}.{sub_idx} {subsection.title}{type_badge}'
                f'</div>'
            )

    tree_html += '</div>'
    return tree_html


def render_workflow_status(stage, status, message):
    """Render workflow stage card (Deep Search style)."""
    icons = {
        "ingestion":   "🔍",
        "planner":     "📋",
        "researcher":  "📚",
        "writer":      "✍️",
        "reviewer":    "👁️",
        "illustrator": "🎨",
        "publisher":   "📦",
    }
    badge_class = {
        "completed": "status-completed",
        "active":    "status-active",
        "pending":   "status-pending",
    }
    badge_text = {
        "completed": "✓ Hoàn tất",
        "active":    "⏳ Đang xử lý",
        "pending":   "⏸️ Chờ xử lý",
    }
    card_class = {
        "completed": "completed",
        "active":    "active",
        "pending":   "pending",
    }

    icon  = icons.get(stage, "📌")
    c_cls = card_class.get(status, "pending")
    b_cls = badge_class.get(status, "status-pending")
    badge = badge_text.get(status, "Pending")

    return f'''
    <div class="workflow-card {c_cls}">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span style="font-size: 1.2rem; margin-right: 0.5rem;">{icon}</span>
                <strong><p style="text-align: center; color: #adb5bd; font-size: 0.85rem;">{message}</p></strong>
            </div>
            <span class="status-badge {b_cls}">{badge}</span>
        </div>
    </div>
    '''


# ============================================================================
# WORKFLOW EXECUTION
# ============================================================================
if start_btn and topic:
    # Reset session state for new run
    st.session_state.generated_file_path = None
    st.session_state.curriculum_structure = None
    st.session_state.current_progress = {
        "chapter": 0, "subsection": 0,
        "total_chapters": 0, "total_subsections": 0,
    }

    st.session_state.stop_event.clear()
    stop_signal.clear()
    st.session_state.is_running = True

    app = create_workflow()

    initial_state = {
        "request": topic,

        # User configuration
        "num_chapters":                num_chapters,
        "enable_images":               enable_images,
        "content_level":               content_level,   # drives char targets via CONTENT_LEVEL_SCALES
        "min_chars_per_section":       0,               # 0 = use content_level as sole floor
        "max_subsections_per_chapter": max_subsections,

        # Runtime state — all reset at workflow start
        "rag_context":              "",
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "revision_number":          0,
        "review_feedback":          "",
        "chapter_header_written":   False,
        "messages":                 [],
        "final_content":            "",
        "current_content":          "",
    }

    st.divider()

    progress_container   = st.container()
    status_container     = st.container()
    curriculum_container = st.container()

    workflow_stages = {
        "ingestion":          {"status": "pending", "message": "Thu thập dữ liệu từ web"},
        "planner":            {"status": "pending", "message": "Lập dàn ý giáo trình"},
        "content_generation": {"status": "pending", "message": "Sinh nội dung"},
        "publisher":          {"status": "pending", "message": "Xuất bản tài liệu"},
    }

    try:
        with progress_container:
            progress_bar  = st.progress(0)
            progress_text = st.empty()

        step_count            = 0
        total_estimated_steps = 30   # updated after planner completes
        recursion_limit       = _auto_limit
        content_started       = False

        # Run streaming in a background thread so the stop button stays responsive
        event_q = _queue.Queue()

        def _stream_worker(rl=recursion_limit):
            try:
                for ev in app.stream(initial_state, {"recursion_limit": rl}):
                    if stop_signal.is_stopped():
                        event_q.put(("STOPPED", None))
                        return
                    event_q.put(("EVENT", ev))
                event_q.put(("DONE", None))
            except Exception as exc:
                event_q.put(("ERROR", exc))

        _worker = threading.Thread(target=_stream_worker, daemon=True)
        _worker.start()

        while True:
            try:
                msg_type, payload = event_q.get(timeout=1.0)
            except _queue.Empty:
                continue
            if msg_type == "STOPPED":
                st.session_state.is_running = False
                st.warning("⛔ Quá trình đã bị dừng.")
                break
            elif msg_type == "DONE":
                st.session_state.is_running = False
                break
            elif msg_type == "ERROR":
                st.session_state.is_running = False
                raise payload

            # msg_type == "EVENT"
            event = payload
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
                        st.session_state.curriculum_structure = plan

                        total_chapters    = len(plan.chapters)
                        total_subsections = sum(len(ch.subsections) for ch in plan.chapters)
                        st.session_state.current_progress['total_chapters']    = total_chapters
                        st.session_state.current_progress['total_subsections'] = total_subsections

                        with status_container:
                            st.markdown(render_workflow_status(
                                "planner", "completed",
                                f"Dàn ý: {plan.topic} ({total_chapters} chương, {total_subsections} mục)"
                            ), unsafe_allow_html=True)

                        with curriculum_container:
                            st.markdown("### 📚 Cấu trúc giáo trình")
                            st.markdown(render_curriculum_tree(plan), unsafe_allow_html=True)

                # === CONTENT GENERATION ===
                elif key in ["researcher", "writer", "reviewer", "illustrator"]:
                    if not content_started:
                        workflow_stages["content_generation"]["status"] = "active"
                        content_started = True

                    current_state = value
                    chap_idx = current_state.get("current_chapter_index", 0)
                    sub_idx  = current_state.get("current_subsection_index", 0)

                    st.session_state.current_progress['chapter']    = chap_idx + 1
                    st.session_state.current_progress['subsection'] = sub_idx + 1

                    stage_label = {
                        "researcher":  "🔍 Tìm kiếm tài liệu",
                        "writer":      "✍️ Viết nội dung",
                        "reviewer":    "👁️ Kiểm tra chất lượng",
                        "illustrator": "🎨 Chèn hình ảnh",
                    }.get(key, key)

                    progress_text.markdown(
                        f"**Bước 3/4:** {stage_label} — "
                        f"Chương {chap_idx + 1}, "
                        f"Mục {sub_idx + 1}/{st.session_state.current_progress['total_subsections']}"
                    )

                # === CHECKPOINT NODES ===
                elif key in ["update_subsection", "update_chapter"]:
                    pass

                # === PUBLISHER ===
                elif key == "publisher":
                    workflow_stages["content_generation"]["status"] = "completed"
                    workflow_stages["publisher"]["status"] = "active"

                    progress_bar.progress(1.0)
                    progress_text.markdown("**Bước 4/4:** Xuất bản tài liệu...")

                    raw_path = value.get("final_filepath")

                    if raw_path:
                        abs_md_path  = os.path.abspath(raw_path)
                        abs_pdf_path = abs_md_path.replace(".md", ".pdf")

                        if os.path.exists(abs_pdf_path):
                            st.session_state.generated_file_path = abs_pdf_path
                            workflow_stages["publisher"]["status"] = "completed"
                            with status_container:
                                st.markdown(render_workflow_status(
                                    "publisher", "completed", "Xuất bản PDF thành công"
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


# ============================================================================
# DOWNLOAD SECTION
# ============================================================================
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
        file_size = os.path.getsize(file_path) / 1024

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