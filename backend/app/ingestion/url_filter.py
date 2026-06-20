"""
URL Filter for AI Textbook Generator.

Filters and classifies URLs to ensure only valid, crawlable
educational resources are processed by the crawler.

Two-stage pipeline:
1. Static validation  — domain/extension/pattern blocklist, no network call
2. Dynamic validation — HTTP content-type check, determines pdf vs html

Quality strategy:
- Expanded domain blocklists to match search_engine noise patterns
- Added topic-relevance hint check via URL path keywords
- Consistent with search_engine.py NOISE_URL_PATTERNS
"""

from urllib.parse import urlparse
from typing import List, Dict, Optional
from threading import Lock
from app.config import settings

URL_FILTER_MAX_WORKERS = settings.URL_FILTER_MAX_WORKERS
from app.ingestion.search_engine import score_search_result
import concurrent.futures
import requests

from app.utils.log_config import setup_logger

logger = setup_logger(name="URLFilter", logfile="logs/url_filter.log")


SNIPPET_SCORE_THRESHOLD: float = settings.MIN_SNIPPET_SCORE
# ---------------------------------------------------------------------------
# Static blocklists — checked without network calls
# ---------------------------------------------------------------------------

# Domains that NEVER contain educational content regardless of query.
# Keep this list SHORT — noise filtering is handled by snippet scoring.
# Only add domains that are: login-gated, watermarked, or fundamentally
# non-educational (social media, e-commerce, job boards, stock photos).
BLACKLIST_DOMAINS = [
    # Social media
    "facebook.com", "twitter.com", "instagram.com",
    "tiktok.com", "youtube.com", "youtu.be",
    "linkedin.com", "pinterest.com", "reddit.com",
    "zalo.me", "threads.net", "vimeo.com",

    # E-commerce
    "shopee.vn", "tiki.vn", "lazada.vn", "sendo.vn",
    "amazon.com", "ebay.com", "aliexpress.com",

    # Login-gated course platforms
    "udemy.com", "coursera.org", "edx.org",
    "skillshare.com", "pluralsight.com",

    # Login-gated document sharing
    "scribd.com", "academia.edu", "123doc.net",
    "tailieu.vn", "slideshare.net",

    # Stock photo (watermarked)
    "shutterstock.com", "gettyimages.com",
    "istockphoto.com", "alamy.com",

    # Paywall academic (only reference lists accessible)
    "springer.com", "ieee.org", "sciencedirect.com",
    "wiley.com", "tandfonline.com", "jstor.org",

    # Ads / tracking
    "googleadservices.com", "doubleclick.net",
    
    "github.com", "gitlab.com", "bitbucket.org",  # code hosting, not educational content
    
    "branddomainsforsale.com",
    "atonu.net",
    
    "nguyenvanhieu.vn",      # personal blog, chỉ list tài liệu
    "glints.com",            # job platform
    "topcv.vn",              # job platform  
    "itviec.com",            # job platform
    "baomoi.com",            # news aggregator
    "vnexpress.net",         # news aggregator — educational content rất ít
    "marketingai.vn",        # marketing blog
    "dichvuseohot.com",      # SEO blog
    "cuuduongthancong.com",  # student sharing site (noisy)
    "blog.baitaptracnghiem.com", 
    "baitaptracnghiem.com",        
    "tracnghiem.net",             
    "tracnghiem.vn",
    "dethi.com",
    "vndoc.com",                   
    "taimienphi.vn",             
    "123doc.net",                
    "tailieu.vn",               
    "metaisach.com",              
    "zbook.vn",                 
    "zun.vn",        
     # High school lesson plan / solution / exam sites (VI)
    "kenhgiaovien.com",    # THCS/THPT lesson plans
    "giaoanmau.com",       # lesson plan templates
    "loigiaihay.com",      # high school exercise solutions
    "hoc24.vn",            # student Q&A forum
    "vietjack.com",        # high school study guides
    "dethi.org",           # exam question bank
    "sgkvn.com",           # THCS textbook content
    "loigiai.io",          # solution aggregator
    "giaitoan.com",        # math solution site
    "toanmath.com",        # math exercise site
]

