"""
Streamlit entry point for AI Textbook Generator.

Workflow phases:
  idle             → user fills topic, hits ↑
  planning         → Phase A: validator + ingestion + curriculum generation
  reviewing        → Phase 4 gate: user reviews/edits curriculum
  generating_ch1   → Phase B1: Chapter 1 content generation
  previewing       → Phase 5 gate: user previews Chapter 1 before continuing
  generating_rest  → Phase B2: remaining chapters generation
  publishing_early → user chose to stop at Chapter 1 and publish
  done             → publisher finished, download available
"""

import os
import queue

import streamlit as st
from src.agents.publisher import cleanup_temp_images
from src.config import CHROMA_DB_DIR
import shutil, threading
from src.config import setup_directories
from src import stop_signal
from src.ui.components import (
    init_session_state,
    load_css,
    render_sidebar,
    render_input_row,
    render_config_panel,
    render_curriculum_tree,
    render_workflow_status,
    render_download_section,
    render_curriculum_editor,
    render_chapter1_preview,
    build_sub_stage_card,
    render_validation_error,
)
from src.ui.events import EventType, WorkflowEvent
from backend import (
    build_initial_state,
    build_content_initial_state,
    build_remaining_state,
    start_planning_thread,
    start_chapter1_thread,
    start_remaining_thread,
)
# Helper function
def _cleanup_background() -> None:
    """Run storage cleanup in a daemon thread to avoid blocking the UI."""
    cleanup_temp_images()
    if CHROMA_DB_DIR.exists():
        shutil.rmtree(CHROMA_DB_DIR, ignore_errors=True)
# ============================================================================
# Bootstrap
# ============================================================================
st.set_page_config(
    page_title="AI Textbook Generator",
    page_icon="📚",
    layout="wide",
)
load_css()
init_session_state()

if not st.session_state.get("_dirs_ready"):
    setup_directories()
    st.session_state["_dirs_ready"] = True

# ============================================================================
# Header
# ============================================================================
st.markdown(
    '<div class="main-header">📚 Hệ Thống Tạo Giáo Trình Tự Động</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="sub-header">'
    "Hệ thống AI — vui lòng kiểm tra lại kết quả trước khi sử dụng"
    "</p>",
    unsafe_allow_html=True,
)

# ============================================================================
# Sidebar / Input / Config
# ============================================================================
render_sidebar()
topic, _default_config = render_input_row()

# ============================================================================
# Phase snapshot — read ONCE at top, never re-read mid-script
# ============================================================================
_phase     = st.session_state.get("workflow_phase", "idle")
_is_active = _phase in (
    "planning", "reviewing",
    "generating_ch1", "previewing",
    "generating_rest", "publishing_early",
    "done",
)

config = render_config_panel() or _default_config

# ============================================================================
# Progress bar + status text
# ============================================================================
if _is_active:
    st.divider()
    st.progress(st.session_state.get("progress_value", 0.0))
    if st.session_state.get("status_text"):
        st.markdown(st.session_state.status_text)

# ============================================================================
# Workflow stage cards (st.empty() slots — atomic, no double-render)
# ============================================================================
ingestion_slot = st.empty()
planner_slot   = st.empty()
tree_slot      = st.empty()
sub_stage_slot = st.empty()
publisher_slot = st.empty()

if st.session_state.get("ingestion_html"):
    ingestion_slot.markdown(st.session_state.ingestion_html, unsafe_allow_html=True)
if st.session_state.get("planner_html"):
    planner_slot.markdown(st.session_state.planner_html, unsafe_allow_html=True)
if st.session_state.get("curriculum_html"):
    tree_slot.markdown(
        "### 📚 Cấu trúc giáo trình\n\n" + st.session_state.curriculum_html,
        unsafe_allow_html=True,
    )
if st.session_state.get("sub_stage_html"):
    sub_stage_slot.markdown(st.session_state.sub_stage_html, unsafe_allow_html=True)
if st.session_state.get("publisher_html"):
    publisher_slot.markdown(st.session_state.publisher_html, unsafe_allow_html=True)

# Validation error card
if st.session_state.get("_validation_error"):
    err = st.session_state["_validation_error"]
    st.markdown(
        render_validation_error(err["reason"], err["suggestion"]),
        unsafe_allow_html=True,
    )

# ============================================================================
# Phase 4 — Curriculum editor slot
# Slot is empty when phase != "reviewing" → Streamlit clears it automatically
# ============================================================================
editor_slot = st.empty()
if st.session_state.get("workflow_phase") == "reviewing":
    with editor_slot.container():
        st.divider()
        render_curriculum_editor()

