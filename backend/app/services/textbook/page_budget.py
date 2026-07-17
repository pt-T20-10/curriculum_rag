"""Page-budget allocation helpers for textbook generation.

The estimates here are intentionally approximate. They convert a user's desired
page count into per-section word/character targets that the writer can enforce,
while keeping the original content-level flow as a fallback when no page target
is provided.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


WARNING_RATIO = 0.25
ERROR_RATIO = 0.40
MIN_PAGES_PER_SUBSECTION = 1.0
IMAGE_PAGE_OVERHEAD_PER_SUBSECTION = 0.25

WORDS_PER_PAGE = {
    "vi": 420,
    "en": 480,
}

WORD_TO_CHAR_RATIO = {
    "vi": 5.0,
    "en": 6.0,
}

SECTION_WEIGHTS = {
    "light": 0.75,
    "medium": 1.0,
    "applied": 1.1,
    "deep": 1.35,
}

IMAGE_WORD_SCALE = {
    "light": 0.90,
    "medium": 0.78,
    "deep": 0.78,
    "applied": 0.72,
}

LAYOUT_WORD_SCALE = {
    "prose": 0.95,
    "technical": 0.72,
    "formula": 0.62,
    "code": 0.58,
    "procedure": 0.82,
    "case_based": 0.88,
    "comparative": 0.86,
}

LONG_TARGET_LAYOUT_WORD_SCALE = {
    "prose": 1.00,
    "technical": 0.95,
    "formula": 0.85,
    "code": 0.75,
    "procedure": 0.96,
    "case_based": 0.98,
    "comparative": 0.98,
}

LAYOUT_IMAGE_EXTRA_SCALE = {
    "prose": 0.92,
    "technical": 0.88,
    "formula": 0.87,
    "code": 0.86,
    "procedure": 0.90,
    "case_based": 0.90,
    "comparative": 0.90,
}

DEFAULT_SECTION_TYPE = "medium"
MIN_SECTION_PAGES = 0.5
MIN_SECTION_WORDS = 180
MAX_WORDS_PER_WRITER_CALL = 1500
MAX_WRITER_CALLS_PER_SECTION = 5

CODE_LAYOUT_KEYWORDS = (
    "python", "javascript", "java", "c++", "c#", "php", "sql", "html", "css",
    "react", "node", "api", "database", "lập trình", "lap trinh", "mã",
    "code", "cú pháp", "cu phap", "chương trình", "chuong trinh", "thuật toán",
    "thuat toan", "biến", "bien", "vòng lặp", "vong lap", "if", "else",
    "list", "tuple", "class", "function", "hàm", "ham",
)
FORMULA_LAYOUT_KEYWORDS = (
    "toán", "toan", "công thức", "cong thuc", "phương trình", "phuong trinh",
    "định lý", "dinh ly", "chứng minh", "chung minh", "tích phân", "tich phan",
    "đạo hàm", "dao ham", "xác suất", "xac suat", "thống kê", "thong ke",
    "vật lý", "vat ly", "hóa học", "hoa hoc",
)
TECHNICAL_LAYOUT_KEYWORDS = (
    "kỹ thuật", "ky thuat", "thực hành", "thuc hanh", "bài tập", "bai tap",
    "ví dụ", "vi du", "quy trình", "quy trinh", "thiết kế", "thiet ke",
    "dữ liệu", "du lieu", "mô hình", "mo hinh", "software", "engineering",
    "phần mềm", "phan mem", "công nghệ", "cong nghe", "hệ thống", "he thong",
)
PROCEDURE_LAYOUT_KEYWORDS = (
    "quy trình", "quy trinh", "tiến trình", "tien trinh", "workflow",
    "process", "procedure", "triển khai", "trien khai", "vận hành",
    "van hanh", "bảo trì", "bao tri", "kiểm thử", "kiem thu", "thực hành",
    "thuc hanh", "hướng dẫn", "huong dan", "các bước", "cac buoc",
)
CASE_BASED_LAYOUT_KEYWORDS = (
    "case", "tình huống", "tinh huong", "dự án", "du an", "doanh nghiệp",
    "doanh nghiep", "quản trị", "quan tri", "quản lý", "quan ly", "rủi ro",
    "rui ro", "nhân sự", "nhan su", "chất lượng", "chat luong", "chi phí",
    "chi phi", "ước lượng", "uoc luong", "kpi", "rubric",
)
COMPARATIVE_LAYOUT_KEYWORDS = (
    "so sánh", "so sanh", "đối chiếu", "doi chieu", "phân loại",
    "phan loai", "mô hình", "mo hinh", "lịch sử", "lich su", "địa lý",
    "dia ly", "xã hội", "xa hoi", "timeline", "giai đoạn", "giai doan",
    "nguyên nhân", "nguyen nhan", "hệ quả", "he qua",
)

EXPANSION_STRATEGIES = {
    "formula": "quantitative_formula_examples",
    "code": "code_examples_debugging_tasks",
    "procedure": "workflow_checklists_practice_steps",
    "case_based": "case_studies_rubrics_metrics",
    "comparative": "comparison_tables_timelines_frameworks",
    "technical": "models_metrics_examples",
    "prose": "analytical_examples_structured_synthesis",
}


@dataclass
class PageValidation:
    severity: str = "ok"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    estimated_total_pages: int | None = None
    target_pages: int | None = None
    front_matter_pages: int = 0
    excluded_export_pages: int = 0
    content_intro_pages: int = 0
    layout_profile: str = "prose"
    layout_word_scale: float = 1.0
    page_fill_bias: float = 1.0
    formula_density: str = "none"
    expansion_strategy: str = "analytical_examples_structured_synthesis"
    ai_note: str = ""

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)
        if self.severity == "ok":
            self.severity = "warning"

    def add_error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)
        self.severity = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "warnings": self.warnings,
            "errors": self.errors,
            "estimated_total_pages": self.estimated_total_pages,
            "target_pages": self.target_pages,
            "front_matter_pages": self.front_matter_pages,
            "excluded_export_pages": self.excluded_export_pages,
            "content_intro_pages": self.content_intro_pages,
            "layout_profile": self.layout_profile,
            "layout_word_scale": self.layout_word_scale,
            "page_fill_bias": self.page_fill_bias,
            "formula_density": self.formula_density,
            "expansion_strategy": self.expansion_strategy,
            "ai_note": self.ai_note,
        }


def _is_vi(language: str | None) -> bool:
    return _language_key(language) == "vi"


def _msg(language: str | None, vi: str, en: str) -> str:
    return vi if _is_vi(language) else en


def _language_key(language: str | None) -> str:
    return "en" if str(language or "").lower().startswith("en") else "vi"


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _round_page(value: float) -> int:
    return max(1, int(round(value)))


def _round_chars(value: float) -> int:
    return max(250, int(round(value / 50) * 50))


def _section_type(subsection: dict[str, Any]) -> str:
    raw = str(subsection.get("section_type") or DEFAULT_SECTION_TYPE).strip().lower()
    return raw if raw in SECTION_WEIGHTS else DEFAULT_SECTION_TYPE


def _layout_text(curriculum: dict[str, Any]) -> str:
    pieces: list[str] = [str(curriculum.get("topic") or "")]
    for chapter in curriculum.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        pieces.append(str(chapter.get("title") or ""))
        for subsection in chapter.get("subsections") or []:
            if not isinstance(subsection, dict):
                continue
            pieces.append(str(subsection.get("title") or ""))
            pieces.append(str(subsection.get("description") or ""))
    return " ".join(pieces).lower()


def _count_keywords(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _classify_layout_text(text: str) -> str:
    text = (text or "").lower()
    scores = {
        "code": _count_keywords(text, CODE_LAYOUT_KEYWORDS),
        "formula": _count_keywords(text, FORMULA_LAYOUT_KEYWORDS),
        "procedure": _count_keywords(text, PROCEDURE_LAYOUT_KEYWORDS),
        "case_based": _count_keywords(text, CASE_BASED_LAYOUT_KEYWORDS),
        "comparative": _count_keywords(text, COMPARATIVE_LAYOUT_KEYWORDS),
        "technical": _count_keywords(text, TECHNICAL_LAYOUT_KEYWORDS),
    }

    if scores["code"] >= 2 or (scores["code"] >= 1 and scores["technical"] >= 2):
        return "code"
    if scores["formula"] >= 2:
        return "formula"
    priority = ("procedure", "case_based", "comparative", "technical")
    best = max(priority, key=lambda key: scores[key])
    if scores[best] >= 2:
        return best
    if scores["technical"] >= 1 or scores["code"] >= 1 or scores["formula"] >= 1:
        return "technical"
    return "prose"


def estimate_layout_profile(curriculum: dict[str, Any]) -> str:
    return _classify_layout_text(_layout_text(curriculum))


def _subsection_layout_profile(
    subsection: dict[str, Any],
    chapter: dict[str, Any],
    fallback: str,
) -> str:
    text = " ".join([
        str(chapter.get("title") or ""),
        str(subsection.get("title") or ""),
        str(subsection.get("description") or ""),
        str(subsection.get("search_query") or ""),
    ])
    local_profile = _classify_layout_text(text)
    return fallback if local_profile == "prose" and fallback != "prose" else local_profile


def _layout_word_scale(
    profile: str,
    enable_images: bool,
    target_pages: float | None = None,
) -> float:
    scale_map = (
        LONG_TARGET_LAYOUT_WORD_SCALE
        if target_pages is not None and target_pages >= 80
        else LAYOUT_WORD_SCALE
    )
    base = scale_map.get(profile, scale_map["prose"])
    if enable_images:
        base *= LAYOUT_IMAGE_EXTRA_SCALE.get(profile, LAYOUT_IMAGE_EXTRA_SCALE["prose"])
    return base


def _page_fill_bias(target_pages: float, layout_profile: str) -> float:
    if target_pages < 40:
        return 1.0
    if target_pages < 80:
        base = 1.06
    elif target_pages < 120:
        base = 1.12
    else:
        base = 1.16
    if layout_profile in {"code", "formula"}:
        return min(base, 1.10)
    return base


def _formula_density(formula_policy: str | None, layout_profile: str) -> str:
    policy = str(formula_policy or "auto").strip().lower()
    if policy == "exclude":
        return "none"
    if policy == "include":
        return "contextual"
    return "high" if layout_profile == "formula" else "none"


def _expansion_strategy(layout_profile: str, formula_density: str) -> str:
    if formula_density in {"contextual", "high"} and layout_profile == "prose":
        return "domain_structuring_tools"
    return EXPANSION_STRATEGIES.get(layout_profile, EXPANSION_STRATEGIES["prose"])


def estimate_excluded_export_pages(enable_images: bool) -> float:
    pages = 2.0  # cover + TOC
    if enable_images:
        pages += 1.0
    return pages


def estimate_content_intro_pages(textbook_mode: str | None) -> float:
    return 0.0 if str(textbook_mode or "standard").strip().lower() == "practice" else 1.0


def estimate_front_matter_pages(enable_images: bool, textbook_mode: str | None) -> float:
    """Backward-compatible alias for content pages before chapters.

    The user's target page count is content-only: preface + chapter content.
    Cover, TOC, and figure list pages are excluded from this budget.
    """
    return estimate_content_intro_pages(textbook_mode)


def _relative_delta(actual: float, expected: float) -> float:
    if expected <= 0:
        return 0.0
    return abs(actual - expected) / expected


def _classify_delta(
    validation: PageValidation,
    actual: float,
    expected: float,
    warning_message: str,
    error_message: str,
) -> None:
    delta = _relative_delta(actual, expected)
    if delta > ERROR_RATIO:
        validation.add_error(error_message)
    elif delta > WARNING_RATIO:
        validation.add_warning(warning_message)


def validate_page_configuration(
    *,
    target_pages: int | float | None,
    num_chapters: int,
    max_subsections_per_chapter: int,
    enable_images: bool,
    language: str = "vi",
    textbook_mode: str = "standard",
    subsection_count: int | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Validate page budget compatibility before expensive planning/writing.

    For auto mode, ``subsection_count`` is unknown, so the upper-bound config
    ``num_chapters * max_subsections_per_chapter`` is used. For structured or
    confirmed curricula, callers should pass the actual subsection count.
    """
    validation = PageValidation()
    pages = _number(target_pages)
    content_intro_pages = estimate_content_intro_pages(textbook_mode)
    excluded_export_pages = estimate_excluded_export_pages(enable_images)
    validation.front_matter_pages = _round_page(content_intro_pages) if content_intro_pages > 0 else 0
    validation.content_intro_pages = _round_page(content_intro_pages) if content_intro_pages > 0 else 0
    validation.excluded_export_pages = _round_page(excluded_export_pages)
    validation.target_pages = _round_page(pages) if pages else None

    if pages is None:
        validation.add_error(_msg(
            language,
            "Vui lòng nhập số trang mong muốn.",
            "Please enter the desired content page count.",
        ))
        validation.ai_note = _msg(
            language,
            "Số trang nội dung mong muốn là bắt buộc vì hệ thống đang dùng số trang để tự quy đổi độ dài nội dung.",
            "Desired content pages are required because the system now derives content length from page count.",
        )
        return validation.as_dict()

    safe_chapters = max(1, int(num_chapters or 1))
    safe_max_subsections = max(1, int(max_subsections_per_chapter or 1))
    expected_subsections = (
        max(1, int(subsection_count))
        if subsection_count is not None
        else safe_chapters * safe_max_subsections
    )
    body_pages = pages - content_intro_pages
    min_pages_per_subsection = (
        MIN_PAGES_PER_SUBSECTION
        + (IMAGE_PAGE_OVERHEAD_PER_SUBSECTION if enable_images else 0.0)
    )
    min_body_pages = max(
        float(safe_chapters),
        expected_subsections * min_pages_per_subsection,
    )
    recommended_body_pages = min_body_pages * 1.25

    if body_pages <= 0:
        validation.add_error(_msg(
            language,
            "Số trang nội dung mong muốn quá thấp so với phần lời nói đầu.",
            "Desired content pages are too low for the preface.",
        ))
    elif body_pages < min_body_pages:
        validation.add_error(_msg(
            language,
            (
                f"Số trang nội dung chưa phù hợp: cần tối thiểu khoảng {_round_page(min_body_pages + content_intro_pages)} "
                f"trang cho {safe_chapters} chương và khoảng {expected_subsections} mục"
                f"{' khi có hình minh họa' if enable_images else ''}."
            ),
            (
                f"Content page count is not compatible: at least about {_round_page(min_body_pages + content_intro_pages)} "
                f"pages are needed for {safe_chapters} chapters and about {expected_subsections} sections"
                f"{' with illustrations enabled' if enable_images else ''}."
            ),
        ))
    elif body_pages < recommended_body_pages:
        message = _msg(
            language,
            (
                f"Số trang khá sát với cấu trúc dự kiến ({safe_chapters} chương, khoảng "
                f"{expected_subsections} mục). Kết quả thực tế có thể lệch ngắn hoặc dài tùy định dạng, hình ảnh, công thức và khối mã."
            ),
            (
                f"Page count is tight for the planned structure ({safe_chapters} chapters, about "
                f"{expected_subsections} sections). Actual output may be shorter or longer depending on formatting, images, formulas, and code blocks."
            ),
        )
        if strict:
            validation.add_warning(message)

    validation.estimated_total_pages = _round_page(max(pages, content_intro_pages + max(0.0, min(body_pages, recommended_body_pages))))
    if validation.severity == "ok":
        validation.ai_note = _msg(
            language,
            "Số trang nội dung mong muốn phù hợp sơ bộ với số chương, số mục và cấu hình hình ảnh; chưa bao gồm bìa, mục lục và danh mục hình.",
            "Desired content pages are preliminarily compatible with the chapter, section, and illustration settings; cover, TOC, and figure list pages are not included.",
        )
    elif validation.severity == "warning":
        validation.ai_note = _msg(
            language,
            "Cấu hình trang nội dung hơi sát; bạn có thể tiếp tục nếu chấp nhận sai số do định dạng, hình ảnh, công thức hoặc khối mã. Số trang này chưa bao gồm bìa, mục lục và danh mục hình.",
            "The content page budget is tight; you can continue if you accept deviation caused by formatting, images, formulas, or code blocks. This page count excludes cover, TOC, and figure list pages.",
        )
    else:
        validation.ai_note = _msg(
            language,
            "Cấu hình số trang nội dung chưa phù hợp. Hãy tăng số trang, giảm số chương, giảm số mục tối đa hoặc tắt hình minh họa.",
            "The content page configuration is not compatible. Increase pages, reduce chapters, reduce max sections, or disable illustrations.",
        )
    return validation.as_dict()


