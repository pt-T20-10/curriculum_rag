"""
Ingestion Agent for AI Textbook Generator.

This agent orchestrates the document ingestion pipeline:
1. Clear old vector database
2. Expand user query for better search results
3. Search web for relevant resources
4. Filter and classify URLs
5. Crawl and ingest into ChromaDB
"""

import logging
import shutil
import os

from src.graph.state import AgentState
from src.config import CHROMA_DB_DIR
from src.agents.query_expansion import QueryExpansionAgent
from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls
from src.ingestion.crawler import ingest_dynamic_data

logger = logging.getLogger("IngestionNode")


def perform_ingestion(state: AgentState) -> dict:
    """
    Ingestion node: Populate vector database with relevant documents.
    
    Pipeline:
    1. Clear old database (clean slate)
    2. Expand query for better search coverage
    3. Search web (Google/DuckDuckGo)
    4. Filter out junk URLs
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

    # Step 2: Query expansion (understand user intent)
    qe = QueryExpansionAgent()
    expanded_queries = qe.expand_query(topic)
    
    # Use best query (usually the first one)
    best_query = expanded_queries[0] if expanded_queries else topic
    logger.info(f"Optimized query: '{best_query}'")
    
    # Step 3: Web search
    raw_results = search_web(best_query, max_results=20)
    raw_urls = [r['href'] for r in raw_results]
    
    if not raw_urls:
        logger.error("No search results found")
        return {"messages": ["✗ Ingestion failed: No search results"]}

    # Step 4: Filter URLs
    clean_links = filter_and_classify_urls(raw_urls)
    logger.info(f"Found {len(clean_links)} valid links to crawl")
    
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