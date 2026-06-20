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

from app.config import settings
from ddgs import DDGS

from app.utils.log_config import setup_logger
from app.utils import stop_signal

MIN_SNIPPET_SCORE: float = settings.MIN_SNIPPET_SCORE

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


def score_search_result(result: dict, topic: str) -> float:
    """
    Score a search result by educational relevance using snippet signals.

    Uses DDGS-provided snippet (body) as a free quality signal — no extra
    network call required. Replaces the need to expand BLACKLIST_DOMAINS
    for noise domains that are not hard-blocked.

    Scoring signals:
        Signal 1: Educational keywords in title + snippet → positive
        Signal 2: Topic keywords in snippet → positive
        Signal 3: Trusted academic domain patterns → positive boost
        Signal 4: Generic commercial/enrollment URL patterns → penalty
        Signal 5: Generic noise domain patterns → penalty

    All penalties are domain-agnostic — no topic-specific patterns.
    This ensures the function generalises across all subject domains
    without overfitting to any particular topic (nail, cooking, IT, etc.)

    Args:
        result: DDGS result dict with keys 'title', 'href', 'body'.
        topic:  User topic string for keyword matching.

    Returns:
        Float score >= 0.0. Caller should reject if below threshold.
        Returns 0.0 for hard rejects (snippet too short).
    """
    body     = result.get("body",  "").lower()
    title    = result.get("title", "").lower()
    url      = result.get("href",  "").lower()
    combined = body + " " + title

    # Hard reject: snippet too short → nav page, login wall, catalog listing
    if len(body) < 80:
        return 0.0

    score = 0.0

    # Signal 1: Educational content keywords
    edu_keywords_vi = [
        "học", "giáo trình", "bài giảng", "khái niệm",
        "thuật toán", "phương pháp", "định nghĩa", "kiến thức",
        "chương", "mục", "giới thiệu", "cơ bản", "nâng cao",
    ]
    edu_keywords_en = [
        "course", "textbook", "lecture", "algorithm", "chapter",
        "introduction", "fundamentals", "tutorial", "definition",
        "concept", "theory", "method", "approach", "technique",
    ]
    edu_hits = sum(1 for kw in edu_keywords_vi + edu_keywords_en
                   if kw in combined)
    score += min(edu_hits * 0.15, 1.5)  # cap at 1.5

    # Signal 2: Topic keywords in snippet
    topic_words = [w for w in topic.lower().split() if len(w) > 2]
    topic_hits  = sum(1 for w in topic_words if w in body)
    score += min(topic_hits * 0.2, 0.6)  # cap at 0.6

    # Signal 3: Trusted academic domain boost
    trusted_patterns = [
        ".edu", ".ac.", "university", "stanford", "mit.edu",
        "wikipedia", "arxiv", "openstax", "encyclopedia",
        "ncbi.nlm", "pmc.", "scholar", "ocw.", "openlearn",
        "slds-lmu", "cs.cmu", "mlhp", "geeksforgeeks",
    ]
    if any(p in url for p in trusted_patterns):
        score += 0.5

    # Signal 4: Generic commercial/enrollment URL penalty
    # Applies to ALL domains — booking pages across any topic (nail, cooking,
    # IT, yoga, etc.) share the same URL path patterns regardless of subject.
    commercial_url_patterns = [
        "/booking", "/enroll", "/register", "/checkout",
        "/payment", "/buy-now", "/purchase", "/sign-up",
        "/book-now", "/get-started", "/join-now",
        "/course-booking", "/training-course/",
    ]
    if any(p in url for p in commercial_url_patterns):
        score -= 0.5

    # Signal 5: Generic noise domain penalty
    # Only truly domain-agnostic noise sources — no topic-specific patterns.
    generic_noise_patterns = [
        "wordpress", "blogspot",   # personal blogs, unreliable
        "baomoi", "vnexpress",     # news aggregators, not educational
        "ebooks.com", "perlego",   # book retail, content behind paywall
        "udacity", "lunartech",    # course platforms (login-gated)
        "scribd", "slideshare",    # document sharing (login-gated)
    ]
    if any(p in url for p in generic_noise_patterns):
        score -= 0.4

    return max(0.0, score)

def search_web(
    query: str,
    max_results: int = 10,
    region: str = "vn-vn",
    min_snippet_score: float | None = None,
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
    # Stage 1: Hard noise filter (social, e-commerce, job sites)
    hard_filtered = [r for r in raw_results if not _is_noise_url(r.get("href", ""))]

    # Stage 2: Snippet quality score
    # Extract topic from query — use query itself as topic signal
   
    
    scored = [
        (r, score_search_result(r, query))
        for r in hard_filtered
    ]
    threshold = MIN_SNIPPET_SCORE if min_snippet_score is None else min_snippet_score
    filtered = [r for r, s in scored if s >= threshold]

    # Log score distribution for tuning
    if scored:
        scores = [s for _, s in scored]
        rejected = len(hard_filtered) - len(filtered)
        logger.info(
            f"Snippet filter: {len(hard_filtered)} → {len(filtered)} results "
            f"({rejected} low-quality removed) "
            f"[scores: min={min(scores):.2f} max={max(scores):.2f} "
            f"avg={sum(scores)/len(scores):.2f}] [region={region}]"
        )
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
    Note: this function returns URLs only (backward compatible).
    For full result dicts with snippet metadata, call search_web() directly
    and collect results — as done in ingester.py perform_ingestion().

    Args:
        query:                  Search query (from QueryExpansion)
        max_results_per_region: Raw results to request per region before filtering.

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

    # Preserve snippet metadata for url_filter.py downstream scoring
    seen: set[str] = set()
    
    unique_urls:    List[str]            = []

    for r in all_results:
        url = r.get("href", "")
        if url and url not in seen:
            seen.add(url)
            unique_urls.append(url)
           

    logger.info(
        f"Multi-region search complete: {len(unique_urls)} unique URLs "
        f"(from up to {max_results_per_region * len(regions)} raw, "
        f"after noise + snippet filter)"
    )
    return unique_urls  # backward compatible — callers receive URLs only
