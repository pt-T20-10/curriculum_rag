"""
Web Crawler for AI Textbook Generator.

Deep crawls educational websites to extract text content:
- HTML pages: BeautifulSoup extraction + depth-1 internal link following
- PDF files: PyMuPDF (fitz) for accurate text extraction (fallback: pypdf)

Quality pipeline (applied before ChromaDB save):
1. is_quality_chunk()    — filter short/noisy chunks (< 200 chars, high non-alpha ratio)
2. Relevance scoring     — cosine similarity vs topic; discard chunks below threshold

This ensures ChromaDB stays dense and relevant rather than large and noisy.
"""

import time
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from typing import Any, List, Dict, Set, Optional

import requests
import concurrent.futures
import numpy as np
from bs4 import BeautifulSoup


from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from sklearn.metrics.pairwise import cosine_similarity
from app.ingestion.query_expansion import QueryExpansionAgent
from app.utils.log_config import setup_logger
from app.config import settings, get_embedding_model
from app.services.runtime_config import get_runtime_config
from app.services.api_rate_limiter import rate_limited_call
from app.utils import stop_signal

CHROMA_DB_DIR = settings.CHROMA_DB_DIR
CRAWL_MAX_WORKERS = settings.CRAWL_MAX_WORKERS
CRAWL_MAX_SUB_LINKS = settings.CRAWL_MAX_SUB_LINKS
MIN_CHUNK_CHARS = settings.MIN_CHUNK_CHARS
MIN_ALPHA_RATIO = settings.MIN_ALPHA_RATIO
MAX_DIGIT_RATIO = settings.MAX_DIGIT_RATIO
MIN_RELEVANCE_SCORE = settings.MIN_RELEVANCE_SCORE
MAX_CITATION_LINE_RATIO = settings.MAX_CITATION_LINE_RATIO
MAX_DUPLICATE_LINE_RATIO = settings.MAX_DUPLICATE_LINE_RATIO
MAX_BOOKING_SIGNALS = settings.MAX_BOOKING_SIGNALS
MAX_CHUNKS_PER_DOMAIN = settings.MAX_CHUNKS_PER_DOMAIN
CRAWL_MAX_DEPTH2_LINKS = settings.CRAWL_MAX_DEPTH2_LINKS
EMBEDDING_PROVIDER = settings.EMBEDDING_PROVIDER
VI_DOMAIN_CAP = settings.VI_DOMAIN_CAP
EN_DOMAIN_CAP = settings.EN_DOMAIN_CAP
UNLIMITED_CAP_DOMAINS = settings.UNLIMITED_CAP_DOMAINS
EMBEDDING_BATCH_SIZE = settings.EMBEDDING_BATCH_SIZE
CHUNK_SIZE = settings.CHUNK_SIZE
CHUNK_OVERLAP = settings.CHUNK_OVERLAP
MIN_EMBEDDED_UNIQUE_SOURCES = settings.MIN_EMBEDDED_UNIQUE_SOURCES
MIN_EMBEDDED_UNIQUE_DOMAINS = settings.MIN_EMBEDDED_UNIQUE_DOMAINS
TARGET_EMBEDDED_UNIQUE_SOURCES = settings.TARGET_EMBEDDED_UNIQUE_SOURCES
MAX_CHUNKS_PER_SOURCE_DEFAULT = settings.MAX_CHUNKS_PER_SOURCE_DEFAULT
MAX_CHUNKS_PER_PRIORITY_PDF = settings.MAX_CHUNKS_PER_PRIORITY_PDF
MAX_SINGLE_SOURCE_CHUNK_RATIO = settings.MAX_SINGLE_SOURCE_CHUNK_RATIO
CUSTOM_URL_DIRECT_SOURCE_CAP = settings.CUSTOM_URL_DIRECT_SOURCE_CAP
MIN_CITABLE_SOURCES = settings.MIN_CITABLE_SOURCES
MIN_RELEVANCE_BY_TYPE: dict[str, float] = {
    "scholarly": 0.30,
    "technical": 0.25,
    "practical": 0.22,
    "lifestyle": 0.22,
}

TEXTBOOK_PDF_SIGNAL_PATTERN = re.compile(
    r"\b(textbook|open\s+textbook|course\s+notes|lecture\s+notes|course\s+reader|"
    r"gi[aá]o\s+tr[ìi]nh|b[aà]i\s+gi[aả]ng)\b",
    re.IGNORECASE,
)
ADMINISTRATIVE_PDF_SIGNAL_PATTERN = re.compile(
    r"\b(registrar|bulletin|catalog|catalogue|plan\s+of\s+study|syllabus|"
    r"degree\s+requirements?|program\s+requirements?|press\s+kit|"
    r"curriculum\s+sheet)\b",
    re.IGNORECASE,
)

logger = setup_logger(name="Crawler", logfile="logs/crawler.log")


def _config_int(config: dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _source_url_for_chunk(chunk: Document) -> str:
    meta = chunk.metadata or {}
    return str(meta.get("source_url") or meta.get("source") or "unknown")


def _source_domain_for_chunk(chunk: Document) -> str:
    meta = chunk.metadata or {}
    source = _source_url_for_chunk(chunk)
    return urlparse(source).netloc.lower() or str(meta.get("domain") or "unknown")


def _is_direct_custom_url_chunk(chunk: Document) -> bool:
    meta = chunk.metadata or {}
    return str(meta.get("direct_custom_url", "")).lower() == "true"


def _runtime_diversity_config(runtime_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "MIN_EMBEDDED_UNIQUE_SOURCES": _config_int(
            runtime_config, "MIN_EMBEDDED_UNIQUE_SOURCES", MIN_EMBEDDED_UNIQUE_SOURCES, minimum=1
        ),
        "MIN_EMBEDDED_UNIQUE_DOMAINS": _config_int(
            runtime_config, "MIN_EMBEDDED_UNIQUE_DOMAINS", MIN_EMBEDDED_UNIQUE_DOMAINS, minimum=1
        ),
        "TARGET_EMBEDDED_UNIQUE_SOURCES": _config_int(
            runtime_config, "TARGET_EMBEDDED_UNIQUE_SOURCES", TARGET_EMBEDDED_UNIQUE_SOURCES, minimum=1
        ),
        "MAX_CHUNKS_PER_SOURCE_DEFAULT": _config_int(
            runtime_config, "MAX_CHUNKS_PER_SOURCE_DEFAULT", MAX_CHUNKS_PER_SOURCE_DEFAULT, minimum=1
        ),
        "MAX_CHUNKS_PER_PRIORITY_PDF": _config_int(
            runtime_config, "MAX_CHUNKS_PER_PRIORITY_PDF", MAX_CHUNKS_PER_PRIORITY_PDF, minimum=1
        ),
        "MAX_SINGLE_SOURCE_CHUNK_RATIO": max(
            0.01,
            min(1.0, _config_float(
                runtime_config, "MAX_SINGLE_SOURCE_CHUNK_RATIO", MAX_SINGLE_SOURCE_CHUNK_RATIO
            )),
        ),
        "CUSTOM_URL_DIRECT_SOURCE_CAP": _config_int(
            runtime_config, "CUSTOM_URL_DIRECT_SOURCE_CAP", CUSTOM_URL_DIRECT_SOURCE_CAP, minimum=1
        ),
        "MIN_CITABLE_SOURCES": _config_int(
            runtime_config, "MIN_CITABLE_SOURCES", MIN_CITABLE_SOURCES, minimum=1
        ),
    }


def _rate_limited_embed_query(embedding_model, query: str):
    if EMBEDDING_PROVIDER == "openai":
        model_name = str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL)
        return rate_limited_call(
            lambda: embedding_model.embed_query(query),
            bucket="embedding",
            model=model_name,
            metadata={"agent": "Crawler", "node": "ingestion"},
        )
    return embedding_model.embed_query(query)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}


_VI_DIACRITIC_PATTERN = re.compile(
    r'[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩị'
    r'òóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
    re.IGNORECASE,
)


