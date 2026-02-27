"""
Researcher Agent for AI Textbook Generator.

This agent retrieves relevant document chunks from the vector database
using semantic search based on the current subsection's search query.
"""

from typing import List

from langchain_chroma import Chroma

from src.graph.state import AgentState, CurriculumOutline, Chapter, SubSection, get_chapter_and_subsection
from src.config import CHROMA_DB_DIR
from src.config import get_embedding_model
from src.log_config import setup_logger

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")


class ResearcherAgent:
    """
    Researcher Agent: Retrieves relevant context from vector database.
    
    Responsibilities:
    - Connect to ChromaDB vector store
    - Perform semantic similarity search
    - Format retrieved documents with source metadata
    """
    
    def __init__(self) -> None:
        """Initialize vector DB connection with embedding model."""
    
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function= get_embedding_model(),
            collection_name="dynamic_context"
        )
    
    def retrieve_context(self, query: str, k: int = 5) -> str:
        """
        Search for the most relevant 'k' document chunks for a given query.
        
        Args:
            query: Search query (typically from subsection.search_query)
            k: Number of documents to retrieve
            
        Returns:
            Formatted string of retrieved documents with metadata, or empty string on error.
        """
        logger.info(f"Searching for: '{query}'")
        
        try:
            # Perform semantic similarity search
            results = self.vector_db.similarity_search(query, k=k)
            
            if not results:
                logger.warning(f"No content found for query: '{query}'")
                return ""
            
            # Format context with source metadata for citation
            formatted_content = ""
            for i, doc in enumerate(results, 1):
                source = doc.metadata.get('source', 'Unknown')
                content = doc.page_content.replace('\n', ' ')  # Clean newlines
                formatted_content += f"Document {i} (Source: {source}):\n{content}\n\n"
            
            logger.info(f"Retrieved {len(results)} relevant documents")
            return formatted_content
        
        except Exception as e:
            logger.error(f"Error during retrieval: {e}", exc_info=True)
            return ""


def perform_research(state: AgentState) -> dict:
    """
    Researcher node: Retrieve RAG context for current subsection.
    
    Workflow integration:
    - Input: state["curriculum"], current chapter/subsection indexes
    - Output: state["messages"] with retrieved context
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with retrieved context in messages.
    """
    logger.info("=" * 60)
    logger.info("NODE: Researcher - Retrieving context")
    logger.info("=" * 60)
    
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    try:
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)
        # Access curriculum structure (Pydantic or dict)
        
        chap_title = chapter.title if isinstance(chapter, Chapter) else chapter.get('title', 'Unknown')
        sec_title = subsection.title if isinstance(subsection, SubSection) else subsection.get('title', 'Unknown')
        query = subsection.search_query if isinstance(subsection, SubSection) else subsection.get('search_query', f"{chap_title} - {sec_title}")
        logger.info(f"Target: Chapter {chap_idx + 1}.{sub_idx + 1} - {sec_title}")
        logger.info(f"Query: {query}")
        
        # Retrieve context
        agent = ResearcherAgent()
        context = agent.retrieve_context(query, k=5)
        
        if not context:
            logger.warning("No context retrieved - Writer will use general knowledge")
            return {"messages": ["No specific context found. Using general knowledge."]}
        
        return {
                "rag_context": context,  # Dedicated field
                "messages": [f"✓ Retrieved context for: '{sec_title}' (query: '{query[:40]}...')"]
            }
        
    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {"messages": ["Error: Invalid curriculum index"]}
    
    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {"messages": ["Error: Malformed curriculum structure"]}
    
    except Exception as e:
        logger.error(f"Unexpected error in Researcher: {e}", exc_info=True)
        return {"messages": ["Error retrieving context"]}