# ============================================================================
# Phase 4b — Build content state after curriculum is confirmed
# Runs once on first "generating_ch1" rerun when _content_initial_state is None
# ============================================================================
if (st.session_state.get("workflow_phase") == "generating_ch1"
        and st.session_state.get("_confirmed_curriculum_dict") is not None
        and st.session_state.get("_content_initial_state") is None):

    edited_dict = st.session_state["_confirmed_curriculum_dict"]

    from src.graph.state import CurriculumOutline
    edited_curriculum = None
    try:
        edited_curriculum = CurriculumOutline(**edited_dict)
    except Exception:
        pass
    if edited_curriculum is None:
        try:
            if hasattr(CurriculumOutline, "model_validate"):
                edited_curriculum = CurriculumOutline.model_validate(edited_dict)
            else:
                edited_curriculum = CurriculumOutline.parse_obj(edited_dict)
        except Exception as e:
            st.error(f"❌ Lỗi phân tích cấu trúc: {e}")

    if edited_curriculum:
        edited_sub_count = sum(len(ch.subsections) for ch in edited_curriculum.chapters)
        _enable_imgs   = st.session_state.get("_pending_config", {}).get("enable_images", True)
        _steps_per_sub = 9 if _enable_imgs else 8
        # Step estimate for Chapter 1 only (~1/N of total)
        total_chapters = len(edited_curriculum.chapters)
        ch1_subs       = len(edited_curriculum.chapters[0].subsections) if total_chapters else 1

        st.session_state["_total_steps"] = int((ch1_subs * _steps_per_sub) * 1.25)
        st.session_state["_step_count"]  = 0
        st.session_state["_sub_stages"]  = {
            "researcher": "pending", "writer": "pending",
            "reviewer": "pending", "illustrator": "pending",
        }
        content_state = build_content_initial_state(
            st.session_state.get("_planning_initial_state", {}),
            edited_curriculum,
            st.session_state.get("_planner_result", {}),
        )
        st.session_state["_content_initial_state"]     = content_state
        st.session_state["_confirmed_curriculum_dict"] = None
        st.session_state.curriculum_structure          = edited_curriculum
        st.session_state.curriculum_html               = render_curriculum_tree(edited_curriculum)
        st.session_state.current_progress["total_chapters"]    = total_chapters
        st.session_state.current_progress["total_subsections"] = edited_sub_count

        for k in [k for k in st.session_state
                  if k.startswith("_edit_") or k.startswith("_del_")
                  or k.startswith("_new_sub") or k.startswith("_add_sub")]:
            del st.session_state[k]
        st.session_state["_deleted_subs"] = set()

        st.session_state.is_running     = True
        st.session_state.event_q        = None
        st.session_state.progress_value = 0.10
        st.session_state.status_text    = "**Bước 3/4:** Đang tạo Chương 1..."

# ============================================================================
# Phase 5 — Chapter 1 preview gate slot
# Same st.empty() pattern as Phase 4: clears when phase != "previewing"
# ============================================================================
preview_slot = st.empty()
if st.session_state.get("workflow_phase") == "previewing":
    with preview_slot.container():
        st.divider()
        render_chapter1_preview(
            st.session_state.get("_chapter1_preview_content", "")
        )

# ============================================================================
# Phase 5b — Build remaining state after user confirms continue
# Runs once on first "generating_rest" rerun when event_q is None
# ============================================================================
if (st.session_state.get("workflow_phase") == "generating_rest"
        and st.session_state.get("event_q") is None
        and st.session_state.get("_remaining_state_built") is not True):

    ch1_content   = st.session_state.get("_chapter1_preview_content", "")
    content_state = st.session_state.get("_content_initial_state", {})

    remaining_state = build_remaining_state(content_state, ch1_content)
    st.session_state["_remaining_initial_state"] = remaining_state
    st.session_state["_remaining_state_built"]   = True

    # Recalculate step count for remaining chapters
    curriculum     = st.session_state.get("curriculum_structure")
    _enable_imgs   = st.session_state.get("_pending_config", {}).get("enable_images", True)
    _steps_per_sub = 9 if _enable_imgs else 8
    if curriculum and len(curriculum.chapters) > 1:
        remaining_subs = sum(
            len(ch.subsections) for ch in curriculum.chapters[1:]
        )
    else:
        remaining_subs = 0
    st.session_state["_total_steps"] = int((remaining_subs * _steps_per_sub) * 1.25) or 30
    st.session_state["_step_count"]  = 0
    st.session_state["_sub_stages"]  = {
        "researcher": "pending", "writer": "pending",
        "reviewer": "pending", "illustrator": "pending",
    }
    st.session_state.is_running     = True
    st.session_state.progress_value = 0.45
    st.session_state.status_text    = "**Bước 3/4:** Đang tạo các chương còn lại..."