def _detect_language(text: str) -> str:
    """Fast VI/EN language marker for retrieval audit metadata."""
    return "vi" if _VI_DIACRITIC_PATTERN.search(text[:500]) else "en"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_embedding_source_audit_record(
    *,
    topic: str,
    content_type: str,
    collection_name: str,
    run_id: str,
    chunks: List[Document],
    raw_chunk_count: int,
    quality_chunk_count: int,
    relevant_chunk_count: int,
    saved_chunk_count: int,
    config_snapshot: dict[str, Any] | None = None,
    diversity_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize final chunks that were written to ChromaDB, grouped by source."""
    source_groups: dict[str, list[Document]] = defaultdict(list)
    domain_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    trusted_chunk_count = 0
    priority_pdf_chunk_count = 0

    for chunk in chunks:
        meta = chunk.metadata or {}
        source = _source_url_for_chunk(chunk)
        domain = _source_domain_for_chunk(chunk)
        language = str(meta.get("language") or _detect_language(chunk.page_content))
        source_groups[source].append(chunk)
        domain_counts[domain] += 1
        language_counts[language] += 1
        if meta.get("trusted_source") == "true":
            trusted_chunk_count += 1
        if meta.get("source_quality") == "priority_textbook_pdf":
            priority_pdf_chunk_count += 1

    sources: list[dict[str, Any]] = []
    for source, source_chunks in sorted(
        source_groups.items(),
        key=lambda item: (-len(item[1]), item[0]),
    ):
        first_meta = source_chunks[0].metadata or {}
        scores = [
            score
            for score in (
                _safe_float((chunk.metadata or {}).get("relevance_score"))
                for chunk in source_chunks
            )
            if score is not None
        ]
        languages = Counter(
            str((chunk.metadata or {}).get("language") or _detect_language(chunk.page_content))
            for chunk in source_chunks
        )
        sources.append({
            "url": source,
            "domain": urlparse(source).netloc.lower() or first_meta.get("domain", ""),
            "type": first_meta.get("type", ""),
            "chunk_count": len(source_chunks),
            "languages": dict(languages),
            "avg_relevance_score": round(sum(scores) / len(scores), 4) if scores else None,
            "trusted_source": first_meta.get("trusted_source") == "true",
            "source_quality": first_meta.get("source_quality", ""),
            "cap_bypass_reason": first_meta.get("cap_bypass_reason", ""),
            "direct_custom_url": first_meta.get("direct_custom_url") == "true",
            "search_region": first_meta.get("search_region", ""),
            "source_query": first_meta.get("source_query", ""),
            "search_title": first_meta.get("search_title", ""),
        })

    total_chunks = len(chunks)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "collection_name": collection_name,
        "topic": topic,
        "content_type": content_type,
        "raw_chunk_count": raw_chunk_count,
        "quality_chunk_count": quality_chunk_count,
        "relevant_chunk_count_before_cap": relevant_chunk_count,
        "saved_chunk_count": saved_chunk_count,
        "final_chunk_count": total_chunks,
        "trusted_chunk_count": trusted_chunk_count,
        "trusted_chunk_ratio": round(trusted_chunk_count / total_chunks, 4) if total_chunks else 0.0,
        "priority_pdf_chunk_count": priority_pdf_chunk_count,
        "unique_sources": len(source_groups),
        "unique_domains": len(domain_counts),
        "language_counts": dict(language_counts),
        "config_snapshot": config_snapshot or {},
        "diversity_status": diversity_status or {},
        "top_domains": [
            {"domain": domain, "chunk_count": count}
            for domain, count in domain_counts.most_common(20)
        ],
        "sources": sources,
    }


def _write_embedding_source_audit(record: dict[str, Any]) -> None:
    """Append one ChromaDB embedding-source audit record as JSONL."""
    try:
        audit_path = settings.BASE_DIR / "logs" / "embedded_sources_audit.jsonl"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            "Embedded source audit written: %s "
            "(run_id=%s, sources=%s, trusted_ratio=%.1f%%)",
            audit_path,
            record.get("run_id"),
            record.get("unique_sources"),
            float(record.get("trusted_chunk_ratio") or 0.0) * 100,
        )
    except Exception as e:
        logger.warning("Could not write embedded source audit: %s", e)


def _has_textbook_pdf_signal(*parts: str) -> bool:
    haystack = " ".join(str(part or "") for part in parts)
    return bool(TEXTBOOK_PDF_SIGNAL_PATTERN.search(haystack))


def _has_administrative_pdf_signal(*parts: str) -> bool:
    haystack = " ".join(str(part or "") for part in parts)
    return bool(ADMINISTRATIVE_PDF_SIGNAL_PATTERN.search(haystack))


def _is_priority_textbook_pdf(
    url: str,
    text: str,
    metadata: dict[str, Any],
) -> bool:
    """Identify trusted full-textbook PDFs after extraction."""
    if not (urlparse(url).path.lower().endswith(".pdf") or metadata.get("type") == "pdf"):
        return False
    if metadata.get("trusted_source") != "true":
        return False
    if _has_administrative_pdf_signal(
        url,
        metadata.get("search_title", ""),
        metadata.get("source_query", ""),
        text[:5000],
    ):
        logger.info(
            "[PDF/NORMAL] %s is trusted but has administrative signals; "
            "not marking as priority textbook PDF",
            url[:100],
        )
        return False
    return _has_textbook_pdf_signal(
        url,
        metadata.get("search_title", ""),
        metadata.get("source_query", ""),
        text[:5000],
    )



# ---------------------------------------------------------------------------
# Quality filter helpers
# ---------------------------------------------------------------------------

def is_quality_chunk(text: str) -> bool:
    """
    Fast heuristic filter — no network/embedding call required.

    Rejects chunks that are:
    - Too short to contain meaningful content (< MIN_CHUNK_CHARS)
    - Dominated by non-alphabetic characters (binary artifacts, nav menus)
    - Dominated by digits (data tables, PDF stream metadata)
    - Bibliography/reference sections (duplicate lines + citation patterns)

    Args:
        text: Raw chunk text

    Returns:
        True if chunk passes quality heuristics, False if it should be discarded.
    """
    stripped = text.strip()

    # Check 1: minimum length
    if len(stripped) < MIN_CHUNK_CHARS:
        return False

    total = len(stripped)
    alpha = sum(1 for c in stripped if c.isalpha())
    digits = sum(1 for c in stripped if c.isdigit())

    # Check 2: alphabetic ratio (catches binary garbage, navigation links)
    if alpha / total < MIN_ALPHA_RATIO:
        return False

    # Check 3: digit ratio (catches PDF stream metadata, data dump tables)
    if digits / total > MAX_DIGIT_RATIO:
        return False

    # Check 4: bibliography/reference section detection
    lines = [l.strip() for l in stripped.split('\n') if l.strip()]
    if len(lines) >= 4:
        # Check 4a: duplicate line ratio
        # Bibliography sections repeat the same citation in different formats
        unique_lines = set(lines)
        if len(unique_lines) / len(lines) < (1 - MAX_DUPLICATE_LINE_RATIO):
            return False

        # Check 4b: citation pattern ratio
        citation_pattern = re.compile(
            r'\b(19|20)\d{2}\b.*?[:;]'
            r'|\d+\(\d+\):\d+'
            r'|doi:\s*10\.'
            r'|arXiv:\d{4}\.\d+'
            r'|pp\.\s*\d{1,4}'
            r'|et al[.,]'
            r'|In:\s+[A-Z]'
            r'|ISBN\s+[\d\-X]+'
            r'|Lưu trữ bản gốc'
            r'|Truy cập ngày \d+'
            r'|Nhà xuất bản'
            r'|\[\s*\d+\s*\]'
            r'|Retrieved\s+20\d{2}'
            r'|\^[\s\w]'
            r'|Archived from the original'   # ← Wikipedia citation footer
            r'|\{\{cite'                      # ← Wikipedia {{cite book}} template
            r'|CS1\s+maint'                   # ← Wikipedia CS1 maintenance tag
            r'|wikimedia\.org'                # ← Wikimedia internal links in refs
            r'|commons\.wikimedia'            # ← Commons links in refs
            ,
            re.IGNORECASE,
        )
        citation_lines = sum(
            1 for l in lines
            if citation_pattern.search(l)
        )
        if citation_lines / len(lines) > MAX_CITATION_LINE_RATIO:
            return False
     # Check 5: commercial/booking content detection
    # Enrollment pages slip through keyword filters because they mention
    # techniques, but their content is commercial, not educational
   
    booking_pattern = re.compile(
        r'\bpayment\b|\benroll|\bbook(?:ing)?\b|\btuition\b'
        r'|\bregister now\b|\bcontact us\b|\bcourse fee\b'
        r'|\bplace.*booking\b|\bavailable dates\b'
        r'|\bdress code\b|\bstudents must\b'
        r'|\bcertificate of attendance\b',
        re.IGNORECASE,
    )
    booking_hits = len(booking_pattern.findall(stripped))
    if booking_hits >= MAX_BOOKING_SIGNALS:
        return False
    
    # Check 6: High word repetition — navigation menus and breadcrumbs
    # Navigation menus repeat the same words across cascading subset lines.
    # Metric: if >60% of all words are repeated, content is likely navigational.
    # Generic check — applies to any domain, not topic-specific.
    if len(lines) >= 4:
        all_words  = [w for line in lines for w in line.lower().split() if len(w) > 2]
        if len(all_words) > 15:
            unique_words = set(all_words)
            word_diversity = len(unique_words) / len(all_words)
            if word_diversity < 0.4:
                return False


    # Check 7: Commercial/promotional content detection
    # Price patterns and CTAs appear in course catalog and e-commerce chunks
    # regardless of domain — domain-agnostic signal that fires on any source
    # selling courses, products, or services.
    commercial_pattern = re.compile(
    r'\$\s*\d+|\d+\s*USD|\d+\s*VNĐ'
    r'|\d+[\.,]\d+\s*₫'                    # 600.000 ₫
    r'|giá\s+(gốc|hiện\s+tại)'             # Giá gốc là, Giá hiện tại là
    r'|save\s+\d+\s*%|off\s+at\s+checkout'
    r'|add\s+to\s+cart|buy\s+now'
    r'|original\s+price|current\s+price'
    r'|lifetime\s+access|certificate\s+included'
    r'|verified\s+buyer',
    re.IGNORECASE,
)
    if len(commercial_pattern.findall(stripped)) >= 2:
        return False
    # Check 8: TOC / syllabus / chapter-listing detection
    # Chapter indexes, syllabi, and book listings consist of repeated
    # short topic-name lines with structural prefixes. These provide no
    # explanatory value as RAG context — LLM needs explanations, not
    # topic lists.
    #
    # Signal: high ratio of lines matching structural prefix patterns
    # (Chapter X, Week X, Unit X, Lecture X, etc.) AND short average
    # words-per-line — real prose has longer sentences.
    toc_prefix_pattern = re.compile(
        r'^(chapter|week|unit|lecture|section|module|part|topic|lesson|chương|bài|mục)'
        r'\s*[\d\.\-\:]+',
        re.IGNORECASE,
    )
    if len(lines) >= 4:
        toc_lines = sum(1 for l in lines if toc_prefix_pattern.match(l))
        toc_ratio = toc_lines / len(lines)

        words_per_line = len(stripped.split()) / len(lines)

        # TOC signature: structural prefix lines dominate AND lines are short
        if toc_ratio >= 0.3 and words_per_line < 12:
            return False

    return True

def compute_relevance_scores(
    chunks, 
    topic_emb, 
    embedding_model,
    progress_callback=None,
    embedding_batch_size: int | None = None,
):
    """
    Compute cosine similarity scores for chunks using batched encoding.
    
    Supports both OpenAI API-based and local HuggingFace embeddings with
    provider-specific optimizations:
    
    - OpenAI: Larger batches (500 chunks), concurrent requests, rate limit handling
    - Local:  Smaller batches (200 chunks), sequential processing
    
    Both providers support bilingual (Vietnamese + English) content equally well.
    
    Phase 2 optimization: Returns both scores and embeddings so ChromaDB can
    reuse the embeddings instead of re-encoding (saves 6+ minutes per run).
    
    Args:
        chunks: List of Document objects with page_content
        topic_emb: Pre-computed bilingual topic embedding (numpy array)
        embedding_model: LangChain embedding wrapper (OpenAI or HuggingFace)
        progress_callback: Optional callback(message: str) for UI updates
    
    Returns:
        Tuple of (scores, embeddings):
            - scores: List[float] - Cosine similarity scores vs topic
            - embeddings: List[List[float]] - Embedding vectors for ChromaDB reuse
    
    Performance:
        OpenAI (1000 chunks): ~170s (0.17s/chunk)
        Local  (1000 chunks): ~1393s (1.39s/chunk)
    """
    if not chunks:
        return [], []
    
    chunk_texts = [c.page_content for c in chunks]
    
    # ========================================================================
    # Provider-specific batch encoding
    # ========================================================================
    
    if EMBEDDING_PROVIDER == "openai":
        # OpenAI API: Large batches with rate limit handling
        all_embeddings = _embed_with_openai(
            chunk_texts, 
            embedding_model,
            progress_callback=progress_callback,
            batch_size=embedding_batch_size,
        )
    
    else:  # EMBEDDING_PROVIDER == "local"
        # Local bge-m3: Sequential batching
        all_embeddings = _embed_with_local(
            chunk_texts,
            embedding_model,
            progress_callback=progress_callback,
            batch_size=embedding_batch_size,
        )
    
    # ========================================================================
    # Compute similarities (same for both providers)
    # ========================================================================
    
    chunk_embeddings_np = np.array(all_embeddings)
    topic_emb_np = np.array(topic_emb).reshape(1, -1)
    
    similarities = cosine_similarity(chunk_embeddings_np, topic_emb_np)
    scores = similarities.flatten().tolist()
    
    return scores, all_embeddings


def _embed_with_openai(
    texts: List[str],
    embedding_model,
    progress_callback=None,
    batch_size: int | None = None,
) -> List[List[float]]:
    """
    Embed texts using OpenAI API with rate limit handling.
    
    OpenAI allows 3000 RPM (requests per minute) on tier 1, so we batch
    aggressively to minimize API calls. Each request can handle up to 2048
    tokens (~500 chunks of avg 300 chars each).
    
    Handles rate limits gracefully with exponential backoff retry.
    
    Args:
        texts: List of text strings to embed
        embedding_model: OpenAIEmbeddings instance
        progress_callback: Optional progress callback
    
    Returns:
        List of embedding vectors (1536 dimensions for text-embedding-3-small)
    """
    import time
    from openai import RateLimitError
    
    BATCH_SIZE = max(1, int(batch_size or 500))  # OpenAI can handle large batches efficiently
    all_embeddings = []
    
    logger.info(
        f"OpenAI embedding: {len(texts)} chunks in batches of {BATCH_SIZE}"
    )
    
    t_start = time.time()
    
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
        
        # Retry logic for rate limits
        max_retries = 3
        for attempt in range(max_retries):
            try:
                batch_embeddings = rate_limited_call(
                    lambda: embedding_model.embed_documents(batch),
                    bucket="embedding",
                    model=str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL),
                    metadata={"agent": "Crawler", "node": "ingestion"},
                )
                all_embeddings.extend(batch_embeddings)
                break  # Success
                
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(
                        f"Rate limit hit on batch {batch_num}, "
                        f"retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Rate limit exceeded after {max_retries} retries")
                    raise
        
        # Progress logging
        elapsed = time.time() - t_start
        processed = i + len(batch)
        
        logger.info(
            f"  Batch {batch_num}/{total_batches} done ({len(batch)} chunks) "
            f"[{elapsed:.1f}s elapsed, {processed}/{len(texts)} total]"
        )
        
        if progress_callback and (batch_num % 2 == 0 or processed == len(texts)):
            progress_callback(
                f"Embedding: {processed}/{len(texts)} chunks — {elapsed:.0f}s"
            )
    
    elapsed_total = time.time() - t_start
    logger.info(
        f"✓ OpenAI embedding complete: {len(texts)} chunks in {elapsed_total:.1f}s "
        f"(avg {elapsed_total/len(texts):.2f}s/chunk)"
    )
    
    return all_embeddings


def _embed_with_local(
    texts: List[str],
    embedding_model,
    progress_callback=None,
    batch_size: int | None = None,
) -> List[List[float]]:
    """
    Embed texts using local bge-m3 model with sequential batching.
    
    Local model runs on CPU, so we use smaller batches to avoid memory
    overflow and process sequentially (no concurrency).
    
    Args:
        texts: List of text strings to embed
        embedding_model: HuggingFaceEmbeddings instance (bge-m3)
        progress_callback: Optional progress callback
    
    Returns:
        List of embedding vectors (1024 dimensions for bge-m3)
    """
    import time
    from app.config import settings
    
    BATCH_SIZE = max(1, int(batch_size or settings.EMBEDDING_BATCH_SIZE))
    all_embeddings = []
    
    logger.info(
        f"Local embedding (bge-m3): {len(texts)} chunks in batches of {BATCH_SIZE}"
    )
    
    t_start = time.time()
    
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
        
        batch_embeddings = embedding_model.embed_documents(batch)
        all_embeddings.extend(batch_embeddings)
        
        # Progress logging
        elapsed = time.time() - t_start
        processed = i + len(batch)
        
        logger.info(
            f"  Batch {batch_num}/{total_batches} done ({len(batch)} chunks) "
            f"[{elapsed:.1f}s elapsed, {processed}/{len(texts)} total]"
        )
        
        if progress_callback and (batch_num % 2 == 0 or processed == len(texts)):
            progress_callback(
                f"Embedding: {processed}/{len(texts)} chunks — {elapsed:.0f}s"
            )
    
    elapsed_total = time.time() - t_start
    logger.info(
        f"✓ Local embedding complete: {len(texts)} chunks in {elapsed_total:.1f}s "
        f"(avg {elapsed_total/len(texts):.2f}s/chunk)"
    )
    
    return all_embeddings


def _score_chunks_heuristic(chunks: List[Document]) -> List[tuple]:
    """
    Fast heuristic scoring for pre-filtering chunks before embedding.
    
    Uses configurable weights from settings to score chunks based on:
    - Chunk length appropriateness
    - Source domain reputation
    - Text structure quality
    - Educational content markers
    
    Args:
        chunks: List of Document objects
    
    Returns:
        List of (chunk, score) tuples, score in [0.0, 1.0]
    """
    from urllib.parse import urlparse
    import re
    from app.config import settings
    
    # Load weights from config
    WEIGHT_LENGTH = settings.HEURISTIC_LENGTH_WEIGHT
    WEIGHT_DOMAIN = settings.HEURISTIC_DOMAIN_WEIGHT
    WEIGHT_STRUCTURE = settings.HEURISTIC_STRUCTURE_WEIGHT
    WEIGHT_EDUCATION = settings.HEURISTIC_EDUCATION_WEIGHT
    
    vi_pattern = re.compile(
        r'[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
        re.IGNORECASE
    )
    
    scored = []
    vi_count = 0
    en_count = 0
    
    for chunk in chunks:
        score = 0.5  # Neutral baseline
        text = chunk.page_content
        source = chunk.metadata.get('source', '')
        
        # Factor 1: Length appropriateness
        length = len(text)
        if 400 <= length <= 1500:
            score += WEIGHT_LENGTH
        elif 200 <= length < 400 or 1500 < length <= 2000:
            score += WEIGHT_LENGTH * 0.5
        elif length < 150 or length > 2500:
            score -= WEIGHT_LENGTH
        
        # Factor 2: Source domain reputation
        domain = urlparse(source).netloc.lower()
        
        TRUSTED_DOMAINS = (
            'wikipedia.org', 'arxiv.org', 'stanford.edu', 'mit.edu',
            'geeksforgeeks.org', 'britannica.com', '.edu', '.gov',
            'vinuni.edu.vn', 'machinelearningcoban', 'topdev.vn',
            'pmc.ncbi.nlm.nih.gov'
        )
        INFORMAL_SOURCES = (
            'wordpress.com', 'blogspot.com', 'medium.com'
        )
        
        if any(d in domain for d in TRUSTED_DOMAINS):
            score += WEIGHT_DOMAIN
        elif any(d in domain for d in INFORMAL_SOURCES):
            score -= WEIGHT_DOMAIN * 0.4
        
        # Factor 3: Text structure quality
        sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 20]
        if len(sentences) >= 3:
            avg_sent_len = sum(len(s) for s in sentences) / len(sentences)
            if 40 <= avg_sent_len <= 200:
                score += WEIGHT_STRUCTURE
            else:
                score -= WEIGHT_STRUCTURE * 0.3
        
        # Factor 4: Educational markers
        edu_markers = re.compile(
            r'\b(definition|example|step|algorithm|theorem|proof|formula|method|'
            r'concept|principle|technique|approach|strategy|'
            r'định nghĩa|ví dụ|bước|thuật toán|định lý|chứng minh|công thức|'
            r'phương pháp|khái niệm|nguyên lý|kỹ thuật|cách tiếp cận|chiến lược)\b',
            re.IGNORECASE
        )
        marker_count = len(edu_markers.findall(text.lower()))
        if marker_count >= 2:
            score += WEIGHT_EDUCATION
        elif marker_count == 0:
            score -= WEIGHT_EDUCATION * 0.7
        
        # Track language diversity
        is_vi = bool(vi_pattern.search(text[:500]))
        if is_vi:
            vi_count += 1
        else:
            en_count += 1
        
        # Clamp to [0.0, 1.0]
        score = max(0.0, min(1.0, score))
        scored.append((chunk, score))
    
    logger.info(
        f"Heuristic scoring complete: {len(chunks)} chunks "
        f"({vi_count} VI [{vi_count/len(chunks)*100:.1f}%], "
        f"{en_count} EN [{en_count/len(chunks)*100:.1f}%])"
    )
    
    return scored



# ============================================================================
# WORKER FUNCTION (runs in separate process)
# ============================================================================

def _embed_batch_worker(chunk_texts: list, batch_size: int, worker_id: int, total_workers: int) -> list:
    """
    Worker function for ProcessPoolExecutor - embeds a batch of chunks.
    
    Runs in separate process with own memory space. Loads embedding model
    fresh in this process (no shared state).
    
    Args:
        chunk_texts: List of text strings to embed
        batch_size: Process this many chunks at a time
        worker_id: Worker index (for logging)
        total_workers: Total number of workers
    
    Returns:
        List of embedding vectors (same length as chunk_texts)
    """
    import time
    from app.config import settings, get_embedding_model
    from app.services.api_rate_limiter import rate_limited_call
    
    # Load model fresh in this worker process
    embedding_model = get_embedding_model()
    
    logger.info(f"[Worker {worker_id + 1}/{total_workers}] Starting: {len(chunk_texts)} chunks")
    
    embeddings = []
    start_time = time.time()
    
    # Process in smaller batches to manage memory
    for i in range(0, len(chunk_texts), batch_size):
        batch = chunk_texts[i:i + batch_size]
        try:
            if settings.EMBEDDING_PROVIDER == "openai":
                batch_emb = rate_limited_call(
                    lambda: embedding_model.embed_documents(batch),
                    bucket="embedding",
                    model=str(get_runtime_config("OPENAI_EMBEDDING_MODEL", required=False) or settings.OPENAI_EMBEDDING_MODEL),
                    metadata={
                        "agent": "CrawlerWorker",
                        "node": "embedding_worker",
                    },
                )
            else:
                batch_emb = embedding_model.embed_documents(batch)
            embeddings.extend(batch_emb)
            
            # Log progress
            elapsed = time.time() - start_time
            logger.info(
                f"[Worker {worker_id + 1}/{total_workers}] "
                f"Progress: {len(embeddings)}/{len(chunk_texts)} chunks "
                f"[{elapsed:.1f}s elapsed]"
            )
        except Exception as e:
            logger.error(f"[Worker {worker_id + 1}] Batch failed: {e}")
            # Fill with zeros as fallback
            embedding_dim = 1024  # bge-m3 dimension
            embeddings.extend([[0.0] * embedding_dim] * len(batch))
    
    elapsed_total = time.time() - start_time
    logger.info(
        f"[Worker {worker_id + 1}/{total_workers}] Complete: "
        f"{len(chunk_texts)} chunks in {elapsed_total:.1f}s"
    )
    
    return embeddings

def _compute_bilingual_stats(chunks: List[Document]) -> dict:
    """
    Compute bilingual distribution statistics for demonstration purposes.
    
    Detects chunk language by searching for Vietnamese diacritics in text.
    This is a fast heuristic that works well for Vietnamese vs English
    classification without requiring language detection models.
    
    Args:
        chunks: List of Document objects from crawler
    
    Returns:
        Dictionary containing:
            - total_chunks: Total number of chunks
            - vi_chunks: Count of Vietnamese chunks
            - en_chunks: Count of English chunks
            - vi_ratio: Ratio of Vietnamese chunks (0.0 to 1.0)
            - en_ratio: Ratio of English chunks (0.0 to 1.0)
            - top_vi_sources: Top 3 Vietnamese source URLs
            - top_en_sources: Top 3 English source URLs
    
    Example output:
        {
            'total_chunks': 1598,
            'vi_chunks': 560,
            'en_chunks': 1038,
            'vi_ratio': 0.35,
            'en_ratio': 0.65,
            'top_vi_sources': ['vi.wikipedia.org', 'vinuni.edu.vn', 'topdev.vn'],
            'top_en_sources': ['arxiv.org', 'geeksforgeeks.org', 'stanford.edu']
        }
    """
    from collections import Counter
    import re
    
    # Vietnamese diacritic characters
    # Presence of these indicates Vietnamese text with high confidence
    vi_pattern = re.compile(
        r'[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
        re.IGNORECASE
    )
    
    vi_chunks = []
    en_chunks = []
    
    for chunk in chunks:
        # Sample first 500 chars for speed (sufficient for language detection)
        text_sample = chunk.page_content[:500]
        
        if vi_pattern.search(text_sample):
            vi_chunks.append(chunk)
        else:
            en_chunks.append(chunk)
    
    # Extract top source domains per language
    vi_sources = Counter([
        chunk.metadata.get('source', '') 
        for chunk in vi_chunks
    ]).most_common(5)
    
    en_sources = Counter([
        chunk.metadata.get('source', '') 
        for chunk in en_chunks
    ]).most_common(5)
    
    total = len(chunks)
    stats = {
        'total_chunks': total,
        'vi_chunks': len(vi_chunks),
        'en_chunks': len(en_chunks),
        'vi_ratio': len(vi_chunks) / total if total > 0 else 0.0,
        'en_ratio': len(en_chunks) / total if total > 0 else 0.0,
        'top_vi_sources': [s[0] for s in vi_sources[:3]],
        'top_en_sources': [s[0] for s in en_sources[:3]],
    }
    
    return stats




def _apply_domain_diversity_cap(
    chunks: List[Document],
    max_per_domain: int,
) -> List[Document]:
    """
    Language-aware per-domain chunk caps with academic whitelist.
    
    Strategy:
    1. Unlimited cap for verified academic domains  
    2. Language-aware caps: VI domains get 50, EN domains get 35
    3. Fallback to base cap for unclassified
    
    Args:
        chunks: Relevance-filtered chunks (with scores)
        max_per_domain: Base cap (fallback, typically 25)
    
    Returns:
        Capped chunk list preserving bilingual balance
    """
    
    # Vietnamese detection pattern
    vi_pattern = re.compile(
        r'[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
        re.IGNORECASE
    )
    
    domain_counts: dict[str, int] = {}
    capped: List[Document] = []
    
    # Track stats for logging
    vi_count = 0
    en_count = 0
    unlimited_domains = set()
    
    for chunk in chunks:
        source = chunk.metadata.get("source", "")
        raw_domain = urlparse(source).netloc.lower()
        
        # Normalize mobile subdomains
        domain = re.sub(
            r'^([a-z]{2,3}\.)?m\.',
            lambda m: m.group(1) or '',
            raw_domain,
        )

        if chunk.metadata.get("source_quality") == "priority_textbook_pdf":
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            capped.append(chunk)
            unlimited_domains.add(domain)
            continue
        
        # Determine cap for this domain
        if any(trusted in domain for trusted in UNLIMITED_CAP_DOMAINS):
            max_for_domain = float('inf')
            cap_type = "unlimited"
            unlimited_domains.add(domain)
        else:
            # Detect language via chunk content
            text_sample = chunk.page_content[:500]
            is_vi = bool(vi_pattern.search(text_sample))
            
            if is_vi:
                max_for_domain = VI_DOMAIN_CAP
                cap_type = "vi"
                vi_count += 1
            else:
                max_for_domain = EN_DOMAIN_CAP
                cap_type = "en"
                en_count += 1
        
        # Apply cap
        current = domain_counts.get(domain, 0)
        if current < max_for_domain:
            domain_counts[domain] = current + 1
            capped.append(chunk)
    
    # Logging
    removed = len(chunks) - len(capped)
    if removed > 0:
        # Count domains by cap type
        vi_domains = sum(1 for d, c in domain_counts.items() 
                        if d not in unlimited_domains and c >= VI_DOMAIN_CAP)
        en_domains = sum(1 for d, c in domain_counts.items() 
                        if d not in unlimited_domains and c >= EN_DOMAIN_CAP)
        
        top_domains = sorted(domain_counts.items(), key=lambda x: -x[1])[:8]
        
        logger.info(
            f"Domain diversity cap: {len(chunks)} → {len(capped)} chunks ({removed} removed)"
        )
        logger.info(
            f"  Cap types: {len(unlimited_domains)} unlimited, "
            f"{vi_domains} VI-capped, {en_domains} EN-capped"
        )
        logger.info(
            f"  Top domains: {[f'{d}={c}' for d, c in top_domains]}"
        )
    
    # Bilingual distribution logging
    vi_final = sum(1 for c in capped 
                   if vi_pattern.search(c.page_content[:500]))
    en_final = len(capped) - vi_final
    
    logger.info(
        f"✓ Bilingual distribution (pre-cap): {vi_count} VI ({vi_count/len(chunks)*100:.1f}%) + "
        f"{en_count} EN ({en_count/len(chunks)*100:.1f}%)"
    )
    logger.info(
        f"  Top VI sources: {[chunk.metadata.get('source', '')[:60] for chunk in chunks[:3] if vi_pattern.search(chunk.page_content[:500])][:3]}"
    )
    logger.info(
        f"  Top EN sources: {[chunk.metadata.get('source', '')[:60] for chunk in chunks[:3] if not vi_pattern.search(chunk.page_content[:500])][:3]}"
    )
    logger.info(
        f"✓ Final ChromaDB corpus: {len(capped)} chunks "
        f"({vi_final} VI [{vi_final/len(capped)*100:.1f}%], "
        f"{en_final} EN [{en_final/len(capped)*100:.1f}%])"
    )
    
    return capped


def _chunk_relevance(chunk: Document) -> float:
    return _safe_float((chunk.metadata or {}).get("relevance_score")) or 0.0


def _apply_source_diversity_controls(
    chunks: List[Document],
    runtime_config: dict[str, Any],
) -> tuple[List[Document], dict[str, Any]]:
    """
    Cap dominant individual sources after relevance filtering.

    Domain caps prevent one host from dominating; this source-level pass prevents
    one large PDF or HTML page from dominating the final Chroma corpus.
    """
    if not chunks:
        return [], {}

    cfg = _runtime_diversity_config(runtime_config)
    by_source: dict[str, list[Document]] = defaultdict(list)
    for chunk in chunks:
        by_source[_source_url_for_chunk(chunk)].append(chunk)

    per_source_limited: dict[str, list[Document]] = {}
    removed_by_source_cap = 0
    source_cap_details: list[dict[str, Any]] = []

    for source, source_chunks in by_source.items():
        sorted_chunks = sorted(source_chunks, key=_chunk_relevance, reverse=True)
        first = sorted_chunks[0]
        if _is_direct_custom_url_chunk(first):
            cap = int(cfg["CUSTOM_URL_DIRECT_SOURCE_CAP"])
            cap_type = "direct_custom_url"
        elif (first.metadata or {}).get("source_quality") == "priority_textbook_pdf":
            cap = int(cfg["MAX_CHUNKS_PER_PRIORITY_PDF"])
            cap_type = "priority_textbook_pdf"
        else:
            cap = int(cfg["MAX_CHUNKS_PER_SOURCE_DEFAULT"])
            cap_type = "default"

        kept = sorted_chunks[:cap]
        per_source_limited[source] = kept
        removed = max(0, len(sorted_chunks) - len(kept))
        removed_by_source_cap += removed
        if removed:
            source_cap_details.append({
                "source": source,
                "cap_type": cap_type,
                "cap": cap,
                "before": len(sorted_chunks),
                "after": len(kept),
                "removed": removed,
            })

    ratio = float(cfg["MAX_SINGLE_SOURCE_CHUNK_RATIO"])
    removed_by_ratio_cap = 0
    ratio_cap_details: list[dict[str, Any]] = []

    for source, kept in list(per_source_limited.items()):
        if not kept or _is_direct_custom_url_chunk(kept[0]):
            continue
        total = sum(len(group) for group in per_source_limited.values())
        current = len(kept)
        if total <= 0 or current / total <= ratio:
            continue
        other_count = total - current
        if other_count <= 0:
            continue
        allowed = max(1, int((other_count * ratio) / max(0.01, 1.0 - ratio)))
        allowed = min(current, allowed)
        if allowed < current:
            per_source_limited[source] = kept[:allowed]
            removed = current - allowed
            removed_by_ratio_cap += removed
            ratio_cap_details.append({
                "source": source,
                "ratio": round(current / total, 4),
                "max_ratio": ratio,
                "before": current,
                "after": allowed,
                "removed": removed,
            })

    kept_ids = {id(chunk) for group in per_source_limited.values() for chunk in group}
    capped = [chunk for chunk in chunks if id(chunk) in kept_ids]
    source_counts = Counter(_source_url_for_chunk(chunk) for chunk in capped)
    domain_counts = Counter(_source_domain_for_chunk(chunk) for chunk in capped)

    status = {
        "unique_sources": len(source_counts),
        "unique_domains": len(domain_counts),
        "min_unique_sources": cfg["MIN_EMBEDDED_UNIQUE_SOURCES"],
        "min_unique_domains": cfg["MIN_EMBEDDED_UNIQUE_DOMAINS"],
        "target_unique_sources": cfg["TARGET_EMBEDDED_UNIQUE_SOURCES"],
        "min_citable_sources": cfg["MIN_CITABLE_SOURCES"],
        "meets_min_sources": len(source_counts) >= int(cfg["MIN_EMBEDDED_UNIQUE_SOURCES"]),
        "meets_min_domains": len(domain_counts) >= int(cfg["MIN_EMBEDDED_UNIQUE_DOMAINS"]),
        "removed_by_source_cap": removed_by_source_cap,
        "removed_by_ratio_cap": removed_by_ratio_cap,
        "source_cap_details": source_cap_details[:20],
        "ratio_cap_details": ratio_cap_details[:20],
    }
    warnings = []
    if not status["meets_min_sources"]:
        warnings.append(
            "Final corpus has fewer unique sources than configured minimum; "
            "workflow will continue best-effort."
        )
    if not status["meets_min_domains"]:
        warnings.append(
            "Final corpus has fewer unique domains than configured minimum; "
            "workflow will continue best-effort."
        )
    status["warnings"] = warnings

    if removed_by_source_cap or removed_by_ratio_cap:
        logger.info(
            "Source diversity controls: %s → %s chunks "
            "(source_cap_removed=%s, ratio_cap_removed=%s)",
            len(chunks),
            len(capped),
            removed_by_source_cap,
            removed_by_ratio_cap,
        )
    if warnings:
        logger.warning(
            "Source diversity warning: sources=%s/%s, domains=%s/%s",
            status["unique_sources"],
            status["min_unique_sources"],
            status["unique_domains"],
            status["min_unique_domains"],
        )

    return capped, status
# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(url: str) -> str:
    """
    Download and extract text from a PDF using PyMuPDF (fitz).
    Falls back to pypdf if fitz is not installed.

    PyMuPDF produces significantly cleaner output than pypdf for:
    - Multi-column layouts
    - PDFs with embedded fonts
    - Scanned PDFs with text layers

    Args:
        url: Direct URL to the PDF file

    Returns:
        Extracted plain text string, or "" on failure.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            logger.warning(f"PDF download failed ({response.status_code}): {url[:60]}")
            return ""

        pdf_bytes = response.content

        # Primary: PyMuPDF
        try:
            import fitz  # type: ignore
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_text = []
            for page in doc:
                page_text = page.get_text() # type: ignore
                if page_text.strip(): # type: ignore
                    pages_text.append(page_text)
            doc.close()
            text = "\n".join(pages_text)
            logger.info(f"[PDF/fitz] {url[:60]} ({len(text)} chars, {len(pages_text)} pages)")
            return text

        except ImportError:
            # Fallback: pypdf (less accurate but always available)
            logger.warning("PyMuPDF (fitz) not installed — falling back to pypdf. "
                           "Install with: pip install pymupdf")
            from pypdf import PdfReader
            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)
            pages_text = []
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    pages_text.append(extracted)
            text = "\n".join(pages_text)
            logger.info(f"[PDF/pypdf] {url[:60]} ({len(text)} chars)")
            return text

    except Exception as e:
        logger.warning(f"PDF extraction failed for {url[:60]}: {e}")
        return ""


