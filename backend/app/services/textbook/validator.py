"""
Validator Agent for AI Textbook Generator.
"""

import json
import re
import unicodedata
from langchain_openai import ChatOpenAI
from app.config import settings
from app.services.runtime_config import get_api_key
from app.schemas.curriculum import AgentState
from app.services.textbook.language import (
    detect_unsupported_requested_language,
    generic_unsupported_language,
    infer_textbook_language,
    get_unsupported_language_info,
    localized_validation_fallback,
    normalize_language,
)
from app.utils.log_config import setup_logger

logger = setup_logger(name="ValidatorAgent", logfile="logs/agents.log")


_FORMULA_NEEDS = {"none", "likely", "essential"}
_FORMULA_POLICIES = {"auto", "include", "exclude"}


def _strip_accents(text: str) -> str:
    stripped = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D")


def _formula_scan_text(*parts: str) -> str:
    text = " ".join(str(part or "") for part in parts)
    text = _strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9+#.\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_formula_intent(text: str) -> str:
    """
    Return 'include', 'exclude', or '' when the user's text mentions formulas.

    This is intentionally deterministic so API behavior is testable and does
    not depend on the topic-validation LLM.
    """
    scan = _formula_scan_text(text)
    if not scan:
        return ""

    negative_patterns = [
        r"\b(khong|ko|k)\s+(can\s+)?(co\s+)?cong\s+thuc\b",
        r"\bkhong\s+dung\s+cong\s+thuc\b",
        r"\bkhong\s+dua\s+cong\s+thuc\b",
        r"\bno\s+(math\s+)?formula(s)?\b",
        r"\bwithout\s+(math\s+)?formula(s)?\b",
        r"\bno\s+equation(s)?\b",
        r"\bwithout\s+equation(s)?\b",
    ]
    if any(re.search(pattern, scan) for pattern in negative_patterns):
        return "exclude"

    positive_patterns = [
        r"\bco\s+(cac\s+)?cong\s+thuc\b",
        r"\bcan\s+(co\s+)?cong\s+thuc\b",
        r"\bthem\s+(cac\s+)?cong\s+thuc\b",
        r"\bkem\s+(cac\s+)?cong\s+thuc\b",
        r"\bcong\s+thuc\s+(toan|chuan|latex)\b",
        r"\b(include|with|add|use)\s+(math\s+)?formula(s)?\b",
        r"\bformula(s)?\b",
        r"\bequation(s)?\b",
        r"\bderivation(s)?\b",
        r"\blatex\b",
    ]
    if any(re.search(pattern, scan) for pattern in positive_patterns):
        return "include"
    return ""


def classify_formula_need(topic: str, core_topic: str = "") -> str:
    """
    Classify whether a textbook subject naturally needs mathematical formulas.

    Values:
      - essential: formulas are intrinsic to the subject.
      - likely: formulas can be useful and expected, but should be confirmed.
      - none: formulas are usually inappropriate unless the topic is reframed.
    """
    scan = _formula_scan_text(topic, core_topic)
    if not scan:
        return "none"

    essential_patterns = [
        r"\b(toan|math|mathematics)\b",
        r"\b(dai\s+so|giai\s+tich|hinh\s+hoc|luong\s+giac)\b",
        r"\b(phuong\s+trinh|equation)\b",
        r"\b(calculus|algebra|geometry|trigonometry)\b",
        r"\b(xac\s+suat|thong\s+ke|probability|statistics|statistical)\b",
        r"\b(vat\s+ly|physics|co\s+hoc|mechanics|dien\s+tu|electronics)\b",
        r"\b(hoa\s+hoc|chemistry|stoichiometry|thermodynamics)\b",
    ]
    if any(re.search(pattern, scan) for pattern in essential_patterns):
        return "essential"

    likely_patterns = [
        r"\b(machine\s+learning|hoc\s+may|deep\s+learning|neural\s+network)\b",
        r"\b(ai|artificial\s+intelligence|tri\s+tue\s+nhan\s+tao)\b",
        r"\b(data\s+science|khoa\s+hoc\s+du\s+lieu|data\s+analysis)\b",
        r"\b(econometrics|kinh\s+te\s+luong|quantitative|dinh\s+luong)\b",
        r"\b(finance|tai\s+chinh|risk\s+management)\b",
        r"\b(algorithm\s+analysis|phan\s+tich\s+thuat\s+toan)\b",
        r"\b(signal\s+processing|xu\s+ly\s+tin\s+hieu|control\s+system)\b",
        r"\b(cryptography|mat\s+ma\s+hoc|optimization|toi\s+uu)\b",
        r"\b(image\s+processing|computer\s+vision|xu\s+ly\s+anh|thi\s+giac\s+may)\b",
        r"\b(nen\s+anh|image\s+compression|nhan\s+dang\s+anh|image\s+recognition)\b",
        r"\b(edge\s+detection|bien\s+anh|filtering|loc\s+anh|transform|chuyen\s+doi\s+anh)\b",
        r"\b(software\s+engineering|cong\s+nghe\s+phan\s+mem|software\s+metrics)\b",
        r"\b(excel|spreadsheet|bang\s+tinh)\s+formula(s)?\b",
        r"\bcong\s+thuc\s+(excel|spreadsheet|bang\s+tinh)\b",
    ]
    if any(re.search(pattern, scan) for pattern in likely_patterns):
        return "likely"

    return "none"