def _allocate_by_weights(items: list[tuple[int, float]], total_pages: float) -> dict[int, float]:
    if not items:
        return {}
    safe_total = max(0.0, total_pages)
    weight_sum = sum(max(weight, 0.01) for _, weight in items)
    if weight_sum <= 0:
        each = safe_total / len(items)
        return {idx: each for idx, _ in items}
    return {
        idx: safe_total * max(weight, 0.01) / weight_sum
        for idx, weight in items
    }


def _allocate_integer_pages(
    items: list[tuple[int, float]],
    total_pages: float,
    *,
    min_pages_per_item: int = 1,
) -> dict[int, int]:
    if not items:
        return {}
    safe_total = max(0, _round_page(total_pages))
    safe_min = max(0, int(min_pages_per_item))
    if safe_total <= 0:
        return {idx: 0 for idx, _ in items}
    if safe_min and safe_total < len(items) * safe_min:
        return {
            idx: safe_min if offset < safe_total else 0
            for offset, (idx, _) in enumerate(items)
        }

    allocations = {idx: safe_min for idx, _ in items}
    remaining = safe_total - (len(items) * safe_min)
    if remaining <= 0:
        return allocations

    weighted = _allocate_by_weights(items, remaining)
    floors = {idx: int(weighted.get(idx, 0.0)) for idx, _ in items}
    for idx, value in floors.items():
        allocations[idx] += value

    assigned = sum(allocations.values())
    leftover = max(0, safe_total - assigned)
    remainders = sorted(
        (
            (weighted.get(idx, 0.0) - floors.get(idx, 0), position, idx)
            for position, (idx, _) in enumerate(items)
        ),
        reverse=True,
    )
    for _, _, idx in remainders[:leftover]:
        allocations[idx] += 1
    return allocations


