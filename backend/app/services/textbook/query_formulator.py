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
        if review_feedback and used_queries:
            logger.info(f"Revision mode — shifting query angle (used: {len(used_queries)})")
            # Append angle-shift suffix so MMR search returns diverse chunks
            enhanced_query = f"{base_query} advanced concepts alternative explanation"
        else:
            enhanced_query = base_query

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
                enhanced_query = f"{enhanced_query} {' '.join(query_extensions[:3])}"
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
