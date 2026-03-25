"""
UI components for AI Textbook Generator.

New in Phase 4:
  - render_curriculum_editor() — review/edit gate between planner and content generation
  - build_sub_stage_card()     — HTML card for per-subsection stage progress
"""

import os
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
        # "idle" | "planning" | "reviewing" | "generating" | "done"
        "workflow_phase": "idle",
        "is_running":     False,   # True when phase in (planning, generating)
        "stop_event":     threading.Event(),
        "event_q":        None,
        # Config persistence
        "config_expanded":       False,
        "_saved_config":         None,
        "_dirs_ready":           False,
        "_curriculum_confirmed":      False,
        "_confirmed_curriculum_dict": None,
        "_show_editor":               False,
        # Planning phase outputs (forwarded to content phase)
        "_planning_initial_state": None,
        "_planner_result": {
            "textbook_title":  "",
            "preface_content": "",
        },
        # Content phase state
        "_content_initial_state": None,
        # Per-step drain state
        "_sub_stages":   {"researcher": "pending", "writer": "pending",
                          "reviewer": "pending", "illustrator": "pending"},
        "_total_steps":  30,
        "_step_count":   0,
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
        "_validation_error": None,
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
    While workflow is running the input shows the submitted topic (disabled).
    """
    config = _build_config_dict()

    _phase    = st.session_state.get("workflow_phase", "idle")
    _disabled = _phase not in ("idle", "done")

    # Show submitted topic in the input box while workflow is active
    _display_value = (
        st.session_state.get("_pending_topic", "")
        if _disabled else ""
    )

    _, center, _ = st.columns([1, 4, 1])
    with center:
        col_gear, col_form = st.columns([1, 14])

        with col_gear:
            st.button(
                "⚙️",
                help="Mở/đóng cấu hình",
                on_click=_toggle_config,
                use_container_width=True,
            )

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
                        "↑",
                        use_container_width=True,
                        disabled=_disabled,
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

def render_config_panel() -> dict:
    if not st.session_state.get("config_expanded", False):
        return st.session_state.get("_saved_config") or _build_config_dict()

    _running = st.session_state.get("workflow_phase", "idle") in ("planning", "generating")

    _, center, _ = st.columns([1, 4, 1])
    with center:
        with st.container(border=True):
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown("**📖 Nội dung**")
                num_chapters = st.slider(
                    "Số chương", min_value=1, max_value=20, value=3,
                    disabled=_running,
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
                enable_images = st.toggle(
                    "Chèn hình ảnh minh họa", value=True, disabled=_running,
                )
                st.markdown(
                    '<div class="config-info">'
                    + ("✓ Tải về, resize và chèn tự động." if enable_images
                       else "✗ Bỏ qua — giáo trình chỉ có text.")
                    + '</div>',
                    unsafe_allow_html=True,
                )
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
                if st.button("⛔ Dừng lại", type="secondary", use_container_width=True):
                    st.session_state.stop_event.set()
                    from src import stop_signal
                    stop_signal.request_stop()
                    st.session_state.workflow_phase = "idle"
                    st.session_state.is_running     = False
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
    """Render curriculum as a monospaced tree (Deep Search style)."""
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
    on_click callback for ✅ button. Fires BEFORE script reruns.
    Sets workflow_phase = "generating" so the editor condition
    (workflow_phase == "reviewing") is False on the very next rerun.
    Also builds and saves the edited curriculum dict.
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
                    "description": f"Content about {new_title}",
                    "search_query": new_title,
                    "section_type": "medium",
                })

        if edited_subs:
            edited_chapters.append({"title": ch_title, "subsections": edited_subs})

    topic = getattr(curriculum, "topic", st.session_state.get("_pending_topic", ""))
    st.session_state["_confirmed_curriculum_dict"] = (
        {"topic": topic, "chapters": edited_chapters} if edited_chapters else None
    )
    # Set phase directly — editor renders only when phase=="reviewing",
    # so this single assignment hides it on next rerun. No extra flags needed.
    st.session_state["workflow_phase"] = "generating"


def render_curriculum_editor() -> tuple[dict | None, bool]:
    """
    Editable curriculum review gate (Phase 4).
    Only renders when workflow_phase == "reviewing".
    Returns immediately (renders nothing) in any other phase.
    """
    # Hard guard — bail out immediately if not in review phase.
    # This is the final safety net regardless of what called this function.
    if st.session_state.get("workflow_phase") != "reviewing":
        return None, False

    curriculum = st.session_state.get("curriculum_structure")
    if not curriculum:
        return None, False

    # Initialise trackers on first render
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
            # ── Chapter title ────────────────────────────────────────
            st.markdown(
                f'<div class="editor-section-header">📖 Chương {i + 1}</div>',
                unsafe_allow_html=True,
            )
            ch_key = f"_edit_ch_{i}"
            if ch_key not in st.session_state:
                st.session_state[ch_key] = chapter.title
            st.text_input(
                f"chapter_title_{i}",
                key=ch_key,
                label_visibility="collapsed",
            )

            # ── Active subsections (original, not deleted) ───────────
            active_subs = [
                (orig_j, sub)
                for orig_j, sub in enumerate(chapter.subsections)
                if (i, orig_j) not in deleted
            ]

            # ── New subsections added by user ───────────────────────
            new_subs_key = f"_new_subs_{i}"
            if new_subs_key not in st.session_state:
                st.session_state[new_subs_key] = []   # list of title strings
            new_subs: list = st.session_state[new_subs_key]

            total_visible = len(active_subs) + len(new_subs)
            if total_visible == 0:
                st.warning(f"⚠️ Chương {i + 1} không còn mục nào — sẽ bị bỏ qua.")
            else:
                display_idx = 1   # sequential display counter, reset per chapter

                # Original subsections
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
                        st.text_input(
                            f"sub_{i}_{orig_j}",
                            key=sub_key,
                            label_visibility="collapsed",
                        )
                    with col_btn:
                        if st.button("🗑️", key=del_key, help="Xóa mục này"):
                            st.session_state["_deleted_subs"].add((i, orig_j))
                            st.rerun()
                    display_idx += 1

                # New subsections added by user
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
                        st.text_input(
                            f"new_sub_{i}_{k}",
                            key=new_sub_key,
                            label_visibility="collapsed",
                        )
                    with col_btn:
                        if st.button("🗑️", key=del_new_key, help="Xóa mục mới"):
                            st.session_state[new_subs_key].pop(k)
                            del st.session_state[new_sub_key]
                            st.rerun()
                    display_idx += 1

            # ── Add subsection button ────────────────────────────────
            add_key = f"_add_sub_btn_{i}"
            if st.button("➕ Thêm mục", key=add_key, help=f"Thêm mục mới vào Chương {i+1}"):
                st.session_state[f"_new_subs_{i}"].append("")
                st.rerun()

    # ── Action buttons ───────────────────────────────────────────────
    st.markdown("")
    col_confirm, col_reset, _ = st.columns([3, 1.5, 3])
    with col_confirm:
        confirmed = st.button(
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

    if not confirmed:
        return None, False

    # ── Build edited curriculum dict ─────────────────────────────────
    edited_chapters = []
    for i, chapter in enumerate(chapters):
        ch_title    = st.session_state.get(f"_edit_ch_{i}", chapter.title)
        edited_subs = []

        # Original (non-deleted) subsections
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

        # New subsections
        new_subs = st.session_state.get(f"_new_subs_{i}", [])
        for k in range(len(new_subs)):
            new_title = st.session_state.get(f"_new_sub_title_{i}_{k}", "").strip()
            if new_title:
                edited_subs.append({
                    "title":        new_title,
                    "description":  f"Nội dung về {new_title}",
                    "search_query": new_title,
                    "section_type": "medium",
                })

        if edited_subs:
            edited_chapters.append({"title": ch_title, "subsections": edited_subs})

    if not edited_chapters:
        st.error("⚠️ Cần ít nhất 1 chương với 1 mục.")
        return None, False

    topic = getattr(curriculum, "topic", st.session_state.get("_pending_topic", ""))
    return {"topic": topic, "chapters": edited_chapters}, True


# ============================================================================
# Sub-stage progress card (replaces plain-text _build_sub_stages_html)
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

    Displayed inside the main progress area while content is being generated.
    States per stage: "pending" | "active" | "done".
    """
    icons  = {
        "researcher": "🔍", "writer": "✍️",
        "reviewer":   "👁️", "illustrator": "🎨",
    }
    labels = {
        "researcher": "Nghiên cứu", "writer": "Viết nội dung",
        "reviewer":   "Kiểm tra",   "illustrator": "Hình ảnh",
    }
    syms   = {"pending": "○", "active": "⏳", "done": "✓"}
    notes  = {"pending": "", "active": " xử lý...", "done": ""}

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
# Workflow status card (ingestion / planner / publisher)
# ============================================================================

def render_workflow_status(stage: str, status: str, message: str) -> str:
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
def render_validation_error(reason: str, suggestion: str) -> str:
    """Render error card when topic is rejected by validator."""
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
        f'<div style="font-weight:600;color:{color};margin-bottom:0.3rem">{icon} Chủ đề không được chấp nhận</div>'
        f'<div style="color:{color};font-size:0.9rem">{reason}</div>'
        f'{suggestions_html}'
        f'<div style="margin-top:0.75rem;font-size:0.82rem;color:{color}">{hint}</div>'
        f'</div>'
    )

# ============================================================================
# Download section
# ============================================================================

def render_download_section() -> None:
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
    """Gear button callback — no explicit st.rerun() needed."""
    st.session_state.config_expanded = not st.session_state.get("config_expanded", False)