"""
Language helpers for textbook generation.

This module keeps UI language, detected input language, and target textbook
language handling deterministic for common cases. The LLM validator still
handles nuanced topic parsing, but these helpers make the language contract
testable without a model call.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


SUPPORTED_LANGUAGES = {"vi", "en"}
DEFAULT_LANGUAGE = "vi"


UNSUPPORTED_LANGUAGE_ALIASES: dict[str, dict[str, str]] = {
    "cs": {
        "name_en": "Czech",
        "name_vi": "tiếng Séc",
        "folded": "tieng sec|sec|cong hoa sec",
        "english": "czech",
    },
    "fr": {
        "name_en": "French",
        "name_vi": "tiếng Pháp",
        "folded": "tieng phap|phap",
        "english": "french",
    },
    "ja": {
        "name_en": "Japanese",
        "name_vi": "tiếng Nhật",
        "folded": "tieng nhat|nhat",
        "english": "japanese",
    },
    "ko": {
        "name_en": "Korean",
        "name_vi": "tiếng Hàn",
        "folded": "tieng han|han",
        "english": "korean",
    },
    "zh": {
        "name_en": "Chinese",
        "name_vi": "tiếng Trung",
        "folded": "tieng trung|trung quoc|trung",
        "english": "chinese|mandarin|cantonese",
    },
    "de": {
        "name_en": "German",
        "name_vi": "tiếng Đức",
        "folded": "tieng duc|duc",
        "english": "german",
    },
    "es": {
        "name_en": "Spanish",
        "name_vi": "tiếng Tây Ban Nha",
        "folded": "tieng tay ban nha|tay ban nha",
        "english": "spanish",
    },
    "ru": {
        "name_en": "Russian",
        "name_vi": "tiếng Nga",
        "folded": "tieng nga|nga",
        "english": "russian",
    },
    "ar": {
        "name_en": "Arabic",
        "name_vi": "tiếng Ả Rập",
        "folded": "tieng a rap|a rap",
        "english": "arabic",
    },
    "th": {
        "name_en": "Thai",
        "name_vi": "tiếng Thái",
        "folded": "tieng thai|thai lan|thai",
        "english": "thai",
    },
    "it": {
        "name_en": "Italian",
        "name_vi": "tiếng Ý",
        "folded": "tieng y",
        "english": "italian",
    },
    "pt": {
        "name_en": "Portuguese",
        "name_vi": "tiếng Bồ Đào Nha",
        "folded": "tieng bo dao nha|bo dao nha",
        "english": "portuguese",
    },
    "pl": {
        "name_en": "Polish",
        "name_vi": "tiếng Ba Lan",
        "folded": "tieng ba lan|ba lan",
        "english": "polish",
    },
    "id": {
        "name_en": "Indonesian",
        "name_vi": "tiếng Indonesia",
        "folded": "tieng indonesia|indonesia|indo",
        "english": "indonesian|bahasa indonesia",
    },
    "ms": {
        "name_en": "Malay",
        "name_vi": "tiếng Mã Lai",
        "folded": "tieng ma lai|ma lai|malay",
        "english": "malay|bahasa malaysia",
    },
    "hi": {
        "name_en": "Hindi",
        "name_vi": "tiếng Hindi",
        "folded": "tieng hindi|hindi|an do",
        "english": "hindi",
    },
    "km": {
        "name_en": "Khmer",
        "name_vi": "tiếng Khmer",
        "folded": "tieng khmer|khmer|campuchia|cam pu chia",
        "english": "khmer|cambodian",
    },
    "lo": {
        "name_en": "Lao",
        "name_vi": "tiếng Lào",
        "folded": "tieng lao|lao",
        "english": "lao|laotian",
    },
}


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str
    prompt_name: str
    chapter_label: str
    preface_heading: str
    toc_label: str
    figure_list_label: str
    figure_label: str
    default_title_prefix: str
    title_example: str
    subsection_example: str
    tone_rule: str
    filler_examples: str
    prior_section_label: str
    image_hint_language: str


LANGUAGE_PROFILES: dict[str, LanguageProfile] = {
    "vi": LanguageProfile(
        code="vi",
        name="Tiếng Việt",
        prompt_name="Vietnamese",
        chapter_label="CHƯƠNG",
        preface_heading="Lời nói đầu",
        toc_label="Mục lục",
        figure_list_label="Danh mục hình",
        figure_label="Hình",
        default_title_prefix="Giáo trình",
        title_example="Giáo trình Hóa học Đại cương",
        subsection_example="Định nghĩa và nguồn gốc",
        tone_rule="Formal Vietnamese academic prose.",
        filler_examples='"Chúng ta hãy cùng xem...", "Trong phần này tôi sẽ...", "Bạn sẽ thấy rằng..."',
        prior_section_label="Mục",
        image_hint_language="Vietnamese",
    ),
    "en": LanguageProfile(
        code="en",
        name="English",
        prompt_name="English",
        chapter_label="CHAPTER",
        preface_heading="Preface",
        toc_label="Table of Contents",
        figure_list_label="List of Figures",
        figure_label="Figure",
        default_title_prefix="Textbook",
        title_example="Introduction to General Chemistry",
        subsection_example="Definitions and Origins",
        tone_rule="Formal English academic prose.",
        filler_examples='"Let us look at...", "In this section I will...", "You will see that..."',
        prior_section_label="Section",
        image_hint_language="English",
    ),
}


_VIETNAMESE_STRONG_CHARS_RE = re.compile(
    r"[ăắằẳẵặâấầẩẫậđêếềểễệôốồổỗộơớờởỡợưứừửữự"
    r"ạảấầẩẫậẹẻếềểễệịỉọỏốồổỗộợởỡớờụủứừửữựỵỷỹ]",
    re.IGNORECASE,
)
UNSUPPORTED_SCRIPT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ja", r"[\u3040-\u30ff]"),
    ("ko", r"[\uac00-\ud7af]"),
    ("zh", r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"),
    ("ru", r"[\u0400-\u04ff]"),
    ("ar", r"[\u0600-\u06ff]"),
    ("th", r"[\u0e00-\u0e7f]"),
    ("km", r"[\u1780-\u17ff]"),
    ("lo", r"[\u0e80-\u0eff]"),
    ("hi", r"[\u0900-\u097f]"),
)

UNSUPPORTED_LATIN_CHAR_PATTERNS: tuple[tuple[str, str], ...] = (
    ("cs", r"[čďěňřšťůž]"),
    ("pl", r"[ąćęłńśźż]"),
    ("de", r"[äöüß]"),
    ("es", r"[ñ¡¿]"),
    ("fr", r"[çœæ]"),
)

UNSUPPORTED_LATIN_WORD_HINTS: dict[str, tuple[str, ...]] = {
    "cs": (
        "ucebnice",
        "zakladni",
        "obecne",
        "logiky",
        "programovani",
        "uvod",
        "zacatecniky",
        "pokrocily",
        "kurz",
    ),
    "fr": (
        "programmation",
        "avancee",
        "debutant",
        "debutants",
        "manuel",
        "cours",
        "pour",
        "informatique",
        "mathematiques",
    ),
    "de": (
        "programmierung",
        "grundlagen",
        "einfuhrung",
        "lehrbuch",
        "anfanger",
        "fortgeschritten",
        "fur",
    ),
    "es": (
        "programacion",
        "basica",
        "avanzada",
        "principiantes",
        "manual",
        "curso",
        "para",
        "universitario",
    ),
    "pt": (
        "programacao",
        "basica",
        "avancada",
        "iniciantes",
        "manual",
        "curso",
        "para",
        "universitario",
    ),
    "it": (
        "programmazione",
        "base",
        "avanzata",
        "principianti",
        "manuale",
        "corso",
        "per",
        "universitario",
    ),
}

_VI_HINTS = (
    "lap trinh",
    "giao trinh",
    "co ban",
    "can ban",
    "cao cap",
    "nang cao",
    "nhap mon",
    "cho nguoi",
    "nguoi moi",
    "nguoi hoc",
    "dai hoc",
    "lop ",
    "ung dung",
    "thuc te",
    "bai tap",
    "vi du",
    "mon hoc",
    "khoa hoc",
    "toan",
    "vat ly",
    "hoa hoc",
    "sinh hoc",
    "lich su",
    "xac suat",
    "thong ke",
    "du lieu",
    "may tinh",
    "tri tue",
    "nhan tao",
    "tuyen tinh",
    "tieng viet",
    "tieng anh",
    "bang tieng",
)

_EN_HINTS = (
    "programming",
    "basic",
    "basics",
    "beginner",
    "advanced",
    "university",
    "college",
    "level",
    "curriculum",
    "textbook",
    "course",
    "introduction",
    "machine learning",
    "data science",
    "probability",
    "statistics",
    "logic",
    "computer",
    "algorithm",
    "software",
    "with exercises",
    "examples",
    "real-world",
    "hands-on",
    "for ",
)

_REQUEST_EN_RE = re.compile(
    r"\b(in|using|written in|by)\s+english\b|"
    r"\benglish\s+(textbook|course|curriculum|version|language)\b|"
    r"\bwrite\s+(it\s+)?in\s+english\b",
    re.IGNORECASE,
)

_REQUEST_VI_RE = re.compile(
    r"\b(in|using|written in|by)\s+vietnamese\b|"
    r"\bvietnamese\s+(textbook|course|curriculum|version|language)\b|"
    r"\bwrite\s+(it\s+)?in\s+vietnamese\b",
    re.IGNORECASE,
)


def normalize_language(value: str | None, default: str = DEFAULT_LANGUAGE) -> str:
    if not value:
        return default
    normalized = str(value).lower().split("-")[0].strip()
    aliases = {
        "vietnamese": "vi",
        "viet": "vi",
        "việt": "vi",
        "anh": "en",
        "tieng viet": "vi",
        "english": "en",
        "eng": "en",
        "tieng anh": "en",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SUPPORTED_LANGUAGES else default


def get_language_profile(language: str | None) -> LanguageProfile:
    return LANGUAGE_PROFILES[normalize_language(language)]


def fold_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def get_unsupported_language_info(value: str | None) -> dict[str, str] | None:
    if not value:
        return None

    lowered = str(value).strip().lower()
    folded = fold_text(lowered)
    if not folded or normalize_language(folded, ""):
        return None

    for code, meta in UNSUPPORTED_LANGUAGE_ALIASES.items():
        folded_aliases = {alias.strip() for alias in meta["folded"].split("|") if alias.strip()}
        english_aliases = {alias.strip() for alias in meta["english"].split("|") if alias.strip()}
        names = {
            code,
            meta["name_en"].lower(),
            fold_text(meta["name_vi"]),
            *folded_aliases,
            *english_aliases,
        }
        if folded in names or lowered in names:
            return {"code": code, **meta}

    return None


def generic_unsupported_language(language_name: str) -> dict[str, str] | None:
    folded = fold_text(language_name)
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    if not folded:
        return None

    folded = re.sub(r"^(?:tieng|language|ngon ngu)\s+", "", folded).strip()
    if not folded or normalize_language(folded, ""):
        return None
    first_word = folded.split()[0]
    if normalize_language(first_word, ""):
        return None

    code = folded.replace(" ", "_")[:32]
    display = " ".join(part.capitalize() for part in folded.split())
    return {
        "code": code,
        "name_en": display,
        "name_vi": f"tiếng {display}",
        "folded": folded,
        "english": folded,
    }


def detect_requested_language(topic: str) -> str | None:
    folded = fold_text(topic)
    lowered = topic.lower()

    if (
        "bang tieng anh" in folded
        or "viet bang tieng anh" in folded
        or "tieng anh" in folded
        or _REQUEST_EN_RE.search(lowered)
    ):
        return "en"

    if (
        "bang tieng viet" in folded
        or "viet bang tieng viet" in folded
        or "tieng viet" in folded
        or _REQUEST_VI_RE.search(lowered)
    ):
        return "vi"

    return None


def _alias_group(values: str) -> str:
    aliases = [re.escape(value.strip()) for value in values.split("|") if value.strip()]
    return "(?:" + "|".join(aliases) + ")"


def detect_unsupported_requested_language(topic: str) -> dict[str, str] | None:
    """
    Detect explicit requests to generate the textbook in a language outside vi/en.

    Keep this conservative so topics *about* a foreign language are still allowed,
    e.g. "French language basics in English" should target English, not be blocked.
    """
    folded = fold_text(topic)
    lowered = topic.lower()

    for code, meta in UNSUPPORTED_LANGUAGE_ALIASES.items():
        folded_aliases = _alias_group(meta["folded"])
        english_aliases = _alias_group(meta["english"])

        vi_patterns = (
            rf"\b(bang|viet bang|viet|tao bang|xuat bang)\s+{folded_aliases}\b",
        )
        en_patterns = (
            rf"\b(in|using|written in|by)\s+{english_aliases}\b",
            rf"\bwrite\s+(it\s+)?in\s+{english_aliases}\b",
            rf"\b{english_aliases}\s+(textbook|course|curriculum|version)\b",
        )

        if any(re.search(pattern, folded, re.IGNORECASE) for pattern in vi_patterns):
            return {"code": code, **meta}
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in en_patterns):
            return {"code": code, **meta}

    generic_vi_patterns = (
        r"\b(?:duoc\s+)?(?:viet|tao|xuat|soan|bien\s+soan)\s+bang\s+(?:tieng|ngon\s+ngu)\s+([a-z][a-z0-9 ]{1,40})\b",
        r"\bbang\s+(?:tieng|ngon\s+ngu)\s+([a-z][a-z0-9 ]{1,40})\b",
    )
    for pattern in generic_vi_patterns:
        match = re.search(pattern, folded, re.IGNORECASE)
        if not match:
            continue
        unsupported = get_unsupported_language_info(match.group(1))
        if not unsupported:
            unsupported = generic_unsupported_language(match.group(1))
        if unsupported:
            return unsupported

    generic_en_patterns = (
        r"\b(?:written|write|generated|generate|created|create)\s+(?:it\s+)?in\s+([a-z][a-z0-9 -]{1,40})\b",
        r"\b(?:using|use|with)\s+(?:the\s+)?([a-z][a-z0-9 -]{1,40})\s+language\b",
        r"\bin\s+(?:the\s+)?([a-z][a-z0-9 -]{1,40})\s+language\b",
    )
    for pattern in generic_en_patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if not match:
            continue
        unsupported = get_unsupported_language_info(match.group(1))
        if not unsupported:
            unsupported = generic_unsupported_language(match.group(1))
        if unsupported:
            return unsupported

    return None


def detect_input_language(topic: str) -> str | None:
    stripped = topic.strip()
    if not stripped:
        return None

    folded = fold_text(stripped)
    if any(hint in folded for hint in _VI_HINTS):
        return "vi"
    if _VIETNAMESE_STRONG_CHARS_RE.search(stripped):
        return "vi"
    if any(hint in folded for hint in _EN_HINTS):
        return "en"

    # Mostly ASCII multi-word topics are usually English in this app, but keep
    # very short or code-like strings ambiguous so UI language can decide.
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    if len(words) >= 3:
        return "en"

    return None


def detect_unsupported_input_language(topic: str) -> dict[str, str] | None:
    """
    Detect topics primarily written in a non-supported language.

    This blocks cases like Chinese or Czech topics under English/Vietnamese UI
    from silently falling back. Small foreign terms inside a Vietnamese/English
    query are tolerated so topics about languages or named entities still work.
    """
    stripped = topic.strip()
    if not stripped:
        return None

    folded = fold_text(stripped)
    script_counts: dict[str, int] = {}
    unsupported_count = 0
    for code, pattern in UNSUPPORTED_SCRIPT_PATTERNS:
        count = len(re.findall(pattern, stripped))
        if count:
            script_counts[code] = count
            unsupported_count += count

    if unsupported_count >= 2:
        latin_count = sum(
            1
            for char in stripped
            if char.isalpha() and "LATIN" in unicodedata.name(char, "")
        )
        if latin_count and unsupported_count / (latin_count + unsupported_count) < 0.3:
            return None

        code = max(script_counts, key=script_counts.get)
        meta = UNSUPPORTED_LANGUAGE_ALIASES.get(
            code,
            {
                "name_en": "an unsupported language",
                "name_vi": "ngôn ngữ không được hỗ trợ",
                "folded": "",
                "english": "",
            },
        )
        return {"code": code, **meta}

    for code, pattern in UNSUPPORTED_LATIN_CHAR_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            meta = UNSUPPORTED_LANGUAGE_ALIASES.get(
                code,
                {
                    "name_en": "an unsupported language",
                    "name_vi": "ngôn ngữ không được hỗ trợ",
                    "folded": "",
                    "english": "",
                },
            )
            return {"code": code, **meta}

    tokens = set(re.findall(r"[a-z]{3,}", folded))
    best_code = ""
    best_count = 0
    for code, hints in UNSUPPORTED_LATIN_WORD_HINTS.items():
        count = sum(1 for hint in hints if hint in tokens or hint in folded)
        if any(len(hint) >= 8 and (hint in tokens or hint in folded) for hint in hints):
            best_code = code
            best_count = max(count, 2)
            break
        if count > best_count:
            best_code = code
            best_count = count

    if best_count < 2:
        return None

    code = best_code
    meta = UNSUPPORTED_LANGUAGE_ALIASES.get(
        code,
        {
            "name_en": "an unsupported language",
            "name_vi": "ngôn ngữ không được hỗ trợ",
            "folded": "",
            "english": "",
        },
    )
    return {"code": code, **meta}


def infer_textbook_language(topic: str, ui_language: str | None = None) -> dict:
    ui_lang = normalize_language(ui_language)
    input_language = detect_input_language(topic)
    requested_language = detect_requested_language(topic)
    unsupported_language = None if requested_language else detect_unsupported_requested_language(topic)
    unsupported_input_language = detect_unsupported_input_language(topic)

    if requested_language:
        target_language = requested_language
        language_source = "query"
        requested_language_value = requested_language
        input_language_value = (
            unsupported_input_language["code"]
            if unsupported_input_language
            else input_language or ""
        )
        unsupported_value = None
    elif unsupported_language:
        target_language = ui_lang
        language_source = "unsupported_query"
        requested_language_value = unsupported_language["code"]
        input_language_value = (
            unsupported_input_language["code"]
            if unsupported_input_language
            else input_language or ""
        )
        unsupported_value = unsupported_language
    elif unsupported_input_language:
        target_language = ui_lang
        language_source = "unsupported_input"
        requested_language_value = ""
        input_language_value = unsupported_input_language["code"]
        unsupported_value = unsupported_input_language
    elif input_language:
        target_language = input_language
        language_source = "input"
        requested_language_value = ""
        input_language_value = input_language
        unsupported_value = None
    else:
        target_language = ui_lang
        language_source = "ui"
        requested_language_value = ""
        input_language_value = ""
        unsupported_value = None

    return {
        "ui_language": ui_lang,
        "input_language": input_language_value,
        "requested_language": requested_language_value,
        "target_language": target_language,
        "language_source": language_source,
        "unsupported_language": unsupported_value["code"] if unsupported_value else "",
        "unsupported_language_name_en": unsupported_value["name_en"] if unsupported_value else "",
        "unsupported_language_name_vi": unsupported_value["name_vi"] if unsupported_value else "",
    }


def localized_validation_fallback(key: str, language: str | None = None, **kwargs) -> str:
    lang = normalize_language(language)
    unsupported_language = kwargs.get("unsupported_language") or (
        "ngôn ngữ này" if lang == "vi" else "that language"
    )
    messages = {
        "invalid_topic": {
            "vi": "Chủ đề không hợp lệ",
            "en": "The topic is not valid.",
        },
        "validator_error": {
            "vi": "Lỗi xác thực topic - vui lòng thử lại",
            "en": "Topic validation failed. Please try again.",
        },
        "validator_unavailable": {
            "vi": "Dịch vụ xác thực tạm thời không khả dụng",
            "en": "The validation service is temporarily unavailable.",
        },
        "system_validation_error": {
            "vi": "Lỗi hệ thống xác thực - vui lòng thử lại",
            "en": "System validation error. Please try again.",
        },
        "insufficient_credits": {
            "vi": "Không đủ credits. Vui lòng nạp thêm để tạo giáo trình.",
            "en": "Insufficient credits. Please top up to create textbooks.",
        },
        "unsupported_textbook_language": {
            "vi": (
                "Hệ thống hiện chỉ hỗ trợ tạo giáo trình bằng tiếng Việt và tiếng Anh. "
                f"Vui lòng bỏ yêu cầu {unsupported_language} hoặc đổi sang tiếng Việt/tiếng Anh."
            ),
            "en": (
                "The system currently supports textbook generation only in Vietnamese and English. "
                f"Please remove the {unsupported_language} request or choose Vietnamese/English."
            ),
        },
        "unsupported_input_language": {
            "vi": (
                "Hệ thống hiện chỉ hỗ trợ nhập chủ đề và tạo giáo trình bằng tiếng Việt hoặc tiếng Anh. "
                f"Phát hiện {unsupported_language}; vui lòng viết lại chủ đề bằng tiếng Việt/tiếng Anh "
                "hoặc thêm yêu cầu tạo giáo trình bằng tiếng Việt/tiếng Anh."
            ),
            "en": (
                "The system currently supports topics and textbook generation only in Vietnamese or English. "
                f"Detected {unsupported_language}; please rewrite the topic in Vietnamese/English "
                "or explicitly request Vietnamese/English output."
            ),
        },
    }
    return messages.get(key, messages["invalid_topic"])[lang]


def progress_text(language: str | None, key: str, **kwargs) -> str:
    lang = normalize_language(language)
    templates = {
        "planning_started": {
            "vi": "Bước 1/3: Đang lập dàn ý...",
            "en": "Step 1/3: Planning the outline...",
        },
        "review_curriculum": {
            "vi": "Bước 1/3: Vui lòng xem xét và xác nhận cấu trúc",
            "en": "Step 1/3: Please review and confirm the structure",
        },
        "collecting_data": {
            "vi": "Bước 2/3: Đang thu thập dữ liệu...",
            "en": "Step 2/3: Collecting source material...",
        },
        "generating_content": {
            "vi": "Bước 3/3: Đang tạo nội dung...",
            "en": "Step 3/3: Generating content...",
        },
        "generating_section": {
            "vi": "Bước 3/3: Chương {chapter}/{total_chapters} - Mục {subsection}",
            "en": "Step 3/3: Chapter {chapter}/{total_chapters} - Section {subsection}",
        },
        "publishing": {
            "vi": "Bước 3/3: Đang xuất bản...",
            "en": "Step 3/3: Publishing...",
        },
        "done": {
            "vi": "Hoàn tất!",
            "en": "Done!",
        },
        "chapter_progress": {
            "vi": "Chương {chapter}/{total_chapters} - Mục {subsection}",
            "en": "Chapter {chapter}/{total_chapters} - Section {subsection}",
        },
        "content_generation_started": {
            "vi": "Bước 3/4: Đang tạo nội dung giáo trình...",
            "en": "Step 3/4: Generating textbook content...",
        },
        "stopped": {
            "vi": "Đã dừng theo yêu cầu",
            "en": "Stopped by request",
        },
        "ingestion_error": {
            "vi": "Lỗi thu thập dữ liệu: {error}",
            "en": "Source collection error: {error}",
        },
    }
    template = templates[key][lang]
    return template.format(**kwargs)
