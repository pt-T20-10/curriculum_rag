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
from src.config import URL_FILTER_MAX_WORKERS
import concurrent.futures
import requests

from src.log_config import setup_logger

logger = setup_logger(name="URLFilter", logfile="logs/url_filter.log")

# ---------------------------------------------------------------------------
# Static blocklists — checked without network calls
# ---------------------------------------------------------------------------

# Domains that produce noise, require login, or block crawling
BLACKLIST_DOMAINS = [
    # Social media
    "facebook.com", "twitter.com", "instagram.com",
    "tiktok.com", "youtube.com", "youtu.be",
    "linkedin.com", "pinterest.com", "reddit.com",
    "zalo.me", "threads.net", "vimeo.com",

    # E-commerce
    "shopee.vn", "tiki.vn", "lazada.vn", "sendo.vn",
    "amazon.com", "ebay.com", "aliexpress.com",

    # Course platforms (login-gated content)
    "udemy.com", "coursera.org", "edx.org",
    "skillshare.com", "pluralsight.com",

    # Login / account subdomains
    "login.", "signup.", "account.", "signin.", "auth.",
    "register.", "checkout.",

    # Sports / betting
    "bongda", "soikeo", "socolive", "xoilac",
    "thethao", "casino", "bet365", "w88",

    # Stock photo (watermarked images, no useful text)
    "shutterstock.com", "gettyimages.com",
    "istockphoto.com", "alamy.com",

    # Ads / tracking
    "googleadservices.com", "doubleclick.net",
    "adnxs.com", "outbrain.com",
]

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
    "/cdn-cgi/",                    # Cloudflare internal
    "/wp-json/",                    # WordPress API
    "/grant", "/award",             # Grant/admin pages
    "/scholarship", "/travel-grant",
    "/career", "/job", "/vacancy",
    "/advertisement", "/ads/",
    "/privacy", "/terms", "/cookie",
    "/sitemap",
]

# User agent to mimic real browser
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}


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
        full   = (domain + path).lower()

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


def filter_and_classify_urls(urls: List[str]) -> List[Dict[str, str]]:
    """
    Filter and classify URLs into valid crawlable resources.

    Pipeline:
    1. Deduplicate
    2. Static validation  (domain / extension / path keyword blocklists)
    3. Dynamic validation (HTTP content-type probe, parallel)
    4. Classification     (pdf vs html)

    Args:
        urls: Raw URL list from search_web_multi_region()

    Returns:
        List of dicts: [{"url": "...", "type": "pdf|html"}, ...]
        Only URLs that pass all filters and have a supported content type.
    """
    # Step 1: Deduplicate
    unique_urls = list(dict.fromkeys(urls))  # preserves insertion order
    logger.info(f"Dedup: {len(urls)} → {len(unique_urls)} unique URLs")

    # Step 2: Static filter
    candidate_urls = [u for u in unique_urls if is_valid_url_static(u)]
    removed_static = len(unique_urls) - len(candidate_urls)
    logger.info(
        f"Static filter: {len(unique_urls)} → {len(candidate_urls)} URLs "
        f"({removed_static} removed)"
    )

    if not candidate_urls:
        logger.warning("No URLs survived static filter")
        return []

    # Step 3 & 4: Dynamic content-type check (parallel)
    clean_urls: List[Dict[str, str]] = []
    lock = Lock()

    def check_and_collect(url: str) -> None:
        doc_type = check_url_content_type(url)
        if doc_type:
            with lock:
                clean_urls.append({"url": url, "type": doc_type})

    with concurrent.futures.ThreadPoolExecutor(max_workers=URL_FILTER_MAX_WORKERS) as executor:
        futures = [executor.submit(check_and_collect, url) for url in candidate_urls]
        concurrent.futures.wait(futures)

    # Count by type for logging
    pdf_count  = sum(1 for u in clean_urls if u["type"] == "pdf")
    html_count = sum(1 for u in clean_urls if u["type"] == "html")
    logger.info(
        f"Dynamic filter: {len(candidate_urls)} → {len(clean_urls)} valid links "
        f"(PDF: {pdf_count}, HTML: {html_count})"
    )

    return clean_urls