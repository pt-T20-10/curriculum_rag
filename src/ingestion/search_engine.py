"""
Web Search Engine for AI Textbook Generator.

Uses DuckDuckGo to search for relevant educational resources
without API keys or rate limits.

Quality strategy:
- Filter noise domains (sports, entertainment, social) before returning URLs
- Increase max_results_per_region to compensate for filtered URLs
- Two-region parallel search (vn-vn + us-en) for coverage
"""

import concurrent.futures
from typing import List, Dict
from urllib.parse import urlparse

from ddgs import DDGS

from src.log_config import setup_logger
from src import stop_signal

logger = setup_logger(name="SearchEngine", logfile="logs/search_engine.log")

# ---------------------------------------------------------------------------
# Noise domain filter — applied BEFORE returning URLs to ingestion pipeline.
# These domains consistently produce irrelevant content regardless of query.
# Expand this list as new noise sources are discovered.
# ---------------------------------------------------------------------------

# Keyword patterns matched against full URL (domain + path)
NOISE_URL_PATTERNS = (
    # Sports / betting
    "bongda", "soikeo", "socolive", "xoilac", "thethao",
    "sport", "football", "soccer", "nba", "nfl",
    "casino", "bet", "poker", "gambling", "lottery", "xoso",

    # Entertainment / social
    "manga", "anime", "phim", "truyen", "game",
    "nhac", "music", "lyric", "tiktok", "reels",

    # E-commerce / classified
    "shopee", "lazada", "tiki", "sendo", "mua-ban",
    "chotot", "muare", "enbac",

    # Job boards (unrelated content)
    "topcv", "vietnamworks", "careerbuilder", "jobstreet",

    # Social media (no crawlable text)
    "facebook.com", "twitter.com", "instagram.com",
    "tiktok.com", "zalo.me", "threads.net",

    # Video platforms
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion",

    # Admin / grant pages (noise from academic domains)
    "/grant", "/award", "/scholarship", "/travel-grant",
    "/career", "/job", "/vacancy", "/recruitment",
)


def _is_noise_url(url: str) -> bool:
    """
    Check if a URL matches any known noise pattern.

    Args:
        url: Full URL string

    Returns:
        True if URL should be excluded, False if it should be kept.
    """
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in NOISE_URL_PATTERNS)


def search_web(
    query: str,
    max_results: int = 10,
    region: str = "vn-vn",
) -> List[Dict[str, str]]:
    """
    Search web using DuckDuckGo for a single region.

    Applies noise URL filtering before returning results — callers receive
    only URLs that pass the domain/pattern blocklist.

    Args:
        query:       Search query string
        max_results: Maximum number of results to request from DDGS
        region:      DuckDuckGo region code (e.g. "vn-vn", "us-en")

    Returns:
        List of dicts with keys: title, href, body.
        Noise URLs are excluded from the list.
    """
    if stop_signal.is_stopped():
        logger.info(f"Search aborted (stop signal): '{query}' [{region}]")
        return []

    logger.info(f"Searching: '{query}' (region={region}, max={max_results})")

    raw_results: List[Dict[str, str]] = []

    try:
        with DDGS() as ddgs:
            ddg_gen = ddgs.text(
                query,
                region=region,
                safesearch="off",
                timelimit=None,
                max_results=max_results,
            )
            if ddg_gen:
                for r in ddg_gen:
                    raw_results.append({
                        "title": r.get("title", ""),
                        "href":  r.get("href", ""),
                        "body":  r.get("body", ""),
                    })

    except Exception as e:
        logger.error(f"DDGS search failed (region={region}): {e}", exc_info=True)

    # Apply noise filter
    filtered = [r for r in raw_results if not _is_noise_url(r.get("href", ""))]
    noise_count = len(raw_results) - len(filtered)

    if noise_count > 0:
        logger.info(
            f"Noise filter: {len(raw_results)} → {len(filtered)} results "
            f"({noise_count} removed) [region={region}]"
        )
    else:
        logger.info(f"Found {len(filtered)} results (region={region})")

    return filtered


def search_web_multi_region(
    query: str,
    max_results_per_region: int = 30,
) -> List[str]:
    """
    Search DuckDuckGo in parallel across Vietnamese and English regions.

    Increased default max_results_per_region (15 → 30) to compensate for
    URLs removed by the noise filter — net useful URLs remains similar
    while noise is excluded early.

    Deduplication is done on URL to avoid crawling the same page twice.

    Args:
        query:                  Search query (from QueryExpansion)
        max_results_per_region: Raw results to request per region before filtering.
                                Default 30 → up to 50 raw, ~30-40 after noise filter.

    Returns:
        Deduplicated list of noise-filtered URLs from both regions,
        preserving result-rank order (vn-vn first, then us-en).
    """
    regions = [
        ("vn-vn", query),  # Vietnamese sources — local context, direct relevance
        ("us-en", query),  # English sources — academic/technical depth
    ]

    all_results: List[Dict[str, str]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(search_web, q, max_results_per_region, r): r
            for r, q in regions
        }
        for future in concurrent.futures.as_completed(futures):
            if stop_signal.is_stopped():
                break
            region = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
                logger.info(f"Region {region}: {len(results)} filtered results collected")
            except Exception as e:
                logger.warning(f"Region {region} failed: {e}")

    # Deduplicate by href while preserving insertion order
    seen: set[str] = set()
    unique_urls: List[str] = []
    for r in all_results:
        url = r.get("href", "")
        if url and url not in seen:
            seen.add(url)
            unique_urls.append(url)

    logger.info(
        f"Multi-region search complete: {len(unique_urls)} unique URLs "
        f"(from up to {max_results_per_region * len(regions)} raw, after noise filter)"
    )
    return unique_urls