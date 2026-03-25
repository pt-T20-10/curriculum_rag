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
from src.config import LLM_MODEL_CHEAP
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
    llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0)

    prompt = f"""You are a quality gate for a Vietnamese university textbook generator.

Evaluate this topic: "{topic}"

Return a single JSON object (no markdown, no explanation):
- valid: true if the topic is specific enough to generate a structured academic textbook
- reason: short explanation in Vietnamese if invalid (≤15 words)
- suggestion: 2-3 more specific alternatives if invalid, separated by " | "
Rules for rejection:
1. Topic is too broad or vague (no specific academic scope)
2. Topic contains adult, sexual, violent, illegal, or harmful content
3. Topic promotes illegal activities, hate speech, or dangerous substances

Examples of INVALID topics (too broad or vague): "AI", "toán", "lập trình", "khoa học"
Examples of VALID topics: "Học máy cơ bản", "Giải tích 1", "Lập trình Python cho người mới"
Examples of REJECTED by rule 2-3: "nội dung 18+", "cách làm vũ khí", 
"hack hệ thống", "ma túy", "cờ bạc"

Output only this JSON:
{{"valid": true, "reason": "", "suggestion": ""}}"""

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