def _chapter_weight(chapter: dict[str, Any]) -> float:
    subsections = chapter.get("subsections") or []
    if not isinstance(subsections, list) or not subsections:
        return 1.0
    return sum(SECTION_WEIGHTS.get(_section_type(sub), 1.0) for sub in subsections)


def _page_budget_mode(page_count: float) -> str:
    if page_count <= 2:
        return "compact"
    if page_count <= 4:
        return "standard"
    return "expanded"


def _apply_section_budget(
    subsection: dict[str, Any],
    pages: float,
    *,
    language: str,
    enable_images: bool,
    layout_profile: str,
    page_fill_bias: float,
    formula_density: str,
    expansion_strategy: str,
    target_total_pages: float | None,
) -> float:
    section_type = _section_type(subsection)
    page_count = max(MIN_SECTION_PAGES, pages)
    page_budget_mode = _page_budget_mode(page_count)
    effective_page_count = page_count * page_fill_bias
    if enable_images and page_budget_mode == "compact":
        effective_page_count *= 0.88
    words_per_page = WORDS_PER_PAGE[_language_key(language)]
    words_per_page *= _layout_word_scale(layout_profile, enable_images, target_total_pages)
    if enable_images:
        words_per_page *= IMAGE_WORD_SCALE.get(section_type, IMAGE_WORD_SCALE["medium"])
    target_words = max(MIN_SECTION_WORDS, int(round(effective_page_count * words_per_page)))
    ratio = WORD_TO_CHAR_RATIO[_language_key(language)]
    target_chars = target_words * ratio
    min_chars = _round_chars(target_chars * 0.90)
    max_chars = _round_chars(target_chars * 1.15)
    writer_calls = max(1, int((target_words + MAX_WORDS_PER_WRITER_CALL - 1) // MAX_WORDS_PER_WRITER_CALL))

    subsection["estimated_pages"] = _round_page(page_count)
    subsection["target_pages"] = _round_page(_number(subsection.get("target_pages")) or page_count)
    subsection["target_words"] = target_words
    subsection["target_chars_min"] = min_chars
    subsection["target_chars_max"] = max(max_chars, min_chars + 250)
    subsection["writer_call_count"] = writer_calls
    subsection["layout_profile"] = layout_profile
    subsection["page_fill_bias"] = round(page_fill_bias, 3)
    subsection["page_budget_mode"] = page_budget_mode
    subsection["formula_density"] = formula_density
    subsection["expansion_strategy"] = expansion_strategy
    return page_count


def allocate_page_budget(
    curriculum: dict[str, Any],
    *,
    target_pages: int | float | None = None,
    enable_images: bool = False,
    language: str = "vi",
    textbook_mode: str = "standard",
    formula_policy: str = "auto",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return curriculum enriched with page/word/char budgets and validation."""
    enriched = deepcopy(curriculum or {})
    chapters = enriched.get("chapters") if isinstance(enriched, dict) else None
    validation = PageValidation()

    if not isinstance(chapters, list) or not chapters:
        validation.add_error(_msg(
            language,
            "Cấu trúc giáo trình cần có ít nhất một chương để ước lượng số trang.",
            "Curriculum must contain at least one chapter before estimating pages.",
        ))
        validation.ai_note = _msg(
            language,
            "AI chưa thể ước lượng số trang vì cấu trúc giáo trình chưa hợp lệ.",
            "AI cannot estimate pages because the textbook structure is not valid.",
        )
        return enriched, validation.as_dict()

    root_target = _number(target_pages) or _number(enriched.get("target_pages"))
    content_intro_pages = estimate_content_intro_pages(textbook_mode)
    excluded_export_pages = estimate_excluded_export_pages(enable_images)
    layout_profile = estimate_layout_profile(enriched)
    formula_density = _formula_density(formula_policy, layout_profile)
    expansion_strategy = _expansion_strategy(layout_profile, formula_density)
    validation.front_matter_pages = _round_page(content_intro_pages) if content_intro_pages > 0 else 0
    validation.content_intro_pages = _round_page(content_intro_pages) if content_intro_pages > 0 else 0
    validation.excluded_export_pages = _round_page(excluded_export_pages)
    validation.layout_profile = layout_profile
    validation.formula_density = formula_density
    validation.expansion_strategy = expansion_strategy

    explicit_chapter_total = sum(
        _number(chapter.get("target_pages")) or 0.0
        for chapter in chapters
        if isinstance(chapter, dict)
    )
    if root_target is None and explicit_chapter_total > 0:
        root_target = explicit_chapter_total + content_intro_pages

    if root_target is None:
        validation.ai_note = _msg(
            language,
            "Chưa có số trang mục tiêu nên hệ thống giữ cơ chế độ dài nội dung hiện tại.",
            "No target content page count was provided, so the system keeps the current content-length mechanism.",
        )
        return enriched, validation.as_dict()

    validation.target_pages = _round_page(root_target)
    layout_scale = _layout_word_scale(layout_profile, enable_images, root_target)
    validation.layout_word_scale = round(layout_scale, 3)
    page_fill_bias = _page_fill_bias(root_target, layout_profile)
    validation.page_fill_bias = round(page_fill_bias, 3)
    body_budget = root_target - content_intro_pages
    if body_budget <= 0:
        validation.add_error(_msg(
            language,
            "Số trang nội dung mong muốn phải lớn hơn phần lời nói đầu.",
            "Target content pages must be greater than the estimated preface pages.",
        ))
        validation.ai_note = _msg(
            language,
            "Số trang nội dung mục tiêu quá thấp so với phần lời nói đầu.",
            "The target content page count is too low for the preface.",
        )
        return enriched, validation.as_dict()

    enriched["target_pages"] = _round_page(root_target)
    enriched["front_matter_pages"] = _round_page(content_intro_pages) if content_intro_pages > 0 else 0
    enriched["content_intro_pages"] = _round_page(content_intro_pages) if content_intro_pages > 0 else 0
    enriched["excluded_export_pages"] = _round_page(excluded_export_pages)
    enriched["body_target_pages"] = _round_page(body_budget)
    enriched["layout_profile"] = layout_profile
    enriched["layout_word_scale"] = round(layout_scale, 3)
    enriched["page_fill_bias"] = round(page_fill_bias, 3)
    enriched["formula_density"] = formula_density
    enriched["expansion_strategy"] = expansion_strategy

    chapter_items: list[tuple[int, float]] = [
        (idx, _chapter_weight(chapter) if isinstance(chapter, dict) else 1.0)
        for idx, chapter in enumerate(chapters)
    ]
    missing_chapter_items: list[tuple[int, float]] = [
        (idx, weight)
        for idx, weight in chapter_items
        if isinstance(chapters[idx], dict) and _number(chapters[idx].get("target_pages")) is None
    ]
    chapter_auto_budget = (
        max(0.0, body_budget - explicit_chapter_total)
        if explicit_chapter_total > 0 and missing_chapter_items
        else body_budget
    )
    auto_chapter_allocations = _allocate_integer_pages(
        missing_chapter_items or chapter_items,
        chapter_auto_budget,
    )

    if explicit_chapter_total > 0 and (
        not missing_chapter_items or explicit_chapter_total > body_budget
    ):
        _classify_delta(
            validation,
            explicit_chapter_total,
            body_budget,
            _msg(
                language,
                "Tổng số trang các chương đang lệch đáng kể so với số trang nội dung còn lại sau lời nói đầu; hệ thống chỉ tiếp tục nếu bạn xác nhận.",
                "Total chapter pages differ noticeably from the content page budget remaining after the preface; the system will keep the requested structure if confirmed.",
            ),
            _msg(
                language,
                "Tổng số trang các chương lệch quá lớn so với số trang nội dung còn lại sau lời nói đầu. Vui lòng chỉnh tổng trang hoặc trang từng chương.",
                "Total chapter pages differ too much from the content page budget remaining after the preface. Please adjust the total or chapter page values.",
            ),
        )

    estimated_body_pages = 0.0
    for chapter_idx, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            continue
        subsections = chapter.get("subsections") or []
        if not isinstance(subsections, list) or not subsections:
            continue

        requested_chapter_pages = _number(chapter.get("target_pages"))
        chapter_pages = requested_chapter_pages or auto_chapter_allocations.get(chapter_idx, 0.0)
        chapter["target_pages"] = _round_page(chapter_pages)

        explicit_sub_total = sum(
            _number(sub.get("target_pages")) or 0.0
            for sub in subsections
            if isinstance(sub, dict)
        )
        missing_items = [
            (sub_idx, SECTION_WEIGHTS.get(_section_type(sub), 1.0))
            for sub_idx, sub in enumerate(subsections)
            if isinstance(sub, dict) and _number(sub.get("target_pages")) is None
        ]
        if explicit_sub_total > chapter_pages:
            validation.add_error(_msg(
                language,
                (
                    f"Tổng số trang các mục trong Chương {chapter_idx + 1} "
                    f"({ _round_page(explicit_sub_total) }) không được vượt quá "
                    f"số trang của chương ({ _round_page(chapter_pages) })."
                ),
                (
                    f"Chapter {chapter_idx + 1} subsection pages "
                    f"({ _round_page(explicit_sub_total) }) must not exceed "
                    f"the chapter page target ({ _round_page(chapter_pages) })."
                ),
            ))
        elif missing_items and explicit_sub_total + len(missing_items) > chapter_pages:
            validation.add_error(_msg(
                language,
                (
                    f"Chương {chapter_idx + 1} không còn đủ trang để phân bổ cho "
                    f"{len(missing_items)} mục chưa nhập trang. Hãy tăng trang chương "
                    "hoặc giảm trang các mục đã nhập."
                ),
                (
                    f"Chapter {chapter_idx + 1} does not have enough remaining pages "
                    f"for {len(missing_items)} sections without page targets. Increase "
                    "the chapter pages or lower the existing section pages."
                ),
            ))
        if explicit_sub_total > 0 and not missing_items:
            _classify_delta(
                validation,
                explicit_sub_total,
                chapter_pages,
                _msg(
                    language,
                    f"Tổng số trang các mục trong Chương {chapter_idx + 1} đang lệch đáng kể so với số trang của chương.",
                    f"Chapter {chapter_idx + 1} subsection pages differ noticeably from the chapter page target.",
                ),
                _msg(
                    language,
                    f"Tổng số trang các mục trong Chương {chapter_idx + 1} lệch quá lớn so với số trang của chương.",
                    f"Chapter {chapter_idx + 1} subsection pages differ too much from the chapter page target.",
                ),
            )

        remaining_pages = max(0.0, chapter_pages - explicit_sub_total)
        auto_sub_allocations = _allocate_integer_pages(missing_items, remaining_pages)

        estimated_chapter_pages = 0.0
        for sub_idx, subsection in enumerate(subsections):
            if not isinstance(subsection, dict):
                continue
            sub_pages = _number(subsection.get("target_pages"))
            if sub_pages is None:
                sub_pages = auto_sub_allocations.get(sub_idx, 0.0)
            if sub_pages <= 0:
                sub_pages = chapter_pages / max(1, len(subsections))
            subsection_profile = _subsection_layout_profile(
                subsection,
                chapter,
                layout_profile,
            )
            subsection_formula_density = _formula_density(
                formula_policy,
                subsection_profile,
            )
            subsection_strategy = _expansion_strategy(
                subsection_profile,
                subsection_formula_density,
            )
            estimated_chapter_pages += _apply_section_budget(
                subsection,
                sub_pages,
                language=language,
                enable_images=enable_images,
                layout_profile=subsection_profile,
                page_fill_bias=page_fill_bias,
                formula_density=subsection_formula_density,
                expansion_strategy=subsection_strategy,
                target_total_pages=root_target,
            )
            if int(subsection.get("writer_call_count") or 1) > MAX_WRITER_CALLS_PER_SECTION:
                validation.add_error(_msg(
                    language,
                    f"Mục {chapter_idx + 1}.{sub_idx + 1} quá dài cho một đơn vị sinh nội dung. Vui lòng tách mục hoặc giảm số trang của mục.",
                    f"Subsection {chapter_idx + 1}.{sub_idx + 1} is too large for one generation unit. Please split it or lower its page target.",
                ))

        chapter["estimated_pages"] = _round_page(estimated_chapter_pages)
        estimated_body_pages += estimated_chapter_pages

    estimated_total = estimated_body_pages + content_intro_pages
    enriched["estimated_pages"] = _round_page(estimated_total)
    validation.estimated_total_pages = _round_page(estimated_total)
    _classify_delta(
        validation,
        estimated_total,
        root_target,
        _msg(
            language,
            "Số trang nội dung ước tính đang lệch đáng kể so với tổng trang mong muốn; kết quả thực tế vẫn có thể thay đổi do định dạng, công thức và hình ảnh.",
            "Estimated content pages differ noticeably from the requested total; actual output may vary because of formatting, formulas, and images.",
        ),
        _msg(
            language,
            "Số trang nội dung ước tính lệch quá lớn so với tổng trang mong muốn. Vui lòng chỉnh lại số trang trước khi tiếp tục.",
            "Estimated content pages differ too much from the requested total. Please adjust the page targets before continuing.",
        ),
    )
    if validation.severity == "ok":
        validation.ai_note = _msg(
            language,
            "Ước lượng trang nội dung đang phù hợp với cấu trúc hiện tại. Chưa bao gồm bìa, mục lục và danh mục hình; do định dạng, bảng, code block, công thức và hình ảnh, hệ thống ưu tiên tránh thiếu trang nên kết quả có thể hơi dài hơn mục tiêu.",
            "The content page estimate fits the current structure. Cover, TOC, and figure list pages are not included; because of formatting, tables, code blocks, formulas, and images, the system prioritizes avoiding under-filled output, so the result may be slightly longer than target.",
        )
    elif validation.severity == "warning":
        validation.ai_note = _msg(
            language,
            "Cấu hình trang nội dung hơi lệch nhưng vẫn có thể tiếp tục nếu bạn chấp nhận sai số tương đối. Chưa bao gồm bìa, mục lục và danh mục hình; hệ thống ưu tiên tránh thiếu trang nên kết quả có thể hơi dài hơn mục tiêu.",
            "The content page configuration is slightly off, but you can continue if you accept the approximate deviation. Cover, TOC, and figure list pages are not included; the system prioritizes avoiding under-filled output, so the result may be slightly longer than target.",
        )
    else:
        validation.ai_note = _msg(
            language,
            "Cấu hình trang nội dung đang lệch quá lớn; nên chỉnh lại tổng trang, trang chương hoặc tách/gộp tiểu mục.",
            "The content page configuration is too far off; adjust total pages, chapter pages, or split/merge sections.",
        )
    return enriched, validation.as_dict()


def page_budget_enabled(curriculum: Any) -> bool:
    if not isinstance(curriculum, dict):
        return False
    if _number(curriculum.get("target_pages")) is not None:
        return True
    chapters = curriculum.get("chapters")
    if not isinstance(chapters, list):
        return False
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        if _number(chapter.get("target_pages")) is not None:
            return True
        for subsection in chapter.get("subsections") or []:
            if isinstance(subsection, dict) and _number(subsection.get("target_pages")) is not None:
                return True
    return False