# ============================================================================
# Download section
# ============================================================================
render_download_section()


# ============================================================================
# Topic submit — reset all state and start planning phase
# ============================================================================
if topic:
    st.session_state.generated_file_path  = None
    st.session_state.generated_docx_path  = None
    st.session_state.curriculum_structure = None
    st.session_state.current_progress     = {
        "chapter": 0, "subsection": 0,
        "total_chapters": 0, "total_subsections": 0,
    }
    st.session_state.event_q = None
    st.session_state["_sub_stages"] = {
        "researcher": "pending", "writer": "pending",
        "reviewer": "pending", "illustrator": "pending",
    }
    st.session_state["_total_steps"]             = 30
    st.session_state["_step_count"]              = 0
    st.session_state["_deleted_subs"]            = set()
    st.session_state["_confirmed_curriculum_dict"] = None
    st.session_state["_content_initial_state"]   = None
    st.session_state["_remaining_initial_state"] = None
    st.session_state["_remaining_state_built"]   = False
    st.session_state["_chapter1_preview_content"] = ""
    st.session_state["_planner_result"] = {"textbook_title": "", "preface_content": ""}
    st.session_state["_validation_error"] = None

    for k in [k for k in st.session_state
              if k.startswith("_edit_") or k.startswith("_del_")
              or k.startswith("_new_sub") or k.startswith("_add_sub")]:
        del st.session_state[k]

    for key in ("progress_value", "status_text", "ingestion_html",
                "planner_html", "sub_stage_html", "publisher_html", "curriculum_html"):
        st.session_state[key] = 0.0 if key == "progress_value" else ""

    stop_signal.clear()
    st.session_state.stop_event.clear()

    initial_planning_state = build_initial_state(topic, **config)
    st.session_state["_planning_initial_state"] = initial_planning_state
    st.session_state["_pending_topic"]          = topic
    st.session_state["_pending_config"]         = config

    st.session_state.workflow_phase = "planning"
    st.session_state.is_running     = True
    st.session_state.progress_value = 0.02
    st.session_state.status_text    = ""
    st.rerun()


# ============================================================================
# Thread start — planning phase
# ============================================================================
if (st.session_state.get("workflow_phase") == "planning"
        and st.session_state.get("event_q") is None):
    eq: queue.Queue[WorkflowEvent] = queue.Queue()
    st.session_state.event_q = eq
    start_planning_thread(
        st.session_state.get("_planning_initial_state", {}),
        st.session_state.get("_pending_config", {}).get("recursion_limit", 105),
        eq,
    )

# ============================================================================
# Thread start — Chapter 1 generation phase
# ============================================================================
if (st.session_state.get("workflow_phase") == "generating_ch1"
        and st.session_state.get("event_q") is None
        and st.session_state.get("_content_initial_state") is not None):
    eq_ch1: queue.Queue[WorkflowEvent] = queue.Queue()
    st.session_state.event_q = eq_ch1
    start_chapter1_thread(
        st.session_state.get("_content_initial_state", {}),
        st.session_state.get("_pending_config", {}).get("recursion_limit", 105),
        eq_ch1,
    )

# ============================================================================
# Thread start — remaining chapters generation phase
# ============================================================================
if (st.session_state.get("workflow_phase") == "generating_rest"
        and st.session_state.get("event_q") is None
        and st.session_state.get("_remaining_initial_state") is not None):
    eq_rest: queue.Queue[WorkflowEvent] = queue.Queue()
    st.session_state.event_q = eq_rest
    start_remaining_thread(
        st.session_state.get("_remaining_initial_state", {}),
        st.session_state.get("_pending_config", {}).get("recursion_limit", 105),
        eq_rest,
    )


# ============================================================================
# Drain event queue
# Runs during planning, generating_ch1, and generating_rest phases.
# st.rerun() is called OUTSIDE try/except so RerunException propagates cleanly.
# ============================================================================
_active_phase = st.session_state.get("workflow_phase", "idle")

