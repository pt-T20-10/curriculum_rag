import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY not found! Please check your .env file.")


SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
if not SERPAPI_API_KEY:
    print("⚠️ CẢNH BÁO: Chưa tìm thấy SERPAPI_API_KEY trong .env")
BASE_DIR = Path(__file__).resolve().parent.parent

# Data path config
DATA_DIR = BASE_DIR / "data"
RAW_MANUAL_DIR = DATA_DIR / "raw_manual"   # Zip files
EXTRACTED_DIR = DATA_DIR / "extracted"    
CHROMA_DB_DIR = DATA_DIR / "chroma_db"    
STORAGE_DIR = BASE_DIR / "storage" 

# Model config
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL_NAME = "gpt-4o-mini"

# Chunking config
CHUNK_SIZE = 1000  
CHUNK_OVERLAP = 200

def setup_directories():
    for path in [DATA_DIR, RAW_MANUAL_DIR, EXTRACTED_DIR, CHROMA_DB_DIR]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Directory ready: {path}")


