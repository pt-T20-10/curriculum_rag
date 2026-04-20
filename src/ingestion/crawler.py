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
import re
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
from src.agents.query_expansion import QueryExpansionAgent

from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR, CRAWL_MAX_WORKERS, CRAWL_MAX_SUB_LINKS, MIN_CHUNK_CHARS, MIN_ALPHA_RATIO, MAX_DIGIT_RATIO, MIN_RELEVANCE_SCORE, MAX_CITATION_LINE_RATIO, MAX_DUPLICATE_LINE_RATIO, MIN_RELEVANCE_SCORE, MAX_BOOKING_SIGNALS, MAX_CHUNKS_PER_DOMAIN, CRAWL_MAX_DEPTH2_LINKS
from src.ingestion.url_filter import WHITELIST_DOMAINS
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
    chunks: List[Document],
    topic_embedding: np.ndarray,
    embedding_model,
) -> List[float]:
    """
    Compute cosine similarity between each chunk and the topic query.

    Embeddings are computed in a single batch call where possible.
    Falls back to per-chunk calls if batch is unavailable.

    Args:
        chunks:          List of Document chunks to score
        topic_embedding: Pre-computed topic embedding vector (np.ndarray).
                         Compute once in the caller and reuse across calls.
        embedding_model: HuggingFaceEmbeddings instance from get_embedding_model()

    Returns:
        List of float scores (same length as chunks), range 0.0–1.0.
        Returns list of 1.0 (pass-through) on any embedding error.
    """
    try:
        topic_emb = topic_embedding
        topic_norm = np.linalg.norm(topic_emb)

        if topic_norm == 0:
            logger.warning("Pre-computed topic embedding is zero vector — skipping relevance filter")
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


def _apply_domain_diversity_cap(
    chunks: List[Document],
    max_per_domain: int,
) -> List[Document]:
    """
    Enforce a per-domain chunk cap to prevent any single source from
    dominating the ChromaDB corpus.

    Domain-agnostic — applies equally to all sources regardless of
    content type or topic. Preserves insertion order so the highest-
    relevance chunks (sorted upstream) are kept and later chunks from
    the same domain are dropped when the cap is reached.

    Args:
        chunks:         Relevance-filtered chunk list.
        max_per_domain: Maximum chunks retained per unique domain.

    Returns:
        Capped chunk list with domain diversity enforced.
    """
    domain_counts: dict[str, int] = {}
    capped: List[Document] = []

    for chunk in chunks:
        source  = chunk.metadata.get("source", "")
        domain  = urlparse(source).netloc.lower()
        current = domain_counts.get(domain, 0)

        if current < max_per_domain:
            domain_counts[domain] = current + 1
            capped.append(chunk)

    removed = len(chunks) - len(capped)
    if removed > 0:
        top_domains = sorted(domain_counts.items(), key=lambda x: -x[1])[:5]
        logger.info(
            f"Domain diversity cap ({max_per_domain}/domain): "
            f"{len(chunks)} → {len(capped)} chunks ({removed} removed). "
            f"Top domains: {[f'{d}={c}' for d, c in top_domains]}"
        )
    return capped

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


def _is_content_page(text: str) -> bool:
    """
    Determine whether a crawled HTML page contains substantive educational
    content, as opposed to a homepage, navigation hub, or landing page.

    Four complementary signals are evaluated — a page must pass ALL of them
    to be classified as a content page worth storing in ChromaDB:

    Signal 1 — Minimum length:
        Homepages and nav hubs extract to very short text after BeautifulSoup
        strips scripts/nav/footer. A genuine article or chapter page produces
        at least MIN_ROOT_CONTENT_CHARS characters of body text.

    Signal 2 — Long line ratio:
        Navigation pages consist mostly of short anchor texts (menu items,
        breadcrumbs, sidebar links). Content pages contain prose paragraphs
        that span many words and exceed 80 characters per line.

    Signal 3 — Sentence punctuation ratio:
        Prose ends sentences with '.', '!', or '?'. Navigation menus and
        course index pages rarely contain sentence-ending punctuation.
        A low ratio indicates link-list content rather than explanatory text.

    Signal 4 — Word diversity:
        Navigation menus repeat the same anchor words (Home, About, Course,
        Chapter, Next, Previous). Educational content pages use a rich and
        varied vocabulary. Low unique/total word ratio flags nav-heavy pages.

    Args:
        text: Raw text extracted by fetch_text_from_url() after BeautifulSoup
              stripping of script/style/nav/footer tags.

    Returns:
        True  — page passes all four signals → worth storing as a Document.
        False — page fails one or more signals → skip root, still crawl sublinks.
    """
    stripped = text.strip()

    # Signal 1: minimum character length
    if len(stripped) < MIN_ROOT_CONTENT_CHARS:
        return False

    lines = [l.strip() for l in stripped.split('\n') if l.strip()]
    if not lines:
        return False

    # Signal 2: long line ratio (prose paragraphs vs short nav links)
    long_lines = sum(1 for l in lines if len(l) > 80)
    if long_lines / len(lines) < MIN_LONG_LINE_RATIO:
        return False

    # Signal 3: sentence-ending punctuation ratio
    punct_lines = sum(1 for l in lines if l[-1] in '.!?')
    if punct_lines / len(lines) < MIN_SENTENCE_PUNCT_RATIO:
        return False

    # Signal 4: word diversity (unique/total ratio)
    words = [w.lower() for w in stripped.split() if len(w) > 2]
    if len(words) > 20:
        diversity = len(set(words)) / len(words)
        if diversity < MIN_WORD_DIVERSITY_RATIO:
            return False

    return True


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

