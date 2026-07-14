"""
Ingester Agent for AI Textbook Generator.

This agent orchestrates the full document ingestion pipeline that populates
ChromaDB before the Planner runs. It is the first node in the workflow graph.

Pipeline:
    1. Ensure the vector database directory exists. Per-run collections provide
       isolation across consecutive runs on different subjects.
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


import concurrent.futures
import re
from pathlib import Path

from typing import Any
from app.schemas.curriculum import (
    AgentState,
    Chapter,
    SubSection,
    clean_section_title,
    get_chapter_and_subsection,
)
from app.config import settings
from app.services.cost_profile import should_reuse_ingestion_query_expansion

from app.ingestion.query_expansion import QueryExpansionAgent
from app.ingestion.search_engine import search_web
from app.ingestion.source_policy import (
    default_domains_for_content_type,
    domains_for_preferences,
    domains_for_source_ids,
    normalize_source_preferences,
)
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


def _config_int(config: dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _run_id_from_collection(collection_name: str) -> str:
    """Derive a compact run id from the per-textbook Chroma collection name."""
    match = re.match(r"^dynamic_context_(.+)$", collection_name or "")
    return match.group(1) if match else (collection_name or "dynamic_context")


def _site_search_domain(domain: str) -> str:
    return str(domain or "").strip().lower().lstrip(".")


def _region_for_domain(domain: str) -> str:
    normalized = domain.lower()
    return "vn-vn" if normalized.endswith(".vn") or ".edu.vn" in normalized else "us-en"


def _domain_queries(
    domains: list[str] | tuple[str, ...],
    topic: str,
    limit: int,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for domain in domains:
        clean_domain = _site_search_domain(domain)
        if not clean_domain or clean_domain in seen:
            continue
        seen.add(clean_domain)
        pairs.append((f"site:{clean_domain} {topic}", _region_for_domain(domain)))
        if len(pairs) >= limit:
            break
    return pairs


def cleanup_rag_collection(collection_name: str) -> bool:
    """
    Best-effort cleanup for a completed run's Chroma collection.

    Chroma stores multiple collections inside the same persistent directory, so
    deleting individual files is unsafe while the worker is alive. Delete only
    the completed run's collection and leave the storage files to Chroma.
    """
    if not collection_name:
        return False
    if collection_name in {"dynamic_context", settings.CHROMA_COLLECTION_NAME}:
        logger.warning("Refusing to cleanup shared Chroma collection: %s", collection_name)
        return False

    try:
        from langchain_chroma import Chroma
        from app.services.textbook.retriever import release_retriever

        release_retriever(collection_name)
        vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            collection_name=collection_name,
        )
        vector_db.delete_collection()
        logger.info("Cleaned Chroma collection after export: %s", collection_name)
        return True
    except Exception as e:
        logger.warning(
            "Could not cleanup Chroma collection '%s' after export: %s",
            collection_name,
            e,
        )
        return False


def recover_rag_for_current_section(state: AgentState) -> dict:
    """
    Targeted one-shot crawl when Chroma has no usable context for a subsection.

    Normal CRAG retries only reformulate queries against the existing Chroma
    collection. This recovery step expands the collection itself for the
    current subsection, then routes back to QueryFormulator.
    """
    if not getattr(settings, "CRAG_TARGETED_RECOVERY_ENABLED", True):
        return {
            "rag_recovery_attempted": True,
            "messages": ["⚠️ Targeted RAG recovery disabled"],
        }

    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    content_type = state.get("content_type", "technical")
    collection_name = state.get("rag_collection_name", "dynamic_context")
    runtime_config = state.get("advanced_config", {}) or {}
    source_preferences = normalize_source_preferences(state.get("source_preferences"))

    try:
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)
        chap_title = chapter.title if isinstance(chapter, Chapter) else chapter.get("title", "")
        sec_title = subsection.title if isinstance(subsection, SubSection) else subsection.get("title", "")
        sec_desc = subsection.description if isinstance(subsection, SubSection) else subsection.get("description", "")
        sec_query = subsection.search_query if isinstance(subsection, SubSection) else subsection.get("search_query", "")
        sec_title = clean_section_title(sec_title)
    except Exception as e:
        logger.warning("Targeted RAG recovery could not read curriculum section: %s", e)
        chap_title = state.get("core_topic", "") or state.get("request", "")
        sec_title = f"Chapter {chap_idx + 1}.{sub_idx + 1}"
        sec_desc = ""
        sec_query = state.get("retrieval_query", "")

    recovery_query = " ".join(
        part.strip()
        for part in [
            state.get("core_topic", "") or state.get("request", ""),
            chap_title,
            sec_title,
            sec_query,
            sec_desc,
        ]
        if str(part or "").strip()
    )
    recovery_query = re.sub(r"\s+", " ", recovery_query).strip()
    if not recovery_query:
        return {
            "rag_recovery_attempted": True,
            "messages": ["⚠️ Targeted RAG recovery skipped: empty query"],
        }

    results_per_query = _config_int(
        runtime_config,
        "CRAG_TARGETED_RECOVERY_RESULTS_PER_QUERY",
        getattr(settings, "CRAG_TARGETED_RECOVERY_RESULTS_PER_QUERY", 4),
        minimum=1,
    )
    max_root_urls = _config_int(
        runtime_config,
        "CRAG_TARGETED_RECOVERY_MAX_ROOT_URLS",
        getattr(settings, "CRAG_TARGETED_RECOVERY_MAX_ROOT_URLS", 3),
        minimum=1,
    )
    min_snippet_score = _config_float(
        runtime_config,
        "MIN_SNIPPET_SCORE",
        settings.MIN_SNIPPET_SCORE,
    )
    url_filter_max_workers = _config_int(
        runtime_config,
        "URL_FILTER_MAX_WORKERS",
        settings.URL_FILTER_MAX_WORKERS,
        minimum=1,
    )

    logger.warning(
        "Targeted RAG recovery: Chapter %s.%s query='%s'",
        chap_idx + 1,
        sub_idx + 1,
        recovery_query[:160],
    )

    all_urls: list[str] = []
    scored_results: list[dict] = []
    seen: set[str] = set()
    for region in ("us-en", "vn-vn"):
        if stop_signal.is_stopped():
            break
        try:
            for result in search_web(
                recovery_query,
                results_per_query,
                region,
                min_snippet_score=min_snippet_score,
            ):
                url = result.get("href", "")
                if not url or url in seen:
                    continue
                item = dict(result)
                item["_query"] = recovery_query
                item["_region"] = region
                seen.add(url)
                all_urls.append(url)
                scored_results.append(item)
        except Exception as e:
            logger.warning("Targeted RAG recovery search failed [%s]: %s", region, e)

    if not all_urls:
        return {
            "rag_recovery_attempted": True,
            "rag_retrieval_attempts": 0,
            "messages": ["⚠️ Targeted RAG recovery found no search results"],
        }

    clean_links = filter_and_classify_urls(
        all_urls,
        scored_results=scored_results,
        topic=recovery_query,
        content_type=content_type,
        min_snippet_score=min_snippet_score,
        max_workers=url_filter_max_workers,
        trusted_domains=list(domains_for_preferences(
            source_preferences,
            content_type,
            include_defaults=source_preferences["source_mode"] != "custom_only",
        )),
    )
    clean_links = clean_links[:max_root_urls]
    if not clean_links:
        return {
            "rag_recovery_attempted": True,
            "rag_retrieval_attempts": 0,
            "messages": ["⚠️ Targeted RAG recovery found no valid URLs"],
        }

    success = ingest_dynamic_data(
        recovery_query,
        clean_links,
        content_type=content_type,
        collection_name=collection_name,
        run_id=_run_id_from_collection(collection_name),
        progress_callback=_get_ingestion_callback(),
        runtime_config=runtime_config,
    )

    return {
        "rag_recovery_attempted": True,
        "rag_retrieval_attempts": 0,
        "retrieval_query": "",
        "context_quality": "sufficient",
        "messages": [
            (
                f"✓ Targeted RAG recovery ingested {len(clean_links)} source(s) "
                f"for Chapter {chap_idx + 1}.{sub_idx + 1}"
            )
            if success
            else (
                f"⚠️ Targeted RAG recovery failed for "
                f"Chapter {chap_idx + 1}.{sub_idx + 1}"
            )
        ],
    }


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
    runtime_config = state.get("advanced_config", {}) or {}
    source_preferences = normalize_source_preferences(state.get("source_preferences"))
    source_mode = source_preferences["source_mode"]
    collection_name = state.get("rag_collection_name", "dynamic_context")
    targeted_per_chapter = _config_int(
        runtime_config,
        "TARGETED_CRAWL_QUERIES_PER_CHAPTER",
        TARGETED_CRAWL_QUERIES_PER_CHAPTER,
    )
    targeted_max_queries = _config_int(
        runtime_config,
        "TARGETED_CRAWL_MAX_QUERIES",
        TARGETED_CRAWL_MAX_QUERIES,
    )
    search_results_per_query = _config_int(
        runtime_config,
        "SEARCH_RESULTS_PER_QUERY",
        SEARCH_RESULTS_PER_QUERY,
        minimum=1,
    )
    search_queries_per_language = _config_int(
        runtime_config,
        "SEARCH_QUERIES_PER_LANGUAGE",
        getattr(settings, "SEARCH_QUERIES_PER_LANGUAGE", 6),
        minimum=1,
    )
    search_max_workers = _config_int(
        runtime_config,
        "SEARCH_MAX_WORKERS",
        SEARCH_MAX_WORKERS,
        minimum=1,
    )
    url_filter_max_workers = _config_int(
        runtime_config,
        "URL_FILTER_MAX_WORKERS",
        settings.URL_FILTER_MAX_WORKERS,
        minimum=1,
    )
    min_snippet_score = _config_float(
        runtime_config,
        "MIN_SNIPPET_SCORE",
        settings.MIN_SNIPPET_SCORE,
    )
    crawl_max_root_urls = _config_int(
        runtime_config,
        "CRAWL_MAX_ROOT_URLS",
        getattr(settings, "CRAWL_MAX_ROOT_URLS", 0),
    )

    print(f"[DEBUG INGESTER] perform_ingestion START — topic='{topic}' callback={'set' if callback else 'NONE'}", flush=True)
    logger.info("=" * 60)
    logger.info(f"NODE: Ingestion - Starting for '{topic}'")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1 — Ensure ChromaDB directory exists.
    #
    # Correctness comes from per-run Chroma collections. Deleting the persistent
    # database directory between runs can invalidate open SQLite/Chroma handles
    # on deployed volumes, so keep the directory and write to the isolated
    # collection for this textbook run.
    # ------------------------------------------------------------------
    print(f"[DEBUG INGESTER] Step 1: preparing ChromaDB", flush=True)
    try:
        CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Prepared ChromaDB directory '%s' for isolated collection '%s'",
            CHROMA_DB_DIR,
            collection_name,
        )
    except Exception as e:
        logger.error("Could not prepare ChromaDB directory '%s': %s", CHROMA_DB_DIR, e)
        return {"messages": ["✗ Ingestion failed: ChromaDB storage unavailable"]}

    if stop_signal.is_stopped():
        print(f"[DEBUG INGESTER] STOPPED after Step 1", flush=True)
        return {"messages": ["⛔ Ingestion stopped by user"]}

    # ------------------------------------------------------------------
    # Step 2 — Bilingual query expansion
    # ------------------------------------------------------------------
    print(f"[DEBUG INGESTER] Step 2: expanding query bilingually", flush=True)
    query_expansion_agent = QueryExpansionAgent()
    expanded = query_expansion_agent.expand_query_bilingual(topic, content_type=content_type)
    reusable_query_expansion = (
        expanded
        if should_reuse_ingestion_query_expansion(runtime_config)
        else None
    )

    if content_type in {"technical", "scholarly"}:
        vi_query_limit = min(3, len(expanded["vi"]))
        en_query_limit = min(6, len(expanded["en"]))
    else:
        vi_query_limit = min(search_queries_per_language, len(expanded["vi"]))
        en_query_limit = min(search_queries_per_language, len(expanded["en"]))

    vi_queries = expanded["vi"][:vi_query_limit]
    en_queries = expanded["en"][:en_query_limit]

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
        targeted_queries = _extract_curriculum_queries(
            curriculum,
            max_per_chapter=targeted_per_chapter,
            total_cap=targeted_max_queries,
        )
        if targeted_queries:
            logger.info(
                f"Targeted crawling: {len(targeted_queries)} curriculum-derived queries "
                f"(cap={targeted_max_queries}, per_chapter={targeted_per_chapter})"
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
    selected_domains = list(domains_for_source_ids(source_preferences["selected_source_ids"]))
    custom_domains = list(source_preferences["custom_domains"])
    custom_url_domains = []
    for custom_url in source_preferences["custom_urls"]:
        try:
            from urllib.parse import urlparse
            custom_url_domains.append(urlparse(custom_url).netloc.lower())
        except Exception:
            pass
    trusted_domains = list(domains_for_preferences(
        source_preferences,
        content_type,
        include_defaults=source_mode != "custom_only",
    ))
    trusted_domains.extend(custom_url_domains)

    custom_domain_pairs = _domain_queries(
        [*selected_domains, *custom_domains],
        topic,
        limit=20,
    )
    default_domain_pairs = []
    if source_mode in {"system_default", "custom_hybrid"} and content_type in {"technical", "scholarly"}:
        default_domain_pairs = _domain_queries(
            list(default_domains_for_content_type(content_type)),
            en_queries[0] if en_queries else topic,
            limit=_config_int(
                runtime_config,
                "TARGET_EMBEDDED_UNIQUE_SOURCES",
                getattr(settings, "TARGET_EMBEDDED_UNIQUE_SOURCES", 15),
                minimum=1,
            ),
        )

    default_region_pairs: list[tuple[str, str]] = []
    if source_mode != "custom_only":
        default_region_pairs = (
            [(q, "vn-vn") for q in vi_queries]      +
            [(q, "us-en") for q in en_queries]       +
            [(q, "us-en") for q in targeted_queries]   # curriculum-specific seeds
        )

    region_query_pairs: list[tuple[str, str]] = (
        custom_domain_pairs +
        default_domain_pairs +
        default_region_pairs
    )

    seen_urls:             set[str]  = set()
    all_raw_urls:          list[str] = []
    all_results_with_meta: list[dict] = []
    skip_snippet_urls:     set[str] = set()

    for custom_url in source_preferences["custom_urls"]:
        if custom_url in seen_urls:
            continue
        seen_urls.add(custom_url)
        skip_snippet_urls.add(custom_url)
        all_raw_urls.append(custom_url)
        all_results_with_meta.append({
            "href": custom_url,
            "title": "User selected source",
            "body": f"Direct user selected source for {topic}",
            "_query": "custom_url",
            "_region": "custom",
            "_direct_custom_url": "true",
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=search_max_workers) as executor:
        futures = {
            executor.submit(
                search_web,
                q,
                search_results_per_query,
                r,
                min_snippet_score=min_snippet_score,
            ): (q, r)
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
                        res = dict(res)
                        res["_query"] = q
                        res["_region"] = r
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
        if source_mode == "custom_only":
            return {
                "messages": [
                    "✗ Ingestion failed: No custom sources were provided or found"
                ]
            }
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
        min_snippet_score=min_snippet_score,
        max_workers=url_filter_max_workers,
        trusted_domains=trusted_domains,
        skip_snippet_urls=skip_snippet_urls,
    )
    if crawl_max_root_urls > 0 and len(clean_links) > crawl_max_root_urls:
        logger.info(
            f"Root URL cap: {len(clean_links)} → {crawl_max_root_urls} before deep crawl"
        )
        clean_links = clean_links[:crawl_max_root_urls]
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
        if source_mode == "custom_only":
            return {
                "messages": [
                    "✗ Ingestion failed: No valid URLs from selected custom sources"
                ]
            }
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
        collection_name=collection_name,
        run_id=_run_id_from_collection(collection_name),
        progress_callback=_get_ingestion_callback(),
        runtime_config=runtime_config,
        query_expansion=reusable_query_expansion,
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
