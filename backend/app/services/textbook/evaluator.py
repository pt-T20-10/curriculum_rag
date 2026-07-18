"""
EvaluatorAgent for the CRAG pipeline.

Responsibility: Assess whether the retrieved RAG context is sufficient to
write the current section. If insufficient, fetch supplemental context via
tool calls (ReAct loop).

This is the agentic core of the CRAG system:
    - Uses LLM reasoning (not just rules) to decide if context is adequate
    - Executes tool calls to retrieve_context_tool when more context is needed
    - Loops up to WRITER_RETRIEVAL_MAX_ROUNDS times before declaring sufficient/insufficient

Positioned as the third node in the CRAG loop:
    QueryFormulator → RetrieverNode → [EvaluatorAgent] → WriterAgent
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from typing import Any

from app.config import settings
from app.services.cost_profile import (
    BALANCED_COST,
    AGGRESSIVE_COST,
    auxiliary_chat_model,
    get_cost_profile,
    get_rag_chunk_llm_filter_mode,
    should_skip_context_evaluator_when_sufficient,
)
from app.services.api_rate_limiter import rate_limited_invoke
from app.services.runtime_config import get_api_key, get_runtime_config
from app.utils import stop_signal
from app.utils.log_config import setup_logger
from app.schemas.curriculum import (
    AgentState,
    SubSection,
    get_chapter_and_subsection,
)
# retrieve_context_tool is defined in retriever.py (the ChromaDB search tool)
from app.services.textbook.retriever import (
    build_source_audit_summary,
    retrieve_context_tool,
)
from app.services.textbook.writer import _build_prior_summary_block

logger = setup_logger(name="EvaluatorAgent", logfile="logs/agents.log")

LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
LLM_MODEL_PREMIUM = settings.LLM_MODEL_PREMIUM
_RETRIEVAL_MAX_ROUNDS: int = settings.WRITER_RETRIEVAL_MAX_ROUNDS


def _runtime_bool(key: str, default: bool = False) -> bool:
    value = get_runtime_config(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _context_evidence_score(
    *,
    chars: int,
    valid_chunks: int,
    unique_sources: int,
    avg_source_score: float,
) -> float:
    """Score context evidence for best-effort fallback selection."""
    char_score = min(1.0, chars / max(1, settings.CRAG_CONTEXT_QUALITY_MIN_CHARS))
    chunk_score = min(1.0, valid_chunks / 2)
    source_score = min(1.0, unique_sources / 2)
    return (
        char_score * 0.25
        + chunk_score * 0.30
        + source_score * 0.25
        + avg_source_score * 0.20
    )


def deterministic_context_is_sufficient(
    rag_context: str,
    source_audit: dict[str, Any] | None = None,
    *,
    require_verified: bool = False,
    min_verified_chunks: int = 2,
) -> bool:
    """
    Fast no-LLM sufficiency check for balanced-cost mode.

    This only approves clearly strong context. Borderline or missing audit data
    falls through to the LLM evaluator so quality_current behavior remains safe.
    """
    audit = source_audit or {}
    chars = len(rag_context or "")
    valid_chunks = int(
        audit.get("valid_chunks")
        or audit.get("total_chunks")
        or 0
    )
    unique_sources = int(audit.get("unique_sources") or 0)
    verified_chunks = int(audit.get("verified_chunks") or 0)
    verified_sources = int(audit.get("verified_sources") or 0)
    if not verified_sources:
        verified_sources = sum(
            1
            for source in audit.get("sources", [])
            if isinstance(source, dict) and source.get("status") == "verified"
        )
    source_scores = [
        source.get("avg_score")
        for source in audit.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("avg_score"), (int, float))
    ]
    avg_source_score = (
        sum(source_scores) / len(source_scores)
        if source_scores else 0.0
    )

    if chars < settings.CRAG_CONTEXT_QUALITY_MIN_CHARS:
        return False
    if valid_chunks < 2 or unique_sources < 2:
        return False
    if require_verified:
        if verified_chunks < min_verified_chunks or verified_sources < 2:
            return False
    if source_scores and avg_source_score < 0.30:
        return False
    return True


def _verified_gate_requirement(section_type: str | None, target_pages: Any = None) -> int:
    try:
        pages = int(target_pages) if target_pages is not None else None
    except (TypeError, ValueError):
        pages = None
    if str(section_type or "").lower() in {"deep", "applied"} or (pages is not None and pages >= 3):
        return 3
    return 2


def _section_gate_metadata(curriculum: Any, chap_idx: int, sub_idx: int) -> tuple[str, int | None]:
    try:
        _chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)
        section_type = (
            subsection.section_type
            if isinstance(subsection, SubSection)
            else subsection.get("section_type", "medium")
        )
        target_pages = (
            subsection.target_pages
            if isinstance(subsection, SubSection)
            else subsection.get("target_pages")
        )
        return str(section_type or "medium"), target_pages
    except Exception:
        return "medium", None


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

    def __init__(self, advanced_config: dict[str, Any] | None = None) -> None:
        model = auxiliary_chat_model(
            cheap_model=str(get_runtime_config("LLM_MODEL_CHEAP", required=False) or LLM_MODEL_CHEAP),
            premium_model=str(get_runtime_config("LLM_MODEL_PREMIUM", required=False) or LLM_MODEL_PREMIUM),
            advanced_config=advanced_config,
        )
        self._llm = ChatOpenAI(
            model=model, #type: ignore
            api_key=get_api_key("OPENAI_API_KEY"), #type: ignore
            temperature=0,
        )
        self._model = model
        self._advanced_config = advanced_config or {}
        self._chunk_llm_filter_mode = get_rag_chunk_llm_filter_mode(self._advanced_config)
        self._llm_with_tools = self._llm.bind_tools([retrieve_context_tool])

    def enrich_context(
        self,
        section_description: str,
        section_type: str,
        initial_context: str,
        section_summaries: list[str],
        collection_name: str = "dynamic_context",
        persist_directory: str = "",
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
                f"For technical/computing topics, prefer concise English keyword queries "
                f"or bilingual VI+EN queries; use Vietnamese-only queries only when the "
                f"missing content is specifically about Vietnam or local terminology.\n"
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

            response = rate_limited_invoke(
                self._llm_with_tools,
                messages,
                bucket="chat",
                metadata={
                    "agent": "Evaluator",
                    "node": "context_evaluator",
                    "model": self._model,
                },
            )
            tool_calls = getattr(response, "tool_calls", [])

            if not tool_calls:
                # LLM decided no additional fetch needed — stop here.
                break

            messages.append(response)

            for tc in tool_calls:
                tool_args = dict(tc["args"])
                tool_args["collection_name"] = collection_name
                tool_args["persist_directory"] = persist_directory
                tool_args["chunk_llm_filter_mode"] = self._chunk_llm_filter_mode
                query = tool_args.get("query", "")
                logger.info(f"[Retrieval] Tool call: '{query[:60]}'")
                _queries_this_call.append(query)

                result = retrieve_context_tool.invoke(tool_args)
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
    collection_name   = state.get("rag_collection_name", "dynamic_context")
    persist_directory = state.get("rag_persist_dir", "")
    prior_source_audit = state.get("rag_source_audit", {}) or {}
    prior_discarded_chunks = (
        prior_source_audit.get("discarded_details", [])
        if isinstance(prior_source_audit, dict)
        else []
    )
    retrieval_attempts = int(state.get("rag_retrieval_attempts", 0) or 0)
    max_retries = max(1, getattr(settings, "CRAG_MAX_CONTEXT_RETRIES", 2))
    allow_best_effort = _runtime_bool("CRAG_BEST_EFFORT_AFTER_RETRIES", False)
    advanced_config = state.get("advanced_config", {}) or {}
    cost_profile = get_cost_profile(advanced_config)
    require_verified_gate = cost_profile in {BALANCED_COST, AGGRESSIVE_COST}
    gate_section_type, gate_target_pages = _section_gate_metadata(curriculum, chap_idx, sub_idx)
    min_verified_chunks = _verified_gate_requirement(gate_section_type, gate_target_pages)

    if (
        should_skip_context_evaluator_when_sufficient(advanced_config)
        and not review_feedback
        and deterministic_context_is_sufficient(
            initial_context,
            prior_source_audit,
            require_verified=require_verified_gate,
            min_verified_chunks=min_verified_chunks,
        )
    ):
        source_audit = dict(prior_source_audit) if prior_source_audit else build_source_audit_summary(
            initial_context,
            used_queries=used_queries,
            context_quality="sufficient",
            chapter_index=chap_idx,
            subsection_index=sub_idx,
            discarded_chunks=prior_discarded_chunks,
        )
        source_audit["context_quality"] = "sufficient"
        source_audit["used_queries"] = list(used_queries)[-5:]
        source_audit["current_section"] = {
            "chapter": chap_idx + 1,
            "subsection": sub_idx + 1,
        }
        logger.info(
            "ContextEvaluator skipped LLM: deterministic audit is sufficient "
            "(len=%s, chunks=%s, sources=%s, verified=%s/%s)",
            len(initial_context),
            source_audit.get("valid_chunks"),
            source_audit.get("unique_sources"),
            source_audit.get("verified_chunks"),
            source_audit.get("verified_sources"),
        )
        return {
            "rag_context":             initial_context,
            "context_quality":         "sufficient",
            "web_supplement_context":  "",
            "used_rag_queries":        used_queries,
            "rag_source_audit":        source_audit,
            "rag_best_effort_context": initial_context,
            "rag_best_effort_audit":   source_audit,
            "rag_best_effort_score":   1.0,
            "messages": [
                "✓ ContextEvaluator: skipped LLM; existing RAG audit is sufficient"
            ],
        }

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

        agent = EvaluatorAgent(advanced_config=advanced_config)
        enriched_context, new_queries = agent.enrich_context(
            section_description = sec_desc,
            section_type        = sec_type,
            initial_context     = initial_context,
            section_summaries   = list(section_summaries),
            collection_name     = collection_name,
            persist_directory   = persist_directory,
            revision_feedback   = review_feedback or "",
            used_queries        = used_queries,
        )

        prior_used    = list(used_queries)
        updated_used  = prior_used + new_queries
        source_audit_probe = build_source_audit_summary(
            enriched_context,
            used_queries=updated_used,
            chapter_index=chap_idx,
            subsection_index=sub_idx,
            discarded_chunks=prior_discarded_chunks,
        )

        valid_chunks = int(source_audit_probe.get("valid_chunks", 0) or 0)
        unique_sources = int(source_audit_probe.get("unique_sources", 0) or 0)
        source_scores = [
            s.get("avg_score")
            for s in source_audit_probe.get("sources", [])
            if isinstance(s.get("avg_score"), (int, float))
        ]
        avg_source_score = (
            sum(source_scores) / len(source_scores)
            if source_scores else 0.0
        )

        is_empty = not enriched_context.strip()
        is_too_short = len(enriched_context) < settings.CRAG_CONTEXT_QUALITY_MIN_CHARS
        too_few_chunks = valid_chunks < 2
        too_few_sources = unique_sources < 2
        low_score = bool(source_scores) and avg_source_score < 0.30
        evidence_score = _context_evidence_score(
            chars=len(enriched_context),
            valid_chunks=valid_chunks,
            unique_sources=unique_sources,
            avg_source_score=avg_source_score,
        )

        if is_empty or is_too_short or too_few_chunks or too_few_sources or low_score:
            context_quality = "insufficient"
            source_audit_probe.setdefault("warnings", []).append(
                "Context did not meet strict RAG gate: "
                f"chars={len(enriched_context)}, chunks={valid_chunks}, "
                f"sources={unique_sources}, avg_score={avg_source_score:.2f}."
            )
            logger.warning(
                f"ContextEvaluator: context quality = 'insufficient' "
                f"(len={len(enriched_context)}, chunks={valid_chunks}, "
                f"sources={unique_sources}, avg_score={avg_source_score:.2f}, "
                f"new_queries={len(new_queries)})"
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

        source_audit = build_source_audit_summary(
            enriched_context,
            used_queries=updated_used,
            context_quality=context_quality,
            chapter_index=chap_idx,
            subsection_index=sub_idx,
            discarded_chunks=prior_discarded_chunks,
        )
        source_audit["warnings"] = source_audit_probe.get("warnings", [])
        if (
            context_quality == "sufficient"
            and require_verified_gate
            and not deterministic_context_is_sufficient(
                enriched_context,
                source_audit,
                require_verified=True,
                min_verified_chunks=min_verified_chunks,
            )
        ):
            context_quality = "insufficient"
            source_audit["context_quality"] = "insufficient"
            source_audit.setdefault("warnings", []).append(
                "Balanced-cost verified gate not met: "
                f"verified_chunks={source_audit.get('verified_chunks', 0)}, "
                f"verified_sources={source_audit.get('verified_sources', 0)}; "
                f"required={min_verified_chunks} verified chunks from at least 2 sources."
            )
            logger.warning(
                "ContextEvaluator: verified gate failed "
                "(verified_chunks=%s, verified_sources=%s, required=%s)",
                source_audit.get("verified_chunks", 0),
                source_audit.get("verified_sources", 0),
                min_verified_chunks,
            )

        best_context = state.get("rag_best_effort_context", "") or ""
        best_audit = state.get("rag_best_effort_audit", {}) or {}
        best_score = float(state.get("rag_best_effort_score", 0.0) or 0.0)
        if valid_chunks > 0 and enriched_context.strip() and evidence_score >= best_score:
            best_context = enriched_context
            best_audit = source_audit
            best_score = evidence_score

        if (
            context_quality == "insufficient"
            and allow_best_effort
            and (
                retrieval_attempts >= max_retries
                or state.get("rag_recovery_attempted", False)
            )
            and best_context.strip()
        ):
            context_quality = "best_effort"
            enriched_context = best_context
            source_audit = dict(best_audit)
            source_audit["context_quality"] = "best_effort"
            source_audit.setdefault("warnings", []).append(
                "Using best available context after retry budget was exhausted."
            )
            logger.warning(
                "ContextEvaluator: using best_effort context after %s/%s "
                "attempts (evidence_score=%.3f)",
                retrieval_attempts,
                max_retries,
                best_score,
            )

        return {
            "rag_context":            enriched_context,
            "context_quality":        context_quality,
            "web_supplement_context": web_supplement,
            "used_rag_queries":       updated_used,
            "rag_source_audit":       source_audit,
            "rag_best_effort_context": best_context,
            "rag_best_effort_audit":   best_audit,
            "rag_best_effort_score":   best_score,
            "messages": [
                f"{'✓' if context_quality == 'sufficient' else '⚠️'} "
                f"ContextEvaluator: quality='{context_quality}', "
                f"total_chars={len(enriched_context)}, "
                f"new_fetches={len(new_queries)}"
            ],
        }

    except Exception as e:
        logger.error(f"ContextEvaluator unexpected error: {e}", exc_info=True)
        best_context = state.get("rag_best_effort_context", "") or ""
        if allow_best_effort and best_context.strip():
            best_audit = dict(state.get("rag_best_effort_audit", {}) or {})
            if not best_audit:
                best_audit = build_source_audit_summary(
                    best_context,
                    used_queries=used_queries,
                    context_quality="best_effort",
                    chapter_index=chap_idx,
                    subsection_index=sub_idx,
                    discarded_chunks=prior_discarded_chunks,
                )
            best_audit["context_quality"] = "best_effort"
            best_audit.setdefault("warnings", []).append(
                f"ContextEvaluator error fallback used best available context: {e}"
            )
            return {
                "rag_context":            best_context,
                "context_quality":        "best_effort",
                "web_supplement_context": "",
                "rag_source_audit":       best_audit,
                "rag_best_effort_context": best_context,
                "rag_best_effort_audit":   best_audit,
                "rag_best_effort_score":   float(state.get("rag_best_effort_score", 0.0) or 0.0),
                "messages": [f"⚠️ ContextEvaluator fallback: best_effort after error: {e}"],
            }

        # Strict gate: retrieval/evaluation errors must not be treated as
        # sufficient source evidence when no prior context exists.
        return {
            "rag_context":            initial_context,
            "context_quality":        "insufficient",
            "web_supplement_context": "",
            "rag_source_audit": build_source_audit_summary(
                initial_context,
                used_queries=used_queries,
                context_quality="insufficient",
                chapter_index=chap_idx,
                subsection_index=sub_idx,
                discarded_chunks=prior_discarded_chunks,
            ),
            "messages": [f"Error in ContextEvaluator: {e}"],
        }