def process_deep_crawl(link_info: Dict[str, str]) -> List[Document]:
    """
        Process a single root URL with adaptive depth crawling.

        PDF: extract text with PyMuPDF (or pypdf fallback).
        HTML: extract root page + sublinks with content-driven depth logic:
            - Root page passes _is_content_page()  → stored, sublinks crawled
            - Root page fails _is_content_page()   → skipped, sublinks crawled
            - Depth-1 passes _is_content_page()    → stored, no further crawl
            - Depth-1 fails _is_content_page()     → skipped, depth-2 triggered
        Depth-2 is content-driven — no domain hardcoding required.

        Args:
            link_info: Dict with keys 'url' (str) and 'type' ('pdf' | 'html')

        Returns:
            List of LangChain Document objects. Empty list on failure or stop signal.
        """
    url          = link_info["url"]
    doc_type     = link_info["type"]
    content_type = link_info.get("content_type", "technical")
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
            if _is_content_page(main_text):
                logger.info(f"[ROOT] {url[:60]} ({len(main_text)} chars)")
                results.append(Document(
                    page_content=main_text,
                    metadata={"source": url, "type": "html", "depth": 0},
                ))
                root_is_nav = False   # ← thêm
            else:
                logger.info(
                    f"[ROOT/NAV] {url[:60]} ({len(main_text)} chars) "
                    f"— low content density, root skipped, sublinks will be crawled"
                )
                root_is_nav = True   # ← thêm

            if stop_signal.is_stopped():
                return results

            if soup:
                sub_links = get_internal_links(soup, url, limit=CRAWL_MAX_SUB_LINKS)
                if sub_links:
                    logger.info(f"  ↳ Crawling {len(sub_links)} sub-links from {url[:50]}")
                    for sub in sub_links:
                        if stop_signal.is_stopped():
                            return results

                        sub_text, sub_soup = fetch_text_from_url(sub)

                        if _is_content_page(sub_text):
                            results.append(Document(
                                page_content=sub_text,
                                metadata={
                                    "source": sub,
                                    "type":   "html",
                                    "depth":  1,
                                    "parent": url,
                                },
                            ))
                        elif root_is_nav and sub_soup is not None and not stop_signal.is_stopped():
                            # Depth-2 only when root was also nav — avoids
                            # unnecessary deep crawl when root had real content.
                            depth2_links = get_internal_links(
                                sub_soup, sub, limit=CRAWL_MAX_DEPTH2_LINKS
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
                                if len(d2_text) > 500:
                                    results.append(Document(
                                        page_content=d2_text,
                                        metadata={
                                            "source": d2_url,
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
    # Inject content_type into each link dict so process_deep_crawl
    # can check whitelist without a separate parameter channel.
    for link in clean_links:
        link["content_type"] = content_type
    with concurrent.futures.ThreadPoolExecutor(max_workers=CRAWL_MAX_WORKERS) as executor:
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
    t4 = time.time()
    logger.info(
        f"Relevance scoring {len(quality_chunks)} chunks "
        f"(threshold={MIN_RELEVANCE_SCORE})..."
    )
    embedding_model = get_embedding_model()

    # Bilingual topic embedding — average VI + EN để không filter EN chunks
    # Vấn đề: embed_query(topic_VI) có cosine similarity thấp với EN chunks
    # → Stanford PDF, CMU lecture bị loại hoàn toàn dù chất lượng cao
    try:
        _qe = QueryExpansionAgent()
        en_queries = _qe.expand_query_bilingual(topic).get("en", [])
        en_topic   = en_queries[0] if en_queries else topic

        topic_emb_vi  = np.array(embedding_model.embed_query(topic))
        topic_emb_en  = np.array(embedding_model.embed_query(en_topic))
        combined      = (topic_emb_vi + topic_emb_en) / 2
        norm          = np.linalg.norm(combined)
        topic_emb     = combined / norm if norm > 0 else topic_emb_vi

        logger.info(
            f"✓ Bilingual topic embedding: "
            f"VI='{topic}' + EN='{en_topic}'"
        )
    except Exception as e:
        logger.warning(f"Bilingual embedding failed ({e}) — falling back to VI only")
        topic_emb = np.array(embedding_model.embed_query(topic))

    scores = compute_relevance_scores(quality_chunks, topic_emb, embedding_model)

    relevant_chunks = [
        chunk for chunk, score in zip(quality_chunks, scores)
        if score >= MIN_RELEVANCE_SCORE
    ]
    removed_irrelevant = len(quality_chunks) - len(relevant_chunks)
    logger.info(
        f"Relevance filter: {len(quality_chunks)} → {len(relevant_chunks)} chunks "
        f"({removed_irrelevant} off-topic chunks removed) "
        f"[{time.time() - t4:.1f}s]"
    )

    # Apply domain diversity cap — prevents any single source from
    # dominating ChromaDB regardless of how many pages it has indexed.
    relevant_chunks = _apply_domain_diversity_cap(relevant_chunks, MAX_CHUNKS_PER_DOMAIN)
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
    t5 = time.time()
    logger.info(f"Saving {len(relevant_chunks)} chunks to ChromaDB...")
    try:
        Chroma.from_documents(
            documents=relevant_chunks,
            embedding=embedding_model,
            persist_directory=str(CHROMA_DB_DIR),
            collection_name="dynamic_context",
        )
        logger.info(f"✓ ChromaDB save complete [{time.time() - t5:.1f}s]")
    except Exception as e:
        logger.error(f"ChromaDB save failed after {time.time() - t5:.1f}s: {e}", exc_info=True)
        return False

    elapsed = time.time() - t_start
    logger.info(
        f"✓ Ingestion complete — "
        f"{len(relevant_chunks)} chunks saved in {elapsed:.1f}s "
        f"(from {len(chunks)} raw chunks, "
        f"{removed_noise} noise + {removed_irrelevant} off-topic removed)"
    )
    return True