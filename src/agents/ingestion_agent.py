import logging
import shutil
import os
from src.graph.state import AgentState
from src.config import CHROMA_DB_DIR

# Import các tool đã viết
from src.agents.query_expansion import QueryExpansionAgent
from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls
from src.ingestion.crawler import ingest_dynamic_data

logger = logging.getLogger("IngestionNode")

def perform_ingestion(state: AgentState):
    """
    Node: Ingestion
    Nhiệm vụ: 
    1. Xóa DB cũ.
    2. Mở rộng truy vấn (Query Expansion).
    3. Tìm kiếm Google/DuckDuckGo.
    4. Lọc link rác.
    5. Cào dữ liệu và nạp vào ChromaDB.
    """
    topic = state["request"]
    logger.info(f"--- INGESTION NODE: Starting for '{topic}' ---")
    
    # 1. Dọn dẹp Database cũ (Clean Slate)
    if os.path.exists(CHROMA_DB_DIR):
        try:
            shutil.rmtree(CHROMA_DB_DIR)
            logger.info("🧹 Cleared old ChromaDB.")
        except Exception as e:
            logger.warning(f"⚠️ Could not clear DB: {e}")

    # 2. Query Expansion (Hiểu ý định người dùng)
    qe = QueryExpansionAgent()
    expanded_queries = qe.expand_query(topic)
    
    # Lấy query tốt nhất (thường là cái đầu tiên)
    best_query = expanded_queries[0] if expanded_queries else topic
    logger.info(f"🔍 Optimized Query: '{best_query}'")
    
    # 3. Search Web
    raw_results = search_web(best_query, max_results=20)
    raw_urls = [r['href'] for r in raw_results]
    
    if not raw_urls:
        return {"messages": ["Error: No search results found."]}

    # 4. Filter Links
    clean_links = filter_and_classify_urls(raw_urls)
    logger.info(f"🔗 Found {len(clean_links)} valid links to crawl.")
    
    # 5. Deep Crawl & Ingest
    success = ingest_dynamic_data(topic, clean_links)
    
    if not success:
        return {"messages": ["Error: Crawling failed or no content found."]}
    
    return {
        "messages": [f"Ingestion complete. Database ready with {len(clean_links)} sources."]
    }