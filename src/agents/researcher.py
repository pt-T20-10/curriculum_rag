"""
Researcher Agent for AI Textbook Generator.

This agent retrieves relevant document chunks from ChromaDB using semantic
similarity search based on the current subsection's search_query field.

It is called once per subsection iteration in the workflow loop:
    Researcher -> Writer -> Reviewer -> Illustrator -> [next subsection]

Performance note:
    ResearcherAgent is instantiated via a module-level lazy singleton
    (_get_researcher()) so that the ChromaDB client connection is created
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
from typing import Optional


from langchain_groq import ChatGroq
from src.config import GROQ_API_KEY
from langchain_core.tools import tool
import re
from src.config import CHROMA_DB_DIR, RAG_TOP_K, RAG_INITIAL_K, RAG_TOOL_K, get_embedding_model, _MIN_SUBSTANTIVE_SENTENCES, _MIN_AVG_SENTENCE_LEN
from langchain_chroma import Chroma
from src.graph.state import AgentState, Chapter, SubSection, get_chapter_and_subsection
from src.log_config import setup_logger

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")


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
            lines += [
                f"[Chunk {i}/{len(chunks)}] Source: {chunk['source']}",
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

class ResearcherAgent:
    """
    Researcher Agent: semantic similarity search over the ingested ChromaDB corpus.

    Responsibilities:
        - Maintain a single ChromaDB client connection (shared via singleton)
        - Perform top-k similarity search for a given subsection query
        - Format retrieved chunks with source metadata for the Writer's RAG context
        - Write full retrieval records to logs/rag_context.log for audit

    Instantiate via _get_researcher() rather than directly — this ensures the
    ChromaDB connection is reused across all subsection calls in the workflow.
    """

    def __init__(self) -> None:
        """
        Open a ChromaDB connection using the singleton embedding model.

        Uses get_embedding_model() which is itself lru_cache-cached, so the
        embedding model is loaded once per process regardless of how many
        ResearcherAgent instances are created.
        """
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=get_embedding_model(),
            collection_name="dynamic_context",
        )
        self._retrieved_ids: set[str] = set()


    def reset_retrieved_ids(self) -> None:
        """
        Reset retrieved chunk blacklist.
        Must be called before each new subsection to prevent
        cross-subsection blacklist contamination.
        """
        self._retrieved_ids.clear()
        logger.debug("Retrieved IDs blacklist reset")
    
    
    def retrieve_context(
        self,
        query:         str,
        k:             int  = RAG_TOP_K,
        context_label: str  = "",
        content_type:  str  = "technical",
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
            results = self.vector_db.max_marginal_relevance_search(
                query,
                k=k + len(self._retrieved_ids),
                fetch_k=(k + len(self._retrieved_ids)) * 4,
                lambda_mult=0.7,
            )

            # Dedup: chunk-level + source-level (unchanged)
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
                max_quota = 3 if any(d in source_url for d in _TRUSTED_EDU_DOMAINS) else 1

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

                if len(fresh_results) >= k:
                    break

            # ----------------------------------------------------------------
            # Post-retrieval quality filter — two layers:
            #   Layer 1: Structural heuristics (no API call, topic-agnostic)
            #   Layer 2: LLM binary classifier via Groq (free tier, fast)
            # Fails open progressively: if both layers are too aggressive,
            # falls back to heuristic-only, then to unfiltered results.
            # ----------------------------------------------------------------
            substantive = []
            for doc in fresh_results:
                text = doc.page_content

                # Layer 1 — fast structural heuristic (no API call)
                if not _is_substantive_chunk(text):
                    logger.debug(f"Heuristic DISCARD: '{text[:60]}'")
                    continue

                # Layer 2 — LLM classifier for chunks that passed heuristics
                # Pass query and content_type for context-aware filtering
                if not _llm_classify_chunk(text, query=query, content_type=content_type):
                    continue
                substantive.append(doc)
                
                 # Layer 2 — LLM classifier for chunks that passed heuristics
            # Pass query and content_type for context-aware filtering
                if not _llm_classify_chunk(text, query=query, content_type=content_type):
                    continue

            substantive.append(doc)

            filtered_count = len(fresh_results) - len(substantive)
            if filtered_count:
                logger.info(
                    f"Chunk quality filter: {len(fresh_results)} → {len(substantive)} "
                    f"({filtered_count} junk chunks removed)"
                )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # Layer 3 — Semantic deduplication + quality scoring
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            
            if substantive:
                # Convert to dict format for deduplication
                chunk_dicts = []
                for doc in substantive:
                    chunk_dicts.append({
                        'content': doc.page_content,
                        'source': doc.metadata.get('source', 'Unknown'),
                        'doc': doc  # Keep reference to original doc
                    })
                
                # Deduplicate semantically similar chunks
                deduped = _deduplicate_chunks_semantic(
                    chunk_dicts,
                    similarity_threshold=0.85,
                    embedding_model=self.vector_db._embedding_function
                )
                
                # Score quality and sort by confidence
                for chunk in deduped:
                    chunk['quality_score'] = _score_chunk_quality(
                        chunk['content'],
                        chunk['source']
                    )
                
                # Sort by quality score (descending) and take top k
                deduped.sort(key=lambda x: x['quality_score'], reverse=True)
                
                # Convert back to Document objects
                substantive = [c['doc'] for c in deduped[:k]]
                
                if len(deduped) > k:
                    logger.info(
                        f"Quality ranking: top {k} of {len(deduped)} chunks selected "
                        f"(avg score: {sum(c['quality_score'] for c in deduped[:k]) / k:.2f})"
                    )

            filtered_count = len(fresh_results) - len(substantive)
            if filtered_count:
                logger.info(
                    f"Chunk quality filter: {len(fresh_results)} → {len(substantive)} "
                    f"({filtered_count} junk chunks removed)"
                )

                # Fail-open tier 1: if Layer 2+3 over-filtered, fall back to Layer 1 only
            if not substantive and fresh_results:
                logger.warning(
                    "Layers 2+3 removed all chunks — "
                    "falling back to heuristic-only (Layer 1) results"
                )
                substantive = [
                    doc for doc in fresh_results
                    if _is_substantive_chunk(doc.page_content)
                ]

            # Fail-open tier 2: if ALL layers removed everything, keep unfiltered
            if not substantive and fresh_results:
                logger.warning(
                    "All 3 quality layers removed every chunk — "
                    "falling back to completely unfiltered results"
                )
                substantive = fresh_results

            results = substantive
    
            if not results:
                logger.warning(f"No fresh content found for query: '{query}'")
                return ""

            # Build chunk list (unchanged from here) ─────────────────────────
            chunks: list[dict] = []
            for doc in results:
                chunks.append({
                    "source":  doc.metadata.get("source", "Unknown"),
                    "content": doc.page_content,
                })

            entry_num = _get_rag_logger().log(
                query         = query,
                chunks        = chunks,
                context_label = context_label,
            )
            logger.info(
                f"Retrieved {len(chunks)} chunks "
                f"({sum(len(c['content']) for c in chunks)} chars) "
                f"— logged as RAG #{entry_num} in logs/rag_context.log"
            )

            formatted_content = ""
            for i, chunk in enumerate(chunks, 1):
                inline_content = chunk["content"].replace("\n", " ")
                formatted_content += (
                    f"Document {i} (Source: {chunk['source']}):\n"
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

_researcher_instance: Optional[ResearcherAgent] = None



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

_chunk_classifier: Optional[ChatGroq] = None


def _get_chunk_classifier() -> ChatGroq:
    """
    Return singleton Groq LLM instance for chunk classification.
    Instantiated lazily to avoid startup overhead.
    """
    global _chunk_classifier
    if _chunk_classifier is None:
        _chunk_classifier = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=GROQ_API_KEY,       # type: ignore[arg-type]
            temperature=0,
            max_tokens=10,              # Only needs "KEEP" or "DISCARD"
        )
    return _chunk_classifier


def _deduplicate_chunks_semantic(
    chunks: list[dict],
    similarity_threshold: float = 0.85,
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
        from src.config import get_embedding_model
        embedding_model = get_embedding_model()
    
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    
    # Batch encode all chunks
    texts = [c['content'][:500] for c in chunks]  # First 500 chars for speed
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
        if 40 <= avg_sent_len <= 200:  # Good sentence length range
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
    if 300 <= length <= 1500:  # Sweet spot for chunks
        score += 0.1
    elif length < 150 or length > 2500:
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
        response = llm.invoke(prompt)
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


def _get_researcher() -> ResearcherAgent:
    """
    Return the module-level ResearcherAgent singleton.

    Instantiates on first call; returns the cached instance on subsequent
    calls. Thread-safety is not guaranteed — this is safe for the single-
    threaded LangGraph workflow but should not be used from multiple threads
    without a lock.

    Returns:
        The shared ResearcherAgent instance.
    """
    global _researcher_instance
    if _researcher_instance is None:
        _researcher_instance = ResearcherAgent()
    return _researcher_instance
@tool
def retrieve_context_tool(query: str, content_type: str = "technical") -> str:
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
    logger.info(f"[TOOL CALL] retrieve_context_tool: '{query[:60]}' (type={content_type})")
    return _get_researcher().retrieve_context(
        query=query,
        k=RAG_TOOL_K,
        context_label="[TOOL CALL]",
        content_type=content_type,
    )
    
    
def perform_research(state: AgentState) -> dict:
    """
    Researcher node: retrieve RAG context for the current subsection.

    Reads curriculum position from state indexes, extracts the subsection's
    search_query, and performs a similarity search against ChromaDB.
    Passes a context_label to retrieve_context() so every RAG log entry
    is tagged with the chapter.subsection position for easy cross-reference.

    Workflow integration:
        Input:  state["curriculum"], state["current_chapter_index"],
                state["current_subsection_index"]
        Output (success):
                state["rag_context"]  — formatted chunk string for Writer
                state["messages"]     — milestone log entry
        Output (no results):
                state["messages"]     — warning; rag_context NOT written,
                                        Writer falls back to internal knowledge
        Output (error):
                state["messages"]     — error description

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict.
    """
    logger.info("=" * 60)
    logger.info("NODE: Researcher - Retrieving context")
    logger.info("=" * 60)

    curriculum = state["curriculum"]
    chap_idx   = state["current_chapter_index"]
    sub_idx    = state["current_subsection_index"]

    try:
        # Unified accessor — handles both Pydantic CurriculumOutline and dict
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

        chap_title = (
            chapter.title if isinstance(chapter, Chapter)
            else chapter.get("title", "Unknown")
        )
        sec_title = (
            subsection.title if isinstance(subsection, SubSection)
            else subsection.get("title", "Unknown")
        )
        query = (
            subsection.search_query if isinstance(subsection, SubSection)
            else subsection.get("search_query", f"{chap_title} - {sec_title}")
        )

        logger.info(f"Target: Chapter {chap_idx + 1}.{sub_idx + 1} - {sec_title}")
        logger.info(f"Query:  {query}")

        # Human-readable label written into the RAG log entry header.
        # Format: "Chapter 1.2 Ten muc" for cross-reference with other logs.
        context_label = f"Chapter {chap_idx + 1}.{sub_idx + 1} {sec_title}"

        # Extract content_type from curriculum if available
        curr_content_type = "technical"  # default
        try:
            if hasattr(curriculum, 'content_type'):
                curr_content_type = curriculum.content_type
            elif isinstance(curriculum, dict) and 'content_type' in curriculum:
                curr_content_type = curriculum['content_type']
        except:
            pass

        context = _get_researcher().retrieve_context(
            query         = query,
            k             = RAG_INITIAL_K,
            context_label = f"[INITIAL] {context_label}",
            content_type  = curr_content_type,
        )

        if not context:
            logger.warning("No context retrieved — Writer will use general knowledge")
            return {
                "messages": ["No specific context found. Using general knowledge."]
            }

        return {
            "rag_context": context,
            "messages": [
                f"✓ Retrieved context for: '{sec_title}' "
                f"(query: '{query[:40]}...') — see logs/rag_context.log"
            ],
        }

    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {"messages": ["Error: Invalid curriculum index"]}

    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {"messages": ["Error: Malformed curriculum structure"]}

    except Exception as e:
        logger.error(f"Unexpected error in Researcher: {e}", exc_info=True)
        return {"messages": ["Error retrieving context"]}