# ---------------------------------------------------------------------------
# HTML crawling helpers
# ---------------------------------------------------------------------------

def get_internal_links(
    soup: BeautifulSoup,
    base_url: str,
    limit: int = 5,
) -> List[str]:
    """
    Find internal links (same domain) for depth-1 crawling.

    Focuses on the main content area (article/main/body) to avoid
    harvesting navigation and footer links.

    Args:
        soup:     BeautifulSoup object of the root page
        base_url: URL of the root page (used for domain comparison)
        limit:    Maximum number of sub-links to return

    Returns:
        List of absolute URLs on the same domain as base_url.
    """
    internal_links: Set[str] = set()
    domain = urlparse(base_url).netloc

    content_area = soup.find("article") or soup.find("main") or soup.find("body")
    if not content_area:
        return []

    for a_tag in content_area.find_all("a", href=True):
        href_attr = a_tag.get("href")
        if not isinstance(href_attr, str):
            continue

        full_url = urljoin(base_url, href_attr)
        parsed   = urlparse(full_url)

        # Must be same domain
        if parsed.netloc != domain:
            continue

        # Skip anchors, login, search, and other noise paths
        skip_patterns = (
            "#", "login", "register", "tag", "search",
            "cart", "logout", "signup", "rss", "feed",
            "privacy", "terms", "about", "contact",  
            "cookie", "booking", "enroll", "checkout",
            "trai-nghiem", "dang-ky",
        )
        if any(p in full_url for p in skip_patterns):
            continue

        # Only HTML or extensionless paths
        path = parsed.path.lower()
        if path.endswith(".pdf") or "." not in path or path.endswith(".html"):
            internal_links.add(full_url)
            if len(internal_links) >= limit:
                break

    return list(internal_links)