def formula_reason(
    formula_need: str,
    ui_language: str = "vi",
    conflict: bool = False,
    confirmation: bool = False,
) -> str:
    language = normalize_language(ui_language)
    if conflict:
        if language == "vi":
            return (
                "Chủ đề này thường không phù hợp để ép công thức. "
                "Hãy bỏ yêu cầu công thức hoặc mô tả rõ phần định lượng cần có."
            )
        return (
            "This topic usually should not force formulas. "
            "Remove the formula request or describe the quantitative angle clearly."
        )
    if confirmation:
        if language == "vi":
            return "Chủ đề này có thể cần công thức. Vui lòng xác nhận trước khi tạo dàn ý."
        return "This topic may need formulas. Please confirm before creating the outline."
    if formula_need == "essential":
        return (
            "Chủ đề này thường cần công thức."
            if language == "vi"
            else "This topic normally requires formulas."
        )
    if formula_need == "likely":
        return (
            "Chủ đề này có thể cần công thức."
            if language == "vi"
            else "This topic may benefit from formulas."
        )
    return ""


def apply_formula_validation(
    result: dict,
    topic: str,
    formula_policy: str = "auto",
    formula_confirmed: bool = False,
    ui_language: str = "vi",
) -> dict:
    policy = formula_policy if formula_policy in _FORMULA_POLICIES else "auto"
    formula_need = classify_formula_need(topic, str(result.get("core_topic") or ""))
    intent = detect_formula_intent(
        " ".join([
            topic,
            str(result.get("user_requirements") or ""),
            str(result.get("core_topic") or ""),
        ])
    )
    formula_intent_present = bool(intent)
    conflict = (
        (formula_need == "none" and (policy == "include" or intent == "include"))
        or (formula_need == "essential" and (policy == "exclude" or intent == "exclude"))
    )
    confirmation_required = (
        formula_need == "likely"
        and policy != "exclude"
        and intent != "exclude"
        and not formula_confirmed
        and not conflict
    )

    effective_policy = policy
    if formula_need == "essential" and not conflict:
        effective_policy = "include"
    elif intent in {"include", "exclude"} and not conflict:
        effective_policy = intent

    enriched = dict(result)
    enriched.update({
        "formula_need": formula_need,
        "formula_policy": effective_policy,
        "formula_intent_present": formula_intent_present,
        "formula_confirmation_required": confirmation_required,
        "formula_conflict": conflict,
        "formula_reason": formula_reason(
            formula_need,
            ui_language,
            conflict=conflict,
            confirmation=confirmation_required,
        ),
    })
    return enriched


_TOPIC_FILLER_TOKENS = {
    "a",
    "an",
    "and",
    "anh",
    "bang",
    "basic",
    "beginner",
    "bằng",
    "cho",
    "co",
    "có",
    "course",
    "cuốn",
    "ebook",
    "en",
    "english",
    "for",
    "giao",
    "giáo",
    "in",
    "khoa",
    "learn",
    "learning",
    "môn",
    "sach",
    "sách",
    "textbook",
    "tieng",
    "tiếng",
    "trinh",
    "trình",
    "vi",
    "viet",
    "việt",
    "vietnamese",
    "về",
    "with",
}

