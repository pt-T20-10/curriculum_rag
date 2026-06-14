"""
Ingester Agent for AI Textbook Generator.

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
from pathlib import Path

from typing import Any
from app.schemas.curriculum import AgentState
from app.config import settings

from app.ingestion.query_expansion import QueryExpansionAgent
from app.ingestion.search_engine import search_web
from app.ingestion.url_filter import filter_and_classify_urls
from app.ingestion.crawler import ingest_dynamic_data
from app.utils import stop_signal
from app.utils.log_config import setup_logger

TARGETED_CRAWL_QUERIES_PER_CHAPTER = settings.TARGETED_CRAWL_QUERIES_PER_CHAPTER
TARGETED_CRAWL_MAX_QUERIES         = settings.TARGETED_CRAWL_MAX_QUERIES

CHROMA_DB_DIR: Path = settings.CHROMA_DB_DIR
SEARCH_RESULTS_PER_QUERY = settings.SEARCH_RESULTS_PER_QUERY
SEARCH_MAX_WORKERS = settings.SEARCH_MAX_WORKERS

logger = setup_logger(name="IngestionNode", logfile="logs/agents.log")

_progress_callback = None


def set_ingestion_callback(callback) -> None:
    """
    Store a progress callback at module level.
    Called by stream_workflow before graph execution starts.

    Args:
        callback: Callable[[str], None] — receives progress message strings.
    """
    global _progress_callback
    _progress_callback = callback


def _get_ingestion_callback():
    """Retrieve the module-level progress callback."""
    return _progress_callback
def perform_ingestion(state: AgentState) -> dict:
    """
    Ingestion node: populate ChromaDB with topic-relevant documents.

    Reads from state:
        request — user's topic string (drives query expansion + relevance scoring)

    Writes to state:
        messages — single-element list with ingestion status string

    Pipeline:
        1. Clear old ChromaDB directory (prevents previous-run contamination)
        2. Expand topic into 6 VI + 6 EN queries via QueryExpansionAgent
        3. Search all 12 query-region pairs in parallel — preserves full result
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
    
    callback     = _get_ingestion_callback()
     # Use core_topic (extracted by Validator) for focused query expansion.
    # Falls back to raw request when core_topic is absent or empty.
    # Example: request="Python có bài tập" → core_topic="Python" gives
    # cleaner bilingual queries without requirement noise polluting the searches.
    topic        = state.get("core_topic", "") or state["request"]
    content_type = state.get("content_type", "technical")

    print(f"[DEBUG INGESTER] perform_ingestion START — topic='{topic}' callback={'set' if callback else 'NONE'}", flush=True)
    logger.info("=" * 60)
    logger.info(f"NODE: Ingestion - Starting for '{topic}'")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1 — Clear old database
    # ------------------------------------------------------------------
    print(f"[DEBUG INGESTER] Step 1: clearing ChromaDB", flush=True)
    if os.path.exists(CHROMA_DB_DIR):
        try:
            shutil.rmtree(CHROMA_DB_DIR)
            logger.info("Cleared old ChromaDB")
        except Exception as e:
            logger.warning(f"Could not clear DB: {e}")

    if stop_signal.is_stopped():
        print(f"[DEBUG INGESTER] STOPPED after Step 1", flush=True)
        return {"messages": ["⛔ Ingestion stopped by user"]}

    # ------------------------------------------------------------------
    # Step 2 — Bilingual query expansion
    # ------------------------------------------------------------------
    print(f"[DEBUG INGESTER] Step 2: expanding query bilingually", flush=True)
    query_expansion_agent = QueryExpansionAgent()
    expanded = query_expansion_agent.expand_query_bilingual(topic, content_type=content_type)

    vi_queries = expanded["vi"]
    en_queries = expanded["en"]

    logger.info(f"Query expansion with content_type: '{content_type}'")
    logger.info(f"VI queries: {vi_queries}")
    logger.info(f"EN queries: {en_queries}")
    if callback:
        callback(
            f"Đã tạo {len(vi_queries) + len(en_queries)} câu truy vấn "
            f"— đang tìm kiếm web..."
        )

    # ------------------------------------------------------------------
    # Step 2b — Curriculum-targeted queries (Targeted Crawling, Shift 3)
    #
    # After the user confirms the curriculum, state["curriculum"] contains
    # the confirmed CurriculumOutline. Extracting subsection search_query
    # fields as additional search seeds ensures ChromaDB receives content
    # that directly maps to what the Writer will later query for each section.
    # These targeted queries run in the us-en region (English technical queries).
    # ------------------------------------------------------------------
    curriculum       = state.get("curriculum")
    targeted_queries: list[str] = []
    if curriculum:
        targeted_queries = _extract_curriculum_queries(curriculum)
        if targeted_queries:
            logger.info(
                f"Targeted crawling: {len(targeted_queries)} curriculum-derived queries "
                f"(cap={TARGETED_CRAWL_MAX_QUERIES}, per_chapter={TARGETED_CRAWL_QUERIES_PER_CHAPTER})"
            )
            if callback:
                callback(
                    f"Đã thêm {len(targeted_queries)} truy vấn từ giáo trình "
                    f"— đang tìm kiếm tổng hợp..."
                )

    # ------------------------------------------------------------------
    # Step 3 — Parallel web search across all query-region pairs
    # ------------------------------------------------------------------
    print(
        f"[DEBUG INGESTER] Step 3: parallel web search "
        f"({len(vi_queries)} VI + {len(en_queries)} EN "
        f"+ {len(targeted_queries)} targeted = "
        f"{len(vi_queries)+len(en_queries)+len(targeted_queries)} total queries)",
        flush=True,
    )
    region_query_pairs: list[tuple[str, str]] = (
        [(q, "vn-vn") for q in vi_queries]      +
        [(q, "us-en") for q in en_queries]       +
        [(q, "us-en") for q in targeted_queries]   # curriculum-specific seeds
    )

    seen_urls:             set[str]  = set()
    all_raw_urls:          list[str] = []
    all_results_with_meta: list[dict] = []

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
                        all_results_with_meta.append(res)
                        added += 1
                logger.info(
                    f"[{r}] '{q[:50]}': {len(results)} results, {added} new unique"
                )
            except Exception as e:
                logger.warning(f"Search failed [{r}] '{q[:50]}': {e}")

    print(f"[DEBUG INGESTER] Step 3 done: {len(all_raw_urls)} unique URLs collected", flush=True)
    logger.info(f"Total unique URLs before filtering: {len(all_raw_urls)}")
    logger.info(
        f"[Ingestion] Step 3 complete: {len(all_raw_urls)} unique URLs from "
        f"{len(region_query_pairs)} queries"
    )

    if stop_signal.is_stopped():
        print(f"[DEBUG INGESTER] STOPPED after Step 3", flush=True)
        return {"messages": ["⛔ Ingestion stopped by user"]}

    if not all_raw_urls:
        print(f"[DEBUG INGESTER] Step 3 FAILED: no search results", flush=True)
        logger.error("No search results found from any region")
        return {"messages": ["✗ Ingestion failed: No search results"]}

    if callback:
        print(f"[DEBUG INGESTER] callback→ search done, {len(all_raw_urls)} URLs", flush=True)
        callback(f"Tìm thấy {len(all_raw_urls)} URLs — đang lọc nguồn...")

    # ------------------------------------------------------------------
    # Step 4 — URL filtering
    #
    # CHANGE: pass scored_results and topic so filter_and_classify_urls()
    # can run snippet pre-filtering with correct topic context.
    # Previously called with all_raw_urls only → snippet scoring was
    # skipped entirely in the production flow.
    # ------------------------------------------------------------------
    print(f"[DEBUG INGESTER] Step 4: URL filtering ({len(all_raw_urls)} raw URLs)", flush=True)
    clean_links = filter_and_classify_urls(
        all_raw_urls,
        scored_results=all_results_with_meta,
        topic=topic,
        content_type=content_type,
    )
    print(f"[DEBUG INGESTER] Step 4 done: {len(clean_links)} clean links after filtering", flush=True)
    logger.info(f"Found {len(clean_links)} valid links to crawl")
    pdf_n  = sum(1 for u in clean_links if u["type"] == "pdf")
    html_n = sum(1 for u in clean_links if u["type"] == "html")
    logger.info(
        f"[Ingestion] Step 4 complete: {len(clean_links)} valid links "
        f"(PDF={pdf_n}, HTML={html_n})"
    )

    if stop_signal.is_stopped():
        print(f"[DEBUG INGESTER] STOPPED after Step 4", flush=True)
        return {"messages": ["⛔ Ingestion stopped by user"]}

    if not clean_links:
        print(f"[DEBUG INGESTER] Step 4 FAILED: all URLs filtered out", flush=True)
        logger.error("No valid links after filtering")
        return {"messages": ["✗ Ingestion failed: All URLs filtered out"]}

    if callback:
        print(f"[DEBUG INGESTER] callback→ url filter done, {len(clean_links)} clean links", flush=True)
        callback(
            f"Lọc còn {len(clean_links)} URLs hợp lệ "
            f"— đang bắt đầu crawl (~3-5 phút)..."
        )

    # ------------------------------------------------------------------
    # Step 5 — Deep crawl and ingest into ChromaDB
    # ------------------------------------------------------------------
    print(f"[DEBUG INGESTER] Step 5: deep crawl + ingest ({len(clean_links)} URLs)", flush=True)
    success = ingest_dynamic_data(
        topic, clean_links,
        content_type=content_type,
        progress_callback=_get_ingestion_callback(),
    )
    print(f"[DEBUG INGESTER] Step 5 done: success={success}", flush=True)
    logger.info(
        f"[Ingestion] Step 5 complete: crawl success={success}, "
        f"{len(clean_links)} sources attempted"
    )

    if not success:
        logger.error("Crawling failed or no content found")
        return {"messages": ["✗ Ingestion failed: Crawling error"]}

    print(f"[DEBUG INGESTER] perform_ingestion COMPLETE — {len(clean_links)} sources", flush=True)
    logger.info(f"✓ Ingestion complete with {len(clean_links)} sources")
    return {
        "messages": [
            f"✓ Ingestion complete: Database ready with {len(clean_links)} sources"
        ]
    }
    
    
