"""
QueryFormulator node for the CRAG pipeline.

Responsibility: Build an enhanced, targeted search query for the current
subsection and write it to state["retrieval_query"].

Positioned as the first node in the CRAG loop:
    QueryFormulator → RetrieverNode → ContextEvaluator → ContentWriter
"""

from app.schemas.curriculum import (
    AgentState, Chapter, SubSection,
    get_chapter_and_subsection, clean_section_title,
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

    try:
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

        chap_title = (
            chapter.title if isinstance(chapter, Chapter)
            else chapter.get("title", "Unknown")
        )
        sec_title = (
            subsection.title if isinstance(subsection, SubSection)
            else subsection.get("title", "Unknown")
        )
        sec_desc = (
            subsection.description if isinstance(subsection, SubSection)
            else subsection.get("description", "")
        )
        base_query = (
            subsection.search_query if isinstance(subsection, SubSection)
            else subsection.get("search_query", f"{chap_title} - {sec_title}")
        )

        logger.info(f"Target: Chapter {chap_idx + 1}.{sub_idx + 1} — {sec_title}")
        logger.info(f"Base query: {base_query}")

        # ----------------------------------------------------------------
        # Revision mode: shift query angle away from already-tried queries
        # to avoid retrieving the same chunks that produced rejected content.
        # ----------------------------------------------------------------
        section_anchor = _compact_query([chap_title, sec_title, sec_desc], max_terms=18)
        base_with_anchor = _compact_query([section_anchor, base_query], max_terms=28)

        if used_queries:
            logger.info(f"Retry mode — shifting query angle (used: {len(used_queries)})")
            # Rotate the angle so repeated strict-gate retries do not ask
            # ChromaDB for the same neighborhood again.
            retry_angles = [
                "definition concepts overview examples",
                "core principles explanation textbook",
                "applications comparison fundamentals",
            ]
            suffix = retry_angles[len(used_queries) % len(retry_angles)]
            if review_feedback:
                suffix = f"{suffix} missing details examples"
            enhanced_query = _compact_query([base_with_anchor, suffix], max_terms=34)
        else:
            enhanced_query = base_with_anchor

        # ----------------------------------------------------------------
        # User requirements enrichment
        # EXTRACTED FROM: researcher.py perform_research() lines 1042-1069
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
