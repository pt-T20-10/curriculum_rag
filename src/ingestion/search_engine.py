"""
Web Search Engine for AI Textbook Generator.

Uses DuckDuckGo to search for relevant educational resources
without API keys or rate limits.
"""

from typing import List, Dict

from ddgs import DDGS

from src.log_config import setup_logger

logger = setup_logger(name="SearchEngine", logfile="logs/search_engine.log")


def search_web(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """
    Search web using DuckDuckGo.
    
    Args:
        query: Search query (typically expanded academic query)
        max_results: Maximum number of results to return
        
    Returns:
        List of search results with title, href, and snippet.
    """
    logger.info(f"Searching for: '{query}' (region: Vietnam)")
    
    results = []
    
    try:
        with DDGS() as ddgs:
            ddg_gen = ddgs.text(
                query,
                region="vn-vn",
                safesearch="off",
                timelimit=None,
                max_results=max_results
            )
            
            if ddg_gen:
                for r in ddg_gen:
                    results.append({
                        "title": r.get("title", ""),
                        "href": r.get("href", ""),
                        "body": r.get("body", "")
                    })
                    
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        
    logger.info(f"Found {len(results)} links")
    return results