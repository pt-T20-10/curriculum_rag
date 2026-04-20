"""
Ingestion Agent for AI Textbook Generator.

This agent orchestrates the full document ingestion pipeline that populates
ChromaDB before the Planner runs. It is the first node in the workflow graph.

Pipeline:
    1. Clear old vector database (clean slate per run — prevents topic pollution
       across consecutive runs on different subjects)
    2. Expand user query bilingually via QueryExpansionAgent:
         VI queries → searched on vn-vn region (Vietnamese academic sources)
         EN queries → searched on us-en region (English academic/technical sources)
    3. Execute 6 parallel web searches (3 VI + 3 EN) via DuckDuckGo
       — preserves full result dicts (title, href, body) for snippet pre-filtering
    4. Deduplicate URLs, run static + snippet + dynamic URL filtering
    5. Deep-crawl valid URLs and ingest chunks into ChromaDB

The bilingual routing (VI queries → vn-vn, EN queries → us-en) is intentional:
using language-matched region codes improves result relevance for each language
beyond what a single unified query would achieve.
"""

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
from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR, SEARCH_RESULTS_PER_QUERY, SEARCH_MAX_WORKERS

logger = setup_logger(name="IngestionNode", logfile="logs/agents.log")


def perform_ingestion(state: AgentState) -> dict:
    """
    Ingestion node: populate ChromaDB with topic-relevant documents.

    Reads from state:
        request — user's topic string (drives query expansion + relevance scoring)

    Writes to state:
        messages — single-element list with ingestion status string

    Pipeline:
        1. Clear old ChromaDB directory (prevents previous-run contamination)
        2. Expand topic into 3 VI + 3 EN queries via QueryExpansionAgent
        3. Search all 6 query-region pairs in parallel — preserves full result
           dicts (title, href, body) for downstream snippet pre-filtering
        4. Deduplicate raw URLs, run static + snippet + dynamic URL filtering
           with topic context passed for accurate snippet scoring
        5. Deep-crawl valid URLs and ingest into ChromaDB via ingest_dynamic_data()

    Stop signal:
        Checked at three points: after DB clear, after search, after URL filter.

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict with a "messages" list entry indicating
        success (✓) or failure reason (✗).
    """
    topic = state["request"]
    logger.info("=" * 60)
    logger.info(f"NODE: Ingestion - Starting for '{topic}'")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1 — Clear old database
    # ------------------------------------------------------------------
    if os.path.exists(CHROMA_DB_DIR):
        try:
            shutil.rmtree(CHROMA_DB_DIR)
            logger.info("Cleared old ChromaDB")
        except Exception as e:
            logger.warning(f"Could not clear DB: {e}")

    if stop_signal.is_stopped():
        return {"messages": ["⛔ Ingestion stopped by user"]}

    # ------------------------------------------------------------------
    # Step 2 — Bilingual query expansion
    # ------------------------------------------------------------------
    qe       = QueryExpansionAgent()
    content_type = state.get("content_type", "technical")
    expanded = qe.expand_query_bilingual(topic, content_type=content_type)
    logger.info(f"Query expansion with content_type: '{content_type}'")
    vi_queries: list[str] = expanded["vi"]
    en_queries: list[str] = expanded["en"]

    logger.info(f"VI queries: {vi_queries}")
    logger.info(f"EN queries: {en_queries}")

    # ------------------------------------------------------------------
    # Step 3 — Parallel web search across all query-region pairs
    #
    # CHANGE: collect full result dicts (title + href + body) instead of
    # URLs only. Body snippets are required by filter_and_classify_urls()
    # for snippet pre-filtering — without them, Signal 2 (topic keyword
    # matching) in score_search_result() always receives an empty string.
    # ------------------------------------------------------------------
    region_query_pairs: list[tuple[str, str]] = (
        [(q, "vn-vn") for q in vi_queries] +
        [(q, "us-en") for q in en_queries]
    )

    seen_urls:           set[str]             = set()
    all_raw_urls:        list[str]            = []
    all_results_with_meta: list[dict]         = []  # ← NEW: full dicts for snippet scoring

    with concurrent.futures.ThreadPoolExecutor(max_workers=SEARCH_MAX_WORKERS) as executor:
        futures = {
            executor.submit(search_web, q, SEARCH_RESULTS_PER_QUERY, r): (q, r)
            for q, r in region_query_pairs
        }
        for future in concurrent.futures.as_completed(futures):
            if stop_signal.is_stopped():
                break
            q, r = futures[future]
            try:
                results = future.result()
                added   = 0
                for res in results:
                    url = res.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_raw_urls.append(url)
                        all_results_with_meta.append(res)  # ← NEW
                        added += 1
                logger.info(
                    f"[{r}] '{q[:50]}': {len(results)} results, {added} new unique"
                )
            except Exception as e:
                logger.warning(f"Search failed [{r}] '{q[:50]}': {e}")

    logger.info(f"Total unique URLs before filtering: {len(all_raw_urls)}")

    if stop_signal.is_stopped():
        return {"messages": ["⛔ Ingestion stopped by user"]}

    if not all_raw_urls:
        logger.error("No search results found from any region")
        return {"messages": ["✗ Ingestion failed: No search results"]}

    # ------------------------------------------------------------------
    # Step 4 — URL filtering
    #
    # CHANGE: pass scored_results and topic so filter_and_classify_urls()
    # can run snippet pre-filtering with correct topic context.
    # Previously called with all_raw_urls only → snippet scoring was
    # skipped entirely in the production flow.
    # ------------------------------------------------------------------
    clean_links = filter_and_classify_urls(
        all_raw_urls,
        scored_results=all_results_with_meta, 
        topic=topic,
        content_type=content_type,                     
    )
    logger.info(f"Found {len(clean_links)} valid links to crawl")

    if stop_signal.is_stopped():
        return {"messages": ["⛔ Ingestion stopped by user"]}

    if not clean_links:
        logger.error("No valid links after filtering")
        return {"messages": ["✗ Ingestion failed: All URLs filtered out"]}

    # ------------------------------------------------------------------
    # Step 5 — Deep crawl and ingest into ChromaDB
    # ------------------------------------------------------------------
    success = ingest_dynamic_data(topic, clean_links, content_type=content_type)

    if not success:
        logger.error("Crawling failed or no content found")
        return {"messages": ["✗ Ingestion failed: Crawling error"]}

    logger.info(f"✓ Ingestion complete with {len(clean_links)} sources")
    return {
        "messages": [
            f"✓ Ingestion complete: Database ready with {len(clean_links)} sources"
        ]
    }