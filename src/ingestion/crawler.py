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
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Set, Optional

import requests
import concurrent.futures
import numpy as np
from bs4 import BeautifulSoup

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.config import get_embedding_model

from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR
from src import stop_signal

logger = setup_logger(name="Crawler", logfile="logs/crawler.log")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Quality filter constants
# ---------------------------------------------------------------------------

# Minimum characters for a chunk to be considered meaningful content
MIN_CHUNK_CHARS = 200

# Minimum ratio of alphabetic characters (filters binary/numeric garbage)
MIN_ALPHA_RATIO = 0.55

# Maximum ratio of digit characters (filters data tables, PDF stream metadata)
MAX_DIGIT_RATIO = 0.40

# Minimum cosine similarity between chunk embedding and topic embedding.
# Chunks below this threshold are considered off-topic and discarded.
# Range 0.0–1.0. Typical values: 0.20 (lenient) to 0.35 (strict).
MIN_RELEVANCE_SCORE = 0.22


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

    return True


def compute_relevance_scores(
    chunks: List[Document],
    topic: str,
    embedding_model,
) -> List[float]:
    """
    Compute cosine similarity between each chunk and the topic query.

    Embeddings are computed in a single batch call where possible.
    Falls back to per-chunk calls if batch is unavailable.

    Args:
        chunks:          List of Document chunks to score
        topic:           User topic string used as the reference embedding
        embedding_model: HuggingFaceEmbeddings instance from get_embedding_model()

    Returns:
        List of float scores (same length as chunks), range 0.0–1.0.
        Returns list of 1.0 (pass-through) on any embedding error.
    """
    try:
        topic_emb = np.array(embedding_model.embed_query(topic))
        topic_norm = np.linalg.norm(topic_emb)

        if topic_norm == 0:
            logger.warning("Topic embedding is zero vector — skipping relevance filter")
            return [1.0] * len(chunks)

        # Batch embed all chunks
        texts = [c.page_content for c in chunks]
        chunk_embs = np.array(embedding_model.embed_documents(texts))

        # Vectorised cosine similarity
        dot_products  = chunk_embs @ topic_emb
        chunk_norms   = np.linalg.norm(chunk_embs, axis=1)
        denominators  = chunk_norms * topic_norm

        # Avoid division by zero
        scores = np.where(
            denominators > 0,
            dot_products / denominators,
            0.0,
        )
        return scores.tolist()

    except Exception as e:
        logger.warning(f"Relevance scoring failed ({e}) — skipping filter")
        return [1.0] * len(chunks)


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

        return "\n\n".join(text_parts), soup

    except Exception as e:
        logger.debug(f"Failed to fetch {url[:60]}: {e}")
        return "", None


# ---------------------------------------------------------------------------
# Deep crawl worker
# ---------------------------------------------------------------------------

def process_deep_crawl(link_info: Dict[str, str]) -> List[Document]:
    """
    Process a single root URL with depth-1 crawling.

    PDF: extract text with PyMuPDF (or pypdf fallback).
    HTML: extract root page + up to 5 internal sub-pages.

    Args:
        link_info: Dict with keys 'url' (str) and 'type' ('pdf' | 'html')

    Returns:
        List of LangChain Document objects.
        Empty list on failure or stop signal.
    """
    url      = link_info["url"]
    doc_type = link_info["type"]
    results: List[Document] = []

    try:
        # ── PDF ──────────────────────────────────────────────────────────────
        if doc_type == "pdf":
            text = extract_pdf_text(url)
            if len(text) > 300:
                results.append(Document(
                    page_content=text,
                    metadata={"source": url, "type": "pdf"},
                ))
            return results

        # ── HTML (depth-1) ───────────────────────────────────────────────────
        main_text, soup = fetch_text_from_url(url)

        if len(main_text) > 300:
            logger.info(f"[ROOT] {url[:60]} ({len(main_text)} chars)")
            results.append(Document(
                page_content=main_text,
                metadata={"source": url, "type": "html", "depth": 0},
            ))

            if stop_signal.is_stopped():
                return results

            if soup:
                sub_links = get_internal_links(soup, url, limit=5)
                if sub_links:
                    logger.info(f"  ↳ Crawling {len(sub_links)} sub-links from {url[:50]}")
                    for sub in sub_links:
                        if stop_signal.is_stopped():
                            return results
                        sub_text, _ = fetch_text_from_url(sub)
                        if len(sub_text) > 500:
                            results.append(Document(
                                page_content=sub_text,
                                metadata={
                                    "source": sub,
                                    "type":   "html",
                                    "depth":  1,
                                    "parent": url,
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
) -> bool:
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

    t_start = time.time()
    logger.info(
        f"Starting deep crawler "
        f"(max depth=1, 5 sub-links/page, {len(clean_links)} root URLs)..."
    )

    # ── Step 1: Parallel deep crawl ──────────────────────────────────────────
    all_docs: List[Document] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(process_deep_crawl, link)
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
                    all_docs.append(doc)

    if not all_docs:
        logger.error("No content crawled — check URL filter and network connectivity")
        return False

    logger.info(f"Crawled: {len(all_docs)} documents (roots + sub-pages)")

    # ── Step 2: Chunking ─────────────────────────────────────────────────────
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    chunks = text_splitter.split_documents(all_docs)
    logger.info(f"Chunked: {len(chunks)} total chunks")

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

    # ── Step 4: Relevance filter ─────────────────────────────────────────────
    logger.info(
        f"Relevance scoring {len(quality_chunks)} chunks "
        f"(threshold={MIN_RELEVANCE_SCORE})..."
    )
    embedding_model = get_embedding_model()
    scores = compute_relevance_scores(quality_chunks, topic, embedding_model)

    relevant_chunks = [
        chunk for chunk, score in zip(quality_chunks, scores)
        if score >= MIN_RELEVANCE_SCORE
    ]
    removed_irrelevant = len(quality_chunks) - len(relevant_chunks)
    logger.info(
        f"Relevance filter: {len(quality_chunks)} → {len(relevant_chunks)} chunks "
        f"({removed_irrelevant} off-topic chunks removed)"
    )

    if not relevant_chunks:
        logger.warning(
            f"All chunks scored below {MIN_RELEVANCE_SCORE} — "
            f"consider lowering MIN_RELEVANCE_SCORE or broadening search queries"
        )
        # Fallback: use quality_chunks without relevance filter
        # to avoid complete ingestion failure
        logger.warning("Falling back to quality-only chunks (relevance filter bypassed)")
        relevant_chunks = quality_chunks

    # ── Step 5: Save to ChromaDB ─────────────────────────────────────────────
    logger.info(f"Saving {len(relevant_chunks)} chunks to ChromaDB...")
    try:
        Chroma.from_documents(
            documents=relevant_chunks,
            embedding=embedding_model,
            persist_directory=str(CHROMA_DB_DIR),
            collection_name="dynamic_context",
        )
    except Exception as e:
        logger.error(f"ChromaDB save failed: {e}", exc_info=True)
        return False

    elapsed = time.time() - t_start
    logger.info(
        f"✓ Ingestion complete — "
        f"{len(relevant_chunks)} chunks saved in {elapsed:.1f}s "
        f"(from {len(chunks)} raw chunks, "
        f"{removed_noise} noise + {removed_irrelevant} off-topic removed)"
    )
    return True