"""
QueryFormulator node for the CRAG pipeline.

Responsibility: Build an enhanced, targeted search query for the current
subsection and write it to state["retrieval_query"].

Positioned as the first node in the CRAG loop:
    QueryFormulator → RetrieverNode → ContextEvaluator → ContentWriter
"""

from app.schemas.curriculum import (
    AgentState, Chapter, SubSection,
    get_chapter_and_subsection,
)
from app.utils.log_config import setup_logger

logger = setup_logger(name="QueryFormulatorNode", logfile="logs/agents.log")


def _compact_query(parts: list[str], max_terms: int = 28) -> str:
    """Build a bounded retrieval query while preserving the section anchors."""
    seen: set[str] = set()
    terms: list[str] = []
    for part in parts:
        for token in str(part or "").replace("/", " ").split():
            normalized = token.strip(" ,.;:()[]{}").lower()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(token.strip(" ,.;:()[]{}"))
            if len(terms) >= max_terms:
                return " ".join(terms)
    return " ".join(terms)


def _section_value(section: Chapter | SubSection | dict, key: str, default: str = "") -> str:
    if isinstance(section, dict):
        return str(section.get(key, default) or default)
    return str(getattr(section, key, default) or default)


def _target_pages_value(subsection: SubSection | dict) -> int | None:
    value = subsection.target_pages if isinstance(subsection, SubSection) else subsection.get("target_pages")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def formulate_query(state: AgentState) -> dict:
    """
    QueryFormulator node: derive an enhanced ChromaDB search query.

    Reads the subsection's base search_query, then enriches it with
    user_requirements keyword extensions and revision-mode angle shifts.
    The resulting query is stored in state["retrieval_query"] for the
    downstream RetrieverNode to consume.

    Args:
        state: Current LangGraph workflow state.

    Returns:
        Partial state update with "retrieval_query" and "messages".
    """
    logger.info("=" * 60)
    logger.info("NODE: QueryFormulator - Building retrieval query")
    logger.info("=" * 60)

    curriculum        = state["curriculum"]
    chap_idx          = state["current_chapter_index"]
    sub_idx           = state["current_subsection_index"]
    user_requirements = state.get("user_requirements", "")
    review_feedback   = state.get("review_feedback", "")
    used_queries      = state.get("used_rag_queries", [])
    textbook_mode     = state.get("textbook_mode", "standard")
    formula_policy    = state.get("formula_policy", "auto")
    formula_need      = state.get("formula_need", "none")

    try:
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

        chap_title = _section_value(chapter, "title", "Unknown")
        sec_title = _section_value(subsection, "title", "Unknown")
        sec_desc = _section_value(subsection, "description", "")
        sec_type = _section_value(subsection, "section_type", "medium")
        target_pages = _target_pages_value(subsection)
        base_query = (
            subsection.search_query if isinstance(subsection, SubSection)
            else subsection.get("search_query", f"{chap_title} - {sec_title}")
        )
        course_topic = str(
            state.get("core_topic")
            or state.get("request")
            or state.get("topic")
            or ""
        )
        compact_section = target_pages is not None and target_pages <= 2

        logger.info(f"Target: Chapter {chap_idx + 1}.{sub_idx + 1} — {sec_title}")
        logger.info(f"Base query: {base_query}")

        # ----------------------------------------------------------------
        # Revision mode: shift query angle away from already-tried queries
        # to avoid retrieving the same chunks that produced rejected content.
        # ----------------------------------------------------------------
        metadata_anchor = _compact_query(
            [
                base_query,
                sec_title,
                sec_desc,
                chap_title,
                course_topic,
                f"{sec_type} section",
                f"{target_pages} pages" if target_pages else "",
            ],
            max_terms=36,
        )

        if used_queries:
            logger.info(f"Retry mode — shifting query angle (used: {len(used_queries)})")
            # Rotate the angle so repeated strict-gate retries do not ask
            # ChromaDB for the same neighborhood again.
            retry_angles = [
                "definition core concepts textbook explanation",
                "implementation configuration examples tutorial",
                "troubleshooting best practices assessment criteria",
                "official documentation course notes worked example",
            ]
            suffix = retry_angles[(len(used_queries) - 1) % len(retry_angles)]
            if review_feedback:
                suffix = f"{suffix} missing details examples"
            enhanced_query = _compact_query([metadata_anchor, suffix], max_terms=42)
        else:
            enhanced_query = metadata_anchor

        # ----------------------------------------------------------------
        # User requirements enrichment for targeted retrieval.
        # ----------------------------------------------------------------
        if user_requirements:
            logger.info(f"User requirements: {user_requirements}")
            req_lower = user_requirements.lower()
            query_extensions = []

            if "bài tập" in user_requirements or "exercise" in req_lower:
                query_extensions.extend(["exercises", "practice problems", "worked examples"])
                logger.info("  → Adding exercise-focused keywords")

            if "ví dụ" in user_requirements or "example" in req_lower or "code" in req_lower:
                query_extensions.extend(["code examples", "sample code", "implementation examples"])
                logger.info("  → Adding example-focused keywords")

            if ("ứng dụng" in user_requirements or "thực tế" in user_requirements
                    or "real" in req_lower or "application" in req_lower):
                if compact_section:
                    query_extensions.extend(["short practical example"])
                else:
                    query_extensions.extend(["real world applications", "use cases", "practical examples"])
                logger.info("  → Adding application-focused keywords")

            if "project" in req_lower or "dự án" in user_requirements:
                query_extensions.extend(["project examples", "hands-on project"])
                logger.info("  → Adding project-focused keywords")

            if query_extensions:
                enhanced_query = _compact_query(
                    [enhanced_query, " ".join(query_extensions[:3])],
                    max_terms=38,
                )
                logger.info(f"Enhanced query: {enhanced_query}")

        if str(textbook_mode or "standard").lower() == "practice":
            enhanced_query = _compact_query(
                [
                    enhanced_query,
                    "lab hands-on tutorial exercise worked example practice bài tập thực hành",
                ],
                max_terms=42,
            )
            logger.info(f"Practice-mode query: {enhanced_query}")

        if formula_policy == "include":
            enhanced_query = _compact_query(
                [
                    enhanced_query,
                    "formula equation model metric rubric KPI calculation worked example evaluation criteria quantitative framework",
                ],
                max_terms=48,
            )
            logger.info(f"Formula-focused query: {enhanced_query}")

        return {
            "retrieval_query": enhanced_query,
            "messages": [
                f"✓ Query formulated for Chapter {chap_idx + 1}.{sub_idx + 1}: "
                f"'{enhanced_query[:60]}...'"
            ],
        }

    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {
            "retrieval_query": f"Chapter {chap_idx + 1} subsection {sub_idx + 1}",
            "messages": ["⚠️ QueryFormulator used fallback query (index error)"],
        }
    except Exception as e:
        logger.error(f"QueryFormulator unexpected error: {e}", exc_info=True)
        return {
            "retrieval_query": "",
            "messages": [f"Error in QueryFormulator: {e}"],
        }
