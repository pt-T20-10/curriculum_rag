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


from app.ingestion.query_expansion import QueryExpansionAgent
from app.utils.log_config import setup_logger
from app.config import settings, get_embedding_model
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
CHUNK_SIZE = settings.CHUNK_SIZE
CHUNK_OVERLAP = settings.CHUNK_OVERLAP
MIN_RELEVANCE_BY_TYPE: dict[str, float] = {
    "scholarly": 0.30,
    "technical": 0.25,
    "practical": 0.22,
    "lifestyle": 0.22,
}

logger = setup_logger(name="Crawler", logfile="/backend/logs/crawler.log")

embedding_model = get_embedding_model()
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




def compute_relevance_scores(chunks, topic_emb, embedding_model):
    """
    Compute cosine similarity scores for chunks using batch encoding.
    
    Uses LangChain's embed_documents() which internally batches requests.
    While we can't control batch_size directly through the wrapper,
    the underlying HuggingFace model still processes in batches automatically.
    
    Args:
        chunks: List of Document objects with page_content
        topic_emb: Pre-computed bilingual topic embedding (numpy array)
        embedding_model: BAAI/bge-m3 embedding model (LangChain wrapper)
    
    Returns:
        List of float scores (same length as chunks)
    
    Performance:
        - Batch encoding via LangChain wrapper: ~60-80s for 300 chunks
        - Vectorized similarity: NumPy matrix operations
    """
    if not chunks:
        return []
    
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    
    # Batch encode all chunks using LangChain wrapper
    # LangChain's HuggingFaceEmbeddings internally uses batch processing
    chunk_texts = [c.page_content for c in chunks]
    chunk_embeddings = embedding_model.embed_documents(chunk_texts)
    
    # Convert to numpy arrays for vectorized operations
    chunk_embeddings_np = np.array(chunk_embeddings)
    topic_emb_np = np.array(topic_emb).reshape(1, -1)
    
    # Vectorized cosine similarity computation
    # Returns shape (n_chunks, 1) — flatten to 1D list
    similarities = cosine_similarity(chunk_embeddings_np, topic_emb_np)
    scores = similarities.flatten().tolist()
    
    return scores


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
        source     = chunk.metadata.get("source", "")
        raw_domain = urlparse(source).netloc.lower()

        # Normalize mobile subdomains to their desktop equivalent.
        # vi.m.wikipedia.org and vi.wikipedia.org serve the same content —
        # counting them separately would give one source double the intended quota.
        # Handles patterns: m.domain.com, vi.m.domain.com, en.m.domain.com
        domain = re.sub(
            r'^([a-z]{2,3}\.)?m\.',   # optional lang prefix + mobile subdomain
            lambda m: m.group(1) or '', # keep lang prefix, strip "m."
            raw_domain,
        )
        

        current = domain_counts.get(domain, 0)
        _TRUSTED_EDU_CAP_DOMAINS = (
            "arxiv.org", "stanford.edu", "mit.edu", "cs.cmu.edu",
            "cambridge.org", "harvard.edu", "geeksforgeeks.org",
            "wikipedia.org", "britannica.com",
        )
        max_for_domain = (
            max_per_domain * 2
            if any(t in domain for t in _TRUSTED_EDU_CAP_DOMAINS)
            else max_per_domain
        )
        if current < max_for_domain:
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

def process_deep_crawl(link_info: Dict[str, str]) -> List[Document]:
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
    results: List[Document] = []

    try:
        # ── PDF ──────────────────────────────────────────────────────────────
        # PDFs from trusted academic sources are stored without classification —
        # quality filtering happens downstream in is_quality_chunk() and
        # relevance scoring. PDF structure is already clean (no nav, no ads).
        if doc_type == "pdf":
            text = extract_pdf_text(url)
            if len(text) > 300:
                results.append(Document(
                    page_content=text,
                    metadata={"source": url, "type": "pdf"},
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
                metadata={"source": url, "type": "html", "depth": 0},
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

        sub_links = get_internal_links(soup, url, limit=CRAWL_MAX_SUB_LINKS)
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
                        "source": sub,
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
                        # Depth-2 uses minimum length check only —
                        # full classification too slow for this depth.
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
    progress_callback=None,
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
    crawled_count = 0
    total_links   = len(clean_links)
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
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
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

    logger.info(f"Quality filter: {len(chunks)} → {len(quality_chunks)} chunks ...")
    if progress_callback:
        progress_callback(
            f"Lọc chất lượng: còn {len(quality_chunks)} đoạn — "
            f"đang tính độ liên quan..."
        )
    # ── Step 4: Relevance filter ─────────────────────────────────────────────
    t4 = time.time()
    min_relevance = MIN_RELEVANCE_BY_TYPE.get(content_type, MIN_RELEVANCE_SCORE)
    logger.info(
    f"Relevance scoring {len(quality_chunks)} chunks "
    f"(threshold={min_relevance}, content_type={content_type})..."
    )
    embedding_model = get_embedding_model()

    # Bilingual topic embedding — average VI + EN để không filter EN chunks
    # Vấn đề: embed_query(topic_VI) có cosine similarity thấp với EN chunks
    # → Stanford PDF, CMU lecture bị loại hoàn toàn dù chất lượng cao
    try:
        _qe = QueryExpansionAgent()
        en_queries = _qe.expand_query_bilingual(topic, content_type=content_type).get("en", [])
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
    if score >= min_relevance
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
            f"All chunks scored below {min_relevance} — "
            f"consider lowering MIN_RELEVANCE_SCORE or broadening search queries"
        )
        # Fallback: use quality_chunks without relevance filter
        # to avoid complete ingestion failure
        logger.warning("Falling back to quality-only chunks (relevance filter bypassed)")
        relevant_chunks = quality_chunks

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
    logger.info(f"✓ ChromaDB save complete [{time.time() - t5:.1f}s]")
    if progress_callback:
        progress_callback(
            f"✓ Hoàn tất: {len(relevant_chunks)} đoạn đã lưu vào ChromaDB"
        )
    return True