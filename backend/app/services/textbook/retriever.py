"""
Retriever node for AI Textbook Generator.

This component retrieves relevant document chunks from ChromaDB using semantic
similarity search based on the current subsection's search_query field.

It is called once per subsection iteration in the workflow loop:
    QueryFormulator -> Retriever -> ContextEvaluator -> Writer -> Reviewer -> Illustrator

Performance note:
    ResearcherAgent is instantiated via a module-level lazy singleton
    (_get_retriever()) so that the ChromaDB client connection is created
    once and reused across all N×M subsection calls, rather than
    reconnecting on every iteration.

RAG Context Logging:
    Every retrieve_context() call writes a structured entry to
    logs/rag_context.log containing:
        - The search query used
        - Total chars retrieved
        - Full content of every chunk with source URL and similarity rank
    This log is the primary audit trail for RAG quality evaluation.
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from collections import Counter
from urllib.parse import urlparse



from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
import re
from app.config import settings, get_embedding_model
from app.services.api_rate_limiter import rate_limited_call, rate_limited_invoke
from app.services.cost_profile import (
    RAG_CHUNK_FILTER_ALWAYS,
    RAG_CHUNK_FILTER_OFF,
    get_rag_chunk_llm_filter_mode,
)
from app.services.runtime_config import get_api_key, get_runtime_config
from app.services.chroma_runtime import chroma_vector_store_kwargs, effective_chroma_persist_dir

LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
CHROMA_DB_DIR = settings.CHROMA_DB_DIR
RAG_TOP_K    = settings.RAG_TOP_K
RAG_INITIAL_K = settings.RAG_INITIAL_K
RAG_TOOL_K   = settings.RAG_TOOL_K
_MIN_SUBSTANTIVE_SENTENCES: int = settings.RAG_MIN_SUBSTANTIVE_SENTENCES
_MIN_AVG_SENTENCE_LEN:      int = settings.RAG_MIN_AVG_SENTENCE_LEN
_TRUSTED_DOMAIN_QUOTA:      int = settings.RAG_TRUSTED_DOMAIN_QUOTA
_DEFAULT_DOMAIN_QUOTA:      int = settings.RAG_DEFAULT_DOMAIN_QUOTA
_SEMANTIC_DEDUP_THRESHOLD: float = settings.RAG_SEMANTIC_DEDUP_THRESHOLD
from langchain_chroma import Chroma
from app.schemas.curriculum import AgentState, get_section_location
from app.utils.log_config import setup_logger

logger = setup_logger(name="Retriever", logfile="logs/agents.log")


class _RateLimitedEmbeddingFunction:
    """Wrap OpenAI embeddings so Chroma query embeddings share the API limiter."""

    def __init__(self, base: Any) -> None:
        self._base = base

    def embed_query(self, text: str) -> list[float]:
        model_name = str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL)
        return rate_limited_call(
            lambda: self._base.embed_query(text),
            bucket="embedding",
            model=model_name,
            metadata={"agent": "Retriever", "node": "retriever_node"},
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model_name = str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL)
        return rate_limited_call(
            lambda: self._base.embed_documents(texts),
            bucket="embedding",
            model=model_name,
            metadata={"agent": "Retriever", "node": "retriever_node"},
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def _get_rate_limited_embedding_model() -> Any:
    model = get_embedding_model()
    if settings.EMBEDDING_PROVIDER == "openai":
        return _RateLimitedEmbeddingFunction(model)
    return model


_SOURCE_LINE_RE = re.compile(
    r"^Document\s+\d+\s+\(Source:\s*(?P<source>.*?)(?:\s+\|\s+Score:\s*(?P<score>[\d.]+))?(?:\s+\|\s+Status:\s*(?P<status>[\w-]+))?\):",
    re.MULTILINE,
)


def build_source_audit_summary(
    rag_context: str,
    used_queries: list[str] | None = None,
    context_quality: str | None = None,
    chapter_index: int | None = None,
    subsection_index: int | None = None,
    discarded_chunks: list[dict[str, Any]] | None = None,
    max_sources: int = 10,
    max_queries: int = 5,
) -> dict[str, Any]:
    """
    Build a compact, UI-safe source audit summary from formatted RAG context.

    The formatted context already contains source URL headers. This helper only
    extracts those headers and never exposes chunk body text to progress polling.
    """
    used_queries = list(used_queries or [])
    discarded_chunks = list(discarded_chunks or [])
    matches = list(_SOURCE_LINE_RE.finditer(rag_context or ""))
    records: list[dict[str, Any]] = []
    for idx, match in enumerate(matches):
        source = match.group("source").strip()
        if not source or source.lower() == "unknown":
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(rag_context or "")
        sample = re.sub(r"\s+", " ", (rag_context or "")[start:end]).strip()[:220]
        score_text = match.group("score")
        try:
            score = float(score_text) if score_text else None
        except ValueError:
            score = None
        records.append({
            "url": source,
            "score": score,
            "status": match.group("status") or "pass",
            "sample": sample,
        })

    counts = Counter(record["url"] for record in records)
    status_counts = Counter(record.get("status") or "pass" for record in records)
    verified_sources = {
        record["url"]
        for record in records
        if (record.get("status") or "pass") == "verified"
    }
    first_seen = {record["url"]: idx for idx, record in enumerate(records)}
    top_sources = sorted(
        counts.items(),
        key=lambda item: (-item[1], first_seen.get(item[0], 0)),
    )[:max_sources]

    summary: dict[str, Any] = {
        "total_retrievals": len(used_queries),
        "total_chunks": len(records),
        "unique_sources": len(counts),
        "valid_chunks": len(records),
        "verified_chunks": int(status_counts.get("verified", 0)),
        "pass_chunks": int(status_counts.get("pass", 0)),
        "verified_sources": len(verified_sources),
        "source_status_summary": dict(status_counts),
        "discarded_chunks": len(discarded_chunks),
        "discarded_details": discarded_chunks[:max_sources],
        "warnings": [],
        "sources": [
            {
                "url": source,
                "domain": urlparse(source).netloc or source,
                "count": count,
                "avg_score": _average_score_for_source(records, source),
                "status": _status_for_source(records, source),
                "queries": used_queries[-max_queries:],
                "sample": next(
                    (record["sample"] for record in records if record["url"] == source),
                    "",
                ),
            }
            for source, count in top_sources
        ],
        "used_queries": used_queries[-max_queries:],
    }

    if not records:
        summary["warnings"].append("No valid source chunks were available for this section.")
    if discarded_chunks:
        reasons = Counter(str(item.get("reason", "unknown")) for item in discarded_chunks)
        summary["warnings"].append(
            "Retriever discarded candidate chunks: "
            + ", ".join(f"{reason}={count}" for reason, count in reasons.items())
        )

    if context_quality:
        summary["context_quality"] = context_quality
    if chapter_index is not None and subsection_index is not None:
        summary["current_section"] = {
            "chapter": chapter_index + 1,
            "subsection": subsection_index + 1,
        }

    return summary


def _average_score_for_source(records: list[dict[str, Any]], source: str) -> float | None:
    scores = [
        record["score"]
        for record in records
        if record["url"] == source and isinstance(record.get("score"), (int, float))
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 3)


def _status_for_source(records: list[dict[str, Any]], source: str) -> str:
    statuses = [
        record.get("status") or "pass"
        for record in records
        if record["url"] == source
    ]
    if not statuses:
        return "unknown"
    if any(status == "warning" for status in statuses):
        return "warning"
    if any(status == "verified" for status in statuses):
        return "verified"
    if all(status == "pass" for status in statuses):
        return "pass"
    return statuses[0]


# ============================================================================
# RAG Context Logger
#
# Writes the full retrieved context (query + all chunks) to a dedicated log
# file separate from the main agents.log. This keeps RAG audit data readable
# without being buried in general workflow logs.
#
# Log format per retrieval call:
#   ════════════════════════════════════════════════════════════════════════
#   [RAG #N] YYYY-MM-DD HH:MM:SS | Chapter X.Y | total_chars chars
#   QUERY: <search_query string>
#   ────────────────────────────────────────────────────────────────────────
#   [Chunk 1/k] Source: <url>
#   <full chunk text — no truncation>
#   ────────────────────────────────────────────────────────────────────────
#   [Chunk 2/k] Source: <url>
#   <full chunk text>
#   ...
#   ════════════════════════════════════════════════════════════════════════
# ============================================================================

_rag_log_counter: int = 0
_rag_log_lock = threading.Lock()


def _detect_chunk_language(text: str) -> str:
    """
    Detect whether a text chunk is Vietnamese or English.
    
    Uses Vietnamese diacritic pattern for fast, accurate detection.
    This heuristic works well because Vietnamese uses extensive diacritics
    that are absent in English text.
    
    Args:
        text: Text content to classify (samples first 500 chars for speed)
    
    Returns:
        'vi' if Vietnamese detected, 'en' otherwise
    
    Examples:
        _detect_chunk_language("Machine learning algorithms...") → 'en'
        _detect_chunk_language("Thuật toán học máy...") → 'vi'
    """
    import re
    
    # Vietnamese diacritics - presence indicates Vietnamese text
    vi_pattern = re.compile(
        r'[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
        re.IGNORECASE
    )
    
    # Sample first 500 chars for speed (sufficient for language detection)
    sample = text[:500]
    
    return 'vi' if vi_pattern.search(sample) else 'en'


def _compute_retrieval_bilingual_stats(chunks: list[dict]) -> dict:
    """
    Compute bilingual distribution of retrieved chunks.
    
    Used for logging and demonstration purposes. Proves that the system
    successfully retrieves content from both Vietnamese and English sources,
    demonstrating cross-lingual retrieval capability of the bge-m3 model.
    
    Args:
        chunks: List of chunk dictionaries with 'source' and 'content' keys
    
    Returns:
        Dictionary containing:
            - total: Total number of chunks retrieved
            - vi_count: Number of Vietnamese chunks
            - en_count: Number of English chunks
            - vi_ratio: Ratio of Vietnamese chunks (0.0 to 1.0)
            - en_ratio: Ratio of English chunks (0.0 to 1.0)
            - languages: List of language codes in retrieval order
    
    Example output:
        {
            'total': 5,
            'vi_count': 2,
            'en_count': 3,
            'vi_ratio': 0.4,
            'en_ratio': 0.6,
            'languages': ['en', 'vi', 'en', 'en', 'vi']
        }
    """
    if not chunks:
        return {
            'total': 0,
            'vi_count': 0,
            'en_count': 0,
            'vi_ratio': 0.0,
            'en_ratio': 0.0,
            'languages': []
        }
    
    # Detect language for each chunk
    languages = [_detect_chunk_language(c['content']) for c in chunks]
    
    vi_count = languages.count('vi')
    en_count = languages.count('en')
    total = len(chunks)
    
    return {
        'total': total,
        'vi_count': vi_count,
        'en_count': en_count,
        'vi_ratio': vi_count / total if total > 0 else 0.0,
        'en_ratio': en_count / total if total > 0 else 0.0,
        'languages': languages,
    }

class RAGContextLogger:
    """
    Writes full RAG retrieval records to logs/rag_context.log.

    Each record captures the search query and the complete untruncated
    content of every retrieved chunk, making it possible to audit:
        - Whether the search query matched useful chunks
        - What information the Writer actually had access to
        - Which source URLs contributed to each section
    """

    def __init__(self, log_dir: str = "logs") -> None:
        self.log_path = Path(log_dir) / "rag_context.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        query:         str,
        chunks:        list[dict],   # list of {"source": str, "content": str}
        context_label: str = "",     # e.g. "Chapter 1.2 Ten muc"
    ) -> int:
        """
        Write one retrieval record to rag_context.log.

        Args:
            query:         The search query sent to ChromaDB.
            chunks:        Retrieved chunks as list of {source, content} dicts.
            context_label: Human-readable label for the retrieval (chapter.section).

        Returns:
            1-indexed sequence number of the entry written.
        """
        global _rag_log_counter

        with _rag_log_lock:
            _rag_log_counter += 1
            n = _rag_log_counter

        timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_chars = sum(len(c["content"]) for c in chunks)
        label_part  = f" | {context_label}" if context_label else ""

        divider_thick = "=" * 72
        divider_thin  = "-" * 72

        lines = [
            divider_thick,
            f"[RAG #{n}] {timestamp}{label_part} | {total_chars} chars retrieved",
            f"QUERY: {query}",
            divider_thin,
        ]

        for i, chunk in enumerate(chunks, 1):
            score = chunk.get("retrieval_score")
            status = chunk.get("status", "pass")
            reason = chunk.get("discard_reason", "")
            score_part = f" | Score: {score:.3f}" if isinstance(score, (int, float)) else ""
            reason_part = f" | Reason: {reason}" if reason else ""
            lines += [
                f"[Chunk {i}/{len(chunks)}] Source: {chunk['source']}{score_part} | Status: {status}{reason_part}",
                chunk["content"],
                divider_thin,
            ]

        lines += ["", ""]   # trailing blank lines for readability

        entry = "\n".join(lines) + "\n"

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        return n


# Module-level singleton logger — one file handle shared across all calls.
_rag_logger: Optional[RAGContextLogger] = None


def _get_rag_logger() -> RAGContextLogger:
    """Return the module-level RAGContextLogger singleton."""
    global _rag_logger
    if _rag_logger is None:
        _rag_logger = RAGContextLogger()
    return _rag_logger


# ============================================================================
# ResearcherAgent
# ============================================================================

class Retriever:
    """
    Retriever: semantic similarity search over the ingested ChromaDB corpus.

    Responsibilities:
        - Maintain a single ChromaDB client connection (shared via singleton)
        - Perform top-k similarity search with MMR for diversity
        - Apply three-layer chunk quality filtering:
            Layer 1: structural heuristics (no LLM)
            Layer 2: deterministic rerank/quality scoring
            Layer 3: optional LLM binary classifier for configured/borderline chunks
            Layer 4: semantic deduplication + quality scoring
        - Format retrieved chunks with source metadata for EvaluatorAgent
        - Write full retrieval records to logs/rag_context.log for audit

    Instantiate via _get_retriever() rather than directly — this ensures the
    ChromaDB connection is reused across all subsection calls in the workflow.

    Note on LLM usage: _llm_classify_chunk() uses an LLM as a binary classifier,
    not as a reasoner. It makes no decisions about retrieval flow — it only
    judges individual chunks in isolation. This distinguishes Retriever from
    EvaluatorAgent which uses LLM reasoning to decide whether to fetch more context.
    """

    def __init__(self, collection_name: str = "dynamic_context", persist_directory: Any = None) -> None:
        """
        Open a ChromaDB connection using the singleton embedding model.

        Uses get_embedding_model() which is itself lru_cache-cached, so the
        embedding model is loaded once per process regardless of how many
        ResearcherAgent instances are created.
        """
        self.collection_name = collection_name
        self.persist_directory = effective_chroma_persist_dir(persist_directory)
        self.vector_db = Chroma(
            **chroma_vector_store_kwargs(persist_directory),
            embedding_function=_get_rate_limited_embedding_model(),
            collection_name=collection_name,
        )
        self._retrieved_ids: set[str] = set()
        self.last_retrieval_audit: dict[str, Any] = {}


    def reset_retrieved_ids(self) -> None:
        """
        Reset retrieved chunk blacklist.
        Must be called before each new subsection to prevent
        cross-subsection blacklist contamination.
        """
        self._retrieved_ids.clear()
        self.last_retrieval_audit = {}
        logger.debug("Retrieved IDs blacklist reset")
    
    
    def retrieve_context(
        self,
        query:         str,
        k:             int  = RAG_TOP_K,
        context_label: str  = "",
        content_type:  str  = "technical",
        advanced_config: dict[str, Any] | None = None,
        chunk_llm_filter_mode: str | None = None,
    ) -> str:
        logger.info(f"Searching ChromaDB — query: '{query}' | k={k}")
        """
        Retrieve the top-k most relevant document chunks for a given query.

        Performs MMR search via ChromaDB for diversity, applies cross-call
        deduplication via _retrieved_ids blacklist (source URL + chunk level),
        writes the full retrieval record to logs/rag_context.log, then returns
        a formatted string suitable for injection into the Writer's system prompt.

        Deduplication strategy:
            - Chunk level: same source + same content prefix → skip
            - Source level: same URL already contributed >= 2 chunks → skip
              Prevents a single high-similarity page from dominating context
              across multiple tool call rounds.

        Args:
            query:         Search query string.
            k:             Maximum number of fresh chunks to return.
            context_label: Human-readable label written to the RAG log.

        Returns:
            Formatted string of retrieved chunks with source metadata.
            Empty string if no results found or on retrieval error.
        """
        

        try:
            effective_filter_mode = get_rag_chunk_llm_filter_mode(
                advanced_config,
                explicit_mode=chunk_llm_filter_mode,
            )
            self.last_retrieval_audit = {
                "query": query,
                "discarded_chunks": [],
                "candidate_count": 0,
                "kept_count": 0,
                "llm_filter_mode": effective_filter_mode,
                "llm_classifier_calls": 0,
            }
            results = self.vector_db.max_marginal_relevance_search(
                query,
                k=max(k * 3, k + len(self._retrieved_ids)),
                fetch_k=max(k * 8, (k + len(self._retrieved_ids)) * 4),
                lambda_mult=0.7,
            )

            # Dedup: chunk-level + source-level
            fresh_results = []
            for doc in results:
                source_url = doc.metadata.get("source", "")
                chunk_id   = source_url + doc.page_content[:50]

                if chunk_id in self._retrieved_ids:
                    continue

                _TRUSTED_EDU_DOMAINS = (
                    "wikipedia.org",
                    "britannica.com",
                    "openstax.org",        
                    "ocw.mit.edu",        
                    "slds-lmu",
                    "cs.cmu",
                    "stanford.edu",
                    "mit.edu",
                    "geeksforgeeks.org",
                    "machinelearningcoban",
                    "arxiv.org",
                    "pmc.ncbi.nlm.nih.gov",
                    "iosrjournals",
                    "ijirt",
                )
                max_quota = (
                    _TRUSTED_DOMAIN_QUOTA
                    if any(d in source_url for d in _TRUSTED_EDU_DOMAINS)
                    else _DEFAULT_DOMAIN_QUOTA
                )

                source_count = sum(
                    1 for cid in self._retrieved_ids
                    if cid.startswith(source_url)
                )
                if source_count >= max_quota:
                    logger.debug(
                        f"Source quota reached ({max_quota}): {source_url[:60]} — skipping"
                    )
                    continue

                self._retrieved_ids.add(chunk_id)
                fresh_results.append(doc)

                if len(fresh_results) >= k * 3:
                    break

            kept = []
            discarded: list[dict[str, Any]] = []
            for doc in fresh_results:
                text = doc.page_content

                if not _is_substantive_chunk(text):
                    discarded.append({
                        "source": doc.metadata.get("source", "Unknown"),
                        "reason": "structural_filter",
                        "sample": text[:120],
                    })
                    logger.debug(f"Heuristic DISCARD: '{text[:60]}'")
                    continue

                retrieval_score, discard_reason = _rerank_retrieved_doc(doc, query)
                doc.metadata["retrieval_score"] = f"{retrieval_score:.4f}"
                if discard_reason:
                    discarded.append({
                        "source": doc.metadata.get("source", "Unknown"),
                        "reason": discard_reason,
                        "sample": text[:120],
                    })
                    logger.debug(
                        f"Rerank DISCARD ({discard_reason}, score={retrieval_score:.3f}): "
                        f"'{text[:60]}'"
                    )
                    continue

                if _should_run_llm_chunk_filter(
                    doc,
                    query=query,
                    mode=effective_filter_mode,
                ):
                    self.last_retrieval_audit["llm_classifier_calls"] += 1
                    if not _llm_classify_chunk(text, query=query, content_type=content_type):
                        discarded.append({
                            "source": doc.metadata.get("source", "Unknown"),
                            "reason": "llm_classifier",
                            "sample": text[:120],
                        })
                        logger.debug(f"LLM DISCARD: '{text[:60]}'")
                        continue

                kept.append(doc)

            filtered_count = len(fresh_results) - len(kept)
            self.last_retrieval_audit.update({
                "candidate_count": len(fresh_results),
                "kept_count": len(kept),
                "discarded_chunks": discarded,
            })
            if filtered_count:
                logger.info(
                    f"Chunk quality filter: {len(fresh_results)} → {len(kept)} "
                    f"({filtered_count} junk chunks removed)"
                )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # Layer 3 — Semantic deduplication + quality scoring
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            
            if kept:
                # Convert to dict format for deduplication
                chunk_dicts = []
                for doc in kept:
                    chunk_dicts.append({
                        'content': doc.page_content,
                        'source': doc.metadata.get('source', 'Unknown'),
                        'retrieval_score': _safe_float(doc.metadata.get('retrieval_score')),
                        'language': doc.metadata.get('language') or _detect_chunk_language(doc.page_content),
                        'doc': doc  # Keep reference to original doc
                    })
                
                # Deduplicate semantically similar chunks
                deduped = _deduplicate_chunks_semantic(
                    chunk_dicts,
                    similarity_threshold=0.85,
                    embedding_model=self.vector_db._embedding_function
                )
                
                # Score quality and sort by retrieval confidence
                for chunk in deduped:
                    chunk['quality_score'] = chunk.get('retrieval_score', 0.0)
                
                deduped.sort(key=lambda x: x['quality_score'], reverse=True)

                selected = deduped[:k]
                if k >= 3 and not any(c.get('language') == 'en' for c in selected):
                    english_candidate = next(
                        (c for c in deduped[k:] if c.get('language') == 'en'),
                        None,
                    )
                    if english_candidate is not None:
                        selected = selected[:-1] + [english_candidate]
                        selected.sort(key=lambda x: x['quality_score'], reverse=True)
                        logger.info(
                            "Bilingual retrieval balance: included one EN chunk "
                            "that passed strict filters"
                        )

                kept = [c['doc'] for c in selected]
                self.last_retrieval_audit["kept_count"] = len(kept)
                
                if len(deduped) > k:
                    logger.info(
                        f"Quality ranking: top {k} of {len(deduped)} chunks selected "
                        f"(avg score: {sum(c['quality_score'] for c in deduped[:k]) / k:.2f})"
                    )

            if not kept and fresh_results:
                logger.warning(
                    f"All candidate chunks were filtered for query '{query}'. "
                    "Strict RAG gate returns empty context instead of unfiltered chunks."
                )
                _get_rag_logger().log(
                    query=query,
                    chunks=[
                        {
                            "source": item["source"],
                            "content": item["sample"],
                            "status": "discarded",
                            "discard_reason": item["reason"],
                        }
                        for item in discarded[:k]
                    ],
                    context_label=f"{context_label} [DISCARDED]",
                )
                return ""

            results = kept
    
            if not results:
                logger.warning(f"No fresh content found for query: '{query}'")
                return ""

            chunks: list[dict] = []
            for doc in results:
                retrieval_score = _safe_float(doc.metadata.get("retrieval_score"))
                query_overlap = _safe_float(doc.metadata.get("query_overlap_score"))
                status = (
                    "verified"
                    if retrieval_score >= 0.55 and query_overlap >= 0.18
                    else "pass"
                )
                chunks.append({
                    "source":          doc.metadata.get("source", "Unknown"),
                    "content":         doc.page_content,
                    "retrieval_score": retrieval_score,
                    "query_overlap":   query_overlap,
                    "status":          status,
                    "source_query":    doc.metadata.get("source_query", ""),
                })

            # Compute bilingual distribution statistics
            bilingual_stats = _compute_retrieval_bilingual_stats(chunks)

            # Log retrieval to RAG audit file
            entry_num = _get_rag_logger().log(
                query         = query,
                chunks        = chunks,
                context_label = context_label,
            )
            
            # Enhanced logging with bilingual information
            logger.info(
                f"Retrieved {len(chunks)} chunks "
                f"({bilingual_stats['vi_count']} VI, {bilingual_stats['en_count']} EN, "
                f"VI ratio: {bilingual_stats['vi_ratio']:.1%}) "
                f"({sum(len(c['content']) for c in chunks)} chars) "
                f"— logged as RAG #{entry_num} in logs/rag_context.log"
            )
            
            # Debug-level logging: language sequence for detailed analysis
            # Useful for verifying cross-lingual retrieval patterns
            if bilingual_stats['languages']:
                lang_sequence = ' → '.join([
                    f"{i+1}:{lang.upper()}" 
                    for i, lang in enumerate(bilingual_stats['languages'])
                ])
                logger.debug(f"  Language sequence: {lang_sequence}")

            # Format chunks for Writer's prompt (unchanged)
            formatted_content = ""
            for i, chunk in enumerate(chunks, 1):
                inline_content = chunk["content"].replace("\n", " ")
                score = chunk.get("retrieval_score", 0.0)
                status = chunk.get("status", "pass")
                source_query = chunk.get("source_query") or query
                formatted_content += (
                    f"Document {i} (Source: {chunk['source']} | "
                    f"Score: {score:.3f} | Status: {status}):\n"
                    f"Source query: {source_query}\n"
                    f"{inline_content}\n\n"
                )

            return formatted_content

        except Exception as e:
            logger.error(f"Error during retrieval: {e}", exc_info=True)
            return ""


# ---------------------------------------------------------------------------
#
# ResearcherAgent.__init__ opens a ChromaDB connection. Without a singleton,
# a new connection would be created for every subsection call (N chapters ×
# M subsections = N×M reconnections). The singleton ensures the connection
# is opened once and reused for the entire workflow run.
# ---------------------------------------------------------------------------

_retriever_instances: dict[tuple[str, str, str], Retriever] = {}



# ---------------------------------------------------------------------------
# Post-retrieval chunk quality filter
# ---------------------------------------------------------------------------

# Academic paper metadata headers — English + Vietnamese journal formats.
# Two or more metadata fields appearing together = paper header block.
_ACADEMIC_METADATA = re.compile(
    r'^(Volume|Issue|DOI|Received|Accepted|Published|Available online'
    r'|Revised|Submitted|Pages|ISSN|ISBN|Impact Factor'
    # Vietnamese equivalents
    r'|Tập|Số|Trang|Ngày nhận|Ngày chấp nhận|Ngày xuất bản'
    r'|Ngày đăng|Ngày nhận bài|Ngày phản biện|Ngày duyệt đăng'
    r'|Tác giả|Từ khóa|Chuyên ngành|Mã số)\s*[:\|]',
    re.IGNORECASE | re.MULTILINE,
)

# Course outline structural prefixes — English + Vietnamese syllabi.
# "Tuần 1:", "Bài 2 —", "Chủ đề 3:" etc.
_COURSE_OUTLINE = re.compile(
    r'^(Unit|Week|Module|Lecture|Session|Tutorial|Lab|Seminar'
    # Vietnamese equivalents
    r'|Tuần|Buổi|Chủ đề|Chuyên đề|Nội dung|Tiết'
    # Note: Bài/Chương/Mục/Phần already handled by crawler._TOC_LINE_PATTERN
    # but added here for retrieval-side defense
    r'|Bài|Chương|Mục|Phần)\s+\d+\s*[:\-–]',
    re.IGNORECASE | re.MULTILINE,
)

# Bibliographic citation entries — English + Vietnamese reference styles.
# Vietnamese citations: "Nguyễn Văn A. (2020). Tên tài liệu."
# or "Trần Thị B, 2019, Nhà xuất bản..."
_CITATION_ENTRY = re.compile(
    r'^[A-Z][a-záéíóúàèìòùâêîôûäëïöü\w]+,\s+[A-Z][\w\s\-]+[\.\(]\s*\d{4}[\.\)]'
    # Vietnamese author name patterns (diacritics in first name)
    r'|^[A-ZÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]'
    r'[a-zàáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ\s]+'
    r'[\.\(]\s*\d{4}[\.\)]',
    re.MULTILINE,
)


def _is_substantive_chunk(text: str) -> bool:
    """
    Topic-agnostic structural quality filter for retrieved chunks.

    Detects document structure rather than topic-specific keywords,
    making it generalizable across all subject domains and languages.

    Four layers:
        Layer 1 — Academic metadata headers (paper/journal boilerplate)
        Layer 2 — TOC / course outline detection (structural prefix lines)
        Layer 3 — Prose density check (sentence count + average length)
        Layer 4 — Reference/bibliography list detection

    Fails open: uncertain chunks are kept to avoid over-filtering.
    The LLM classifier (_llm_classify_chunk) handles remaining edge cases.
    """
    non_empty_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    total_lines     = len(non_empty_lines)

    # Layer 1 — Academic paper metadata header detection.
    # Two or more metadata fields (Volume, DOI, Received...) = paper header block,
    # not educational prose.
    if total_lines >= 3:
        metadata_hits = len(_ACADEMIC_METADATA.findall(text))
        if metadata_hits >= 2:
            return False

    # Layer 2a — Traditional TOC: high ratio of short lines.
    if total_lines >= 5:
        short_line_ratio = (
            sum(1 for ln in non_empty_lines if len(ln) < 60) / total_lines
        )
        if short_line_ratio > 0.70:
            return False

    # Layer 2b — Course outline: structural prefix lines (Unit 1:, Week 2:).
    if total_lines >= 3:
        outline_hits = len(_COURSE_OUTLINE.findall(text))
        if outline_hits >= 2:
            return False

    # Layer 3 — Prose density check.
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 20]
    if len(sentences) < _MIN_SUBSTANTIVE_SENTENCES:
        return False
    if sentences and (sum(len(s) for s in sentences) / len(sentences)) < _MIN_AVG_SENTENCE_LEN:
        return False

    # Layer 4 — Bibliography / reference list detection.
    if total_lines >= 4:
        # Pattern A: " - " separator dominates (aggregator reference list).
        dash_sep_ratio = (
            sum(1 for ln in non_empty_lines if ' - ' in ln) / total_lines
        )
        if dash_sep_ratio > 0.60:
            return False

        # Pattern B: year-range endings dominate (britannica-style timeline TOC).
        # e.g. "The Western Front, 1915–16" or "Mesopotamia, 1914–April 1916"
        year_range_ratio = (
            sum(1 for ln in non_empty_lines
                if re.search(r'\b1[89]\d{2}[–\-]\w+', ln))
            / total_lines
        )
        if year_range_ratio > 0.40:
            return False

        # Pattern C: citation entry lines (Author, Year. Title. Publisher.).
        citation_hits = len(_CITATION_ENTRY.findall(text))
        if citation_hits >= 3:
            return False
        
        # Pattern D: Vietnamese Wikipedia citation footer lines.
        # "Lưu trữ bản gốc ngày..." or "Truy cập ngày 12 tháng 3..."
        # These appear as dense blocks of short reference lines.
        vi_ref_ratio = (
            sum(1 for ln in non_empty_lines
                if re.search(
                    r'Lưu trữ bản gốc|Truy cập ngày|Nhà xuất bản|'
                    r'Bản gốc lưu trữ|\[\d+\]|tr\.\s*\d+|trang\s*\d+',
                    ln, re.IGNORECASE
                ))
            / total_lines
        )
        if vi_ref_ratio > 0.35:
            return False

    return True

# ---------------------------------------------------------------------------
# LLM-based chunk classifier — second filter layer using Groq (free tier).
# Only called on chunks that passed structural heuristics, so API usage
# is minimal (~3 calls × ~200 tokens per retrieve_context() invocation).
# ---------------------------------------------------------------------------

_chunk_classifier: Optional[ChatOpenAI] = None
_chunk_classifier_runtime_key: tuple[str, str] | None = None


def _get_chunk_classifier() -> ChatOpenAI:
    """
    Return singleton Groq LLM instance for chunk classification.
    Instantiated lazily to avoid startup overhead.
    """
    global _chunk_classifier, _chunk_classifier_runtime_key
    model = str(get_runtime_config("LLM_MODEL_CHEAP", required=False) or LLM_MODEL_CHEAP)
    api_key = get_api_key("OPENAI_API_KEY")
    runtime_key = (model, api_key)
    if _chunk_classifier is None or _chunk_classifier_runtime_key != runtime_key:
        _chunk_classifier = ChatOpenAI(
            model=model,
            openai_api_key=api_key,       # type: ignore[arg-type]
            temperature=0,
            max_completion_tokens=10
                         
        )
        _chunk_classifier_runtime_key = runtime_key
    return _chunk_classifier


def _deduplicate_chunks_semantic(
    chunks: list[dict],
    similarity_threshold: float = _SEMANTIC_DEDUP_THRESHOLD,
    embedding_model = None
) -> list[dict]:
    """
    Remove semantically duplicate chunks using embedding similarity.
    
    Keeps the first occurrence of each semantic cluster, removing near-duplicates
    that would add redundancy without new information. This is crucial when
    crawling multiple sources that quote the same content.
    
    Args:
        chunks: List of chunk dicts with 'content' key
        similarity_threshold: Cosine similarity above which chunks are considered duplicates
        embedding_model: Pre-loaded embedding model (reuse from retrieve_context)
    
    Returns:
        Deduplicated chunk list (preserves original order)
    
    Performance:
        - O(n²) worst case, but early termination on high similarity
        - ~2-3s for 10 chunks with BAAI/bge-m3
        - Skipped if chunks <= 3 (not worth the overhead)
    """
    if len(chunks) <= 3:
        # Too few chunks to deduplicate - overhead not worth it
        return chunks
    
    if embedding_model is None:
        from app.config import get_embedding_model
        embedding_model = get_embedding_model()
    
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    
    # Batch encode all chunks
    texts = [c['content'][:500] for c in chunks]  # First 500 chars for speed
    if settings.EMBEDDING_PROVIDER == "openai":
        embeddings = rate_limited_call(
            lambda: embedding_model.embed_documents(texts),
            bucket="embedding",
            model=str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL),
            metadata={"agent": "Retriever", "node": "retriever_node"},
        )
    else:
        embeddings = embedding_model.embed_documents(texts)
    embeddings_np = np.array(embeddings)
    
    # Track which chunks to keep
    keep_indices = []
    seen_embeddings = []
    
    for i, emb in enumerate(embeddings_np):
        # Check similarity against all kept chunks
        is_duplicate = False
        for kept_emb in seen_embeddings:
            sim = cosine_similarity([emb], [kept_emb])[0][0] # type: ignore
            if sim >= similarity_threshold:
                is_duplicate = True
                logger.debug(
                    f"Semantic duplicate detected (sim={sim:.3f}): "
                    f"'{texts[i][:60]}'"
                )
                break
        
        if not is_duplicate:
            keep_indices.append(i)
            seen_embeddings.append(emb)
    
    deduplicated = [chunks[i] for i in keep_indices]
    removed = len(chunks) - len(deduplicated)
    
    if removed > 0:
        logger.info(
            f"Semantic deduplication: {len(chunks)} → {len(deduplicated)} chunks "
            f"({removed} near-duplicates removed)"
        )
    
    return deduplicated

_CHUNK_SWEET_SPOT_MIN: int   = settings.RAG_CHUNK_SWEET_SPOT_MIN
_CHUNK_SWEET_SPOT_MAX: int   = settings.RAG_CHUNK_SWEET_SPOT_MAX
_CHUNK_SENT_LEN_MIN:   int   = settings.RAG_CHUNK_SENT_LEN_MIN
_CHUNK_SENT_LEN_MAX:   int   = settings.RAG_CHUNK_SENT_LEN_MAX

_TRUSTED_RETRIEVAL_DOMAINS = (
    "wikipedia.org", "britannica.com", "openstax.org", "ocw.mit.edu",
    "stanford.edu", "mit.edu", "berkeley.edu", "cs.cmu.edu",
    "arxiv.org", "acm.org", "ieee.org", "geeksforgeeks.org",
    ".edu", ".gov",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _keyword_overlap_score(query: str, text: str) -> float:
    query_terms = {
        term
        for term in re.findall(r"[\wÀ-ỹ]+", (query or "").lower())
        if len(term) >= 3
    }
    if not query_terms:
        return 0.0
    text_lower = (text or "").lower()
    hits = sum(1 for term in query_terms if term in text_lower)
    return min(1.0, hits / max(1, min(len(query_terms), 8)))


def _rerank_retrieved_doc(doc, query: str) -> tuple[float, str]:
    source = doc.metadata.get("source", "")
    domain = urlparse(source).netloc.lower()
    ingest_relevance = _safe_float(doc.metadata.get("relevance_score"), 0.0)
    keyword_overlap = _keyword_overlap_score(query, doc.page_content)
    doc.metadata["query_overlap_score"] = f"{keyword_overlap:.4f}"
    quality_score = _score_chunk_quality(doc.page_content, source)
    doc.metadata["chunk_quality_score"] = f"{quality_score:.4f}"
    trust_bonus = 0.05 if any(d in domain for d in _TRUSTED_RETRIEVAL_DOMAINS) else 0.0

    score = (
        ingest_relevance * 0.45
        + keyword_overlap * 0.35
        + quality_score * 0.20
        + trust_bonus
    )
    if keyword_overlap < 0.05:
        return score, "very_low_query_overlap"
    if keyword_overlap < 0.12 and ingest_relevance < 0.40:
        return score, "low_query_overlap"
    if quality_score < 0.25:
        return score, "low_chunk_quality"
    return min(1.0, score), ""


def _should_run_llm_chunk_filter(doc, query: str, mode: str) -> bool:
    """Return True when a retrieved chunk still needs LLM binary verification."""
    if mode == RAG_CHUNK_FILTER_OFF:
        return False
    if mode == RAG_CHUNK_FILTER_ALWAYS:
        return True

    source = doc.metadata.get("source", "")
    domain = urlparse(source).netloc.lower()
    if any(trusted in domain for trusted in _TRUSTED_RETRIEVAL_DOMAINS):
        return False

    retrieval_score = _safe_float(doc.metadata.get("retrieval_score"), 0.0)
    ingest_relevance = _safe_float(doc.metadata.get("relevance_score"), 0.0)
    keyword_overlap = _safe_float(
        doc.metadata.get("query_overlap_score"),
        _keyword_overlap_score(query, doc.page_content),
    )
    quality_score = _safe_float(
        doc.metadata.get("chunk_quality_score"),
        _score_chunk_quality(doc.page_content, source),
    )

    strong_relevance = (
        retrieval_score >= 0.62
        and keyword_overlap >= 0.18
        and quality_score >= 0.45
    )
    strong_ingest = (
        ingest_relevance >= 0.55
        and keyword_overlap >= 0.12
        and quality_score >= 0.55
    )
    if strong_relevance or strong_ingest:
        return False

    return True

def _score_chunk_quality(chunk_text: str, source_url: str) -> float:
    """
    Compute quality confidence score for a chunk based on multiple signals.
    
    Scoring factors:
    - Source domain reputation (trusted edu domains get boost)
    - Text structure quality (sentence count, avg length, punctuation)
    - Educational markers (presence of definitions, examples, steps)
    - Length appropriateness (not too short, not too long)
    
    Args:
        chunk_text: The chunk content
        source_url: Source URL for domain reputation
    
    Returns:
        Quality score in range [0.0, 1.0], where:
        - 0.0-0.3: Low quality (consider discarding)
        - 0.3-0.6: Medium quality (acceptable)
        - 0.6-1.0: High quality (prioritize)
    """
    score = 0.5  # Start at neutral
    
    # Factor 1: Source domain reputation (+/- 0.2)
    from urllib.parse import urlparse
    domain = urlparse(source_url).netloc.lower()
    
    TRUSTED_EDU_DOMAINS = (
        "wikipedia.org", "britannica.com", "stanford.edu", "mit.edu",
        "arxiv.org", "geeksforgeeks.org", "healthline.com", "mayoclinic.org"
    )
    INFORMAL_SOURCES = (
        "wordpress.com", "blogspot.com", "medium.com"
    )
    
    if any(d in domain for d in TRUSTED_EDU_DOMAINS):
        score += 0.2
    elif any(d in domain for d in INFORMAL_SOURCES):
        score -= 0.1
    
    # Factor 2: Text structure quality (+/- 0.2)
    sentences = [s.strip() for s in re.split(r'[.!?]', chunk_text) if len(s.strip()) > 15]
    if len(sentences) >= 3:
        avg_sent_len = sum(len(s) for s in sentences) / len(sentences)
        if _CHUNK_SENT_LEN_MIN <= avg_sent_len <= _CHUNK_SENT_LEN_MAX:  # Good sentence length range
            score += 0.15
        else:
            score -= 0.05
    
    # Factor 3: Educational markers (+/- 0.2)
    edu_markers = re.compile(
        r'\b(definition|example|step|first|second|third|however|therefore|because)\b',
        re.IGNORECASE
    )
    marker_count = len(edu_markers.findall(chunk_text.lower()))
    if marker_count >= 3:
        score += 0.15
    elif marker_count == 0:
        score -= 0.1
    
    # Factor 4: Length appropriateness (+/- 0.1)
    length = len(chunk_text)
    if _CHUNK_SWEET_SPOT_MIN <= length <= _CHUNK_SWEET_SPOT_MAX:  # Sweet spot for chunks
        score += 0.1
    elif length < (_CHUNK_SWEET_SPOT_MIN // 2) or length > (_CHUNK_SWEET_SPOT_MAX * 1.67):
        score -= 0.1
    
    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))


def _llm_classify_chunk(text: str, query: str = "", content_type: str = "technical") -> bool:
    """
    LLM-based chunk classification with content-type specific filtering.
    
    Uses Groq Llama to classify chunks as KEEP or DISCARD. Applies stricter
    criteria for news articles, listings, and promotional content based on
    the content_type of the query.
    
    Design philosophy:
        - Bias toward KEEPING educational content (even from informal sources)
        - Strict rejection only for clear junk (news, listings, ads)
        - Fail-open on errors to avoid data loss
    
    Args:
        text: Text content to classify (first 800 chars used)
        query: Search query for relevance context (optional)
        content_type: One of "scholarly", "technical", "practical", "lifestyle"
    
    Returns:
        True if chunk should be KEPT, False if DISCARDED
    
    Content-Type Specific Rules:
        - scholarly: Reject news, blogs without analysis, opinion pieces
        - technical: Reject marketing, ads, news, product reviews
        - practical: Reject news, listings, directories WITHOUT instructions
        - lifestyle: Reject news, product reviews, ads WITHOUT techniques
    """
    # Content-type specific DISCARD criteria (examples, not exhaustive)
    discard_examples = {
        "scholarly": "news articles reporting events, personal blog opinions without analysis, forum discussions",
        "technical": "product marketing pages, software advertisements, news announcements about tech companies",
        "practical": "news articles about cooking trends, restaurant listings, equipment shopping guides",
        "lifestyle": "news about wellness trends, yoga studio directories, product reviews for yoga mats"
    }
    
    extra_discard = discard_examples.get(content_type, "")
    
    prompt = f"""You are evaluating a text chunk for educational content.

