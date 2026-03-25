"""
UI components for AI Textbook Generator.

Phase 4: render_curriculum_editor() — curriculum review/edit gate
Phase 5: render_chapter1_preview()  — Chapter 1 preview gate
"""

import os
import re
import threading
from pathlib import Path

import streamlit as st


# ============================================================================
# Session state
# ============================================================================

def init_session_state() -> None:
    defaults = {
        # Output files
        "generated_file_path":  None,
        "generated_docx_path":  None,
        # Curriculum
        "curriculum_structure": None,
        "current_progress": {
            "chapter": 0, "subsection": 0,
            "total_chapters": 0, "total_subsections": 0,
        },
        # Phase management
        # "idle" | "planning" | "reviewing" | "generating_ch1"
        # | "previewing" | "generating_rest" | "done"
        "workflow_phase": "idle",
        "is_running":     False,
        "stop_event":     threading.Event(),
        "event_q":        None,
        # Config persistence
        "config_expanded":            False,
        "_saved_config":              None,
        "_dirs_ready":                False,
        "_curriculum_confirmed":      False,
        "_confirmed_curriculum_dict": None,
        # Planning outputs
        "_planning_initial_state": None,
        "_planner_result": {"textbook_title": "", "preface_content": ""},
        # Content phase state
        "_content_initial_state":  None,
        # Chapter 1 preview (Phase 5)
        "_chapter1_preview_content": "",
        # Per-step drain state
        "_sub_stages": {
            "researcher": "pending", "writer": "pending",
            "reviewer":   "pending", "illustrator": "pending",
        },
        "_total_steps": 30,
        "_step_count":  0,
        # Progress display — persists across reruns
        "progress_value":  0.0,
        "status_text":     "",
        "ingestion_html":  "",
        "planner_html":    "",
        "sub_stage_html":  "",
        "publisher_html":  "",
        "curriculum_html": "",
        # Curriculum editor state
        "_deleted_subs":   set(),
        # Topic / config carry-through
        "_pending_topic":  "",
        "_pending_config": {},
        # Validation
        "_validation_error": None,
        # Image toggle confirmation
        "_images_confirmed":     False,
        "_image_warning_pending": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ============================================================================
# CSS
# ============================================================================

def load_css() -> None:
    css_path = Path(__file__).parent / "styles.css"
    css = css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ============================================================================
# Sidebar
# ============================================================================

def render_sidebar() -> None:
    with st.sidebar:
        st.header("📊 Thống kê")
        if st.session_state.curriculum_structure:
            st.metric("Số chương",
                      st.session_state.current_progress["total_chapters"])
            st.metric("Tổng số mục",
                      st.session_state.current_progress["total_subsections"])
        else:
            st.caption("Chưa có dàn ý.")
        st.divider()
        if st.button("🧹 Xóa Cache & Reset", use_container_width=True):
            st.session_state.clear()
            st.rerun()


# ============================================================================
# Input row
# ============================================================================

def render_input_row() -> tuple[str | None, dict]:
    """
    Render: [⚙️] [text input...] [↑]
    Returns (topic_submitted | None, default_config_dict).
    Input is disabled and shows the pending topic while any workflow phase is active.
    """
    config = _build_config_dict()

    _phase    = st.session_state.get("workflow_phase", "idle")
    _disabled = _phase not in ("idle", "done")

    _display_value = (
        st.session_state.get("_pending_topic", "") if _disabled else ""
    )

    _, center, _ = st.columns([1, 4, 1])
    with center:
        col_gear, col_form = st.columns([1, 14])

        with col_gear:
            st.button("⚙️", help="Mở/đóng cấu hình",
                      on_click=_toggle_config, use_container_width=True)

        with col_form:
            with st.form("topic_form", clear_on_submit=True, border=False):
                col_text, col_send = st.columns([16, 1])
                with col_text:
                    topic_input = st.text_input(
                        "Chủ đề giáo trình",
                        value=_display_value,
                        placeholder="Nhập chủ đề giáo trình...",
                        label_visibility="collapsed",
                        disabled=_disabled,
                    )
                with col_send:
                    submitted = st.form_submit_button(
                        "↑", use_container_width=True, disabled=_disabled,
                    )

    topic = None
    if submitted:
        stripped = topic_input.strip() if topic_input else ""
        if not stripped:
            st.toast("Vui lòng nhập chủ đề giáo trình.", icon="⚠️")
        elif len(stripped) < 3:
            st.toast("Chủ đề quá ngắn, vui lòng nhập rõ hơn.", icon="⚠️")
        elif not any(c.isalpha() for c in stripped):
            st.toast("Chủ đề không hợp lệ.", icon="⚠️")
        else:
            topic = stripped
    return topic, config


# ============================================================================
# Config panel
# ============================================================================

# --- Image toggle callbacks (must be module-level for Streamlit on_change/on_click) ---

def _img_toggle_changed() -> None:
    """on_change callback for the image illustration toggle."""
    toggled_on = st.session_state.get("_img_toggle", False)
    if toggled_on and not st.session_state["_images_confirmed"]:
        # User flipped ON without confirming — flag warning; visual revert handled pre-render.
        st.session_state["_image_warning_pending"] = True
    elif not toggled_on and st.session_state["_images_confirmed"]:
        # User flipped OFF after a previous confirmation — disable images.
        st.session_state["_images_confirmed"] = False
        st.session_state["_image_warning_pending"] = False


def _img_confirm() -> None:
    """on_click callback for the Confirm button in the image warning dialog."""
    st.session_state["_images_confirmed"] = True
    st.session_state["_image_warning_pending"] = False


def _img_cancel() -> None:
    """on_click callback for the Cancel button in the image warning dialog."""
    st.session_state["_images_confirmed"] = False
    st.session_state["_image_warning_pending"] = False


def render_config_panel() -> dict:
    if not st.session_state.get("config_expanded", False):
        return st.session_state.get("_saved_config") or _build_config_dict()

    _running = st.session_state.get("workflow_phase", "idle") in (
        "planning", "generating_ch1", "generating_rest"
    )

    _, center, _ = st.columns([1, 4, 1])
    with center:
        with st.container(border=True):
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown("**📖 Nội dung**")
                num_chapters = st.slider(
                    "Số chương", min_value=1, max_value=20, value=3, disabled=_running,
                )
                _level_desc = {
                    "Ngắn":       "~350–500 từ/mục · Súc tích",
                    "Trung Bình": "~600–950 từ/mục · Cân bằng",
                    "Dài":        "~1000–1500 từ/mục · Chi tiết",
                    "Rất Dài":    "~1400–2200 từ/mục · Học thuật",
                }
                content_level = st.radio(
                    "Độ dài nội dung",
                    options=["Ngắn", "Trung Bình", "Dài", "Rất Dài"],
                    index=1, horizontal=True, disabled=_running,
                )
                st.markdown(
                    f'<div class="config-info">{_level_desc[content_level]}</div>',
                    unsafe_allow_html=True,
                )
                max_subsections = st.slider(
                    "Số mục tối đa / chương", min_value=2, max_value=10, value=3,
                    disabled=_running,
                )

            with col_b:
                st.markdown("**🖼️ Hình ảnh & Xuất**")

                # Sync toggle widget key to confirmed/pending state BEFORE instantiation.
                # Setting session_state BEFORE the widget renders is always allowed.
                _desired_toggle = st.session_state.get("_images_confirmed", False)
                if st.session_state.get("_image_warning_pending"):
                    _desired_toggle = False  # Revert to OFF while warning is displayed.
                st.session_state["_img_toggle"] = _desired_toggle

                st.toggle(
                    "Chèn hình ảnh minh họa",
                    key="_img_toggle",
                    disabled=_running,
                    on_change=_img_toggle_changed,
                )

                enable_images = st.session_state["_images_confirmed"]

                st.markdown(
                    '<div class="config-info">'
                    + ("✓ Tải về, resize và chèn tự động." if enable_images
                       else "✗ Bỏ qua — giáo trình chỉ có text.")
                    + '</div>',
                    unsafe_allow_html=True,
                )

                if not _running and st.session_state.get("_image_warning_pending"):
                    st.warning(
                        "⚠️ **Lưu ý về hình ảnh minh họa:**\n"
                        "- Hình ảnh được tìm kiếm từ web hoặc tạo bởi AI\n"
                        "- Có thể không hoàn toàn chính xác với nội dung giáo trình\n"
                        "- Nên kiểm tra lại từng hình sau khi xuất bản\n\n"
                        "Bạn có muốn tiếp tục chèn hình ảnh không?"
                    )
                    _col_yes, _col_no = st.columns(2)
                    with _col_yes:
                        st.button("✅ Xác nhận", key="_img_confirm_btn",
                                  use_container_width=True, on_click=_img_confirm)
                    with _col_no:
                        st.button("❌ Hủy", key="_img_cancel_btn",
                                  use_container_width=True, on_click=_img_cancel)

                export_formats = st.multiselect(
                    "Định dạng xuất", options=["PDF", "Word"], default=["PDF"],
                    disabled=_running,
                )
                if not export_formats:
                    st.warning("⚠️ Chọn ít nhất một định dạng.")
                    export_formats = ["PDF"]

            _est_subs       = num_chapters * max_subsections
            _steps_per_sub  = 9 if enable_images else 8
            recursion_limit = int((3 + _est_subs * _steps_per_sub) * 1.25)
            st.markdown(
                f'<div class="config-info">Recursion limit: <b>{recursion_limit}</b> '
                f'(~{_est_subs} mục × {_steps_per_sub} steps + 25% buffer)</div>',
                unsafe_allow_html=True,
            )

            if _running:
                st.divider()
                from src import stop_signal as _ss
                _stopping = _ss.is_stopping()
                if _stopping:
                    st.button("⏳ Đang dừng...", disabled=True,
                              use_container_width=True)
                    st.caption("Đang hoàn thành tác vụ hiện tại, vui lòng chờ...")
                else:
                    if st.button("⛔ Dừng lại", type="secondary",
                                 use_container_width=True):
                        st.session_state.stop_event.set()
                        _ss.request_stop()
                        # Do NOT reset state here — wait for STOPPED event
                        # from drain loop which is the single source of truth.
                        st.rerun()

        result = {
            "num_chapters":    num_chapters,
            "content_level":   content_level,
            "max_subsections": max_subsections,
            "enable_images":   enable_images,
            "export_formats":  export_formats,
            "recursion_limit": recursion_limit,
        }
        st.session_state["_saved_config"] = result
        return result


def _build_config_dict() -> dict:
    return {
        "num_chapters":    3,
        "content_level":   "Trung Bình",
        "max_subsections": 3,
        "enable_images":   True,
        "export_formats":  ["Word"],
        "recursion_limit": int((3 + 9 * 9) * 1.25),
    }


# ============================================================================
# Curriculum tree (read-only display)
# ============================================================================

def render_curriculum_tree(curriculum) -> str:
    """Render curriculum as a monospaced tree."""
    tree_html = '<div class="curriculum-tree">'
    tree_html += (
        f'<div style="color:#1D4ED8;font-weight:700;margin-bottom:0.5rem;">'
        f'📘 {curriculum.topic}</div>'
    )
    for idx, chapter in enumerate(curriculum.chapters, 1):
        tree_html += f'<div class="chapter-item">├─ Chương {idx}: {chapter.title}</div>'
        for sub_idx, subsection in enumerate(chapter.subsections, 1):
            is_last   = sub_idx == len(chapter.subsections)
            connector = "└─" if is_last else "├─"
            stype     = getattr(subsection, "section_type", "")
            badge     = (
                f' <span style="color:#94A3B8;font-size:0.75em">[{stype}]</span>'
                if stype else ""
            )
            tree_html += (
                f'<div class="section-item">'
                f'│&nbsp;&nbsp;{connector} {idx}.{sub_idx} {subsection.title}{badge}'
                f'</div>'
            )
    tree_html += "</div>"
    return tree_html


# ============================================================================
# Curriculum editor (Phase 4)
# ============================================================================

def _confirm_curriculum_callback() -> None:
    """
    on_click callback for ✅ confirm button.
    Fires BEFORE script reruns — sets workflow_phase and saves edited dict atomically.
    """
    curriculum = st.session_state.get("curriculum_structure")
    if not curriculum:
        return

    deleted  = st.session_state.get("_deleted_subs", set())
    chapters = curriculum.chapters
    edited_chapters = []

    for i, chapter in enumerate(chapters):
        ch_title    = st.session_state.get(f"_edit_ch_{i}", chapter.title)
        edited_subs = []

        for orig_j, sub in enumerate(chapter.subsections):
            if (i, orig_j) in deleted:
                continue
            sub_title = st.session_state.get(f"_edit_sub_{i}_{orig_j}", sub.title)
            edited_subs.append({
                "title":        sub_title,
                "description":  getattr(sub, "description", ""),
                "search_query": getattr(sub, "search_query", sub_title),
                "section_type": getattr(sub, "section_type", "medium"),
            })

        new_subs = st.session_state.get(f"_new_subs_{i}", [])
        for k in range(len(new_subs)):
            new_title = st.session_state.get(f"_new_sub_title_{i}_{k}", "").strip()
            if new_title:
                edited_subs.append({
                    "title":        new_title,
                    "description":  f"Content about {new_title}",
                    "search_query": new_title,
                    "section_type": "medium",
                })

        if edited_subs:
            edited_chapters.append({"title": ch_title, "subsections": edited_subs})

    topic = getattr(curriculum, "topic", st.session_state.get("_pending_topic", ""))
    st.session_state["_confirmed_curriculum_dict"] = (
        {"topic": topic, "chapters": edited_chapters} if edited_chapters else None
    )
    # Transition to ch1 generation — editor hides because phase != "reviewing"
    st.session_state["workflow_phase"] = "generating_ch1"


def render_curriculum_editor() -> tuple[dict | None, bool]:
    """
    Editable curriculum review gate (Phase 4).
    Hard guard: returns immediately if workflow_phase != 'reviewing'.
    """
    if st.session_state.get("workflow_phase") != "reviewing":
        return None, False

    curriculum = st.session_state.get("curriculum_structure")
    if not curriculum:
        return None, False

    if not isinstance(st.session_state.get("_deleted_subs"), set):
        st.session_state["_deleted_subs"] = set()

    st.markdown(
        '<div class="review-banner">'
        '✏️&nbsp;&nbsp;Xem xét &amp; Chỉnh sửa Cấu trúc Giáo Trình'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="editor-hint">'
        'Chỉnh sửa tiêu đề, xóa hoặc thêm mục trước khi tạo nội dung. '
        'Nhấn <strong>Xác nhận</strong> khi sẵn sàng.'
        '</p>',
        unsafe_allow_html=True,
    )

    chapters = curriculum.chapters
    deleted: set = st.session_state["_deleted_subs"]

    for i, chapter in enumerate(chapters):
        with st.container(border=True):
            st.markdown(
                f'<div class="editor-section-header">📖 Chương {i + 1}</div>',
                unsafe_allow_html=True,
            )
            ch_key = f"_edit_ch_{i}"
            if ch_key not in st.session_state:
                st.session_state[ch_key] = chapter.title
            st.text_input(f"chapter_title_{i}", key=ch_key, label_visibility="collapsed")

            active_subs = [
                (orig_j, sub) for orig_j, sub in enumerate(chapter.subsections)
                if (i, orig_j) not in deleted
            ]
            new_subs_key = f"_new_subs_{i}"
            if new_subs_key not in st.session_state:
                st.session_state[new_subs_key] = []
            new_subs: list = st.session_state[new_subs_key]

            total_visible = len(active_subs) + len(new_subs)
            if total_visible == 0:
                st.warning(f"⚠️ Chương {i + 1} không còn mục nào — sẽ bị bỏ qua.")
            else:
                display_idx = 1

                for orig_j, sub in active_subs:
                    sub_key = f"_edit_sub_{i}_{orig_j}"
                    del_key = f"_del_btn_{i}_{orig_j}"
                    if sub_key not in st.session_state:
                        st.session_state[sub_key] = sub.title
                    col_num, col_inp, col_btn = st.columns([1, 10, 1])
                    with col_num:
                        st.markdown(
                            f'<div style="padding-top:0.55rem;color:#89D4FF;'
                            f'font-size:0.82rem;text-align:right">'
                            f'{i+1}.{display_idx}</div>',
                            unsafe_allow_html=True,
                        )
                    with col_inp:
                        st.text_input(f"sub_{i}_{orig_j}", key=sub_key,
                                      label_visibility="collapsed")
                    with col_btn:
                        if st.button("🗑️", key=del_key, help="Xóa mục này"):
                            st.session_state["_deleted_subs"].add((i, orig_j))
                            st.rerun()
                    display_idx += 1

                for k, _ in enumerate(new_subs):
                    new_sub_key = f"_new_sub_title_{i}_{k}"
                    del_new_key = f"_del_new_btn_{i}_{k}"
                    if new_sub_key not in st.session_state:
                        st.session_state[new_sub_key] = f"Mục {i+1}.{display_idx} (mới)"
                    col_num, col_inp, col_btn = st.columns([1, 10, 1])
                    with col_num:
                        st.markdown(
                            f'<div style="padding-top:0.55rem;color:#44ACFF;'
                            f'font-size:0.82rem;text-align:right;font-weight:600">'
                            f'{i+1}.{display_idx} ✦</div>',
                            unsafe_allow_html=True,
                        )
                    with col_inp:
                        st.text_input(f"new_sub_{i}_{k}", key=new_sub_key,
                                      label_visibility="collapsed")
                    with col_btn:
                        if st.button("🗑️", key=del_new_key, help="Xóa mục mới"):
                            st.session_state[new_subs_key].pop(k)
                            del st.session_state[new_sub_key]
                            st.rerun()
                    display_idx += 1

            add_key = f"_add_sub_btn_{i}"
            if st.button("➕ Thêm mục", key=add_key,
                         help=f"Thêm mục mới vào Chương {i+1}"):
                st.session_state[f"_new_subs_{i}"].append("")
                st.rerun()

    st.markdown("")
    col_confirm, col_reset, _ = st.columns([3, 1.5, 3])
    with col_confirm:
        st.button(
            "✅ Xác nhận & Bắt đầu tạo nội dung",
            type="primary",
            use_container_width=True,
            on_click=_confirm_curriculum_callback,
        )
    with col_reset:
        if st.button("🔄 Đặt lại", use_container_width=True):
            keys_to_del = [
                k for k in st.session_state
                if (k.startswith("_edit_") or k.startswith("_del_")
                    or k.startswith("_new_sub") or k.startswith("_add_sub"))
            ]
            for k in keys_to_del:
                del st.session_state[k]
            st.session_state["_deleted_subs"] = set()
            st.rerun()

    return None, False


# ============================================================================
# Chapter 1 preview gate (Phase 5)
# ============================================================================

def _continue_generation_callback() -> None:
    """
    on_click callback for the Continue button in the Chapter 1 preview gate.
    Sets workflow_phase = 'generating_rest' so the remaining-chapters thread starts.
    """
    st.session_state["workflow_phase"] = "generating_rest"
    st.session_state["is_running"]     = True
    st.session_state["event_q"]        = None


def _stop_early_callback() -> None:
    st.session_state["workflow_phase"]            = "idle"
    st.session_state["is_running"]                = False
    st.session_state["event_q"]                   = None
    st.session_state["_pending_topic"]            = ""
    st.session_state["_content_initial_state"]    = None
    st.session_state["_remaining_initial_state"]  = None
    st.session_state["_chapter1_preview_content"] = ""
    st.session_state["_confirmed_curriculum_dict"] = None
    st.session_state["_planner_result"]           = {"textbook_title": "", "preface_content": ""}
    st.session_state["_remaining_state_built"]    = False


def _clean_chapter1_for_preview(content: str) -> str:
    """
    Clean Chapter 1 markdown content for Streamlit preview rendering.

    Transformations applied:
    - Image tags replaced with placeholder text showing the caption
    - Typst raw blocks stripped
    - Consecutive blank lines collapsed
    - Math delimiters kept as-is (st.markdown renders $...$ with LaTeX)

    Args:
        content: Raw accumulated markdown of Chapter 1.

    Returns:
        Cleaned markdown safe for st.markdown() rendering.
    """
    # Replace image figure blocks: ![caption](path){attrs} → [Hình: caption]
    cleaned = re.sub(
        r'!\[([^\]]*)\]\([^)]+\)(?:\{[^}]*\})?',
        lambda m: f'*[Hình minh họa: {m.group(1)}]*' if m.group(1) else '*[Hình minh họa]*',
        content,
    )
    # Replace remaining IMAGE tags (not yet processed by illustrator)
    cleaned = re.sub(r'> \[IMAGE[^\]]*\]', '*[Hình minh họa]*', cleaned)

    # Strip Typst raw blocks
    cleaned = re.sub(r'```\{=typst\}.*?```', '', cleaned, flags=re.DOTALL)

    # Collapse excessive blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned.strip()


def render_chapter1_preview(content: str) -> None:
    """
    Render the Chapter 1 preview gate (Phase 5).

    Displays a cleaned markdown preview of Chapter 1 content and offers
    two actions:
      - Continue: start generating remaining chapters
      - Stop & Publish: publish Chapter 1 only as the final output

    Args:
        content: Accumulated markdown of Chapter 1 from state snapshot.
    """
    if st.session_state.get("workflow_phase") != "previewing":
        return

    st.markdown(
        '<div class="review-banner">'
        '👁️&nbsp;&nbsp;Xem trước Chương 1 — Kiểm tra trước khi tiếp tục'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="editor-hint">'
        'Đây là nội dung Chương 1 đã hoàn tất. '
        'Xem qua để đánh giá chất lượng trước khi tạo các chương còn lại.'
        '</p>',
        unsafe_allow_html=True,
    )

    # Preview in a scrollable bordered container
    with st.container(border=True):
        preview_md = _clean_chapter1_for_preview(content)
        st.markdown(preview_md)

    st.markdown("")
    col_continue, col_stop, _ = st.columns([3, 2, 3])
    with col_continue:
        st.button(
            "✅ Tiếp tục tạo các chương còn lại",
            type="primary",
            use_container_width=True,
            on_click=_continue_generation_callback,
        )
    with col_stop:
        st.button(
            "🔄 Bắt đầu lại",
            use_container_width=True,
            on_click=_stop_early_callback,
        )


# ============================================================================
# Sub-stage progress card
# ============================================================================

def build_sub_stage_card(
    sub_stages:   dict,
    chap:         int,
    sub:          int,
    subs_in_chap: int,
    total_ch:     int,
) -> str:
    """
    Return an HTML card string for per-subsection stage progress.
    States per stage: 'pending' | 'active' | 'done'.
    """
    icons  = {
        "researcher": "🔍", "writer": "✍️",
        "reviewer":   "👁️", "illustrator": "🎨",
    }
    labels = {
        "researcher": "Nghiên cứu", "writer": "Viết nội dung",
        "reviewer":   "Kiểm tra",   "illustrator": "Hình ảnh",
    }
    syms  = {"pending": "○", "active": "⏳", "done": "✓"}
    notes = {"pending": "", "active": " xử lý...", "done": ""}

    any_active = any(s == "active" for s in sub_stages.values())
    card_cls   = "active" if any_active else "pending"
    badge_cls  = "status-active" if any_active else "status-pending"
    badge_txt  = "⏳ Đang xử lý" if any_active else "⏸️ Chờ xử lý"

    stage_items = "".join(
        f'<div class="stage-item {state}">'
        f'{icons[stage]}&nbsp;{labels[stage]}<br>'
        f'<small><b>{syms[state]}</b>{notes[state]}</small>'
        f'</div>'
        for stage, state in sub_stages.items()
    )

    return (
        f'<div class="workflow-card {card_cls}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'margin-bottom:0.75rem">'
        f'<div><span style="font-size:1.1rem">⚙️</span>'
        f'&nbsp;<strong>Chương {chap+1}/{total_ch} — Mục {sub+1}/{subs_in_chap}</strong></div>'
        f'<span class="status-badge {badge_cls}">{badge_txt}</span>'
        f'</div>'
        f'<div class="stage-grid">{stage_items}</div>'
        f'</div>'
    )


# ============================================================================
# Workflow status card
# ============================================================================

def render_workflow_status(stage: str, status: str, message: str) -> str:
    """Render a workflow stage card (ingestion / planner / publisher)."""
    icons = {
        "ingestion": "🔍", "planner": "📋", "researcher": "📚",
        "writer": "✍️", "reviewer": "👁️", "illustrator": "🎨", "publisher": "📦",
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
    card_class = {"completed": "completed", "active": "active", "pending": "pending"}

    icon  = icons.get(stage, "📌")
    c_cls = card_class.get(status, "pending")
    b_cls = badge_class.get(status, "status-pending")
    badge = badge_text.get(status, "Pending")

    return (
        f'<div class="workflow-card {c_cls}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<div><span style="font-size:1.2rem;margin-right:0.5rem">{icon}</span>'
        f'<span style="color:#64748B;font-size:0.88rem">{message}</span></div>'
        f'<span class="status-badge {b_cls}">{badge}</span>'
        f'</div></div>'
    )


# ============================================================================
# Validation error card
# ============================================================================

def render_validation_error(reason: str, suggestion: str) -> str:
    """Render warning/error card when the submitted topic is rejected by the validator."""
    is_content_violation = not suggestion
    suggestions_html = ""
    if suggestion:
        items = "".join(
            f'<span style="background:#EBF6FF;color:#0078D4;padding:0.2rem 0.6rem;'
            f'border-radius:6px;margin-right:0.4rem;font-size:0.85rem">{s.strip()}</span>'
            for s in suggestion.split("|") if s.strip()
        )
        suggestions_html = f'<div style="margin-top:0.6rem">{items}</div>'

    icon   = "🚫" if is_content_violation else "⚠️"
    color  = "#DC2626" if is_content_violation else "#92400E"
    bg     = "#FEF2F2" if is_content_violation else "#FFFBEB"
    border = "#EF4444" if is_content_violation else "#F59E0B"
    hint   = "Vui lòng nhập chủ đề học thuật phù hợp." if is_content_violation \
             else "Hãy thử lại với chủ đề cụ thể hơn."

    return (
        f'<div class="workflow-card" style="border-left:4px solid {border};background:{bg}">'
        f'<div style="font-weight:600;color:{color};margin-bottom:0.3rem">'
        f'{icon} Chủ đề không được chấp nhận</div>'
        f'<div style="color:{color};font-size:0.9rem">{reason}</div>'
        f'{suggestions_html}'
        f'<div style="margin-top:0.75rem;font-size:0.82rem;color:{color}">{hint}</div>'
        f'</div>'
    )


# ============================================================================
# Download section
# ============================================================================

def render_download_section() -> None:
    """Render download buttons for generated files."""
    _has_pdf = (
        st.session_state.generated_file_path
        and str(st.session_state.generated_file_path).endswith(".pdf")
        and os.path.exists(st.session_state.generated_file_path)
    )
    _has_docx = (
        st.session_state.get("generated_docx_path")
        and os.path.exists(st.session_state.generated_docx_path)  # type: ignore
    )

    if not (_has_pdf or _has_docx):
        return

    st.divider()
    st.markdown(
        '<div class="success-box">🎉 <strong>Giáo trình của bạn đã sẵn sàng!</strong></div>',
        unsafe_allow_html=True,
    )
    st.write("")

    available = []
    if _has_pdf:
        available.append(("pdf",  st.session_state.generated_file_path))
    if _has_docx:
        available.append(("docx", st.session_state.generated_docx_path))

    cols = st.columns(len(available))
    for col, (fmt, fpath) in zip(cols, available):
        with col:
            fname    = os.path.basename(fpath)
            fsize    = os.path.getsize(fpath) / 1024
            mime_map = {
                "pdf":  "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document",
            }
            icon_map  = {"pdf": "📕", "docx": "📘"}
            label_map = {"pdf": "PDF", "docx": "Word (.docx)"}

            st.metric(f"{icon_map[fmt]} {label_map[fmt]}", f"{fsize:.1f} KB")
            with open(fpath, "rb") as f:
                st.download_button(
                    label=f"⬇️ Tải xuống {label_map[fmt]}",
                    data=f,
                    file_name=fname,
                    mime=mime_map[fmt],
                    type="primary",
                    use_container_width=True,
                )
            st.code(fpath, language=None)


# ============================================================================
# Internal helpers
# ============================================================================

def _toggle_config() -> None:
    """Gear button callback — toggles config panel without explicit st.rerun()."""
    st.session_state.config_expanded = not st.session_state.get("config_expanded", False)