"""
Validator Agent for AI Textbook Generator.
"""

import json
from app.config import settings
from langchain_groq import ChatGroq
GROQ_API_KEY = settings.GROQ_API_KEY
from app.schemas.curriculum import AgentState
from app.utils.log_config import setup_logger

logger = setup_logger(name="ValidatorAgent", logfile="backend/logs/agents.log")


def validate_topic(topic: str) -> dict:
    """
    Validate topic suitability for textbook generation.
    
    Returns:
        dict: {
            "valid": bool,
            "reason": str,
            "suggestion": str,
            "content_type": str
        }
        
        On error: Returns {"valid": False, ...} to REJECT by default
    """
    logger.info(f"[VALIDATOR] Validating topic: '{topic}'")
    
    try:
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=GROQ_API_KEY, #type: ignore
            temperature=0,
            max_tokens=512,  # Increased for better response
        )

        prompt = f"""
[CONTEXT]
You are a strict validator for educational content generation. Your role is to 
reject vague, single-word topics that lack sufficient context to build a 
structured curriculum, while accepting topics with clear learning scope.
[/CONTEXT]

[TASK]
Evaluate this topic: "{topic}"

Decision criteria:
1. Does it have sufficient specificity (level, scope, or context)?
2. Does it violate content policies?

Return valid=true ONLY if both conditions are met.
[/TASK]

[CRITICAL RULES]

Rule 1 — SINGLE-WORD REJECTION:
  REJECT any topic that is 1-2 isolated words WITHOUT modifiers or context.
  
  Examples of INSUFFICIENT topics (REJECT):
    ❌ "AI" (no level, no context)
    ❌ "toán" (no grade, no subject area)
    ❌ "lập trình" (no language, no level)
    ❌ "math" | "coding" | "science" | "business"
    ❌ "xyz" | "abc" (meaningless)
  
  Examples of SUFFICIENT topics (ACCEPT):
    ✅ "Toán lớp 10" (has level)
    ✅ "Toán cao cấp 1" (has level + subject)
    ✅ "Lập trình Python cơ bản" (has language + level)
    ✅ "Giải tích 1" (specific course)
    ✅ "AI cho người mới bắt đầu" (has level)
  
  The difference: Context transforms ambiguity into specificity.
  "toán" alone → infinite possible scopes → REJECT
  "toán lớp 10" → clear scope → ACCEPT

Rule 2 — INAPPROPRIATE CONTENT:
  Reject topics containing adult, violent, or harmful content.

Rule 3 — ILLEGAL CONTENT:
  Reject topics promoting illegal activities, hate speech, or dangerous substances.
[/CRITICAL RULES]

[ADDITIONAL EXAMPLES]

✅ ACCEPT — these have sufficient context:
  "Giáo trình học Trí tuệ nhân tạo chuẩn bị cho học thạc sĩ"
  "Học máy cơ bản cho người mới"
  "Nấu ăn Nhật Bản truyền thống"
  "Lịch sử Việt Nam thế kỷ 20"
  "Vật lý đại cương 1"

❌ REJECT — insufficient context:
  "vật lý" → Which physics? What level?
  "lịch sử" → Which period? What region?
  "AI" → Which aspect? What level?
  "programming" → Which language? What level?

[FORMAT]
Return ONLY a JSON object. No markdown, no explanation.

{{
  "valid": true/false,
  "reason": "Vietnamese explanation if rejected (empty if valid, max 20 words)",
  "suggestion": "2-3 specific alternatives separated by ' | ' (empty if valid)",
  "content_type": "scholarly|technical|practical|lifestyle"
}}

Content type classification:
  scholarly  — academic subjects: mathematics, physics, history, literature, biology
  technical  — IT/engineering: programming, networking, machine learning, electronics
  practical  — vocational skills: cooking, sewing, carpentry, accounting
  lifestyle  — personal development: yoga, meditation, photography, finance, gardening

Example output: {{"valid": false, "reason": "Chủ đề quá chung chung, thiếu ngữ cảnh về cấp độ hoặc phạm vi", "suggestion": "Toán lớp 10 đại số | Toán cao cấp 1 | Giải tích cơ bản", "content_type": "scholarly"}}
[/FORMAT]
"""

        response = llm.invoke(prompt)
        raw = str(response.content).strip()
        
        # Log raw response for debugging
        logger.info(f"[VALIDATOR] LLM raw response: {raw[:200]}")
        
        # Parse JSON
        result = json.loads(raw)
        
        # Validate response structure
        required_keys = ["valid", "reason", "suggestion", "content_type"]
        if not all(key in result for key in required_keys):
            logger.error(f"[VALIDATOR] Invalid response structure: {result}")
            return {
                "valid": False,
                "reason": "Lỗi xác thực topic - vui lòng thử lại",
                "suggestion": "",
                "content_type": "technical"
            }
        
        logger.info(f"[VALIDATOR] Result: valid={result['valid']}, type={result['content_type']}")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"[VALIDATOR] JSON parse error: {e}")
        logger.error(f"[VALIDATOR] Raw response was: {raw if 'raw' in locals() else 'N/A'}")
        return {
            "valid": False,  # ⭐ REJECT on error
            "reason": "Lỗi hệ thống xác thực - vui lòng thử lại",
            "suggestion": "",
            "content_type": "technical"
        }
        
    except Exception as e:
        logger.error(f"[VALIDATOR] LLM invocation failed: {e}", exc_info=True)
        return {
            "valid": False,  # ⭐ REJECT on error  
            "reason": "Dịch vụ xác thực tạm thời không khả dụng",
            "suggestion": "",
            "content_type": "technical"
        }


def validate_topic_node(state: AgentState) -> dict:
    """
    LangGraph node wrapper for validate_topic.
    
    Used in planning workflow (Phase A) for validation before ingestion.
    """
    topic = state["request"]
    result = validate_topic(topic)

    content_type = result.get("content_type", "technical")

    if result.get("valid", False):  # ⭐ Changed default from True to False
        logger.info(f"[VALIDATOR NODE] ✓ Accepted: '{topic}' [{content_type}]")
        return {
            "messages": [f"✓ Topic validated: '{topic}' [{content_type}]"],
            "content_type": content_type,
        }

    logger.info(f"[VALIDATOR NODE] ✗ Rejected: '{topic}' - {result.get('reason')}")
    return {
        "messages": [f"✗ Invalid topic: {result.get('reason', '')}"],
        "validation_failed": True,
        "validation_reason": result.get("reason", ""),
        "validation_suggestion": result.get("suggestion", ""),
        "content_type": content_type,
    }