Query context: {query if query else "general educational content"}
Content type: {content_type}

DISCARD if the chunk is:
- News reporting (events, announcements, press releases)
- Directory listing ("Top 10 X", "Best Y in Z", address lists)
- Commercial content (ads, product pages, course enrollment forms)
- Navigation (menus, headers, footers)
- User reviews without educational substance
- Specific to {content_type}: {extra_discard}

KEEP if the chunk contains:
- Concept explanations, definitions, how things work
- Step-by-step instructions or procedures
- Technical documentation or specifications
- Practical advice with actionable information
- Academic analysis or research findings
- Educational content from any source (blogs/forums acceptable)

Priority:
1. News/journalism → DISCARD
2. Pure listings/directories → DISCARD
3. Pure advertising/enrollment → DISCARD
4. Has educational explanations → KEEP
5. Mixed content with educational portion → KEEP
6. Uncertain → KEEP

Examples:
DISCARD: "VnExpress reports yoga popularity increased 20%..."
KEEP: "Yoga breathing: 1) Ujjayi breath - constrict throat..."

DISCARD: "Top 10 restaurants: 1. Sushi Bar A (15 Hai Ba Trung)"
KEEP: "Top 5 techniques: 1. Julienne - cut into thin strips..."

Text chunk:
{text[:800]}