def _extract_curriculum_queries(
    curriculum: Any,
    max_per_chapter: int = TARGETED_CRAWL_QUERIES_PER_CHAPTER,
    total_cap: int       = TARGETED_CRAWL_MAX_QUERIES,
) -> list[str]:
    """
    Extract targeted search queries from a confirmed CurriculumOutline.

    Reads the search_query field of each subsection — these are already
    optimised English queries written by the Planner for RAG retrieval.
    Using them as ingestion seeds ensures ChromaDB receives content that
    directly matches what the Writer will later query.

    Deduplication is handled by the caller via the seen_urls set in
    perform_ingestion() — no extra dedup needed here.

    Args:
        curriculum:      CurriculumOutline (Pydantic) or equivalent dict.
        max_per_chapter: Max subsection queries extracted per chapter.
        total_cap:       Hard cap on total queries returned.

    Returns:
        List of unique search_query strings, capped at total_cap.
    """
    queries: list[str] = []
    seen:    set[str]  = set()

    chapters = (
        curriculum.chapters
        if hasattr(curriculum, "chapters")
        else curriculum.get("chapters", [])
    )

    for chapter in chapters:
        subsections = (
            chapter.subsections
            if hasattr(chapter, "subsections")
            else chapter.get("subsections", [])
        )
        count = 0
        for sub in subsections:
            if count >= max_per_chapter:
                break
            q = (
                sub.search_query
                if hasattr(sub, "search_query")
                else sub.get("search_query", "")
            )
            if q and q not in seen:
                seen.add(q)
                queries.append(q)
                count += 1

        if len(queries) >= total_cap:
            break

    return queries[:total_cap]