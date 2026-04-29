"""
RAG service using ChromaDB for vector storage.
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_huggingface import HuggingFaceEmbeddings
from app.config import settings


class RAGService:
    """Singleton RAG service for ChromaDB operations."""
    
    _instance = None
    _client = None
    _collection = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._initialize()
    
    def _initialize(self):
        """Initialize ChromaDB client and collection."""
        # Create ChromaDB client
        self._client = chromadb.PersistentClient(
            path=str(settings.BASE_DIR / settings.CHROMA_PERSIST_DIR),
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION_NAME,
            metadata={"description": "RAG knowledge base for textbook generation"}
        )
    
    @property
    def collection(self):
        """Get ChromaDB collection."""
        return self._collection
    
    def get_embedding_model(self):
        """Get HuggingFace embedding model."""
        return HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL_NAME,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )


# Singleton instance
rag_service = RAGService()