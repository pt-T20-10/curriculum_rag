from pyexpat import model
from unittest import result
from torch import embedding
from src.log_config import setup_logger

from yarl import Query
from src.graph.state import AgentState
from typing import List
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from src.config import CHROMA_DB_DIR, EMBEDDING_MODEL_NAME

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")

class ResearcherAgent:
    """_summary_
        ResearcherAgent:
        Responsible for retrieving relevant context (chunks) from the Vector Database
        based on a specific query (Chapter/ Section title).
    """
    
    def __init__(self):
        # Initialize Vector DB Connection
        
        embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=embedding_model,
            collection_name="dynamic_context"
        )
    def retrieve_context(self, query: str, k: int = 5) -> str: # type: ignore
        """
        Search for the most relevant 'k' chunks for a given section title.
        """
        logger.info(f"      Researcher looking for: '{query}")
        
        try:
            # Sematic search
            results = self.vector_db.similarity_search(query, k=k)
            
            if not results:
                logger.warning(f"       No content found for: '{query}'")
                return ""
            
            #Format context string with Source metadata (for citation if needed)
            
            formatted_content = ""
            
            for i, doc in enumerate(results,1):
                source = doc.metadata.get('source', 'Unknown')
                content = doc.page_content.replace('\n', ' ') # Clean newlines
                formatted_content += f"Document {i} (Source: {source}): \n{content}\n\n"
                
            logger.info(f"      Found {len(results)} relevant documents. ")
            return formatted_content
        
        except Exception as e:
            logger.error(f"Error in Researcher: {e}")
            return ""