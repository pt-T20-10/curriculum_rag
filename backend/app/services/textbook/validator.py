"""
Validator Agent for AI Textbook Generator.
"""

import json
from app.config import settings
from langchain_groq import ChatGroq
GROQ_API_KEY = settings.GROQ_API_KEY
from app.schemas.curriculum import AgentState
from app.utils.log_config import setup_logger

logger = setup_logger(name="ValidatorAgent", logfile="logs/agents.log")


def validate_topic(topic: str) -> dict:
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
You are a strict validator AND topic parser for educational content generation.

Your dual role:
1. VALIDATE if the topic is suitable (reject vague/inappropriate topics)
2. EXTRACT the core topic and user requirements (if any)
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
  "reason": "Vietnamese explanation if rejected (empty if valid, max 20 words)",
  "suggestion": "2-3 specific alternatives separated by ' | ' (empty if valid)",
  "content_type": "scholarly|technical|practical|lifestyle",
  "core_topic": "extracted core subject (same as input if no requirements)",
  "user_requirements": "extracted requirements (empty string if none)"
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
{{"valid": false, "reason": "Thiếu ngữ cảnh về chủ đề cụ thể", "suggestion": "Học toán lớp 10 | Học lập trình Python | Học tiếng Anh giao tiếp", "content_type": "technical", "core_topic": "", "user_requirements": ""}}
[/FORMAT]
"""

        response = llm.invoke(prompt)
        raw = str(response.content).strip()
        
        # Log raw response for debugging
        logger.info(f"[VALIDATOR] LLM raw response: {raw[:200]}")
        
        # Parse JSON
        result = json.loads(raw)
        
        # Validate response structure
        required_keys = ["valid", "reason", "suggestion", "content_type", "core_topic", "user_requirements"]
        if not all(key in result for key in required_keys):
            logger.error(f"[VALIDATOR] Invalid response structure: {result}")
            return {
                "valid": False,
                "reason": "Lỗi xác thực topic - vui lòng thử lại",
                "suggestion": "",
                "content_type": "technical",
                "core_topic": "",
                "user_requirements": "" 
            }
        
        logger.info(f"[VALIDATOR] Result: valid={result['valid']}, type={result['content_type']}")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"[VALIDATOR] JSON parse error: {e}")
        logger.error(f"[VALIDATOR] Raw response was: {raw if 'raw' in locals() else 'N/A'}")
        return {
            "valid": False, 
            "reason": "Lỗi hệ thống xác thực - vui lòng thử lại",
            "suggestion": "",
            "content_type": "technical",
            "core_topic": "",  
            "user_requirements": "" 
        }
        
    except Exception as e:
        logger.error(f"[VALIDATOR] LLM invocation failed: {e}", exc_info=True)
        return {
            "valid": False, 
            "reason": "Dịch vụ xác thực tạm thời không khả dụng",
            "suggestion": "",
            "content_type": "technical",
            "core_topic": "",  
            "user_requirements": ""
        }


def validate_topic_node(state: AgentState) -> dict:
    """
    LangGraph node wrapper for validate_topic.
    
    Used in planning workflow (Phase A) for validation before ingestion.
    """
    topic = state["request"]
    result = validate_topic(topic)

    content_type = result.get("content_type", "technical")

    if result.get("valid", False):  
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