# ---------------------------------------------------------------------------
# Source-Aware Whitelist — per content_type priority boost
# URLs from these domains get automatic score boost in snippet scoring,
# bypassing the MIN_SNIPPET_SCORE threshold entirely.
# ---------------------------------------------------------------------------
WHITELIST_DOMAINS: dict[str, tuple[str, ...]] = {
    "scholarly": (
    "wikipedia.org",
    "openstax.org",
    "ocw.mit.edu",
    "arxiv.org",
    "ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "encyclopedia.com",
    "britannica.com",
    ),
    "technical": (
        "wikipedia.org",    
        "geeksforgeeks.org",
        "arxiv.org",
        "docs.python.org",
        "developer.mozilla.org",
    ),
    "practical": (
        "wikihow.com",
        "instructables.com",
    ),
    "lifestyle": (
        "wikihow.com",
        "instructables.com",
        "healthline.com",
    ),
}


# File extensions that cannot be processed as text
BLACKLIST_EXTENSIONS = [
    # Archives
    ".zip", ".rar", ".7z", ".tar", ".gz",
    # Executables
    ".exe", ".msi", ".dmg", ".iso", ".apk",
    # Media
    ".mp4", ".mp3", ".avi", ".mov", ".wav", ".flac",
    # Images (handled separately by illustrator, not ingester)
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
    # Office (no plain-text extraction in crawler)
    ".ppt", ".pptx", ".xls", ".xlsx",
    # Misc binary
    ".bin", ".dat", ".db",
]

# URL path keywords that indicate non-content pages
BLACKLIST_PATH_KEYWORDS = [
    "/tag/", "/tags/",
    "/category/", "/categories/",
    "/author/", "/user/",
    "/login", "/logout", "/register", "/signup",
    "/search", "/cart", "/checkout",
    "/feed", "/rss",
    "/cdn-cgi/",                  
    "/wp-json/",                   
    "/grant", "/award",             
    "/scholarship", "/travel-grant",
    "/career", "/job", "/vacancy",
    "/advertisement", "/ads/",
    "/privacy", "/terms", "/cookie",
    "/sitemap",
    "/nextsem",
    "/pages/",
    "/subjects/",
    "/catalog/",
    "/about",
    "/news/",
    "/byline/",
    "/blog/category/",             
    "/collections/",  
    "/tour", 
    "/du-lich",            
]

# User agent to mimic real browser
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}

# Minimum snippet score to proceed to dynamic content-type check.
# URLs below this threshold are rejected without a network probe.
# Populated by search_engine.score_search_result() upstream.
# Only applied when snippet metadata is available — falls back to
# static-only validation when snippet is absent (e.g. direct URL input).



