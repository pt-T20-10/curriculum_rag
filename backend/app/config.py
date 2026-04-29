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
    
    # ==================== Existing AI API Keys ==================  ==
    OPENAI_API_KEY: str
    GROQ_API_KEY: str
    GEMINI_API_KEY: str
    ANTHROPIC_API_KEY: str
    SERPER_API_KEY: str = ""  # Optional
    
    # ==================== Database (NEW) ====================
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "textbook_user"
    MYSQL_PASSWORD: str = "textbook_password_change_me"
    MYSQL_DATABASE: str = "ai_textbook_db"
    
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )
    
    # ==================== Security (NEW) ====================
    SECRET_KEY: str = "your-secret-key-minimum-32-characters-long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # ==================== Google OAuth (NEW) ====================
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    
    # ==================== SePay (NEW) ====================
    SEPAY_API_KEY: str = ""
    SEPAY_ACCOUNT_NUMBER: str = ""
    
    # ==================== Application URLs (NEW) ====================
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    
    # ==================== Existing RAG Settings ====================
    RAG_TOP_K: int = 8
    RAG_INITIAL_K: int = 3
    RAG_TOOL_K: int = 3
    RAG_TOOL_MAX_ROUNDS: int = 3
    
    # ==================== Existing LLM Models ====================
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    LLM_MODEL_CHEAP: str = "gpt-4o-mini"
    LLM_MODEL_PREMIUM: str = "gpt-4o"
    IMAGE_MODEL_DEFAULT: str = "gpt-image-1-mini"
    IMAGE_MODEL_PREMIUM: str = "gpt-image-1.5"
    
    # ==================== Existing Chunking ====================
    CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 400
    
    # ==================== Existing Ingestion Speed Controls ====================
    SEARCH_RESULTS_PER_QUERY: int = 30
    SEARCH_MAX_WORKERS: int = 6
    CRAWL_MAX_WORKERS: int = 5
    CRAWL_MAX_SUB_LINKS: int = 5
    URL_FILTER_MAX_WORKERS: int = 5
    INDICATE_LINKS_FOR_PICS: int = 12
    MAX_CHUNKS_PER_DOMAIN: int = 25
    CRAWL_MAX_DEPTH2_LINKS: int = 3
    
    # ==================== Existing Quality Filters ====================
    MIN_CHUNK_CHARS: int = 200
    MIN_ALPHA_RATIO: float = 0.55
    MAX_DIGIT_RATIO: float = 0.40
    MIN_RELEVANCE_SCORE: float = 0.22
    MAX_BOOKING_SIGNALS: int = 2
    MAX_DUPLICATE_LINE_RATIO: float = 0.4
    MAX_CITATION_LINE_RATIO: float = 0.3
    
    # ChromaDB
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
    return Settings()  # type: ignore[call-arg]

# Singleton instance
settings = get_settings()

# Keep get_embedding_model for backward compatibility
@lru_cache(maxsize=1)
def get_embedding_model():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name=settings.EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )