import stat
import sys
import os
import json
import logging
from typing import Any, List, Dict, Optional

# --- Import Libraries ---
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF
from sympy import Plane
from src.graph.state import AgentState

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from src.config import CHROMA_DB_DIR, EMBEDDING_MODEL_NAME, LLM_MODEL_NAME
from src.log_config import setup_logger

# Setup Logger
logger = setup_logger(name="PlannerAgent", logfile="logs/agents.log")


class HybridPlanner:
    """
    Hybrid Planner Agent:
    Combines Unsupervised Machine Learning (NMF) for cost-effective topic discovery
    with LLM (GPT) for semantic structuring and titling.
    """
    def __init__(self) -> None:
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.3)
        
        embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=embedding_model,
            collection_name="dynamic_context"
        )

        # Stopwords
        self.stop_words = [
            'là', 'của', 'và', 'các', 'những', 'cái', 'trong', 'khi', 'bằng', 'người', 
            'được', 'thì', 'mà', 'này', 'nọ', 'với', 'như', 'có', 'cho', 'về', 'tại',
            'the', 'is', 'and', 'to', 'of', 'in', 'for', 'on', 'with', 'as', 'by', 'it',
            'this', 'that', 'are', 'be', 'or', 'from', 'at'
        ]
        
        
    def get_all_documents(self) -> List[str]: 
        """Retrieve all text chunks from ChromaDB."""
        try:
            data = self.vector_db.get()
            docs = data['documents']
            logger.info(f"      Loaded {len(docs)} chunks from Database")
            return docs
        except Exception as e:
            logger.error(f"Error fetching docs: {e}")
            return []
        
        
    def extract_topics_with_nmf(self, docs: List[str], num_topics=8) -> str:
        """PHASE 1 (ALGO): Topic Modeling using NMF."""
        logger.info("       Algo Phase: Running Topic Modeling (NMF)...")
        
        # 1. TF-IDF
        vectorizer = TfidfVectorizer(
               max_df=0.95, # Maximum Document Frequency
               min_df=2,  # Minimum Document Frequency
               stop_words=self.stop_words,
               max_features=2000 
            )
        
        
        try: 
            tfidf = vectorizer.fit_transform(docs)
            
        except ValueError:
            logger.warning("Not enough data for TF-IDF. Returning empty topics.")
            return ""
        
        # 2. NMF
        # Non-negative Matrix Factorization
        nmf = NMF(n_components=num_topics, random_state=42, init='nndsvd')
        nmf.fit(tfidf)         
        
        feature_names = vectorizer.get_feature_names_out()
        
        # 3. Extract Keywords
        topics_summary = []
        for topic_idx, topic in enumerate(nmf.components_):
            topic_indices = topic.argsort()[:-11:-1]

            keywords = [str(feature_names[i]) for i in topic_indices]
            
            summary_line = f"- Nhóm {topic_idx + 1}: {', '.join(keywords)}"
            topics_summary.append(summary_line)
            
        result_text = "\n".join(topics_summary)
        

        logger.info(f"       Identified raw topic clusters: \n{result_text}")
        return result_text
    
    
    def refine_plan_with_llm(self, topic_name: str, raw_topics: str) -> Optional[Dict[str, Any]]:
        """PHASE 2 (LLM): Refine and Structure using GPT."""
        logger.info("   🧠 LLM Phase: Refining structure (English Instructions)...")
        
        system_prompt = """You are a Professor and Expert Curriculum Designer.
        You will receive raw topic keywords extracted from a dataset about a specific subject via an algorithm (NMF).
        
        YOUR TASK:
        1. Analyze the raw keywords to understand the core content themes available in the database.
        2. Structure these topics into a logical pedagogical flow (e.g., from Basic concepts to Advanced techniques).
        3. Create professional, academic Chapter Titles based on the keywords.
        4. Design concise Sections (sub-chapters) for each chapter.
        
        CRITICAL CONSTRAINTS:
        - The Output Content (Titles, Sections) MUST BE in VIETNAMESE (Tiếng Việt).
        - The Output Format MUST BE valid JSON.
        
        JSON STRUCTURE EXAMPLE:
        {{
            "title": "Tên giáo trình (in Vietnamese)",
            "chapters": [
                {{
                    "chapter_title": "Tên chương 1 (in Vietnamese)",
                    "sections": ["Mục 1.1", "Mục 1.2", "Mục 1.3"]
                }}
            ]
        }}
        """      
        user_prompt = f"""
        Subject: {topic_name}
        
        Raw Keyword Clusters (from NMF Algorithm):
        {raw_topics}
        
        Generate the Vietnamese Curriculum Plan now:
        """
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        
        chain = prompt | self.llm
        response = chain.invoke({})
        
        # Parse Json Response 
        try:
            content = response.content.strip() # type: ignore
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()
            
            # FIX JSON: Used json.loads (for string) instead of json.load (for file)
            return json.loads(content) 
        
        except Exception as e:
            logger.error(f"Failed to parse Json from Planner Output: {e}")
            # FIX LOG: Fixed typo 'respone' and added 'f'
            logger.debug(f"Raw Output: {response.content}")
            return None
        
        
    def create_curriculum(self, topic: str) -> Optional[Dict[str, Any]]: 
        """Main orchestration method."""
        docs = self.get_all_documents()
        if not docs:
            logger.error("No documents found in DB. Please run Crawler first.")
            return None
        
        raw_topic_str = self.extract_topics_with_nmf(docs, num_topics=7)
        if not raw_topic_str:
            return None
        
        final_plan = self.refine_plan_with_llm(topic, raw_topic_str)
        return final_plan
    
def plan_curriculum(state: AgentState):
        """
        Node: Planner 
        Input request -> Output Curriculum Outline (Dict)
        """
        logger.info(f"--- PLANNER NODE: Building Curriculum ---")
        user_request = state["request"]
        
        planner = HybridPlanner()
        plan_data = planner.create_curriculum(user_request)
        
        if not plan_data:
            return {"messages": ["Error: Planner failed."]}
        
        
        if 'chapters' in plan_data and len(plan_data['chapters']) > 0:
            logger.warning("⚠️ TEST MODE: Keeping only the first chapter for speed.")
            plan_data['chapters'] = plan_data['chapters'][:1]  # <--- CẮT NGẮN TẠI ĐÂY
        
        return{
            "curriculum": plan_data,
            "current_chapter_index": 0,
            "current_subsection_index": 0,
            "final_content": "",
            "revision_number": 0,
            "messages": [f"Plan created for: {user_request}"]
        }