if (_active_phase in ("planning", "generating_ch1", "generating_rest")
        and st.session_state.get("event_q") is not None):

    event_q_live:     queue.Queue[WorkflowEvent] = st.session_state.event_q  # type: ignore
    is_planning_phase = (_active_phase == "planning")
    is_ch1_phase      = (_active_phase == "generating_ch1")

    sub_stages:  dict = st.session_state.get("_sub_stages", {
        "researcher": "pending", "writer": "pending",
        "reviewer":   "pending", "illustrator": "pending",
    })
    total_steps: int = st.session_state.get("_total_steps", 30)
    step_count:  int = st.session_state.get("_step_count", 0)

    needs_rerun = False
    terminal    = False
    drain_error = None

    try:
        first = True
        while True:
            try:
                event: WorkflowEvent = event_q_live.get(timeout=0.1 if first else 0)
                first = False
            except queue.Empty:
                needs_rerun = True
                break

            needs_rerun = True
            step_count += 1

            match event.type:

                case EventType.VALIDATION_FAILED:
                    st.session_state.workflow_phase = "idle"
                    st.session_state.is_running     = False
                    st.session_state.event_q        = None
                    st.session_state.progress_value = 0.0
                    st.session_state.status_text    = ""
                    st.session_state.ingestion_html = ""
                    st.session_state["_validation_error"] = {
                        "reason":     event.validation_reason,
                        "suggestion": event.validation_suggestion,
                    }
                    terminal    = True
                    needs_rerun = True
                    break

                case EventType.INGESTION_START:
                    st.session_state.progress_value = 0.03
                    st.session_state.status_text    = (
                        "**Bước 1/4:** Đang mở rộng truy vấn và thu thập dữ liệu..."
                    )
                    
                case EventType.INGESTION_PROGRESS:
                    print(f"[DEBUG APP] received INGESTION_PROGRESS, status_text updated", flush=True)
                    st.session_state.status_text = (
                        f"**Bước 1/4:** {event.progress_message}"
                    )


                case EventType.INGESTION_DONE:
                    st.session_state.progress_value = 0.05
                    st.session_state.status_text    = "**Bước 1/4:** Thu thập dữ liệu — ✓ Hoàn tất"
                    _h = render_workflow_status(
                        "ingestion", "completed",
                        f"Thu thập dữ liệu về '{st.session_state.get('_pending_topic', '')}'"
                    )
                    st.session_state.ingestion_html = _h
                    ingestion_slot.markdown(_h, unsafe_allow_html=True)

                case EventType.PLANNER_DONE:
                    total_steps = int((3 + event.total_subsections * 9) * 1.25)
                    st.session_state.current_progress["total_chapters"]    = event.total_chapters
                    st.session_state.current_progress["total_subsections"] = event.total_subsections
                    st.session_state.curriculum_structure = event.curriculum
                    st.session_state["_planner_result"] = {
                        "textbook_title":  event.textbook_title,
                        "preface_content": event.preface_content,
                    }
                    st.session_state.progress_value = 0.10
                    st.session_state.status_text    = "**Bước 2/4:** Lập dàn ý — ✓ Hoàn tất"
                    _ph = render_workflow_status(
                        "planner", "completed",
                        f"Dàn ý: {event.curriculum.topic} "
                        f"({event.total_chapters} chương, {event.total_subsections} mục)"
                    )
                    st.session_state.planner_html = _ph
                    planner_slot.markdown(_ph, unsafe_allow_html=True)
                    _tree = render_curriculum_tree(event.curriculum)
                    st.session_state.curriculum_html = _tree
                    tree_slot.markdown(
                        "### 📚 Cấu trúc giáo trình\n\n" + _tree,
                        unsafe_allow_html=True,
                    )

                case EventType.CONTENT_UPDATE:
                    progress = min(
                        (0.10 if is_ch1_phase else 0.45)
                        + step_count / max(total_steps, 1) * (0.35 if is_ch1_phase else 0.50),
                        0.95,
                    )
                    st.session_state.progress_value = progress

                    chap         = event.chapter_idx
                    sub          = event.subsection_idx
                    total_ch     = st.session_state.current_progress["total_chapters"]
                    subs_in_chap = event.subsections_in_chapter or 1

                    if event.stage == "researcher" and event.stage_status == "start":
                        for k in sub_stages:
                            sub_stages[k] = "pending"

                    sub_stages[event.stage] = (
                        "active" if event.stage_status == "start" else "done"
                    )
                    st.session_state.status_text = (
                        f"**Bước 3/4:** Chương {chap+1}/{total_ch} · "
                        f"Mục {sub+1}/{subs_in_chap}"
                    )
                    _ss = build_sub_stage_card(sub_stages, chap, sub, subs_in_chap, total_ch)
                    st.session_state.sub_stage_html = _ss
                    sub_stage_slot.markdown(_ss, unsafe_allow_html=True)

                case EventType.CHECKPOINT:
                    for k in sub_stages:
                        sub_stages[k] = "pending"

                case EventType.CHAPTER1_PREVIEW:
                    # Chapter 1 complete — save content for preview gate
                    st.session_state["_chapter1_preview_content"] = event.chapter1_content
                    st.session_state.progress_value = 0.45
                    st.session_state.status_text    = (
                        "✅ Chương 1 hoàn tất — Xem trước trước khi tiếp tục"
                    )

                case EventType.PUBLISHER_DONE:
                    st.session_state.progress_value = 1.0
                    st.session_state.status_text    = "**Bước 4/4:** Xuất bản — ✓ Hoàn tất"
                    _pub = render_workflow_status(
                        "publisher", "completed", "Xuất bản tài liệu hoàn tất"
                    )
                    st.session_state.publisher_html = _pub
                    publisher_slot.markdown(_pub, unsafe_allow_html=True)
                    if event.final_filepath:
                        abs_path = os.path.abspath(event.final_filepath)
                        pdf_path = abs_path.replace(".md", ".pdf")
                        st.session_state.generated_file_path = (
                            pdf_path if os.path.exists(pdf_path) else
                            abs_path if os.path.exists(abs_path) else None
                        )
                    if event.final_docx_filepath:
                        docx_abs = os.path.abspath(event.final_docx_filepath)
                        if os.path.exists(docx_abs):
                            st.session_state.generated_docx_path = docx_abs

                case EventType.DONE:
                    st.session_state.event_q    = None
                    st.session_state.is_running = False
                    if is_planning_phase:
                        st.session_state.workflow_phase = "reviewing"
                        st.session_state.config_expanded = False
                    elif is_ch1_phase:
                        # Check if preview was set (multi-chapter) or publisher ran (single-chapter)
                        if st.session_state.get("_chapter1_preview_content"):
                            st.session_state.workflow_phase = "previewing"
                        else:
                            st.session_state.workflow_phase = "done"
                            st.balloons()
                    else:
                        st.session_state.workflow_phase = "done"
                        st.balloons()
                    terminal    = True
                    needs_rerun = True
                    break

                case EventType.STOPPED:
                    stop_signal.clear()
                    st.session_state.workflow_phase = "idle"
                    st.session_state.is_running     = False
                    st.session_state.event_q        = None
                    st.session_state.progress_value = 0.0
                    # Clear all progress display state
                    for _k in ("status_text", "ingestion_html", "planner_html",
                               "sub_stage_html", "publisher_html", "curriculum_html"):
                        st.session_state[_k] = ""
                    st.session_state.curriculum_structure = None
                    st.session_state["_chapter1_preview_content"] = ""
                    st.session_state["_remaining_state_built"]    = False
                    st.session_state["_remaining_initial_state"]  = None
                    st.session_state["_content_initial_state"]    = None
                    terminal    = True
                    needs_rerun = True
                    threading.Thread(target=_cleanup_background, daemon=True).start()
                    break

                case EventType.ERROR:
                    stop_signal.clear()
                    st.session_state.workflow_phase = "idle"
                    st.session_state.is_running     = False
                    st.session_state.event_q        = None
                    st.session_state.progress_value = 0.0
                    st.session_state.status_text    = f"❌ Lỗi hệ thống: {event.error}"
                    for _k in ("ingestion_html", "planner_html",
                               "sub_stage_html", "publisher_html", "curriculum_html"):
                        st.session_state[_k] = ""
                    st.session_state.curriculum_structure = None
                    st.session_state["_chapter1_preview_content"] = ""
                    st.session_state["_remaining_state_built"]    = False
                    st.session_state["_remaining_initial_state"]  = None
                    st.session_state["_content_initial_state"]    = None
                    terminal    = True
                    needs_rerun = True
                    threading.Thread(target=_cleanup_background, daemon=True).start()
                    break

        st.session_state["_sub_stages"]  = sub_stages
        st.session_state["_total_steps"] = total_steps
        st.session_state["_step_count"]  = step_count

    except Exception as exc:
        st.session_state.workflow_phase = "idle"
        st.session_state.is_running     = False
        st.session_state.event_q        = None
        st.session_state.status_text    = f"❌ Lỗi hệ thống: {exc}"
        drain_error  = exc
        needs_rerun  = False
        threading.Thread(target=_cleanup_background, daemon=True).start()

    if drain_error is not None:
        st.error(f"❌ Lỗi hệ thống: {drain_error}")
        with st.expander("Chi tiết lỗi"):
            st.exception(drain_error)

    # st.rerun() OUTSIDE try/except so RerunException propagates cleanly
    if needs_rerun:
        st.rerun()