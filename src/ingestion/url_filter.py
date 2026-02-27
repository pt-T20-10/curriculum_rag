"""
URL Filter for AI Textbook Generator.

Filters and classifies URLs to ensure only valid, crawlable
educational resources are processed.
"""

from urllib.parse import urlparse
from typing import List, Dict, Optional
from threading import Lock

import concurrent.futures
import requests

from src.log_config import setup_logger

logger = setup_logger(name="URLFilter", logfile="logs/url_filter.log")

# Domains to exclude (social media, e-commerce, login pages)
BLACKLIST_DOMAINS = [
    "facebook.com", "twitter.com", "instagram.com", "youtube.com", "tiktok.com", "linkedin.com",
    "shopee.vn", "tiki.vn", "lazada.vn", "sendo.vn",  # E-commerce
    "udemy.com", "coursera.org",  # Course platforms (often require login)
    "login.", "signup.", "account.", "signin."  # Login pages
]

# File extensions that cannot be processed as text
BLACKLIST_EXTENSIONS = [
    ".zip", ".rar", ".exe", ".iso",
    ".mp4", ".mp3", ".avi",
    ".jpg", ".jpeg", ".png", ".gif",
    ".ppt", ".pptx", ".xls", ".xlsx"
]

# User agent to mimic real browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def is_valid_url_static(url: str) -> bool:
    """
    Static validation: Check domain and file extension.
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL passes static filters, False otherwise.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        # Check blacklisted domains
        for bad_domain in BLACKLIST_DOMAINS:
            if bad_domain in domain:
                return False
        
        # Check blacklisted extensions
        for ext in BLACKLIST_EXTENSIONS:
            if path.endswith(ext):
                return False
        
        return True
    except Exception:
        return False


def check_url_content_type(url: str) -> Optional[str]:
    """
    Dynamic validation: Check content type via HTTP request.
    
    Uses GET with stream=True (more reliable than HEAD for many sites).
    
    Args:
        url: URL to check
        
    Returns:
        'pdf' for PDF files, 'html' for HTML pages, None for other/error.
    """
    try:
        # Stream=True: Only fetch headers, don't download body
        response = requests.get(url, headers=HEADERS, timeout=5, stream=True)
        
        if response.status_code != 200:
            return None
        
        content_type = response.headers.get('Content-Type', '').lower()
        
        # Close connection immediately
        response.close()
        
        if 'application/pdf' in content_type:
            return 'pdf'
        elif 'text/html' in content_type:
            return 'html'
        else:
            return None
            
    except Exception as e:
        logger.debug(f"Failed to check content type for {url}: {e}")
        return None


def filter_and_classify_urls(urls: List[str]) -> List[Dict[str, str]]:
    """
    Filter and classify URLs into valid crawlable resources.
    
    Pipeline:
    1. Remove duplicates
    2. Static validation (domain/extension blacklist)
    3. Dynamic validation (content-type check)
    4. Classification (pdf vs html)
    
    Args:
        urls: List of raw URLs from search results
        
    Returns:
        List of dicts with 'url' and 'type' (pdf/html) keys.
    """
    unique_urls = list(set(urls))
    

    candidate_urls = [url for url in unique_urls if is_valid_url_static(url)]
    logger.info(f"Static filter: {len(unique_urls)} → {len(candidate_urls)} URLs")
    
    if not candidate_urls:
        return []
    
 
    clean_urls = []
    lock = Lock()
    
    def check_and_collect(url: str) -> None:
        doc_type = check_url_content_type(url)
        if doc_type:
            with lock:
                clean_urls.append({"url": url, "type": doc_type})
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_and_collect, url) for url in candidate_urls]
        concurrent.futures.wait(futures)
    
    logger.info(f"Dynamic filter: {len(candidate_urls)} → {len(clean_urls)} valid links")
    return clean_urls