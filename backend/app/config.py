# ============================================================================
# FILE: backend/app/config.py - COMPLETE FIXED VERSION
# ============================================================================

"""
Application configuration using Pydantic Settings.
"""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    # ==================== Existing AI API Keys ====================
    OPENAI_API_KEY: str
    GROQ_API_KEY: str
    GEMINI_API_KEY: str
    ANTHROPIC_API_KEY: str
    SERPER_API_KEY: str = ""  # Optional
    
    # ==================== Database ====================
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "textbook_user"
    MYSQL_PASSWORD: str = "textbook_password_change_me"
    MYSQL_DATABASE: str = "ai_textbook_db"
    
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )
    
    # ==================== Security ====================
    SECRET_KEY: str = "your-secret-key-minimum-32-characters-long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    REMEMBER_ME_EXPIRE_DAYS: int = 30
    
    # ==================== Google OAuth ====================
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    
    # ==================== SePay ====================
    SEPAY_API_KEY: str = ""
    SEPAY_ACCOUNT_NUMBER: str = ""
    
    # ==================== Application URLs ====================
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    
    # ==================== RAG Settings ====================
    RAG_TOP_K: int = 8
    RAG_INITIAL_K: int = 3
    RAG_TOOL_K: int = 3
    RAG_TOOL_MAX_ROUNDS: int = 3
    
    # ==================== LLM Models ====================
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small" 
    
    LLM_MODEL_CHEAP: str = "gpt-4o-mini"
    LLM_MODEL_PREMIUM: str = "gpt-4o"
    IMAGE_MODEL_DEFAULT: str = "gpt-image-1-mini"
    IMAGE_MODEL_PREMIUM: str = "gpt-image-1.5"
    
    # Embedding provider selection
    # Options:
    #   - "openai": Fast API-based, supports multilingual (VI + EN)
    #   - "local":  bge-m3 local model, slower but free, 1024 dims
    EMBEDDING_PROVIDER: str = "openai" 
    # ==================== Chunking ====================
    CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 400
    
    # ==================== Ingestion Speed Controls ====================
    SEARCH_RESULTS_PER_QUERY: int = 30
    SEARCH_MAX_WORKERS: int = 6
    CRAWL_MAX_WORKERS: int = 5
    CRAWL_MAX_SUB_LINKS: int = 5
    URL_FILTER_MAX_WORKERS: int = 5
    INDICATE_LINKS_FOR_PICS: int = 12
    CRAWL_MAX_DEPTH2_LINKS: int = 3
    
    # ==================== Quality Filters ====================
    MIN_CHUNK_CHARS: int = 200
    MIN_ALPHA_RATIO: float = 0.55
    MAX_DIGIT_RATIO: float = 0.40
    MIN_RELEVANCE_SCORE: float = 0.22
    MAX_BOOKING_SIGNALS: int = 2
    MAX_DUPLICATE_LINE_RATIO: float = 0.4
    MAX_CITATION_LINE_RATIO: float = 0.3
    
    # ==================== Heuristic Scoring Weights ====================
    HEURISTIC_LENGTH_WEIGHT: float = 0.2
    HEURISTIC_DOMAIN_WEIGHT: float = 0.25
    HEURISTIC_STRUCTURE_WEIGHT: float = 0.15
    HEURISTIC_EDUCATION_WEIGHT: float = 0.15
    
    # ==================== Phase 1: Language-Aware Domain Caps ====================
    
    # Base domain cap - applies to most domains
    MAX_CHUNKS_PER_DOMAIN: int = 25  # ✅ FIX: Only define once
    
    # Vietnamese content is scarcer → allow more chunks per domain
    VI_DOMAIN_CAP: int = 50
    
    # English content is abundant → moderate restriction
    EN_DOMAIN_CAP: int = 35
    
    # Academic domains bypass all caps (verified high-quality sources)
    UNLIMITED_CAP_DOMAINS: tuple = (
        "arxiv.org",
        "stanford.edu",
        "mit.edu",
        "berkeley.edu",
        "ptolemy.berkeley.edu",
        "cs.cmu.edu",
        "cambridge.org",
        "acm.org",
        "ieee.org",
        "springer.com",
    )
    
    # ==================== Phase 1 & 2: Embedding Optimization ====================
    
    # Embedding batch size (trade-off: larger = faster but more memory)
    EMBEDDING_BATCH_SIZE: int = 200
    
    # ChromaDB batch insertion size
    CHROMADB_BATCH_SIZE: int = 100
    
    # Maximum chunks to embed (pre-filter with heuristics to save time)
    MAX_CHUNKS_TO_EMBED: int = 1000
    
    # ==================== ChromaDB ====================
    CHROMA_PERSIST_DIR: str = "data/chroma_db"
    CHROMA_COLLECTION_NAME: str = "curriculum_knowledge"
    
    # ==================== Paths ====================
    @property
    def BASE_DIR(self) -> Path:
        return Path(__file__).resolve().parent.parent
    
    @property
    def DATA_DIR(self) -> Path:
        return self.BASE_DIR / "data"
    
    @property
    def CHROMA_DB_DIR(self) -> Path:
        return self.DATA_DIR / "chroma_db"
    
    # Pydantic config
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # type: ignore[call-arg]


# Singleton instance
settings = get_settings()


@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Singleton embedding model factory.
    
    Returns embedding model based on EMBEDDING_PROVIDER setting:
    - "openai": OpenAI text-embedding-3-small (fast, API-based, multilingual)
    - "local":  BAAI/bge-m3 (slower, local CPU, multilingual)
    
    Both models support Vietnamese and English content equally well.
    OpenAI model is 8x faster but has API cost (~$0.002 per ingestion).
    
    The model is loaded once and cached for reuse across all ingestion calls.
    
    Returns:
        LangChain embedding model wrapper (OpenAIEmbeddings or HuggingFaceEmbeddings)
    
    Raises:
        ValueError: If OPENAI_API_KEY not set when using "openai" provider
        ValueError: If EMBEDDING_PROVIDER is invalid
    """
    if settings.EMBEDDING_PROVIDER == "openai":
        # OpenAI API-based embedding (fast, multilingual)
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY required for OpenAI embeddings. "
                "Set it in .env or switch to EMBEDDING_PROVIDER='local'"
            )
        
        from langchain_openai import OpenAIEmbeddings
        
       
        # OpenAIEmbeddings automatically reads from OPENAI_API_KEY env var
        # which Pydantic Settings already set
        return OpenAIEmbeddings(
            model=settings.OPENAI_EMBEDDING_MODEL,
            # Dimensions: 1536 for text-embedding-3-small
            # No normalization needed - OpenAI handles internally
        )
    
    elif settings.EMBEDDING_PROVIDER == "local":
        # Local bge-m3 model (slower, free, CPU-based)
        from langchain_huggingface import HuggingFaceEmbeddings
        
        return HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL_NAME,  # "BAAI/bge-m3"
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},  # bge-m3 requires normalization
        )
    
    else:
        raise ValueError(
            f"Invalid EMBEDDING_PROVIDER: '{settings.EMBEDDING_PROVIDER}'. "
            f"Must be 'openai' or 'local'"
        )