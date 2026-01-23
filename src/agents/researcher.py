from pyexpat import model
import stat
from unittest import result
from sympy import EX
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
        

def perform_research(state: AgentState):
    """
    Node: Researcher
    Lấy vị trí hiện tại -> Tìm context -> Đẩy vào messages
    """
    logger.info("--- RESEARCHER NODE: Retrieving Context ---")
    
    curriculum = state["curriculum"]
    chap_idx = state["current_chapter_index"]
    sub_idx = state["current_subsection_index"]
    
    try:
        # 1. LẤY CHAPTER
        if isinstance(curriculum, dict):
            current_chapter = curriculum['chapters'][chap_idx]
            
            # 2. LẤY SUBSECTIONS (Hỗ trợ cả 2 key)
            # Thử lấy 'subsections', nếu không có thì lấy 'sections', nếu không có nữa thì lỗi
            if 'subsections' in current_chapter:
                items = current_chapter['subsections']
                is_complex = True # Dạng Dict {title, description...}
            elif 'sections' in current_chapter:
                items = current_chapter['sections']
                is_complex = False # Dạng List[str] cũ
            else:
                raise KeyError("Chapter data missing 'subsections' or 'sections' key.")
            
            # 3. LẤY ITEM CỤ THỂ
            current_item = items[sub_idx]
            
            chap_title = current_chapter.get('title', current_chapter.get('chapter_title', 'Unknown Chapter'))
            
            if is_complex:
                # Nếu là cấu trúc mới (Dict)
                sec_title = current_item.get('title', 'Unknown Section')
                query = current_item.get('search_query', f"{chap_title} - {sec_title}")
            else:
                # Nếu là cấu trúc cũ (String)
                sec_title = current_item
                query = f"{chap_title} - {sec_title}"

        else:
            # Fallback cho Pydantic Object
            current_chapter = curriculum.chapters[chap_idx]
            current_item = current_chapter.subsections[sub_idx]
            chap_title = current_chapter.title
            sec_title = current_item.title
            query = current_item.search_query

        logger.info(f"Target: {sec_title} | Query: {query}")
        
        agent = ResearcherAgent()
        context = agent.retrieve_context(query, k=5)
        
        return {"messages": [context]}
        
    except Exception as e:
        logger.error(f"Error in Researcher Node: {e}")
        # Trả về chuỗi rỗng để không crash luồng, Writer sẽ tự xử lý
        return {"messages": ["Error retrieving context"]}
    
    