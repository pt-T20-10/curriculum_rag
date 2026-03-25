import os
import warnings
from pathlib import Path
from dotenv import load_dotenv
from functools import lru_cache


load_dotenv()

# -- Required keys (app cannot function without these)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found! Please check your .env file.")

# -- Optional keys (app degrades gracefully without these)
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
if not SERPER_API_KEY:
    warnings.warn(
        "SERPER_API_KEY not set. Image generation will be disabled.",
        UserWarning,
        stacklevel=2
    )
    
BASE_DIR = Path(__file__).resolve().parent.parent


# --DATA PATHS --
DATA_DIR = BASE_DIR / "data"
CHROMA_DB_DIR = DATA_DIR / "chroma_db"    

# -- AI MODELS --
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL_CHEAP =   "gpt-4o-mini" #"gpt-4o"
LLM_MODEL_PREMIUM = "gpt-4o-mini" #"gpt-5.4-mini"

# -- CHUNKINGS --
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# ============================================================================
# INGESTION SPEED CONTROLS
#
# Giảm các giá trị này để test nhanh hơn, tăng để crawl đầy đủ hơn.
#
# Chế độ TEST nhanh (gợi ý):
#   SEARCH_RESULTS_PER_QUERY  = 5
#   SEARCH_MAX_WORKERS        = 6   (giữ nguyên, chỉ giảm số kết quả)
#   CRAWL_MAX_WORKERS         = 3
#   CRAWL_MAX_SUB_LINKS       = 1
#   URL_FILTER_MAX_WORKERS    = 5
#
# Chế độ PRODUCTION (mặc định):
#   SEARCH_RESULTS_PER_QUERY  = 20
#   SEARCH_MAX_WORKERS        = 6
#   CRAWL_MAX_WORKERS         = 5
#   CRAWL_MAX_SUB_LINKS       = 5
#   URL_FILTER_MAX_WORKERS    = 10
# ============================================================================
 
# Số kết quả DuckDuckGo mỗi query (3 VI + 3 EN queries = tổng raw URLs)
SEARCH_RESULTS_PER_QUERY: int = 5
 
# Số worker crawl song song (ingester.py ThreadPoolExecutor)
SEARCH_MAX_WORKERS: int = 6
 
# Số worker crawl URL song song (crawler.py ThreadPoolExecutor)
CRAWL_MAX_WORKERS: int = 3
 
# Số sub-link depth-1 tối đa mỗi root page (crawler.py)
CRAWL_MAX_SUB_LINKS: int = 1
 
# Số worker probe content-type song song (url_filter.py ThreadPoolExecutor)
URL_FILTER_MAX_WORKERS: int = 5

INDICATE_LINKS_FOR_PICS = 15

def setup_directories():
    for path in [DATA_DIR, CHROMA_DB_DIR]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Directory ready: {path}")

@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Singleton embedding model — loaded once, reused everywhere.
    """
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
