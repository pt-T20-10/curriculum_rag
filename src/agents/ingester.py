"""
Ingestion Agent for AI Textbook Generator.

This agent orchestrates the document ingestion pipeline:
1. Clear old vector database
2. Expand user query into bilingual queries (Vietnamese + English)
3. Search web — vn-vn with VI queries, us-en with EN queries (parallel)
4. Filter and classify URLs
5. Crawl and ingest into ChromaDB
"""

import logging
import shutil
import os
import concurrent.futures

from src.graph.state import AgentState
from src.config import CHROMA_DB_DIR
from src.agents.query_expansion import QueryExpansionAgent
from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls
from src.ingestion.crawler import ingest_dynamic_data
from src import stop_signal

logger = logging.getLogger("IngestionNode")


def perform_ingestion(state: AgentState) -> dict:
    """
    Ingestion node: Populate vector database with relevant documents.
    
    Pipeline:
    1. Clear old database (clean slate)
    2. Expand query bilingually: VI queries for vn-vn, EN queries for us-en
    3. Search all query-region pairs in parallel
    4. Deduplicate → Filter URLs
    5. Crawl and ingest into ChromaDB
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with ingestion status message.
    """
    topic = state["request"]
    logger.info("=" * 60)
    logger.info(f"NODE: Ingestion - Starting for '{topic}'")
    logger.info("=" * 60)
    
    # Step 1: Clear old database
    if os.path.exists(CHROMA_DB_DIR):
        try:
            shutil.rmtree(CHROMA_DB_DIR)
            logger.info("Cleared old ChromaDB")
        except Exception as e:
            logger.warning(f"Could not clear DB: {e}")

    if stop_signal.is_stopped():
        return {"messages": ["⛔ Ingestion stopped by user"]}

    # Step 2: Bilingual query expansion
    # VI queries → vn-vn (Vietnamese sources)
    # EN queries → us-en (English academic sources)
    qe = QueryExpansionAgent()
    expanded = qe.expand_query_bilingual(topic)
    vi_queries = expanded["vi"]
    en_queries = expanded["en"]

    logger.info(f"VI queries: {vi_queries}")
    logger.info(f"EN queries: {en_queries}")

    # Step 3: Search all query-region pairs in parallel
    # 3 VI queries × vn-vn + 3 EN queries × us-en = 6 concurrent searches
    # Each search fetches 15 results → up to 90 raw, ~40-60 unique after dedup
    region_query_pairs = (
        [(q, "vn-vn") for q in vi_queries] +
        [(q, "us-en") for q in en_queries]
    )

    seen_urls: set[str] = set()
    all_raw_urls: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(search_web, q, 15, r): (q, r)
            for q, r in region_query_pairs
        }
        for future in concurrent.futures.as_completed(futures):
            if stop_signal.is_stopped():
                break
            q, r = futures[future]
            try:
                results = future.result()
                added = 0
                for res in results:
                    url = res.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_raw_urls.append(url)
                        added += 1
                logger.info(f"[{r}] '{q[:50]}': {len(results)} results, {added} new unique")
            except Exception as e:
                logger.warning(f"Search failed [{r}] '{q[:50]}': {e}")

    logger.info(f"Total unique URLs before filtering: {len(all_raw_urls)}")

    if stop_signal.is_stopped():
        return {"messages": ["⛔ Ingestion stopped by user"]}

    if not all_raw_urls:
        logger.error("No search results found from any region")
        return {"messages": ["✗ Ingestion failed: No search results"]}

    # Step 4: Filter URLs (parallel inside filter_and_classify_urls)
    clean_links = filter_and_classify_urls(all_raw_urls)
    logger.info(f"Found {len(clean_links)} valid links to crawl")

    if stop_signal.is_stopped():
        return {"messages": ["⛔ Ingestion stopped by user"]}

    if not clean_links:
        logger.error("No valid links after filtering")
        return {"messages": ["✗ Ingestion failed: All URLs filtered out"]}

    # Step 5: Deep crawl & ingest
    success = ingest_dynamic_data(topic, clean_links)
    
    if not success:
        logger.error("Crawling failed or no content found")
        return {"messages": ["✗ Ingestion failed: Crawling error"]}
    
    logger.info(f"✓ Ingestion complete with {len(clean_links)} sources")
    return {
        "messages": [f"✓ Ingestion complete: Database ready with {len(clean_links)} sources"]
    }