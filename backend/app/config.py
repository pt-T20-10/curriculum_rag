# ============================================================================
# FILE: backend/app/config.py - COMPLETE FIXED VERSION
# ============================================================================

"""
Application configuration using Pydantic Settings.
"""
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator


load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    # ==================== Existing AI API Keys ====================
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    SERPER_API_KEY: str = ""  # Optional
    
    # ==================== Database ====================
    MYSQL_URL: str = ""
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "textbook_user"
    MYSQL_PASSWORD: str = "textbook_password_change_me"
    MYSQL_DATABASE: str = "ai_textbook_db"
    # Native variable names exposed by Railway's MySQL service.
    MYSQLHOST: str = ""
    MYSQLPORT: int | None = None
    MYSQLUSER: str = ""
    MYSQLPASSWORD: str = ""
    MYSQLDATABASE: str = ""
    
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_PROVIDER: str = "smtp"
    RESEND_API_KEY: str = ""
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = ""

    @field_validator("MYSQL_PORT", "MYSQLPORT", mode="before")
    @classmethod
    def default_empty_mysql_port(cls, value, info):
        """Railway may expose an unresolved/empty optional port reference."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None if info.field_name == "MYSQLPORT" else 3306
        return value

    @property
    def REDIS_CONNECTION_URL(self) -> str:
        """Use a provider URL (including credentials) when one is available."""
        return self.REDIS_URL or f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # Deployment/runtime controls. Development defaults preserve existing local
    # behaviour; the production compose file overrides them explicitly.
    CORS_ORIGINS: str = ""
    CELERY_CONCURRENCY: int = 1
    ENABLE_PROMPT_LOGS: bool = True
    LOG_TO_FILES: bool = True
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5
    DOCUMENT_FONT: str = "Times New Roman"
    
    @property
    def DATABASE_URL(self) -> str:
        if self.MYSQL_URL:
            if self.MYSQL_URL.startswith("mysql://"):
                return self.MYSQL_URL.replace("mysql://", "mysql+pymysql://", 1)
            return self.MYSQL_URL.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
        host = self.MYSQLHOST or self.MYSQL_HOST
        port = self.MYSQLPORT if self.MYSQLPORT is not None else self.MYSQL_PORT
        user = self.MYSQLUSER or self.MYSQL_USER
        password = self.MYSQLPASSWORD or self.MYSQL_PASSWORD
        database = self.MYSQLDATABASE or self.MYSQL_DATABASE
        return (
            f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{database}"
        )

    @property
    def ALLOWED_CORS_ORIGINS(self) -> list[str]:
        configured = [
            origin.strip().rstrip("/")
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]
        if configured:
            return configured
        if self.ENVIRONMENT == "production":
            return [self.FRONTEND_URL.rstrip("/")]
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    
    # ==================== Security ====================
    SECRET_KEY: str = "your-secret-key-minimum-32-characters-long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    REMEMBER_ME_EXPIRE_DAYS: int = 30
    
    # ==================== Bootstrap Admin ====================
    DEFAULT_ADMIN_ENABLED: bool = True
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_FULL_NAME: str = "System Administrator"
    DEFAULT_ADMIN_PASSWORD_HASH: str = "$2b$12$oHvFFApYhi6yUrJfVVORkuG2oQWumTsc37Qr6o9FLV5sqUO8nDvjy"
    
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
    RAG_TOP_K: int = 5
    RAG_INITIAL_K: int = 5 
    RAG_TOOL_K: int = 5
    RAG_TOOL_MAX_ROUNDS: int = 4
    
    # ==================== LLM Models ====================
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small" 
    
    LLM_MODEL_CHEAP: str = "gpt-4o-mini"
    LLM_MODEL_PREMIUM: str = "gpt-4.1"
    IMAGE_MODEL_DEFAULT: str = "gpt-image-1-mini"
    IMAGE_MODEL_PREMIUM: str = "gpt-image-1.5"
    # Deprecated compatibility aliases. Textbook agents use
    # LLM_MODEL_PREMIUM or LLM_MODEL_CHEAP directly.
    LLM_MODEL_WRITER_LONGFORM: str = "gpt-4.1"
    LLM_MODEL_REVIEWER_LONGFORM: str = "gpt-4.1"
    LLM_MODEL_PLANNER_LONGFORM: str = "gpt-4.1"
    # Embedding provider selection
    # Options:
    #   - "openai": Fast API-based, supports multilingual (VI + EN)
    #   - "local":  bge-m3 local model, slower but free, 1024 dims
    EMBEDDING_PROVIDER: str = "openai" 
    # ==================== Chunking ====================
    CHUNK_SIZE: int = 1500
    CHUNK_OVERLAP: int = 300
    
    # ==================== Ingestion Speed Controls ====================
    SEARCH_QUERIES_PER_LANGUAGE: int = 4  #6
    SEARCH_RESULTS_PER_QUERY: int = 15  #30
    SEARCH_MAX_WORKERS: int = 6
    CRAWL_MAX_WORKERS: int = 5
    CRAWL_MAX_SUB_LINKS: int = 3 #5
    CRAWL_MAX_ROOT_URLS: int = 50 #0
    URL_FILTER_MAX_WORKERS: int = 5
    INDICATE_LINKS_FOR_PICS: int = 12
    CRAWL_MAX_DEPTH2_LINKS: int = 1 #3
    
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
    VI_DOMAIN_CAP: int = 80
    
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
        "viblo.asia", 
        "towardsdatascience.com/vi", 
        "123dok.com",
        "machinelearningmastery.com"
    )
    
    
    # ==================== CRAG Pipeline ====================
    CRAG_CONTEXT_QUALITY_MIN_CHARS: int = 2500
    """
    Minimum total chars of enriched RAG context for ContextEvaluator to mark
    context_quality='sufficient'. Below this → 'insufficient' → retry or fail-open.
    CAUTION: Lowering this causes ContentWriter to write with sparse context.
    """
    CRAG_MAX_CONTEXT_RETRIES: int = 4
    """
    Maximum times QueryFormulator retries before ContentWriter proceeds regardless.
    CAUTION: Raising this increases per-subsection latency by ~3-5s per retry.
    """
    CRAG_BEST_EFFORT_AFTER_RETRIES: bool = True #False
    """
    If True, after CRAG_MAX_CONTEXT_RETRIES is exhausted, keep the best
    available non-empty context for the section and continue as 'best_effort'
    instead of stopping the whole workflow. Keep False for strict thesis runs.
    """
    CRAG_TARGETED_RECOVERY_ENABLED: bool = True
    """
    If strict retrieval still has no usable context after the retry budget,
    crawl a small set of URLs for the current subsection and ingest them into
    the same Chroma collection before retrying QueryFormulator once.
    """
    CRAG_TARGETED_RECOVERY_RESULTS_PER_QUERY: int = 4
    CRAG_TARGETED_RECOVERY_MAX_ROOT_URLS: int = 3

    # ==================== Content Generation ====================
    CHECKPOINT_MARKDOWN_AFTER_SECTION: bool = True
    """
    Write a recoverable .partial.md file after each reviewed/illustrated section.
    This protects generated content if a later RAG gate or export step fails.
    """
    WRITER_RETRIEVAL_MAX_ROUNDS: int = 3
    """Max tool-call rounds ContextRetrievalAgent may use to supplement context."""
    WRITER_SUMMARY_PREVIEW_CHARS: int = 200
    """Chars truncated per section summary entry stored in section_summaries."""
    WRITER_MAX_PRIOR_SUMMARIES: int = 6
    """Max prior section summaries injected into Writer prompt (token budget guard)."""

    # ==================== Quality Control ====================
    REVIEWER_MAX_REVISIONS: int = 2
    """
    Max reviewer→writer revision cycles per subsection before forcing approval.
    CAUTION: Setting to 0 disables the quality gate entirely.
    Setting above 3 significantly increases generation time.
    """

    # ==================== RAG Chunk Quality ====================
    RAG_MIN_SUBSTANTIVE_SENTENCES: int = 2
    """Minimum sentence count for a chunk to pass the heuristic quality filter."""
    RAG_MIN_AVG_SENTENCE_LEN: int = 30
    """Minimum average sentence length (chars) for heuristic quality filter."""
    RAG_TRUSTED_DOMAIN_QUOTA: int = 3
    """Max chunks from a single trusted edu domain (wikipedia, arxiv, etc.)."""
    RAG_DEFAULT_DOMAIN_QUOTA: int = 1
    """Max chunks from a single non-trusted domain (prevents single-source bias)."""
    RAG_SEMANTIC_DEDUP_THRESHOLD: float = 0.85
    """Cosine similarity ceiling for semantic deduplication (0.0–1.0).
    CAUTION: Lowering removes more chunks; raising allows more near-duplicates."""
    RAG_CHUNK_SWEET_SPOT_MIN: int = 300
    """Chunk length floor for quality scoring sweet-spot bonus."""
    RAG_CHUNK_SWEET_SPOT_MAX: int = 1500
    """Chunk length ceiling for quality scoring sweet-spot bonus."""
    RAG_CHUNK_SENT_LEN_MIN: int = 40
    """Minimum average sentence length for structure quality bonus."""
    RAG_CHUNK_SENT_LEN_MAX: int = 200
    """Maximum average sentence length for structure quality bonus."""

    # ==================== Snippet / Search Quality ====================
    MIN_SNIPPET_SCORE: float = 0.3
    """
    Minimum score_search_result() score for a URL to pass snippet pre-filter.
    Applied in both search_engine.py and url_filter.py.
    CAUTION: Lowering this floods ingestion with low-relevance pages.
    Raising this may cut valid sources from niche topics.
    """

    # ==================== Targeted Crawling (Shift 3) ====================
    TARGETED_CRAWL_QUERIES_PER_CHAPTER: int =  1 #2
    """
    Number of subsection search_query fields extracted per chapter for
    curriculum-grounded ingestion. Keeps targeted queries focused per chapter.
    """
    TARGETED_CRAWL_MAX_QUERIES: int = 6  #12
    """
    Hard cap on total curriculum-derived queries appended to the ingestion search.
    Prevents over-querying on textbooks with many chapters/subsections.
    """
    
    # ==================== Phase 1 & 2: Embedding Optimization ====================
    
    # Embedding batch size (trade-off: larger = faster but more memory)
    EMBEDDING_BATCH_SIZE: int = 200
    
    # ChromaDB batch insertion size
    CHROMADB_BATCH_SIZE: int = 100
    
    # Maximum chunks to embed (pre-filter with heuristics to save time)
    MAX_CHUNKS_TO_EMBED: int = 500  #1000

    # ==================== LangGraph Workflow Runtime ====================
    PLANNING_WORKFLOW_RECURSION_LIMIT: int = 250
    CONTENT_WORKFLOW_RECURSION_LIMIT: int = 3000
    
    # ==================== ChromaDB ====================
    CHROMA_PERSIST_DIR: str = "data/chroma_db"
    CHROMA_COLLECTION_NAME: str = "curriculum_knowledge"
    CLEANUP_RAG_COLLECTION_AFTER_EXPORT: bool = True

    # ==================== Shared API Rate Limiting ====================
    OPENAI_RATE_LIMIT_ENABLED: bool = False
    OPENAI_SHARED_RATE_LIMIT_ENABLED: bool = True
    OPENAI_REQUEST_MIN_INTERVAL_SECONDS: float = 0.0
    OPENAI_CHAT_MIN_INTERVAL_SECONDS: float = 0.0
    OPENAI_EMBEDDING_MIN_INTERVAL_SECONDS: float = 0.0
    OPENAI_IMAGE_MIN_INTERVAL_SECONDS: float = 0.0
    OPENAI_RATE_LIMIT_MAX_RETRIES: int = 5
    OPENAI_RATE_LIMIT_BACKOFF_BASE_SECONDS: float = 2.0
    OPENAI_RATE_LIMIT_BACKOFF_MAX_SECONDS: float = 60.0
    OPENAI_RATE_LIMIT_JITTER_SECONDS: float = 0.2

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
    
    # Settings that, when changed from default, should trigger a startup warning.
    # Format: field_name → (default_value, reason)
    _CRITICAL_DEFAULTS: dict = {
        "REVIEWER_MAX_REVISIONS":        (2,    "Controls quality gate depth — 0 disables review entirely"),
        "CRAG_CONTEXT_QUALITY_MIN_CHARS":(1200, "Too low = ContentWriter gets sparse context"),
        "MIN_SNIPPET_SCORE":             (0.3,  "Too low floods ingestion; too high starves niche topics"),
        "RAG_TOP_K":                     (8,    "Affects retrieval diversity — changes output quality"),
        "CHUNK_SIZE":                    (2000, "Affects all downstream RAG quality"),
        "MIN_RELEVANCE_SCORE":           (0.22, "Controls ChromaDB post-filter — affects context richness"),
        "RAG_TRUSTED_DOMAIN_QUOTA":      (3,    "Controls single-source dominance in retrieved context"),
        "WRITER_MAX_PRIOR_SUMMARIES":    (6,    "Affects token budget — raising may cause context overflow"),
    }

    @model_validator(mode="after")
    def warn_critical_changes(self) -> "Settings":
        """
        Log startup warnings when critical settings deviate from recommended defaults.
        Fires once at application startup — does not block execution.
        """
        import logging
        _cfg_logger = logging.getLogger("ConfigValidator")

        changed = []
        for field, (default, reason) in self._CRITICAL_DEFAULTS.items():
            current = getattr(self, field, None)
            if current != default:
                changed.append((field, default, current, reason))

        if changed:
            _cfg_logger.warning("=" * 60)
            _cfg_logger.warning("⚠️  CONFIG: %d critical setting(s) differ from defaults:", len(changed))
            for field, default, current, reason in changed:
                _cfg_logger.warning(
                    "  • %-38s %s → %s  [%s]",
                    field, default, current, reason
                )
            _cfg_logger.warning("=" * 60)

        if self.ENVIRONMENT == "production":
            errors: list[str] = []
            default_admin_hash = "$2b$12$oHvFFApYhi6yUrJfVVORkuG2oQWumTsc37Qr6o9FLV5sqUO8nDvjy"

            def missing(value: str) -> bool:
                return not value or value.startswith("REPLACE_")

            if (
                missing(self.SECRET_KEY)
                or len(self.SECRET_KEY) < 32
                or self.SECRET_KEY == "your-secret-key-minimum-32-characters-long"
            ):
                errors.append("SECRET_KEY must be a non-default value of at least 32 characters")
            if not self.MYSQL_URL and (
                missing(self.MYSQLPASSWORD or self.MYSQL_PASSWORD)
                or (self.MYSQLPASSWORD or self.MYSQL_PASSWORD)
                == "textbook_password_change_me"
            ):
                errors.append(
                    "MYSQL_URL, MYSQLPASSWORD, or MYSQL_PASSWORD must be configured "
                    "on the application service"
                )
            if self.MYSQL_URL and not self.MYSQL_URL.startswith(
                ("mysql://", "mysql+pymysql://", "mysql+aiomysql://")
            ):
                errors.append("MYSQL_URL must use a MySQL URL scheme")
            for name, value in (
                ("FRONTEND_URL", self.FRONTEND_URL),
                ("BACKEND_URL", self.BACKEND_URL),
                ("GOOGLE_REDIRECT_URI", self.GOOGLE_REDIRECT_URI),
            ):
                if (
                    not value.startswith("https://")
                    or "localhost" in value
                    or "127.0.0.1" in value
                    or "example.com" in value
                ):
                    errors.append(f"{name} must be a public HTTPS URL")
            if any(
                not origin.startswith("https://")
                or "localhost" in origin
                or "127.0.0.1" in origin
                for origin in self.ALLOWED_CORS_ORIGINS
            ):
                errors.append("CORS_ORIGINS must contain only public HTTPS origins")
            if missing(self.OPENAI_API_KEY):
                errors.append("OPENAI_API_KEY is required")
            if missing(self.GROQ_API_KEY):
                errors.append("GROQ_API_KEY is required")
            if missing(self.GOOGLE_CLIENT_ID) or missing(self.GOOGLE_CLIENT_SECRET):
                errors.append("Google OAuth credentials are required")
            if missing(self.SMTP_USER) or missing(self.SMTP_PASSWORD) or missing(self.EMAIL_FROM):
                errors.append("SMTP credentials are required for password recovery")
            if missing(self.SEPAY_ACCOUNT_NUMBER):
                errors.append("SEPAY_ACCOUNT_NUMBER must be configured for the demo payment screen")
            if self.EMBEDDING_PROVIDER != "openai":
                errors.append("EMBEDDING_PROVIDER must be 'openai' on the low-memory demo server")
            if self.CELERY_CONCURRENCY != 1:
                errors.append("CELERY_CONCURRENCY must remain 1 until per-job RAG isolation is implemented")
            if self.DEFAULT_ADMIN_ENABLED:
                if (
                    self.DEFAULT_ADMIN_EMAIL == "admin@example.com"
                    or self.DEFAULT_ADMIN_EMAIL.endswith("@example.com")
                ):
                    errors.append("DEFAULT_ADMIN_EMAIL must not use a sample/development account")
                if (
                    missing(self.DEFAULT_ADMIN_PASSWORD_HASH)
                    or self.DEFAULT_ADMIN_PASSWORD_HASH == default_admin_hash
                    or not self.DEFAULT_ADMIN_PASSWORD_HASH.startswith(("$2a$", "$2b$", "$2y$"))
                ):
                    errors.append("DEFAULT_ADMIN_PASSWORD_HASH must be replaced")

            if errors:
                raise ValueError("Invalid production configuration: " + "; ".join(errors))

        return self
    
    
    


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
        from app.services.runtime_config import get_api_key

        openai_api_key = get_api_key("OPENAI_API_KEY", required=True)
        if not openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY required for OpenAI embeddings. "
                "Set it in Admin system config, .env, or switch to EMBEDDING_PROVIDER='local'"
            )
        
        from langchain_openai import OpenAIEmbeddings
        
       
        return OpenAIEmbeddings(
            model=settings.OPENAI_EMBEDDING_MODEL,
            api_key=openai_api_key, #type: ignore
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
        
