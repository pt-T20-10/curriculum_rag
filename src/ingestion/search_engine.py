import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.log_config import setup_logger
from ddgs import DDGS

logger = setup_logger(name="Search Engine", logfile="logs/search_engine.log")


def search_web(query: str, max_results: int = 10):
    """
        Using DuckDuckGo search links
    """
    
    logger.info(f"Search for: '{query}' Region(Vietnam)...")
    
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
                    results.append(
                        {
                            "title": r.get("title",""),
                            "href": r.get("href",""),
                            "body": r.get("body","")
                        }
                    )
    except Exception as e:
        logger.error(f"Search Failed: {e}")
        
    logger.info(f"Final Result: Found {len(results)} links.")
    return results