def fetch_text_from_url(url: str) -> tuple[str, Optional[BeautifulSoup]]:
    """
    Fetch and extract text from an HTML page.

    Strips noise tags (script, style, nav, footer, etc.) then extracts
    text from semantic content tags (h1-h3, p, li, pre, code).
    TOC header lines are removed via clean_toc_lines() to preserve prose
    descriptions while discarding structural navigation entries.

    Args:
        url: HTML page URL

    Returns:
        Tuple of (extracted_text, BeautifulSoup_object).
        Returns ("", None) on any error.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return "", None

        soup = BeautifulSoup(response.content, "html.parser")

        # Remove noise elements
        for tag in soup([
            "script", "style", "nav", "footer", "header",
            "aside", "form", "iframe", "noscript", "ads",
        ]):
            tag.decompose()

        # Extract meaningful text from semantic tags
        text_parts = []
        for tag in soup.find_all(["h1", "h2", "h3", "p", "li", "pre", "code"]):
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 30:  # ignore very short snippets (nav items, etc.)
                text_parts.append(text)

        raw_text = "\n\n".join(text_parts)
        cleaned  = clean_toc_lines(raw_text)  # ← strip TOC header lines, keep prose
        return cleaned, soup

    except Exception as e:
        logger.debug(f"Failed to fetch {url[:60]}: {e}")
        return "", None

# Minimum character count for a root page to be considered a content page.
# Pages below this threshold are likely homepages or navigation pages.
MIN_ROOT_CONTENT_CHARS = 1500

# Minimum ratio of long lines (> 80 chars) in a content page.
# Navigation pages consist mostly of short link texts.
MIN_LONG_LINE_RATIO = 0.15

# Minimum ratio of lines ending with sentence punctuation.
# Prose-heavy pages have many sentence-ending lines; nav pages do not.
MIN_SENTENCE_PUNCT_RATIO = 0.08

# Minimum word diversity ratio (unique words / total words).
# Navigation menus repeat the same anchor texts; content pages are diverse.
MIN_WORD_DIVERSITY_RATIO = 0.45


# ---------------------------------------------------------------------------
# Page-level classifier — three-way classification replacing _is_content_page().
#
# Three outcomes determine how each crawled page is processed:
#   EDUCATIONAL → store page content + crawl sublinks
#   NAVIGATION  → skip page content, crawl sublinks (may link to good content)
#   JUNK        → skip page content AND skip sublinks entirely
#
# Content-type aware: what counts as "educational" differs per domain.
#   scholarly/technical → formal prose, definitions, analysis
#   practical           → step-by-step instructions, numbered guides
#   lifestyle           → technique descriptions, health/wellness content
# ---------------------------------------------------------------------------

_PAGE_EDUCATIONAL = "educational"
_PAGE_NAVIGATION  = "navigation"
_PAGE_JUNK        = "junk"

# Promotional / commercial language — topic-agnostic, fires across all domains.
# Covers both VI and EN patterns.
_PROMO_PATTERN = re.compile(
    r'miễn phí|free download|tải ngay|click here|đăng ký ngay'
    r'|enroll now|sign up|get started|join now|buy now'
    r'|giảm giá|khuyến mãi|ưu đãi|coupon|discount'
    r'|thay vì tốn tiền|hoàn toàn có thể tận dụng'
    r'|top \d+ (best|tốt nhất|hay nhất)'
    r'|recommended for you|you might also like'
    r'|limited time offer|act now|claim your',
    re.IGNORECASE,
)

# Personal blog / course review language — opinions without instructions.
_REVIEW_PATTERN = re.compile(
    r'thầy\s+\w+\s+(dạy|giảng)|cô\s+\w+\s+(dạy|giảng)'
    r'|nếu bạn học\s+(thầy|cô)\s+\w+'
    r'|học\s+(thầy|cô)\s+\w+\s+thì'       
    r'|nếu bạn học\s+thầy|nếu bạn học\s+cô'
    r'|theo (mình|tôi|cá nhân mình)'
    r'|mình nghĩ|mình thấy|kinh nghiệm (của mình|bản thân)'
    r'|review (môn|khóa học)|chia sẻ kinh nghiệm học'
    r'|in my (opinion|experience)|i (think|feel|believe)'
    r'|my favorite|personally i|from my experience',
    re.IGNORECASE,
)

# Login-gated content — page requires authentication to view content.
_LOGIN_PATTERN = re.compile(
    r'đăng nhập để (xem|tải|đọc|truy cập)'
    r'|vui lòng đăng nhập|please (log in|sign in)'
    r'|login to (view|download|read|access)'
    r'|nội dung chỉ dành cho thành viên|members only'
    r'|create (a free )?account to|sign up to (access|view)',
    re.IGNORECASE,
)

# Step-by-step instruction markers — strong EDUCATIONAL signal for practical/lifestyle.
_STEP_PATTERN = re.compile(
    r'^(bước|step)\s+\d+\s*[:\.\-]'             # "Bước 1:" or "Step 1:"
    r'|^\d+\.\s+[A-ZÀÁẢÃẠ\w]'                   # "1. Do something" numbered list
    r'|(cách|how to)\s+\w+\s+(để|to)\s+\w+',    # "cách X để Y" / "how to X"
    re.IGNORECASE | re.MULTILINE,
)

# Technique / concept definition markers — EDUCATIONAL for scholarly/technical.
_DEFINITION_PATTERN = re.compile(
    r'(là|được định nghĩa (là|như)|có nghĩa là)'   # VI definitions
    r'|(is defined as|refers to|is a (type|form|method|process|technique) of)'  # EN
    r'|(bao gồm|consists of|encompasses|comprises)'  # inclusion
    r'|(cho phép|enables|allows|facilitates)',        # capability statements
    re.IGNORECASE,
)

# Booking / spa / service page signals — strong JUNK for lifestyle topics.
_BOOKING_PATTERN = re.compile(
    r'đặt (lịch|phòng|chỗ)|book (a session|appointment|class)'
    r'|giá (dịch vụ|khóa học|vé)|pricing|our (services|packages|rates)'
    r'|lịch học|class schedule|available (times|slots)'
    r'|contact us (to|for)|liên hệ để (đăng ký|biết thêm)',
    re.IGNORECASE,
)

_NAV_URL_PATTERNS = re.compile(
    r'/abs/\d+|/abstract|/book\b|mlbook|/catalog|/index\.html$'
    
    # Course/enrollment URL patterns
    r'|/khoa-hoc/|/course/|/courses/|/class/|/enroll'
    r'|/hoc-vien/|/tuyen-sinh/|/dang-ky/'
    r'|/products/khoa-hoc|/products/course'
    r'|course-details|class-details',
    
    re.IGNORECASE,
)


_COURSE_MARKETING_PATTERN = re.compile(
    # Enrollment CTAs
    r'(enroll|sign up|join|register|đăng ký)\s+(now|today|for free|ngay|miễn phí)'
    r'|(enroll|đăng ký)\s+(here|tại đây)'
    
    # Speed claims
    r'|learn\s+\w+\s+in \d+ (days|weeks|months)'
    r'|học\s+\w+\s+trong \d+ (ngày|tuần|tháng)'
    
    # Career promises
    r'|(boost|advance|kickstart)\s+your\s+(career|skills)'
    r'|(nâng cao|phát triển)\s+(sự nghiệp|kỹ năng)'
    r'|industry.ready|job.ready|placement (assistance|guarantee)'
    
    # Batch/cohort scheduling
    r'|batch (starts|starting)|next batch|upcoming (batch|cohort)'
    r'|khai giảng|lịch khai giảng|lớp khai giảng'
    
    # Pricing
    r'|học phí|course fee|tuition fee|phí khóa học'
    r'|\d+[\.,]\d+\s*(vnđ|vnd|đồng|usd|\$)'  # Price amounts
    
    # Certificates
    r'|chứng chỉ (được cấp|hoàn thành)|certificate of completion'
    r'|cấp chứng chỉ|nhận chứng chỉ'
    
    # Course structure keywords
    r'|khóa học\s+(gồm có|\d+\s+(buổi|tiết))'  # "Khóa học 20 buổi"
    r'|course (includes|comprises)\s+\d+\s+(sessions?|lessons?)'
    
    # Contact for enrollment
    r'|liên hệ để (đăng ký|tham gia)|contact (us )?(to|for) (enroll|register)'
    r'|hotline|phone|số điện thoại.*đăng ký',
    
    re.IGNORECASE,
)


# ============================================================================
# NEWS SITE DETECTION
# Domain-agnostic news/journalism patterns — fires on attribution, bylines,
# copyright notices common to news articles regardless of topic.
# Bilingual (VI + EN) to catch both Vietnamese news sites and international
# news aggregators that appear in us-en search results.
# ============================================================================
_NEWS_PATTERN = re.compile(
    # Vietnamese news markers
    r'phóng viên|tác giả|biên tập viên|nguồn tin|bản quyền thuộc'
    r'|theo\s+(VnExpress|Dantri|Tuoitre|VTC|Thanh\s+Niên|Vietnamnet)'
    r'|nguồn:\s*\w+|trích dẫn từ'
    
    # English news markers
    r'|staff writer|correspondent|byline|all rights reserved'
    r'|copyright\s+\d{4}|published\s+\d{1,2}\s+(hours?|days?)\s+ago'
    r'|source:\s*\w+|according to\s+[A-Z][\w]+'
    
    # Generic journalism patterns (both languages)
    r'|breaking news|tin tức|bài viết liên quan|related articles'
    r'|đọc thêm:|read more:|xem thêm:|see also:',
    
    re.IGNORECASE,
)


# ============================================================================
# LISTING/DIRECTORY PAGE DETECTION
# Detects ranking pages, directory listings, "top N places" compilations.
# These pages aggregate multiple entities (schools, gyms, restaurants) without
# providing substantive educational content about the subject itself.
# Bilingual to catch both Vietnamese listicles and English directory sites.
# ============================================================================
_LISTING_PATTERN = re.compile(
    # Vietnamese listing markers
    r'top\s+\d+\s+(trung\s+tâm|địa\s+chỉ|khóa\s+học|nơi\s+học|lớp\s+học|phòng\s+tập|quán\s+ăn|nhà\s+hàng)'
    r'|danh\s+sách\s+\d+\s+(trung\s+tâm|khóa|lớp|địa\s+điểm|quán)'
    r'|\d+\s+địa\s+chỉ\s+(học|tập|ăn|mua)'
    
    # English listing markers
    r'|top\s+\d+\s+(centers?|schools?|classes?|gyms?|studios?|restaurants?|places?)'
    r'|best\s+\d+\s+(centers?|schools?|places?)\s+(to|for|in)'
    r'|\d+\s+best\s+(places?|schools?|centers?)'
    
    # Structural listing patterns (language-agnostic)
    # Repeated "#1 Name... #2 Name..." or "1. Place A... 2. Place B..."
    r'|#\d+[\s\.\-:]+[\w\s]{5,50}#\d+'  # "#1 Yoga Studio A #2 Studio B"
    r'|\d+\.[\s]+[\w\s]{10,60}\n\d+\.'   # "1. Some Place\n2. Another Place"
    
    # Review aggregate patterns
    r'|rating:?\s*\d+[\.,]\d+/\d+|⭐{2,5}|\d+\s+reviews?|\d+\s+đánh\s+giá',
    
    re.IGNORECASE | re.MULTILINE,
)
# ============================================================================
# NEWS DOMAIN BLACKLIST
# Known Vietnamese and international news sites that should ALWAYS return JUNK
# regardless of content analysis. Domain-level blocking is more reliable than
# pattern matching for well-known news organizations.
# ============================================================================
_NEWS_DOMAINS = (
    # Vietnamese news sites
    "dantri.com", "vnexpress.net", "tuoitre.vn",
    "thanhnien.vn", "vietnamnet.vn", "vtc.vn",
    "baomoi.com", "tienphong.vn", "nld.com.vn",
    
    # International news (Vietnamese sections)
    "bbc.com/vietnamese", "voanews.com/vietnamese",
    "rfi.fr/vi",
    
    # Exclude these from the blacklist if they have educational sections:
    # - None currently, but could add exceptions here
)

# ============================================================================
# TRUSTED PRACTICAL DOMAINS WHITELIST
# High-quality instructional sites that consistently provide step-by-step
# educational content for practical/lifestyle topics. These domains bypass
# all scoring and return EDUCATIONAL immediately to prevent false negatives
# (e.g., wikihow being marked JUNK due to footer signup forms).
# 
# Only applies when content_type is 'practical' or 'lifestyle'.
# Domain-agnostic quality threshold: must have established reputation for
# accurate, beginner-friendly, step-by-step instructional content.
# ============================================================================
_PRACTICAL_TRUSTED_DOMAINS = (
    # Step-by-step how-to guides
    "wikihow.com",
    "instructables.com",
    
    # Health and wellness (lifestyle)
    "healthline.com",
    "mayoclinic.org",
    "webmd.com",
    
    # Cooking and food (practical)
    "allrecipes.com",
    "seriouseats.com",
    "bonappetit.com",
    "foodnetwork.com",
    
    # Educational platforms with practical courses
    "masterclass.com",
    "skillshare.com",  # Note: may be login-gated, but content is educational
)
def classify_page(text: str, url: str, content_type: str = "technical") -> str:
    """
    Three-way page classifier to determine crawl strategy per page.

    Replaces the binary _is_content_page() with a content-type-aware
    scoring system. Each content_type uses different signal weights
    to correctly classify pages across all educational domains.

    Enhancements:
        - Trusted domain whitelist for practical/lifestyle content
        - News site detection (bilingual)
        - Listing/directory page detection (bilingual)

    Args:
        text:         Extracted page text from fetch_text_from_url().
        url:          Page URL — used for domain-level signals.
        content_type: One of 'scholarly'|'technical'|'practical'|'lifestyle'.

    Returns:
        _PAGE_EDUCATIONAL — store content, crawl sublinks
        _PAGE_NAVIGATION  — skip content, crawl sublinks
        _PAGE_JUNK        — skip content AND sublinks
    """
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # EARLY RETURN: News domain blacklist
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Domain-level blocking for known news organizations
    # More reliable than pattern matching alone
    url_lower = url.lower()
    if any(domain in url_lower for domain in _NEWS_DOMAINS):
        logger.info(f"News domain blacklist hit: {url[:60]}")
        return _PAGE_JUNK
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # EARLY RETURN: Trusted practical domain whitelist
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Bypass all scoring for known high-quality practical instructional sites.
    # Prevents false negatives like wikihow.com being marked JUNK due to
    # footer signup forms triggering promo pattern.
    if content_type in ("practical", "lifestyle"):
        url_lower = url.lower()
        if any(domain in url_lower for domain in _PRACTICAL_TRUSTED_DOMAINS):
            logger.info(f"Trusted practical domain whitelist hit: {url[:60]}")
            return _PAGE_EDUCATIONAL
    
    stripped = text.strip()

    # Hard floor: too short to classify — treat as navigation
    if len(stripped) < 500:
        return _PAGE_NAVIGATION

    lines      = [l.strip() for l in stripped.split('\n') if l.strip()]
    total_lines = len(lines)
    if not total_lines:
        return _PAGE_NAVIGATION

    words       = stripped.lower().split()
    total_words = len(words)

    edu_score  = 0.0
    junk_score = 0.0

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SIGNAL 1: Hard junk detection — applies to ALL content types
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 1a. Login-gated pages: never have retrievable content
    if _LOGIN_PATTERN.search(stripped):
        return _PAGE_JUNK

    # 1b. News sites: articles about topics, not educational material - STRENGTHENED
    # Fires on bylines, copyright, news attribution (bilingual)
    news_hits = len(_NEWS_PATTERN.findall(stripped))
    if news_hits >= 3:
        junk_score += 2.5  # strong news signal
    elif news_hits >= 2:
        junk_score += 2.0  # Increased from 1.5
    elif news_hits >= 1:
        junk_score += 1.0  # Increased from 0.5 - KEY FIX for weak signals

    # 1c. Listing/directory pages: "top 10 gyms/schools/restaurants" - STRENGTHENED
    # No substantive educational content, just aggregated links
    listing_hits = len(_LISTING_PATTERN.findall(stripped))
    if listing_hits >= 3:
        junk_score += 3.0  # confirmed listing page (increased from 2.5)
    elif listing_hits >= 2:
        junk_score += 2.5  # increased from 2.0
    elif listing_hits >= 1:
        junk_score += 1.5  # increased from 0.8 - KEY FIX for weak signals

    # 1d. Heavy promotional language
    promo_hits = len(_PROMO_PATTERN.findall(stripped))
    if promo_hits >= 4:
        return _PAGE_JUNK
    elif promo_hits >= 2:
        junk_score += 1.8
    elif promo_hits >= 1:
        junk_score += 0.3

    # 1e. Booking/service page (especially harmful for lifestyle topics)
    booking_hits = len(_BOOKING_PATTERN.findall(stripped))
    if booking_hits >= 3:
        return _PAGE_JUNK
    elif booking_hits >= 1:
        junk_score += 0.5 if content_type == "lifestyle" else 0.2

    # 1f. Resource aggregator: page is mostly a list of URLs
    url_count = len(re.findall(r'https?://', stripped))
    if url_count >= 8 and url_count / total_lines > 0.25:
        junk_score += 1.5

    # 1g. Personal course review / blog opinion
    review_hits = len(_REVIEW_PATTERN.findall(stripped))
    if review_hits >= 3:
        junk_score += 1.5
    elif review_hits >= 1:
        junk_score += 0.5

    # 1h. Landing/hub URL patterns — these pages link to real content elsewhere
    # Demote edu_score to prevent storing hub pages as educational content
    if _NAV_URL_PATTERNS.search(url):
        junk_score += 1.5  

   # 1i. Course marketing - STRENGTHENED for enrollment pages
    marketing_hits = len(_COURSE_MARKETING_PATTERN.findall(stripped))
    if marketing_hits >= 3:
        return _PAGE_JUNK  
    elif marketing_hits >= 2:
        junk_score += 2.5  
    elif marketing_hits >= 1:
        junk_score += 1.0  #
    # 1j. Combined signals amplify junk score
    if review_hits >= 1 and promo_hits >= 1:
        junk_score += 1.5
        
    
  # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SIGNAL 2: Prose quality — universal positive signal (REDUCED WEIGHT)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # Long lines ratio: prose paragraphs are longer than nav link texts
    # REDUCED WEIGHT: news articles also have long lines
    long_lines = sum(1 for l in lines if len(l) > 80)
    prose_ratio = long_lines / total_lines
    if prose_ratio >= 0.25:
        edu_score += 0.8  # Reduced from 1.0
    elif prose_ratio >= 0.15:
        edu_score += 0.4  # Reduced from 0.5

    # Sentence-ending punctuation ratio: prose ends sentences
    punct_lines = sum(1 for l in lines if l and l[-1] in '.!?')
    sent_ratio = punct_lines / total_lines
    if sent_ratio >= 0.15:
        edu_score += 0.5
    elif sent_ratio < 0.04:
        junk_score += 0.3

    # Word diversity: educational content uses varied vocabulary
    # REDUCED WEIGHT: news also has high diversity
    if total_words > 30:
        diversity = len(set(words)) / total_words
        if diversity >= 0.52:
            edu_score += 0.3  # Reduced from 0.5
        elif diversity < 0.32:
            junk_score += 0.5

    # Page length bonus: very long pages are more likely substantive
    if len(stripped) > 15000:
        edu_score += 0.5
    if len(stripped) > 30000:
        edu_score += 0.5
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SIGNAL 3: Content-type specific signals
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    if content_type in ("scholarly", "technical"):
        # Definitions and explanations — strong educational signal
        def_hits = len(_DEFINITION_PATTERN.findall(stripped))
        if def_hits >= 3:
            edu_score += 1.0
        elif def_hits >= 1:
            edu_score += 0.5

        # Personal opinion without instructions — junk for scholarly
        if review_hits >= 1 and def_hits == 0:
            junk_score += 0.5

        # Code blocks in technical content
        if content_type == "technical":
            code_blocks = stripped.count("```") + stripped.count("    ") // 3
            if code_blocks >= 2:
                edu_score += 0.5

    elif content_type in ("practical", "lifestyle"):
        # Step-by-step instructions — strongest educational signal
        step_hits = len(_STEP_PATTERN.findall(stripped))
        if step_hits >= 4:
            edu_score += 1.5
        elif step_hits >= 2:
            edu_score += 0.8
        elif step_hits >= 1:
            edu_score += 0.3

        # For practical/lifestyle: personal experience WITH instructions is OK
        # Only penalize opinion without any instructional content
        if review_hits >= 2 and step_hits == 0:
            junk_score += 0.5

        # Technique / health keyword density for lifestyle
        if content_type == "lifestyle":
            wellness_pattern = re.compile(
                r'\b(tư thế|pose|kỹ thuật|technique|hít thở|breathing'
                r'|lợi ích|benefit|sức khỏe|health|thực hành|practice'
                r'|bài tập|exercise|hướng dẫn|instruction)\b',
                re.IGNORECASE,
            )
            wellness_hits = len(wellness_pattern.findall(stripped))
            if wellness_hits >= 5:
                edu_score += 0.8
            elif wellness_hits >= 2:
                edu_score += 0.3
                
    logger.info(f"classify_page scores | edu={edu_score:.2f} junk={junk_score:.2f} | {url[:50]}")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # DECISION LOGIC
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Strong junk: skip page AND sublinks
# LOWERED THRESHOLD: from 2.5 to 2.0, margin from 0.5 to 0.3
    if junk_score >= 2.0 and junk_score > edu_score + 0.3:
        return _PAGE_JUNK

# Moderate junk with no educational signal: skip page, try sublinks
    if junk_score >= 1.5 and edu_score < 0.5:
        return _PAGE_NAVIGATION

    # Educational: sufficient positive signals
    if edu_score >= 1.0 and edu_score >= junk_score:
        return _PAGE_EDUCATIONAL

    # Borderline: enough content to maybe be worth crawling sublinks
    return _PAGE_NAVIGATION

# Compiled once at module level for performance
_TOC_LINE_PATTERN = re.compile(
    r'^(chapter|week|unit|lecture|section|module|part|topic|lesson'
    r'|chương|bài|mục|phần)\s*[\d\.\-\:]+\s*\S'
    r'|.*\d+\s+min\s+read$',  
    re.IGNORECASE,
)

_INLINE_TOC_PATTERN = re.compile(
    r'(chapter|topic|section|module|unit)\s+\d+[\.\:]\d*.*?'
    r'(chapter|topic|section|module|unit)\s+\d+[\.\:]\d*'
    r'|:\s*(chapter|topic|section|module|unit)\s+\d+[\.\:]',
    re.IGNORECASE,
)

def clean_toc_lines(text: str) -> str:
    """
    Remove pure table-of-contents lines from extracted page text, preserving
    any prose descriptions that follow structural prefix lines.

    Many academic course pages mix TOC entries with inline descriptions:
        "Chapter 01.02: Data"                     ← pure TOC header, remove
        "In this section we explain tabular data"  ← prose description, keep
        "Chapter 01.03: Tasks"                    ← pure TOC header, remove
        "The tasks of supervised learning..."     ← prose description, keep

    This function strips the TOC header lines while preserving the prose,
    allowing downstream chunking and quality filters to work on actual content
    rather than rejecting the entire chunk due to high TOC line ratio.

    Domain-agnostic — applies to any page structure that mixes navigation
    headers with inline descriptions regardless of site or topic.

    Args:
        text: Raw text extracted by fetch_text_from_url().

    Returns:
        Cleaned text with TOC header lines removed. Prose lines are preserved
        unchanged. Consecutive blank lines are collapsed to a single blank.
    """
   # Step 1: Strip inline TOC — all chapters listed on a single long line
    # e.g. "Chapter 01.01: Intro Chapter 01.02: Data Chapter 01.03: Tasks"
    # Must run BEFORE line splitting since it operates on the full text.
    text = _INLINE_TOC_PATTERN.sub('', text)

    # Step 2: Strip per-line TOC headers
    lines      = text.split('\n')
    cleaned    = []
    prev_blank = False

    for line in lines:
        stripped = line.strip()

        if _TOC_LINE_PATTERN.match(stripped) and len(stripped) < 120:
            continue

        if not stripped:
            if not prev_blank:
                cleaned.append('')
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return '\n'.join(cleaned)

# ---------------------------------------------------------------------------
# Deep crawl worker
# ---------------------------------------------------------------------------

def process_deep_crawl(
    link_info: Dict[str, str],
    crawl_max_sub_links: int | None = None,
    crawl_max_depth2_links: int | None = None,
) -> List[Document]:
    """
    Process a single root URL with adaptive depth crawling.

    PDF: extract text with PyMuPDF (or pypdf fallback).
    HTML: three-way page classification drives crawl strategy:
        EDUCATIONAL → store content + crawl sublinks
        NAVIGATION  → skip content, crawl sublinks (hub pages)
        JUNK        → skip content AND sublinks entirely

    Depth-2 triggered only when root classified as NAVIGATION —
    avoids unnecessary deep crawl when root has real content.

    Args:
        link_info: Dict with keys 'url', 'type', and 'content_type'.

    Returns:
        List of LangChain Document objects.
    """
    url          = link_info["url"]
    doc_type     = link_info["type"]
    content_type = link_info.get("content_type", "technical")
    base_metadata = {
        "source": url,
        "source_url": url,
        "source_query": link_info.get("source_query", ""),
        "search_region": link_info.get("search_region", ""),
        "search_title": link_info.get("search_title", ""),
        "snippet_score": link_info.get("snippet_score", ""),
        "trusted_source": link_info.get("trusted_source", "false"),
        "direct_custom_url": link_info.get("direct_custom_url", link_info.get("_direct_custom_url", "false")),
    }
    sub_link_limit = CRAWL_MAX_SUB_LINKS if crawl_max_sub_links is None else crawl_max_sub_links
    depth2_limit = CRAWL_MAX_DEPTH2_LINKS if crawl_max_depth2_links is None else crawl_max_depth2_links
    results: List[Document] = []

    try:
        # ── PDF ──────────────────────────────────────────────────────────────
        # PDFs from trusted academic sources are stored without classification —
        # quality filtering happens downstream in is_quality_chunk() and
        # relevance scoring. PDF structure is already clean (no nav, no ads).
        if doc_type == "pdf":
            text = extract_pdf_text(url)
            if len(text) > 300:
                pdf_metadata = {**base_metadata, "type": "pdf"}
                if _is_priority_textbook_pdf(url, text, pdf_metadata):
                    pdf_metadata["source_quality"] = "priority_textbook_pdf"
                    pdf_metadata["cap_bypass_reason"] = "trusted_textbook_pdf"
                    logger.info(
                        f"[PDF/PRIORITY] {url[:80]} marked as priority textbook PDF"
                    )
                results.append(Document(
                    page_content=text,
                    metadata=pdf_metadata,
                ))
            return results

        # ── HTML ─────────────────────────────────────────────────────────────
        main_text, soup = fetch_text_from_url(url)

        if len(main_text) <= 300:
            return results

        page_class = classify_page(main_text, url, content_type)

        if page_class == _PAGE_EDUCATIONAL:
            # Store root content — it has substantive educational value.
            logger.info(
                f"[ROOT/EDU] {url[:60]} ({len(main_text)} chars) "
                f"[{content_type}]"
            )
            results.append(Document(
                page_content=main_text,
                metadata={**base_metadata, "type": "html", "depth": 0},
            ))
            root_is_nav = False

        elif page_class == _PAGE_JUNK:
            # Hard skip — junk root pages link to more junk.
            # Do NOT crawl sublinks to avoid polluting corpus.
            logger.info(
                f"[ROOT/JUNK] {url[:60]} ({len(main_text)} chars) "
                f"— promotional/login-gated, skipping page and sublinks"
            )
            return results

        else:  # _PAGE_NAVIGATION
            # Navigation hub — skip root content but crawl sublinks.
            # Sublinks may point to high-value content pages.
            logger.info(
                f"[ROOT/NAV] {url[:60]} ({len(main_text)} chars) "
                f"— navigation hub, crawling sublinks only"
            )
            root_is_nav = True

        if stop_signal.is_stopped():
            return results

        # ── Sublink crawl ─────────────────────────────────────────────────────
        if not soup:
            return results

        sub_links = get_internal_links(soup, url, limit=sub_link_limit)
        if not sub_links:
            return results

        logger.info(f"  ↳ Crawling {len(sub_links)} sub-links from {url[:50]}")

        for sub in sub_links:
            if stop_signal.is_stopped():
                return results

            sub_text, sub_soup = fetch_text_from_url(sub)
            sub_class = classify_page(sub_text, sub, content_type)

            if sub_class == _PAGE_EDUCATIONAL:
                results.append(Document(
                    page_content=sub_text,
                    metadata={
                        **base_metadata,
                        "source": sub,
                        "source_url": sub,
                        "type":   "html",
                        "depth":  1,
                        "parent": url,
                    },
                ))

            elif sub_class == _PAGE_JUNK:
                # Junk sublink — skip and do not recurse deeper
                logger.debug(f"  [SUB/JUNK] {sub[:60]} — skipping")

            else:
                # Navigation sublink: only go deeper if root was also nav.
                # Avoids unnecessary depth-2 when root had real content.
                if root_is_nav and sub_soup is not None and not stop_signal.is_stopped():
                    depth2_links = get_internal_links(
                        sub_soup, sub, limit=depth2_limit
                    )
                    if depth2_links:
                        logger.info(
                            f"    ↳↳ Depth-2: {len(depth2_links)} sub-sub-links "
                            f"from nav depth-1 {sub[:50]}"
                        )
                    for d2_url in depth2_links:
                        if stop_signal.is_stopped():
                            return results
                        d2_text, _ = fetch_text_from_url(d2_url)
                        # Depth-2 uses minimum length check only —
                        # full classification too slow for this depth.
                        if len(d2_text) > 500:
                            results.append(Document(
                                page_content=d2_text,
                                metadata={
                                    **base_metadata,
                                    "source": d2_url,
                                    "source_url": d2_url,
                                    "type":   "html",
                                    "depth":  2,
                                    "parent": sub,
                                },
                            ))

    except Exception as e:
        logger.warning(f"Error processing {url[:60]}: {e}")

    return results


# ---------------------------------------------------------------------------
# Main ingestion entry point
# ---------------------------------------------------------------------------

def ingest_dynamic_data(
    topic: str,
    clean_links: List[Dict[str, str]],
    content_type: str = "technical",
    collection_name: str = "dynamic_context",
    run_id: str = "dynamic_context",
    progress_callback=None,
    runtime_config: dict[str, Any] | None = None,
    query_expansion: dict[str, list[str]] | None = None,
) -> bool: #type: ignore
    """
    Ingest data from filtered URLs into ChromaDB.

    Full pipeline:
    1. Deep crawl all URLs in parallel (max_workers=5)
    2. Chunk documents (chunk_size=1000, overlap=200)
    3. Quality filter — remove short/noisy chunks via is_quality_chunk()
    4. Relevance filter — discard chunks below cosine similarity threshold
    5. Save to ChromaDB

    Args:
        topic:       User's topic string — used as metadata + relevance reference
        clean_links: Validated URL list from filter_and_classify_urls()

    Returns:
        True if at least some chunks were saved successfully, False otherwise.
    """
    if not clean_links:
        logger.warning("No clean links provided — skipping ingestion")
        return False

    runtime_config = runtime_config or {}
    crawl_max_workers = _config_int(
        runtime_config, "CRAWL_MAX_WORKERS", CRAWL_MAX_WORKERS, minimum=1
    )
    crawl_max_sub_links = _config_int(
        runtime_config, "CRAWL_MAX_SUB_LINKS", CRAWL_MAX_SUB_LINKS
    )
    crawl_max_depth2_links = _config_int(
        runtime_config, "CRAWL_MAX_DEPTH2_LINKS", CRAWL_MAX_DEPTH2_LINKS
    )
    chunk_size = _config_int(runtime_config, "CHUNK_SIZE", CHUNK_SIZE, minimum=1)
    chunk_overlap = _config_int(runtime_config, "CHUNK_OVERLAP", CHUNK_OVERLAP)
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 5)
        logger.warning(
            "CHUNK_OVERLAP must be smaller than CHUNK_SIZE; using %s for this run",
            chunk_overlap,
        )
    max_chunks_to_embed = _config_int(
        runtime_config, "MAX_CHUNKS_TO_EMBED", settings.MAX_CHUNKS_TO_EMBED, minimum=1
    )
    embedding_batch_size = _config_int(
        runtime_config, "EMBEDDING_BATCH_SIZE", settings.EMBEDDING_BATCH_SIZE, minimum=1
    )
    chromadb_batch_size = _config_int(
        runtime_config, "CHROMADB_BATCH_SIZE", settings.CHROMADB_BATCH_SIZE, minimum=1
    )
    configured_min_relevance = _config_float(
        runtime_config, "MIN_RELEVANCE_SCORE", settings.MIN_RELEVANCE_SCORE
    )
    if configured_min_relevance != settings.MIN_RELEVANCE_SCORE:
        min_relevance = configured_min_relevance
    else:
        min_relevance = MIN_RELEVANCE_BY_TYPE.get(content_type, configured_min_relevance)

    t_start = time.time()
    logger.info(
        f"Starting deep crawler "
        f"(max depth=1, {crawl_max_sub_links} sub-links/page, "
        f"{crawl_max_depth2_links} depth-2 links/page, {len(clean_links)} root URLs)..."
    )

    # ── Step 1: Parallel deep crawl ──────────────────────────────────────────
    all_docs: List[Document] = []
    # Inject content_type into each link dict so process_deep_crawl
    # can check whitelist without a separate parameter channel.
    for link in clean_links:
        link["content_type"] = content_type
    crawled_count = 0
    total_links   = len(clean_links)
    with concurrent.futures.ThreadPoolExecutor(max_workers=crawl_max_workers) as executor:
        futures = [
            executor.submit(
                process_deep_crawl,
                link,
                crawl_max_sub_links,
                crawl_max_depth2_links,
            )
            for link in clean_links
            if not stop_signal.is_stopped()
        ]
        for future in concurrent.futures.as_completed(futures):
            if stop_signal.is_stopped():
                logger.info("Stop signal received — halting crawl")
                break
            docs = future.result()
            if docs:
                for doc in docs:
                    doc.metadata["topic"] = topic
                    doc.metadata["run_id"] = run_id
                    doc.metadata["content_type"] = content_type
                    doc.metadata["domain"] = urlparse(
                        doc.metadata.get("source_url")
                        or doc.metadata.get("source", "")
                    ).netloc.lower()
                    all_docs.append(doc)
            crawled_count += 1
            if progress_callback and (crawled_count % 3 == 0 or crawled_count == total_links):
                print(f"[DEBUG CRAWLER] emitting progress: {crawled_count} URLs done", flush=True)
                progress_callback(
                    f"Đang crawl: {crawled_count}/{total_links} trang nguồn "
                    f"({len(all_docs)} trang có nội dung)..."
                )

    if not all_docs:
        logger.error("No content crawled — check URL filter and network connectivity")
        return False
    
    logger.info(f"Crawled: {len(all_docs)} documents (roots + sub-pages)")
    if progress_callback:
        progress_callback(f"Đã thu thập {len(all_docs)} trang — đang chia nhỏ nội dung...")

    # ── Step 2: Chunking ─────────────────────────────────────────────────────
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = text_splitter.split_documents(all_docs)
    logger.info(f"Chunked: {len(chunks)} total chunks")

    logger.info(f"Chunked: {len(chunks)} total chunks")
    if progress_callback:
        progress_callback(f"Đã chia {len(chunks)} đoạn — đang lọc chất lượng...")

    # ── Step 3: Quality heuristic filter ────────────────────────────────────
    quality_chunks = [c for c in chunks if is_quality_chunk(c.page_content)]
    removed_noise = len(chunks) - len(quality_chunks)
    logger.info(
        f"Quality filter: {len(chunks)} → {len(quality_chunks)} chunks "
        f"({removed_noise} noise chunks removed)"
    )

    if not quality_chunks:
        logger.error("All chunks removed by quality filter — data may be entirely noise")
        return False
    quality_chunk_count_before_caps = len(quality_chunks)

    if len(quality_chunks) > max_chunks_to_embed:
        priority_chunks = [
            chunk for chunk in quality_chunks
            if chunk.metadata.get("source_quality") == "priority_textbook_pdf"
        ]
        priority_ids = {id(chunk) for chunk in priority_chunks}
        regular_cap = max(0, max_chunks_to_embed - len(priority_chunks))
        regular_chunks = [
            chunk for chunk in quality_chunks
            if id(chunk) not in priority_ids
        ][:regular_cap]
        regular_ids = {id(chunk) for chunk in regular_chunks}
        if len(priority_chunks) > max_chunks_to_embed:
            logger.warning(
                "Priority textbook PDF chunks (%s) exceed MAX_CHUNKS_TO_EMBED=%s; "
                "keeping all priority chunks after quality filtering",
                len(priority_chunks),
                max_chunks_to_embed,
            )
        logger.info(
            f"Max chunks cap: {len(quality_chunks)} → "
            f"{len(priority_chunks) + len(regular_chunks)} before embedding "
            f"({len(priority_chunks)} priority textbook PDF chunks kept)"
        )
        quality_chunks = [
            chunk for chunk in quality_chunks
            if id(chunk) in priority_ids or id(chunk) in regular_ids
        ]

    logger.info(f"Quality filter: {len(chunks)} → {len(quality_chunks)} chunks ...")
    if progress_callback:
        progress_callback(
            f"Lọc chất lượng: còn {len(quality_chunks)} đoạn — "
            f"đang tính độ liên quan..."
        )
    # ── Step 4: Relevance filter ─────────────────────────────────────────────
    t4 = time.time()
    logger.info(
    f"Relevance scoring {len(quality_chunks)} chunks "
    f"(threshold={min_relevance}, content_type={content_type})..."
    )
    embedding_model = get_embedding_model()

    # Bilingual topic embedding — average VI + EN để không filter EN chunks
    # Vấn đề: embed_query(topic_VI) có cosine similarity thấp với EN chunks
    # → Stanford PDF, CMU lecture bị loại hoàn toàn dù chất lượng cao
    try:
        if query_expansion is not None:
            en_queries = query_expansion.get("en", [])
        else:
            _qe = QueryExpansionAgent()
            en_queries = _qe.expand_query_bilingual(topic, content_type=content_type).get("en", [])
        en_topic   = en_queries[0] if en_queries else topic

        topic_emb_vi  = np.array(_rate_limited_embed_query(embedding_model, topic))
        topic_emb_en  = np.array(_rate_limited_embed_query(embedding_model, en_topic))
        combined      = (topic_emb_vi + topic_emb_en) / 2
        norm          = np.linalg.norm(combined)
        topic_emb     = combined / norm if norm > 0 else topic_emb_vi

        logger.info(
            f"✓ Bilingual topic embedding: "
            f"VI='{topic}' + EN='{en_topic}'"
        )
    except Exception as e:
        logger.warning(f"Bilingual embedding failed ({e}) — falling back to VI only")
        topic_emb = np.array(_rate_limited_embed_query(embedding_model, topic))

    scores, chunk_embeddings = compute_relevance_scores(  
        quality_chunks, 
        topic_emb, 
        embedding_model,
        progress_callback=progress_callback,
        embedding_batch_size=embedding_batch_size,
    )

    # A chunk should be relevant either to the whole textbook topic OR to the
    # search query that discovered its root URL. This bridges the gap between
    # broad corpus ingestion and subsection-specific retrieval without letting
    # arbitrary quality-only chunks through.
    source_query_embeddings: dict[str, np.ndarray] = {}
    for chunk in quality_chunks:
        source_query = (chunk.metadata.get("source_query") or "").strip()
        if source_query and source_query not in source_query_embeddings:
            try:
                source_query_embeddings[source_query] = np.array(
                    _rate_limited_embed_query(embedding_model, source_query)
                )
            except Exception as e:
                logger.debug(f"Source-query embedding failed for '{source_query[:50]}': {e}")

    adjusted_scores: list[float] = []
    for chunk, topic_score, embedding in zip(quality_chunks, scores, chunk_embeddings):
        source_query = (chunk.metadata.get("source_query") or "").strip()
        final_score = float(topic_score)
        if source_query in source_query_embeddings:
            query_emb = source_query_embeddings[source_query].reshape(1, -1)
            chunk_emb = np.array(embedding).reshape(1, -1)
            query_score = float(cosine_similarity(chunk_emb, query_emb)[0][0])
            final_score = max(final_score, query_score)
        chunk.metadata["relevance_score"] = f"{final_score:.4f}"
        chunk.metadata["language"] = _detect_language(chunk.page_content)
        adjusted_scores.append(final_score)
    scores = adjusted_scores

    relevant_pairs = [
        (chunk, embedding) 
        for chunk, score, embedding in zip(quality_chunks, scores, chunk_embeddings)
        if score >= min_relevance
    ]
    relevant_chunks = [pair[0] for pair in relevant_pairs]
    relevant_embeddings = [pair[1] for pair in relevant_pairs]
    relevant_chunk_count_before_cap = len(relevant_chunks)
    
    removed_irrelevant = len(quality_chunks) - len(relevant_chunks)
    logger.info(
        f"Relevance filter: {len(quality_chunks)} → {len(relevant_chunks)} chunks "
        f"({removed_irrelevant} off-topic chunks removed) "
        f"[{time.time() - t4:.1f}s]"
    )
    if not relevant_chunks:
        logger.error(
            f"All chunks scored below {min_relevance} — "
            f"aborting ingestion instead of falling back to quality-only chunks"
        )
        return False
    
    bilingual_stats = _compute_bilingual_stats(relevant_chunks)
    logger.info(
        f"✓ Bilingual distribution (pre-cap): "
        f"{bilingual_stats['vi_chunks']} VI ({bilingual_stats['vi_ratio']:.1%}) + "
        f"{bilingual_stats['en_chunks']} EN ({bilingual_stats['en_ratio']:.1%})"
    )
    logger.info(f"  Top VI sources: {bilingual_stats['top_vi_sources']}")
    logger.info(f"  Top EN sources: {bilingual_stats['top_en_sources']}")

    # Apply cap and track indices to filter embeddings accordingly
    capped_chunks = _apply_domain_diversity_cap(relevant_chunks, MAX_CHUNKS_PER_DOMAIN)
    capped_chunks, diversity_status = _apply_source_diversity_controls(
        capped_chunks,
        runtime_config,
    )
    
    # Filter embeddings to match capped chunks
    # Build mapping from chunk id to embedding
    chunk_to_embedding = {
        id(chunk): emb 
        for chunk, emb in zip(relevant_chunks, relevant_embeddings)
    }
    capped_embeddings = [
        chunk_to_embedding[id(chunk)] 
        for chunk in capped_chunks
    ]
    
    relevant_chunks = capped_chunks  # Update variable name for consistency
    final_stats = _compute_bilingual_stats(relevant_chunks)
    logger.info(
        f"✓ Final ChromaDB corpus: {final_stats['total_chunks']} chunks "
        f"({final_stats['vi_chunks']} VI [{final_stats['vi_ratio']:.1%}], "
        f"{final_stats['en_chunks']} EN [{final_stats['en_ratio']:.1%}])"
    )
    logger.info(f"Relevance filter: {len(quality_chunks)} → {len(relevant_chunks)} chunks ...")
    if progress_callback:
        progress_callback(
            f"Lọc liên quan: còn {len(relevant_chunks)} đoạn — "
            f"đang lưu vào ChromaDB..."
        )

    # ── Step 5: Save to ChromaDB ─────────────────────────────────────────────
    t5 = time.time()
    logger.info(f"Saving {len(relevant_chunks)} chunks to ChromaDB...")
    
    try:
        if len(relevant_chunks) == 0:
            logger.warning("No chunks to save after filtering")
            return False
        
        # Prepare data for batch insertion
        texts = [chunk.page_content for chunk in relevant_chunks]
        metadatas = [chunk.metadata for chunk in relevant_chunks]
        
        # Initialize ChromaDB collection
        CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
        from langchain_chroma import Chroma
        vector_db = Chroma(
            embedding_function=embedding_model,
            persist_directory=str(CHROMA_DB_DIR),
            collection_name=collection_name,
        )
        
        # Batch insertion with pre-computed embeddings
        total_saved = 0
        for i in range(0, len(texts), chromadb_batch_size):
            batch_texts = texts[i:i + chromadb_batch_size]
            batch_metas = metadatas[i:i + chromadb_batch_size]
            batch_embs = capped_embeddings[i:i + chromadb_batch_size]
            batch_num = (i // chromadb_batch_size) + 1
            total_batches = (len(texts) + chromadb_batch_size - 1) // chromadb_batch_size
            
            try:
                # Use add_texts with pre-computed embeddings
                # This bypasses re-encoding and uses our cached embeddings
                vector_db._collection.add(
                    documents=batch_texts,
                    metadatas=batch_metas, #type: ignore
                    embeddings=batch_embs, #type: ignore
                    ids=[
                        f"{run_id}_{total_saved + j}"
                        for j in range(len(batch_texts))
                    ],
                )
                total_saved += len(batch_texts)
                
                # Progress logging
                if batch_num % 3 == 0 or total_saved == len(texts):
                    elapsed = time.time() - t5
                    logger.info(
                        f"  ChromaDB save progress: {total_saved}/{len(texts)} chunks "
                        f"[{elapsed:.1f}s elapsed, avg {elapsed/total_saved:.3f}s/chunk]"
                    )
                    
                    if progress_callback:
                        progress_callback(
                            f"Lưu vào ChromaDB: {total_saved}/{len(texts)} chunks — "
                            f"{elapsed:.0f}s"
                        )
                        
            except Exception as batch_e:
                logger.error(f"ChromaDB batch {batch_num} save failed: {batch_e}")
                # Fallback: try individual insertion
                for j, (text, meta, emb) in enumerate(zip(batch_texts, batch_metas, batch_embs)):
                    try:
                        vector_db._collection.add(
                            documents=[text],
                            metadatas=[meta],
                            embeddings=[emb],
                            ids=[f"doc_{total_saved + j}"],
                        )
                        total_saved += 1
                    except Exception as doc_e:
                        logger.error(f"Failed to save individual chunk: {doc_e}")
        
        elapsed_save = time.time() - t5
        logger.info(
            f"✓ ChromaDB save complete: {total_saved}/{len(texts)} chunks "
            f"in {elapsed_save:.1f}s (avg {elapsed_save/total_saved:.3f}s/chunk)"
        )
        _write_embedding_source_audit(
            _build_embedding_source_audit_record(
                topic=topic,
                content_type=content_type,
                collection_name=collection_name,
                run_id=run_id,
                chunks=relevant_chunks,
                raw_chunk_count=len(chunks),
                quality_chunk_count=quality_chunk_count_before_caps,
                relevant_chunk_count=relevant_chunk_count_before_cap,
                saved_chunk_count=total_saved,
                config_snapshot={
                    "CHUNK_SIZE": chunk_size,
                    "CHUNK_OVERLAP": chunk_overlap,
                    "MAX_CHUNKS_TO_EMBED": max_chunks_to_embed,
                    "MAX_CHUNKS_PER_DOMAIN": MAX_CHUNKS_PER_DOMAIN,
                    "VI_DOMAIN_CAP": VI_DOMAIN_CAP,
                    "EN_DOMAIN_CAP": EN_DOMAIN_CAP,
                    **_runtime_diversity_config(runtime_config),
                },
                diversity_status=diversity_status,
            )
        )
        
        if progress_callback:
            progress_callback(
                f"✓ Hoàn tất: {total_saved} đoạn đã lưu vào ChromaDB"
            )
            
    except Exception as e:
        logger.error(
            f"ChromaDB save failed after {time.time() - t5:.1f}s: {e}",
            exc_info=True
        )
        return False

    # Final logging
    elapsed = time.time() - t_start
    logger.info(
        f"✓ Ingestion complete — "
        f"{len(relevant_chunks)} chunks saved in {elapsed:.1f}s "
        f"(from {len(chunks)} raw chunks, "
        f"{removed_noise} noise + {removed_irrelevant} off-topic removed)"
    )
    
    return True
