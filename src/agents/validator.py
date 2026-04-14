"""
Validator Agent for AI Textbook Generator.

Checks whether the user-submitted topic is specific enough to generate
a structured university-level textbook before ingestion begins.

Returns:
    {"valid": True,  "reason": "", "suggestion": ""}
    {"valid": False, "reason": "...", "suggestion": "..."}
"""

import json
from langchain_openai import ChatOpenAI
from src.config import GROQ_API_KEY
from langchain_groq import ChatGroq
from src.graph.state import AgentState
from src.log_config import setup_logger

logger = setup_logger(name="ValidatorAgent", logfile="logs/agents.log")


def validate_topic(topic: str) -> dict:
    """
    Call LLM to classify whether the topic is suitable for textbook generation.

    Falls back to valid=True on any LLM error so the workflow is never
    blocked by a transient API failure.

    Args:
        topic: Raw topic string submitted by the user.

    Returns:
        Dict with keys: valid (bool), reason (str), suggestion (str).
    """
    logger.info(f"validate_topic is running")
    llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=GROQ_API_KEY,     # type: ignore[arg-type]
            temperature=0,
            max_tokens=256,
        )


    prompt = f"""
[CONTEXT]
You are a neutral logic evaluator specialized in assessing the feasibility of 
learning topics. The system generates educational content across all domains 
the user wants to learn — not limited to formal academic subjects.
[/CONTEXT]

[TASK]
Evaluate the user-submitted topic: "{topic}"
Determine: does this topic contain sufficient semantic signal to infer a learning 
domain and scope, and does it violate any content constraints?
[/TASK]

[CRITERION]
A topic is considered VALID (valid = true) when it satisfies both conditions:
  (a) A learning domain can be inferred — even if the user uses natural language
      rather than formal academic terminology.
  (b) It does not violate any rule in [CONSTRAINT].

Note: If a topic is loosely phrased but a learning intent can be inferred,
prefer ACCEPTING it — downstream components will clarify the scope.
[/CRITERION]

[CONSTRAINT]
Rule 1 — ABSOLUTE AMBIGUITY:
  Reject only when the topic is 1–2 isolated words with no context and no 
  inferrable learning domain or goal whatsoever.
  Rejection threshold: missing BOTH domain AND intent.
  Do NOT reject: when a domain can be inferred despite non-standard phrasing.

Rule 2 — INAPPROPRIATE CONTENT:
  Reject when the topic contains adult, violent, or harmful content.

Rule 3 — ILLEGAL CONTENT:
  Reject when the topic promotes illegal activities, hate speech, or dangerous 
  substances.
[/CONSTRAINT]

[EXEMPLAR]
REJECT — Rule 1 (absolute ambiguity, no domain inferrable):
  "AI" | "math" | "coding" | "science" | "business" | "toán" | "lập trình"

ACCEPT — natural language, learning intent inferrable:
  "Giáo trình học Trí tuệ nhân tạo chuẩn bị cho học thạc sĩ"
    → domain: AI, level: advanced — sufficient to process
  "Tôi muốn học nấu ăn Nhật Bản"
    → domain: Japanese cuisine — sufficient to process
  "Học máy cơ bản" | "Giải tích 1" | "Lập trình Python cho người mới"

REJECT — Rule 2–3 (content violation):
  "nội dung 18+" | "cách làm vũ khí" | "hack hệ thống" | "ma túy"
[/EXEMPLAR]

[FORMAT]
Return a single JSON object only. No markdown, no additional explanation.
Fields:
  valid      : true if the topic has sufficient learning signal and no constraint violations
  reason     : Vietnamese string ≤15 words explaining the rejection reason (empty if valid)
  suggestion : 2–3 more specific topic alternatives in Vietnamese, separated by " | " (empty if valid)

Output: {{"valid": true, "reason": "", "suggestion": ""}}
[/FORMAT]
"""

    try:
        response = llm.invoke(prompt)
        raw      = str(response.content).strip()
        result   = json.loads(raw)
        logger.info(f"Validation result for '{topic}': {result}")
        return result
    except Exception as e:
        logger.warning(f"Validator LLM failed ({e}) — defaulting to valid")
        return {"valid": True, "reason": "", "suggestion": ""}


def validate_topic_node(state: AgentState) -> dict:
    """
    LangGraph node: validate the user topic after ingestion, before planner.

    Writes validation_failed=True to state when the topic is rejected,
    which triggers the conditional edge to route to END instead of planner.

    Args:
        state: Current LangGraph workflow state.

    Returns:
        Partial state update dict.
    """
    topic  = state["request"]
    result = validate_topic(topic)

    if result.get("valid", True):
        return {"messages": [f"✓ Topic validated: '{topic}'"]}

    # Signal to graph router to route to END instead of planner
    return {
        "messages":              [f"✗ Invalid topic: {result.get('reason', '')}"],
        "validation_failed":     True,
        "validation_reason":     result.get("reason", ""),
        "validation_suggestion": result.get("suggestion", ""),
    }