_KNOWN_SHORT_TECH_TOKENS = {
    "ai",
    "c",
    "c#",
    "c++",
    "css",
    "go",
    "html",
    "ip",
    "js",
    "ml",
    "nlp",
    "os",
    "php",
    "r",
    "sql",
    "ui",
    "ux",
}


def _topic_tokens(text: str) -> list[str]:
    """Tokenize topic-like text while preserving common technical tokens."""
    return re.findall(r"[\w+#.]+", str(text or "").lower(), flags=re.UNICODE)


def _token_counts(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _looks_like_noise_token(token: str) -> bool:
    if not token or token in _TOPIC_FILLER_TOKENS:
        return False
    if token in _KNOWN_SHORT_TECH_TOKENS:
        return False
    if token.isdigit():
        return len(token) >= 2
    if re.fullmatch(r"[a-z]{3,}", token):
        return True
    if re.fullmatch(r"(.)\1{2,}", token):
        return True
    return False


def _unexplained_topic_noise(topic: str, result: dict) -> list[str]:
    """
    Detect leftover junk that the validator ignored while extracting core_topic.

    The LLM is allowed to normalize and translate topics, so this guard only
    fires when the extracted core/requirements already explain most of the raw
    input and the remaining tokens are clearly low-information noise.
    """
    topic_tokens = _topic_tokens(topic)
    if not topic_tokens:
        return []

    explained_tokens = _topic_tokens(
        " ".join([
            str(result.get("core_topic") or ""),
            str(result.get("user_requirements") or ""),
        ])
    )
    if not explained_tokens:
        return []

    explained_counts = _token_counts(explained_tokens)
    leftover: list[str] = []
    explained_matches = 0

    for token in topic_tokens:
        if explained_counts.get(token, 0) > 0:
            explained_counts[token] -= 1
            explained_matches += 1
        elif token not in _TOPIC_FILLER_TOKENS:
            leftover.append(token)

    if not leftover:
        return []

    coverage = explained_matches / max(len(topic_tokens), 1)
    if coverage < 0.5:
        return []

    noisy = [token for token in leftover if _looks_like_noise_token(token)]
    if not noisy:
        return []

    if len(noisy) == len(leftover) or any(token.isdigit() for token in noisy):
        return noisy
    return []


def _parse_json_object(raw: str) -> dict:
    """
    Parse an LLM JSON object response.

    Models sometimes ignore "ONLY JSON" and wrap the object in ```json fences.
    This parser accepts raw JSON, fenced JSON, or text containing one JSON object.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _normalize_validation_result(result: dict, language_info: dict) -> dict:
    valid_types = {"scholarly", "technical", "practical", "lifestyle"}
    content_type = str(result.get("content_type") or "").strip().lower()
    if content_type not in valid_types:
        content_type = "technical"

    deterministic_source = language_info.get("language_source", "ui")
    llm_source = str(result.get("language_source") or "").strip()
    unsupported_output_language = (
        get_unsupported_language_info(result.get("requested_language"))
        or get_unsupported_language_info(result.get("target_language"))
        or generic_unsupported_language(str(result.get("requested_language") or ""))
        or generic_unsupported_language(str(result.get("target_language") or ""))
    )
    llm_requested_language = normalize_language(result.get("requested_language"), "")
    llm_target_language = normalize_language(result.get("target_language"), "")

    if unsupported_output_language:
        requested_language = unsupported_output_language["code"]
        target_language = language_info.get("target_language", "vi")
        language_source = "unsupported_query"
        unsupported_language = unsupported_output_language["code"]
        unsupported_language_name_en = unsupported_output_language["name_en"]
        unsupported_language_name_vi = unsupported_output_language["name_vi"]
    elif deterministic_source == "unsupported_input" and llm_source == "query" and llm_target_language:
        requested_language = llm_requested_language or llm_target_language
        target_language = llm_target_language
        language_source = "query"
        unsupported_language = ""
        unsupported_language_name_en = ""
        unsupported_language_name_vi = ""
    elif deterministic_source != "unsupported_input" and (llm_requested_language or llm_target_language):
        requested_language = llm_requested_language or language_info.get("requested_language", "")
        target_language = llm_target_language or llm_requested_language
        language_source = llm_source if llm_source in {"query", "input", "ui"} else deterministic_source
        unsupported_language = language_info.get("unsupported_language", "")
        unsupported_language_name_en = language_info.get("unsupported_language_name_en", "")
        unsupported_language_name_vi = language_info.get("unsupported_language_name_vi", "")
    else:
        requested_language = language_info.get("requested_language", "")
        target_language = language_info.get("target_language", "vi")
        language_source = deterministic_source
        unsupported_language = language_info.get("unsupported_language", "")
        unsupported_language_name_en = language_info.get("unsupported_language_name_en", "")
        unsupported_language_name_vi = language_info.get("unsupported_language_name_vi", "")

    normalized = dict(result)
    normalized["valid"] = bool(result.get("valid", False))
    normalized["reason"] = str(result.get("reason") or "")
    normalized["suggestion"] = str(result.get("suggestion") or "")
    normalized["content_type"] = content_type
    normalized["core_topic"] = str(result.get("core_topic") or "")
    normalized["user_requirements"] = str(result.get("user_requirements") or "")
    normalized["formula_need"] = str(result.get("formula_need") or "none")
    normalized["formula_policy"] = str(result.get("formula_policy") or "auto")
    normalized["formula_intent_present"] = bool(result.get("formula_intent_present", False))
    normalized["formula_confirmation_required"] = bool(result.get("formula_confirmation_required", False))
    normalized["formula_conflict"] = bool(result.get("formula_conflict", False))
    normalized["formula_reason"] = str(result.get("formula_reason") or "")
    normalized.update({
        "input_language": language_info.get("input_language", ""),
        "requested_language": requested_language,
        "target_language": target_language,
        "language_source": language_source,
        "unsupported_language": unsupported_language,
        "unsupported_language_name_en": unsupported_language_name_en,
        "unsupported_language_name_vi": unsupported_language_name_vi,
    })
    return normalized


def _localized_unsupported_language_name(ui_language: str, language_info: dict) -> str:
    key = (
        "unsupported_language_name_vi"
        if normalize_language(ui_language) == "vi"
        else "unsupported_language_name_en"
    )
    return (
        language_info.get(key)
        or language_info.get("unsupported_language")
        or ("ngôn ngữ này" if normalize_language(ui_language) == "vi" else "that language")
    )


def _with_unsupported_language(language_info: dict, unsupported_language: dict) -> dict:
    return {
        **language_info,
        "requested_language": unsupported_language.get("code", ""),
        "language_source": "unsupported_query",
        "unsupported_language": unsupported_language.get("code", ""),
        "unsupported_language_name_en": unsupported_language.get("name_en", ""),
        "unsupported_language_name_vi": unsupported_language.get("name_vi", ""),
    }


def _validation_fallback(
    key: str,
    ui_language: str,
    language_info: dict,
    valid: bool = False,
) -> dict:
    reason = ""
    if not valid:
        reason = localized_validation_fallback(
            key,
            ui_language,
            unsupported_language=_localized_unsupported_language_name(ui_language, language_info),
        )

    return {
        "valid": valid,
        "reason": reason,
        "suggestion": "",
        "content_type": "technical",
        "core_topic": "",
        "user_requirements": "",
        "input_language": language_info.get("input_language", ""),
        "requested_language": language_info.get("requested_language", ""),
        "target_language": language_info.get("target_language", normalize_language(ui_language)),
        "language_source": language_info.get("language_source", "ui"),
        "unsupported_language": language_info.get("unsupported_language", ""),
        "unsupported_language_name_en": language_info.get("unsupported_language_name_en", ""),
        "unsupported_language_name_vi": language_info.get("unsupported_language_name_vi", ""),
        "formula_need": "none",
        "formula_policy": "auto",
        "formula_intent_present": False,
        "formula_confirmation_required": False,
        "formula_conflict": False,
        "formula_reason": "",
    }


def validate_topic(
    topic: str,
    ui_language: str = "vi",
    formula_policy: str = "auto",
    formula_confirmed: bool = False,
) -> dict:
    """
    Validate topic suitability for textbook generation.
    
    Returns:
        dict: {
            "valid": bool,
            "reason": str,
            "suggestion": str,
            "content_type": str,
            "core_topic": str,         
            "user_requirements": str,
            "input_language": str,
            "requested_language": str,
            "target_language": "vi"|"en",
            "language_source": "query"|"input"|"ui"|"unsupported_query"|"unsupported_input",
        }
        
        On error: Returns {"valid": False, ...} to REJECT by default
    """
    ui_language = normalize_language(ui_language)
    language_info = infer_textbook_language(topic, ui_language)
    target_language = language_info["target_language"]
    feedback_language = ui_language
    logger.info(
        "[VALIDATOR] Validating topic: '%s' (ui=%s, input=%s, requested=%s, target=%s)",
        topic,
        feedback_language,
        language_info.get("input_language") or "unknown",
        language_info.get("requested_language") or "none",
        target_language,
    )

    if language_info.get("language_source") == "unsupported_query":
        logger.info(
            "[VALIDATOR] Rejected unsupported requested language: %s",
            language_info.get("unsupported_language"),
        )
        return _validation_fallback("unsupported_textbook_language", ui_language, language_info)
    
    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_CHEAP,
            api_key=get_api_key("OPENAI_API_KEY"), #type: ignore
            temperature=0,
            max_completion_tokens=700,
        )

        prompt = f"""
[CONTEXT]
You are a strict validator, topic parser, and language-aware normalizer for
educational textbook generation.

Your dual role:
1. VALIDATE if the topic is suitable (reject vague/inappropriate topics)
2. EXTRACT the core topic and user requirements (if any)
3. NORMALIZE the core topic and extracted requirements into the target textbook language
[/CONTEXT]

[TASK 1 - VALIDATION]
Evaluate this topic: "{topic}"

Decision criteria:
1. Does it have sufficient specificity (level, scope, or context)?
2. Does it violate content policies?

Return valid=true ONLY if both conditions are met.
[/TASK 1]

[TASK 2 - EXTRACTION]
If valid, parse the topic into TWO parts:

A. CORE TOPIC: The main subject/skill to teach
B. USER REQUIREMENTS: Optional additional requests (exercises, examples, etc.)

Language context:
  - UI feedback language: {feedback_language}
  - Deterministic input-language candidate: {language_info.get("input_language") or "unknown"}
  - Deterministic requested output-language candidate: {language_info.get("requested_language") or "none"}
  - Provisional target textbook language: {target_language}
  - Provisional language source: {language_info.get("language_source")}

Important language rules:
  - Return "reason" and "suggestion" in the UI feedback language ({feedback_language}).
  - The system supports textbook output only in Vietnamese and English.
  - The input topic itself must be written primarily in Vietnamese or English,
    unless it explicitly requests Vietnamese or English as the output language.
  - If the input is primarily another language, inspect the topic semantically
    for an output-language request that means "in Vietnamese" or "in English".
    This request may be written in that input language.
    Examples: Czech "ve vietnamštině" = in Vietnamese; Czech "v angličtině" = in English;
    French "en vietnamien" = in Vietnamese; German "auf Englisch" = in English.
  - If such a supported output-language request exists, set:
      requested_language: "vi" or "en"
      target_language: same value
      language_source: "query"
    Then return "core_topic" and "user_requirements" in that target language.
  - If the topic explicitly asks to generate/write the textbook in any other
    language, reject it with valid=false and explain this limit in the UI
    feedback language ({feedback_language}).
  - If the topic is primarily written in any other language and does not request
    Vietnamese/English output, reject it with valid=false and ask the user to
    rewrite the topic in Vietnamese or English.
  - Remove explicit language-control phrases from core_topic/user_requirements.
    Example: "Lập trình Python cơ bản bằng tiếng Anh"
      target_language: "en"
      core_topic: "Basic Python Programming"
      user_requirements: ""
    Example: "Python Programming Vietnamese Curriculum basic for university level"
      target_language: "vi"
      core_topic: "Lập trình Python cơ bản ở bậc đại học"
      user_requirements: "theo chương trình tiếng Việt"
    Example: "Učebnice základní obecné logiky ve vietnamštině"
      requested_language: "vi"
      target_language: "vi"
      language_source: "query"
      core_topic: "Logic đại cương cơ bản"
      user_requirements: ""
    Example: "Učebnice základní obecné logiky"
      valid: false
      reason: localized message asking the user to rewrite the topic or request Vietnamese/English output

Examples:
  Input: "Toán cao cấp 1"
  → core_topic: "Toán cao cấp 1"
  → user_requirements: ""

  Input: "Học Python có bài tập"
  → core_topic: "Python"
  → user_requirements: "có bài tập"

  Input: "Machine Learning với nhiều ví dụ code và ứng dụng thực tế"
  → core_topic: "Machine Learning"
  → user_requirements: "với nhiều ví dụ code và ứng dụng thực tế"

  Input: "Lập trình web React kèm project thực tế"
  → core_topic: "Lập trình web React"
  → user_requirements: "kèm project thực tế"

Requirement indicators (extract these phrases):
  - "có bài tập" / "with exercises"
  - "nhiều ví dụ" / "many examples"
  - "ứng dụng thực tế" / "real-world applications"
  - "kèm project" / "with projects"
  - "code examples" / "sample code"
  - "hands-on" / "thực hành"
[/TASK 2]

[CRITICAL RULES]

Rule 0 — DO NOT IGNORE JUNK:
  REJECT if the input contains a valid topic plus unrelated random text,
  meaningless letters, or meaningless numbers that are not part of the subject.
  Do not silently drop the noisy part while returning a cleaned core_topic.

  Examples to REJECT:
    ❌ "Lập trình Python abc"
    ❌ "Lập trình Python 123"
    ❌ "Machine Learning xyz"

Rule 1 — SINGLE-WORD REJECTION:
  REJECT any topic that is 1-2 isolated words WITHOUT modifiers or context.
  
  Examples of INSUFFICIENT topics (REJECT):
    ❌ "AI" (no level, no context)
    ❌ "toán" (no grade, no subject area)
    ❌ "lập trình" (no language, no level)
  
  Examples of SUFFICIENT topics (ACCEPT):
    ✅ "Toán lớp 10" (has level)
    ✅ "Lập trình Python cơ bản" (has language + level)
    ✅ "AI cho người mới bắt đầu" (has level)

Rule 2 — INAPPROPRIATE CONTENT:
  Reject topics containing adult, violent, or harmful content.

Rule 3 — ILLEGAL CONTENT:
  Reject topics promoting illegal activities, hate speech, or dangerous substances.
[/CRITICAL RULES]

[FORMAT]
Return ONLY a JSON object. No markdown, no explanation.

{{
  "valid": true/false,
  "reason": "localized explanation if rejected (empty if valid, max 20 words)",
  "suggestion": "2-3 localized alternatives separated by ' | ' (empty if valid)",
  "content_type": "scholarly|technical|practical|lifestyle",
  "core_topic": "extracted core subject normalized to target textbook language",
  "user_requirements": "extracted requirements normalized to target textbook language",
  "input_language": "detected input language code, e.g. vi|en|cs|zh|unknown",
  "requested_language": "vi|en|unsupported language code|empty string",
  "target_language": "vi|en",
  "language_source": "query|input|ui|unsupported_query|unsupported_input"
}}

Content type classification:
  scholarly  — academic subjects: mathematics, physics, history, literature, biology
  technical  — IT/engineering: programming, networking, machine learning, electronics
  practical  — vocational skills: cooking, sewing, carpentry, accounting
  lifestyle  — personal development: yoga, meditation, photography, finance, gardening

Example outputs:

Input: "Toán cao cấp 1"
{{"valid": true, "reason": "", "suggestion": "", "content_type": "scholarly", "core_topic": "Toán cao cấp 1", "user_requirements": ""}}

Input: "Python có bài tập"
{{"valid": true, "reason": "", "suggestion": "", "content_type": "technical", "core_topic": "Python", "user_requirements": "có bài tập"}}

Input: "học"
{{"valid": false, "reason": "Thiếu ngữ cảnh về chủ đề cụ thể", "suggestion": "Học toán lớp 10 | Học lập trình Python | Học tiếng Anh giao tiếp", "content_type": "technical", "core_topic": "", "user_requirements": "", "input_language": "{language_info.get("input_language")}", "requested_language": "{language_info.get("requested_language")}", "target_language": "{target_language}", "language_source": "{language_info.get("language_source")}"}}
[/FORMAT]
"""

        response = llm.invoke(prompt)
        raw = str(response.content).strip()
        
        # Log raw response for debugging
        logger.info(f"[VALIDATOR] LLM raw response: {raw[:200]}")
        
        # Parse JSON
        result = _normalize_validation_result(
            _parse_json_object(raw),
            {
                **language_info,
                "target_language": target_language,
                "language_source": language_info.get("language_source", "ui"),
            },
        )
        
        # Validate response structure
        required_keys = [
            "valid",
            "reason",
            "suggestion",
            "content_type",
            "core_topic",
            "user_requirements",
            "input_language",
            "requested_language",
            "target_language",
            "language_source",
        ]
        if not all(key in result for key in required_keys):
            logger.error(f"[VALIDATOR] Invalid response structure: {result}")
            return _validation_fallback("validator_error", ui_language, language_info)

        if result.get("language_source") == "unsupported_query":
            result_language_info = _with_unsupported_language(
                language_info,
                {
                    "code": result.get("unsupported_language") or result.get("requested_language", ""),
                    "name_en": result.get("unsupported_language_name_en") or result.get("requested_language", ""),
                    "name_vi": result.get("unsupported_language_name_vi") or result.get("requested_language", ""),
                },
            )
            logger.info(
                "[VALIDATOR] Rejected unsupported output language from validator result: %s",
                result_language_info.get("unsupported_language"),
            )
            return _validation_fallback("unsupported_textbook_language", ui_language, result_language_info)

        result_language_text = " ".join(
            str(result.get(key, ""))
            for key in ("reason", "suggestion", "core_topic", "user_requirements")
        )
        leaked_unsupported_request = detect_unsupported_requested_language(result_language_text)
        if leaked_unsupported_request:
            logger.info(
                "[VALIDATOR] Rejected leaked unsupported output-language request: %s",
                leaked_unsupported_request.get("code"),
            )
            return _validation_fallback(
                "unsupported_textbook_language",
                ui_language,
                _with_unsupported_language(language_info, leaked_unsupported_request),
            )

        if (
            language_info.get("language_source") == "unsupported_input"
            and result.get("language_source") != "query"
        ):
            logger.info(
                "[VALIDATOR] Unsupported input language has no supported output-language request: %s",
                language_info.get("unsupported_language"),
            )
            return _validation_fallback("unsupported_input_language", ui_language, language_info)

        if result.get("valid", False):
            noisy_tokens = _unexplained_topic_noise(topic, result)
            if noisy_tokens:
                logger.info(
                    "[VALIDATOR] Rejected unexplained topic noise: %s",
                    noisy_tokens,
                )
                return _validation_fallback("topic_contains_noise", ui_language, language_info)

        result = apply_formula_validation(
            result,
            topic,
            formula_policy=formula_policy,
            formula_confirmed=formula_confirmed,
            ui_language=ui_language,
        )
        
        logger.info(
            "[VALIDATOR] Result: valid=%s, type=%s, target_language=%s",
            result["valid"],
            result["content_type"],
            result["target_language"],
        )
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"[VALIDATOR] JSON parse error: {e}")
        logger.error(f"[VALIDATOR] Raw response was: {raw if 'raw' in locals() else 'N/A'}")
        return _validation_fallback("system_validation_error", ui_language, language_info)
        
    except Exception as e:
        logger.error(f"[VALIDATOR] LLM invocation failed: {e}", exc_info=True)
        return _validation_fallback("validator_unavailable", ui_language, language_info)


def validate_topic_node(state: AgentState) -> dict:
    """
    LangGraph node wrapper for validate_topic.
    
    Used in planning workflow (Phase A) for validation before ingestion.
    """
    topic = state["request"]
    result = validate_topic(topic, state.get("ui_language", state.get("language", "vi")))

    content_type = result.get("content_type", "technical")
    target_language = result.get("target_language", state.get("language", "vi"))

    if result.get("valid", False):  
        logger.info(f"[VALIDATOR NODE] ✓ Accepted: '{topic}' [{content_type}]")
        return {
            "messages": [f"✓ Topic validated: '{topic}' [{content_type}]"],
            "content_type": content_type,
            "core_topic": result.get("core_topic", state.get("core_topic", topic)),
            "user_requirements": result.get("user_requirements", state.get("user_requirements", "")),
            "language": target_language,
        }

    logger.info(f"[VALIDATOR NODE] ✗ Rejected: '{topic}' - {result.get('reason')}")
    return {
        "messages": [f"✗ Invalid topic: {result.get('reason', '')}"],
        "validation_failed": True,
        "validation_reason": result.get("reason", ""),
        "validation_suggestion": result.get("suggestion", ""),
        "content_type": content_type,
        "language": target_language,
    }
