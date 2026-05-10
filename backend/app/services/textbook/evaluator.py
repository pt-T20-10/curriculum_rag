"""
EvaluatorAgent for the CRAG pipeline.

Responsibility: Assess whether the retrieved RAG context is sufficient to
write the current section. If insufficient, fetch supplemental context via
tool calls (ReAct loop).

This is the agentic core of the CRAG system:
    - Uses LLM reasoning (not just rules) to decide if context is adequate
    - Executes tool calls to retrieve_context_tool when more context is needed
    - Loops up to RAG_TOOL_MAX_ROUNDS times before declaring sufficient/insufficient

Positioned as the third node in the CRAG loop:
    QueryFormulator → RetrieverNode → [EvaluatorAgent] → WriterAgent
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from app.config import settings
from app.utils import stop_signal
from app.utils.log_config import setup_logger
from app.schemas.curriculum import (
    AgentState,
    SubSection,
    get_chapter_and_subsection,
)
# retrieve_context_tool is defined in retriever.py (the ChromaDB search tool)
from app.services.textbook.retriever import retrieve_context_tool
from app.services.textbook.writer import _build_prior_summary_block

logger = setup_logger(name="EvaluatorAgent", logfile="logs/agents.log")

OPENAI_API_KEY = settings.OPENAI_API_KEY
LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
_RETRIEVAL_MAX_ROUNDS: int = settings.WRITER_RETRIEVAL_MAX_ROUNDS


# ============================================================================
# EvaluatorAgent
# ============================================================================

class EvaluatorAgent:
    """
    Lightweight retrieval component using gpt-4o-mini with tool access.

    Responsibilities:
    - Assess whether initial RAG context is sufficient for the section.
    - Call retrieve_context_tool (max _RETRIEVAL_MAX_ROUNDS times) when needed.
    - Inject prior section summaries to avoid fetching redundant context.
    - Return a single enriched context string for WriterAgent.

    Uses gpt-4o-mini deliberately — this is an assessment/retrieval task,
    not a generation task, and does not require premium model quality.
    Returns:
        (enriched_context_string, list_of_queries_used)
    """

    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            model=LLM_MODEL_CHEAP,
            api_key=OPENAI_API_KEY, #type: ignore
            temperature=0,
        )
        self._llm_with_tools = self._llm.bind_tools([retrieve_context_tool])

    def enrich_context(
        self,
        section_description: str,
        section_type: str,
        initial_context: str,
        section_summaries: list[str],
        revision_feedback: str = "",
        used_queries: list[str] = [],
    ) -> tuple[str, list[str]]:
        prior_block = _build_prior_summary_block(section_summaries)
        _queries_this_call: list[str] = []

        # Accumulate all raw chunks fetched via tool calls.
        # We collect ToolMessage content directly instead of relying on the LLM
        # to return verbatim text — LLMs tend to synthesize even when instructed not to.
        _fetched_chunks: list[str] = []

        def _build_system(extra_used: list[str]) -> str:
            """Rebuild system prompt with updated list of already-used queries."""
            all_used = used_queries + extra_used
            used_block = ""
            if all_used:
                used_block = (
                    "ALREADY FETCHED — do NOT use these exact queries again:\n"
                    + "\n".join(f"- {q}" for q in all_used)
                    + "\n"
                )

            revision_block = ""
            if revision_feedback:
                revision_block = (
                    "\n[REVISION MODE]\n"
                    f"The previous draft was rejected with this feedback:\n{revision_feedback}\n\n"
                    f"{used_block}"
                    "You MUST fetch queries targeting DIFFERENT angles from those already used.\n"
                    "Focus on the SPECIFIC GAPS in the feedback above.\n"
                    "[/REVISION MODE]\n"
                )
            elif used_block:
                revision_block = f"\n{used_block}"

            return (
                f"You are a research assistant deciding whether to fetch additional context.\n"
                f"Task: assess whether the provided context is sufficient to write "
                f"a {section_type} section about: {section_description}\n\n"
                f"{prior_block}\n"
                f"{revision_block}\n"
                f"If context is thin OR in revision mode, call retrieve_context_tool "
                f"with specific queries targeting missing content. Max {_RETRIEVAL_MAX_ROUNDS} calls.\n"
                f"If context is already sufficient, do NOT call any tool — just reply 'OK'.\n\n"
                # Removed the instruction to return verbatim chunks — we collect them ourselves.
                f"Your only job is to decide WHAT to fetch, not to summarize or rewrite anything."
            )

        messages: list = [
            SystemMessage(content=_build_system([])),
            HumanMessage(content=f"Initial context:\n{initial_context}"),
        ]

        for _ in range(_RETRIEVAL_MAX_ROUNDS):
            if stop_signal.is_stopped():
                break

            response = self._llm_with_tools.invoke(messages)
            tool_calls = getattr(response, "tool_calls", [])

            if not tool_calls:
                # LLM decided no additional fetch needed — stop here.
                break

            messages.append(response)

            for tc in tool_calls:
                query = tc["args"].get("query", "")
                logger.info(f"[Retrieval] Tool call: '{query[:60]}'")
                _queries_this_call.append(query)

                result = retrieve_context_tool.invoke(tc["args"])
                result_str = str(result)

                # Store raw chunk text directly — bypass LLM synthesis entirely.
                if result_str.strip():
                    _fetched_chunks.append(result_str)

                messages.append(ToolMessage(
                    content=result_str,
                    tool_call_id=tc["id"],
                ))

            # Update system message with queries used so far to prevent repeats.
            messages[0] = SystemMessage(content=_build_system(_queries_this_call))

        # Build final context: initial context + all raw fetched chunks concatenated.
        # This guarantees the Writer receives source material, not LLM commentary.
        all_context_parts = [initial_context] + _fetched_chunks
        enriched = "\n\n---\n\n".join(p for p in all_context_parts if p.strip())

        if not enriched.strip():
            logger.warning("enrich_context: no context available after retrieval attempts")

        logger.info(
            f"Context enriched: {len(_fetched_chunks)} additional chunk(s) fetched, "
            f"{len(enriched)} total chars"
        )

        return enriched, _queries_this_call


# ============================================================================
# CRAG Node — evaluate_context
# ============================================================================

def evaluate_context(state: AgentState) -> dict:
    """
    ContextEvaluator node: assess and optionally enrich RAG context.

    Runs EvaluatorAgent.enrich_context() on the initial rag_context
    produced by RetrieverNode. The agent internally decides (via LLM) whether
    additional tool-call retrievals are needed before writing.

    Sets context_quality based on enrichment outcome:
        'sufficient'   — context is rich enough for WriterAgent
        'insufficient' — context too sparse; routes graph back to QueryFormulator
                         for a fresh retrieval attempt with a shifted query

    Args:
        state: Current LangGraph workflow state.

    Returns:
        Partial state update with enriched rag_context, context_quality,
        web_supplement_context, and updated used_rag_queries.
    """
    logger.info("=" * 60)
    logger.info("NODE: ContextEvaluator - Assessing context sufficiency")
    logger.info("=" * 60)

    curriculum        = state["curriculum"]
    chap_idx          = state["current_chapter_index"]
    sub_idx           = state["current_subsection_index"]
    initial_context   = state.get("rag_context", "")
    section_summaries = state.get("section_summaries", [])
    review_feedback   = state.get("review_feedback", "")
    used_queries      = state.get("used_rag_queries", [])

    try:
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)
        sec_desc = (
            subsection.description if isinstance(subsection, SubSection)
            else subsection.get("description", "")
        )
        sec_type = (
            subsection.section_type if isinstance(subsection, SubSection)
            else subsection.get("section_type", "medium")
        )

        agent = EvaluatorAgent()
        enriched_context, new_queries = agent.enrich_context(
            section_description = sec_desc,
            section_type        = sec_type,
            initial_context     = initial_context,
            section_summaries   = list(section_summaries),
            revision_feedback   = review_feedback or "",
            used_queries        = used_queries,
        )

        # Determine context quality verdict
        is_empty     = not enriched_context.strip()
        is_too_short = (
            len(enriched_context) < settings.CRAG_CONTEXT_QUALITY_MIN_CHARS
            and not new_queries
        )

        if is_empty or is_too_short:
            context_quality = "insufficient"
            logger.warning(
                f"ContextEvaluator: context quality = 'insufficient' "
                f"(len={len(enriched_context)}, new_queries={len(new_queries)})"
            )
        else:
            context_quality = "sufficient"
            logger.info(
                f"ContextEvaluator: context quality = 'sufficient' "
                f"(len={len(enriched_context)}, new_queries={len(new_queries)})"
            )

        # Separate supplemental chunks from the initial context for audit trail
        web_supplement = ""
        if new_queries and initial_context:
            # Everything after the first separator is supplemental
            parts = enriched_context.split("\n\n---\n\n", 1)
            web_supplement = parts[1] if len(parts) > 1 else ""
        elif new_queries and not initial_context:
            web_supplement = enriched_context

        prior_used    = list(used_queries)
        updated_used  = prior_used + new_queries

        return {
            "rag_context":            enriched_context,
            "context_quality":        context_quality,
            "web_supplement_context": web_supplement,
            "used_rag_queries":       updated_used,
            "messages": [
                f"{'✓' if context_quality == 'sufficient' else '⚠️'} "
                f"ContextEvaluator: quality='{context_quality}', "
                f"total_chars={len(enriched_context)}, "
                f"new_fetches={len(new_queries)}"
            ],
        }

    except Exception as e:
        logger.error(f"ContextEvaluator unexpected error: {e}", exc_info=True)
        # Fail open — pass through whatever context we have
        return {
            "rag_context":            initial_context,
            "context_quality":        "sufficient",
            "web_supplement_context": "",
            "messages": [f"Error in ContextEvaluator: {e}"],
        }
