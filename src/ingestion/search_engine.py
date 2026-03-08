"""
Web Search Engine for AI Textbook Generator.

Uses DuckDuckGo to search for relevant educational resources
without API keys or rate limits.
"""

import concurrent.futures
from typing import List, Dict

from ddgs import DDGS

from src.log_config import setup_logger
from src import stop_signal

logger = setup_logger(name="SearchEngine", logfile="logs/search_engine.log")


def search_web(
    query: str,
    max_results: int = 10,
    region: str = "vn-vn"
) -> List[Dict[str, str]]:
    """
    Search web using DuckDuckGo for a single region.
    
    Args:
        query: Search query
        max_results: Maximum number of results to return
        region: DuckDuckGo region code (e.g. "vn-vn", "us-en")
        
    Returns:
        List of search results with title, href, and snippet.
    """
    if stop_signal.is_stopped():
        logger.info(f"Search aborted (stop signal): '{query}' [{region}]")
        return []

    logger.info(f"Searching for: '{query}' (region: {region})")

    results = []

    try:
        with DDGS() as ddgs:
            ddg_gen = ddgs.text(
                query,
                region=region,
                safesearch="off",
                timelimit=None,
                max_results=max_results
            )
            
            if ddg_gen:
                for r in ddg_gen:
                    results.append({
                        "title": r.get("title", ""),
                        "href":  r.get("href", ""),
                        "body":  r.get("body", "")
                    })
                    
    except Exception as e:
        logger.error(f"Search failed (region={region}): {e}", exc_info=True)
        
    logger.info(f"Found {len(results)} links (region: {region})")
    return results


def search_web_multi_region(
    query: str,
    max_results_per_region: int = 15,
) -> List[str]:
    """
    Search DuckDuckGo in parallel across Vietnamese and English regions.
    Deduplicates URLs before returning.

    Rationale:
    - vn-vn: Vietnamese content, directly relevant for local context
    - us-en: English academic/technical content, higher quality for NMF topics
    - No translation needed — Writer LLM reads English context natively

    Args:
        query: Search query (usually from QueryExpansion)
        max_results_per_region: Results to fetch per region (default 15 → up to 30 raw)

    Returns:
        Deduplicated list of URLs from both regions.
    """
    regions = [
        ("vn-vn", query),   # Vietnamese sources
        ("us-en", query),   # English sources — same query, LLM handles both
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
                logger.info(f"Region {region}: {len(results)} results collected")
            except Exception as e:
                logger.warning(f"Region {region} failed: {e}")

    # Deduplicate by URL while preserving order
    seen: set[str] = set()
    unique_urls: List[str] = []
    for r in all_results:
        url = r.get("href", "")
        if url and url not in seen:
            seen.add(url)
            unique_urls.append(url)

    logger.info(
        f"Multi-region search complete: {len(unique_urls)} unique URLs "
        f"(from up to {max_results_per_region * len(regions)} raw results)"
    )
    return unique_urls