Reply with ONLY one word: KEEP or DISCARD"""
    
    try:
        llm = _get_chunk_classifier()
        response = rate_limited_invoke(
            llm,
            prompt,
            bucket="chat",
            metadata={
                "agent": "Retriever",
                "node": "retriever_node",
                "model": LLM_MODEL_CHEAP,
                "operation": "chunk_classifier",
            },
        )
        result = response.content.strip().upper() #type: ignore[attr-defined]
        
        # Extract decision from response (may include reasoning)
        if "KEEP" in result and "DISCARD" not in result:
            return True
        elif "DISCARD" in result and "KEEP" not in result:
            logger.debug(f"LLM DISCARD ({content_type}): '{text[:60]}'")
            return False
        else:
            # Ambiguous response - fail open
            logger.warning(f"Ambiguous LLM response '{result[:50]}' — keeping chunk (fail-open)")
            return True
    
    except Exception as e:
        logger.warning(f"LLM classification failed: {e} — keeping chunk (fail-open)")
        return True


def _get_retriever(collection_name: str = "dynamic_context", persist_directory: Any = None) -> Retriever:
    """
    Return the module-level Retriever singleton.

    Instantiates on first call; returns the cached instance on subsequent
    calls. Thread-safety is not guaranteed — safe for single-threaded
    LangGraph workflow only.
    """
    runtime_key = (
        collection_name,
        repr(chroma_vector_store_kwargs(persist_directory)),
        str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL),
        get_api_key("OPENAI_API_KEY", required=False),
    )
    if runtime_key not in _retriever_instances:
        _retriever_instances[runtime_key] = Retriever(
            collection_name=collection_name,
            persist_directory=persist_directory,
        )
    return _retriever_instances[runtime_key]


def release_retriever(collection_name: str = "dynamic_context") -> None:
    """Drop the cached retriever for a finished run's collection."""
    for key in list(_retriever_instances):
        if key[0] == collection_name:
            _retriever_instances.pop(key, None)


