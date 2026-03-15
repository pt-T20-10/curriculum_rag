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
LLM_MODEL_CHEAP = "gpt-4o-mini"
LLM_MODEL_PREMIUM = "gpt-4o"

# -- CHUNKINGS --
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# -- PDF RENDERING (override in .env) --
PDF_BODY_FONTSIZE    = os.getenv("PDF_BODY_FONTSIZE",    "12pt")   # xelatex body font size
PDF_CHAPTER_FONTSIZE = os.getenv("PDF_CHAPTER_FONTSIZE", "Large")   # LaTeX size cmd for chapter titles
PDF_TOC_TITLE        = os.getenv("PDF_TOC_TITLE","MỤC LỤC")  # TOC section heading

def setup_directories():
    for path in [DATA_DIR, CHROMA_DB_DIR]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Directory ready: {path}")

@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Singleton embedding model — loaded once, reused everywhere.
    lru_cache đảm bảo chỉ khởi tạo 1 lần duy nhất trong suốt app lifetime.
    """
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