def is_valid_url_static(url: str) -> bool:
    """
    Static validation: Check domain, extension, and path keywords.
    No network call — fast O(n) string matching.

    Checks performed:
    1. URL must be parseable
    2. Domain must not be in BLACKLIST_DOMAINS
    3. Path extension must not be in BLACKLIST_EXTENSIONS
    4. Path must not contain BLACKLIST_PATH_KEYWORDS

    Args:
        url: URL string to validate

    Returns:
        True if URL passes all static checks, False otherwise.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path   = parsed.path.lower()
       

        # Check 1: domain blocklist
        for bad_domain in BLACKLIST_DOMAINS:
            if bad_domain in domain:
                logger.debug(f"Blocked domain '{bad_domain}': {url[:60]}")
                return False

        # Check 2: extension blocklist
        for ext in BLACKLIST_EXTENSIONS:
            if path.endswith(ext):
                logger.debug(f"Blocked extension '{ext}': {url[:60]}")
                return False

        # Check 3: path keyword blocklist
        for keyword in BLACKLIST_PATH_KEYWORDS:
            if keyword in path:
                logger.debug(f"Blocked path keyword '{keyword}': {url[:60]}")
                return False

        return True

    except Exception:
        return False


def check_url_content_type(url: str) -> Optional[str]:
    """
    Dynamic validation: Determine content type via HTTP GET (stream mode).

    Uses stream=True to fetch only headers without downloading the full body.
    Falls back gracefully on timeout or connection errors.

    Args:
        url: URL to probe

    Returns:
        'pdf'  — content-type is application/pdf
        'html' — content-type is text/html
        None   — other content type, non-200 status, or network error
    """
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=5,
            stream=True,    # headers only, don't download body
            allow_redirects=True,
        )

        # Close connection immediately after reading headers
        response.close()

        if response.status_code != 200:
            logger.debug(f"Non-200 ({response.status_code}): {url[:60]}")
            return None

        content_type = response.headers.get("Content-Type", "").lower()

        if "application/pdf" in content_type:
            return "pdf"
        elif "text/html" in content_type:
            return "html"
        else:
            logger.debug(f"Unsupported content-type '{content_type}': {url[:60]}")
            return None

    except requests.exceptions.Timeout:
        logger.debug(f"Timeout checking: {url[:60]}")
        return None
    except Exception as e:
        logger.debug(f"Content-type check failed for {url[:60]}: {e}")
        return None


def filter_and_classify_urls(
    urls: List[str],
    scored_results: Optional[List[Dict[str, str]]] = None,
    topic: str = "",
    content_type: str = "technical",   # ← thêm parameter
    min_snippet_score: float | None = None,
    max_workers: int | None = None,
) -> List[Dict[str, str]]:
    """
    Filter and classify URLs into valid crawlable resources.

    Pipeline:
    1. Deduplicate
    2. Whitelist check — URLs from trusted domain list for this content_type
       bypass snippet scoring entirely (guaranteed crawl)
    3. Snippet pre-filter — rejects low-quality URLs before network probe
    4. Static validation  — domain/extension/path keyword blocklists
    5. Dynamic validation — HTTP content-type probe, parallel
    6. Classification     — pdf vs html

    Args:
        urls:           Raw URL list from search results.
        scored_results: Optional DDGS result dicts with 'href', 'title', 'body'.
        topic:          User topic string for snippet scoring context.
        content_type:   One of "scholarly"|"technical"|"practical"|"lifestyle"
                        — determines which whitelist domain set to apply.

    Returns:
        List of dicts: [{"url": "...", "type": "pdf|html"}, ...]
    """
    threshold = SNIPPET_SCORE_THRESHOLD if min_snippet_score is None else min_snippet_score
    worker_count = URL_FILTER_MAX_WORKERS if max_workers is None else max_workers

    # Step 1: Deduplicate
    unique_urls = list(dict.fromkeys(urls))
    logger.info(f"Dedup: {len(urls)} → {len(unique_urls)} unique URLs")

    # Step 2: Whitelist check — split into guaranteed + candidates
    whitelist = WHITELIST_DOMAINS.get(content_type, ())
    whitelisted_urls: List[str] = []
    remaining_urls:   List[str] = []

    for u in unique_urls:
        u_lower = u.lower()
        if any(domain in u_lower for domain in whitelist):
            whitelisted_urls.append(u)
        else:
            remaining_urls.append(u)

    if whitelisted_urls:
        logger.info(
            f"Whitelist ({content_type}): {len(whitelisted_urls)} URLs bypass "
            f"snippet filter — {len(remaining_urls)} remain for scoring"
        )

    # Step 3: Snippet pre-filter on non-whitelisted URLs
    if scored_results and remaining_urls:
        score_map: Dict[str, float] = {}
        for r in scored_results:
            href = r.get("href", "")
            if href and href not in score_map:
                score_map[href] = score_search_result(r, topic or r.get("_topic", ""))

        before_snippet = len(remaining_urls)
        remaining_urls = [
            u for u in remaining_urls
            if score_map.get(u, threshold) >= threshold
        ]
        removed_snippet = before_snippet - len(remaining_urls)
        if removed_snippet > 0:
            logger.info(
                f"Snippet pre-filter: {before_snippet} → {len(remaining_urls)} URLs "
                f"({removed_snippet} low-quality removed before network probe)"
            )

    # Merge whitelisted + scored survivors
    unique_urls = whitelisted_urls + remaining_urls

    # Step 4: Static filter
    candidate_urls = [u for u in unique_urls if is_valid_url_static(u)]
    removed_static = len(unique_urls) - len(candidate_urls)
    logger.info(
        f"Static filter: {len(unique_urls)} → {len(candidate_urls)} URLs "
        f"({removed_static} removed)"
    )

    if not candidate_urls:
        logger.warning("No URLs survived static filter")
        return []

    # Step 5 & 6: Dynamic content-type check (unchanged)
    clean_urls: List[Dict[str, str]] = []
    lock = Lock()

    def check_and_collect(url: str) -> None:
        doc_type = check_url_content_type(url)
        if doc_type:
            with lock:
                clean_urls.append({"url": url, "type": doc_type})

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:
        futures = [
            executor.submit(check_and_collect, url)
            for url in candidate_urls
        ]
        concurrent.futures.wait(futures)

    pdf_count  = sum(1 for u in clean_urls if u["type"] == "pdf")
    html_count = sum(1 for u in clean_urls if u["type"] == "html")
    logger.info(
        f"Dynamic filter: {len(candidate_urls)} → {len(clean_urls)} valid links "
        f"(PDF: {pdf_count}, HTML: {html_count})"
    )

    return clean_urls