@tool
def retrieve_context_tool(
    query: str,
    content_type: str = "technical",
    collection_name: str = "dynamic_context",
    persist_directory: str = "",
    chunk_llm_filter_mode: str = "",
) -> str:
    """
    Retrieve relevant chunks from the knowledge base for a given query.
    Use this tool when you need more specific information about a topic
    to write better content. Returns formatted text chunks with source metadata.

    Args:
        query: Specific search query targeting the concept you need more info on.
        content_type: One of 'scholarly'|'technical'|'practical'|'lifestyle'
                      (default: 'technical'). Affects filtering strictness.

    Returns:
        Formatted string of retrieved chunks with source metadata.
    """
    logger.info(
        f"[TOOL CALL] retrieve_context_tool: '{query[:60]}' "
        f"(type={content_type}, collection={collection_name})"
    )
    return _get_retriever(collection_name, persist_directory).retrieve_context(
        query=query,
        k=RAG_TOOL_K,
        context_label="[TOOL CALL]",
        content_type=content_type,
        chunk_llm_filter_mode=chunk_llm_filter_mode or None,
    )


def retriever_node(state: AgentState) -> dict:
    """
    RetrieverNode: execute ChromaDB similarity search using the pre-formed
    retrieval_query from the QueryFormulator node.

    This is the second node in the CRAG pipeline:
        QueryFormulator → [RetrieverNode] → ContextEvaluator → ContentWriter

    Unlike the legacy perform_research() which builds its own query, this node
    receives a fully-formed query via state["retrieval_query"] and executes
    retrieval only — no query construction logic.

    State reads:
        retrieval_query — formed by QueryFormulator
        current_chapter_index, current_subsection_index — for log labels
        content_type — controls LLM chunk filtering strictness

    State writes:
        rag_context — formatted chunk string for ContextEvaluator
        messages    — milestone log entry

    Args:
        state: Current LangGraph workflow state.

    Returns:
        Partial state update dict.
    """
    logger.info("=" * 60)
    logger.info("NODE: RetrieverNode - Executing ChromaDB retrieval")
    logger.info("=" * 60)

    query        = state.get("retrieval_query", "")
    chap_idx     = state["current_chapter_index"]
    sub_idx      = state["current_subsection_index"]
    content_type = state.get("content_type", "technical")
    collection_name = state.get("rag_collection_name", "dynamic_context")
    persist_directory = state.get("rag_persist_dir", "")
    advanced_config = state.get("advanced_config", {}) or {}

    if not query:
        logger.warning("retrieval_query is empty — RetrieverNode skipped")
        return {"messages": ["⚠️ RetrieverNode: empty retrieval_query — skipped"]}

    try:
        display_number = get_section_location(
            state["curriculum"],
            chap_idx,
            sub_idx,
        )["display_number"]
    except Exception:
        display_number = f"{chap_idx + 1}.{sub_idx + 1}"
    context_label = f"[CRAG] Chapter {display_number}"

    try:
        retriever = _get_retriever(collection_name, persist_directory)
        retriever.reset_retrieved_ids()
        context = retriever.retrieve_context(
            query         = query,
            k             = RAG_INITIAL_K,
            context_label = context_label,
            content_type  = content_type,
            advanced_config = advanced_config,
        )

        prior_used = list(state.get("used_rag_queries", []))
        retrieval_attempts = int(state.get("rag_retrieval_attempts", 0) or 0) + 1

        if not context:
            return {
                "rag_context":      "",
                "used_rag_queries": prior_used + [query],
                "rag_retrieval_attempts": retrieval_attempts,
                "rag_source_audit": build_source_audit_summary(
                    "",
                    used_queries=prior_used + [query],
                    context_quality="insufficient",
                    chapter_index=chap_idx,
                    subsection_index=sub_idx,
                    discarded_chunks=retriever.last_retrieval_audit.get(
                        "discarded_chunks",
                        [],
                    ),
                ),
                "messages": ["⚠️ RetrieverNode: no chunks found for query"],
            }

        updated_used = prior_used + [query]
        return {
            "rag_context":      context,
            "used_rag_queries": updated_used,  # track all attempted retrieval queries
            "rag_retrieval_attempts": retrieval_attempts,
            "rag_source_audit": build_source_audit_summary(
                context,
                used_queries=updated_used,
                chapter_index=chap_idx,
                subsection_index=sub_idx,
                discarded_chunks=retriever.last_retrieval_audit.get(
                    "discarded_chunks",
                    [],
                ),
            ),
                "messages": [
                f"✓ RetrieverNode: retrieved context for Chapter {display_number} "
                f"(query: '{query[:50]}...') — see logs/rag_context.log"
            ],
        }

    except Exception as e:
        logger.error(f"RetrieverNode unexpected error: {e}", exc_info=True)
        return {
            "rag_context": "",
            "messages": [f"Error in RetrieverNode: {e}"],
        }
