"""
Planner Agent for AI Textbook Generator.

This module implements a hybrid planning approach:
1. Unsupervised ML (NMF) for cost-effective topic discovery from documents
2. LLM (GPT) for semantic structuring and curriculum design

The planner generates a complete curriculum outline (CurriculumOutline) that
serves as the blueprint for the entire content generation workflow.
"""

import json
from typing import Any, List, Dict, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_chroma import Chroma
from src.config import get_embedding_model

from src.graph.state import AgentState, CurriculumOutline
from src.config import CHROMA_DB_DIR, LLM_MODEL_NAME
from src.log_config import setup_logger

logger = setup_logger(name="PlannerAgent", logfile="logs/agents.log")


class HybridPlanner:
    """
    Hybrid planning agent combining unsupervised ML with LLM refinement.
    
    Architecture:
    - Phase 1 (NMF): Extract topic clusters from vector DB documents
    - Phase 2 (LLM): Refine clusters into structured curriculum with proper schema
    
    The output is a Pydantic CurriculumOutline object that enforces type safety
    and provides JSON schema for downstream nodes.
    """
    
    def __init__(self) -> None:
        """Initialize LLM, vector DB connection, and stopwords."""
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.3)
     
        
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=get_embedding_model(),
            collection_name="dynamic_context"
        )

        # Multilingual stopwords (Vietnamese + English)
        self.stop_words = [
            # Vietnamese
            'là', 'của', 'và', 'các', 'những', 'cái', 'trong', 'khi', 'bằng', 'người', 
            'được', 'thì', 'mà', 'này', 'nọ', 'với', 'như', 'có', 'cho', 'về', 'tại',
            # English
            'the', 'is', 'and', 'to', 'of', 'in', 'for', 'on', 'with', 'as', 'by', 'it',
            'this', 'that', 'are', 'be', 'or', 'from', 'at'
        ]
        
    def get_all_documents(self) -> List[str]:
        """
        Retrieve all document chunks from ChromaDB.
        
        Returns:
            List of text chunks for topic modeling, or empty list on error.
        """
        try:
            data = self.vector_db.get()
            docs = data['documents']
            logger.info(f"Retrieved {len(docs)} document chunks from vector database")
            return docs
        except Exception as e:
            logger.error(f"Failed to fetch documents from vector DB: {e}", exc_info=True)
            return []
        
    def extract_topics_with_nmf(self, docs: List[str], num_topics: int = 8) -> str:
        """
        Phase 1: Extract topic clusters using Non-negative Matrix Factorization (NMF).
        
        Pipeline:
        1. TF-IDF vectorization (term importance weighting)
        2. NMF decomposition (dimensionality reduction to topics)
        3. Keyword extraction (top-N terms per topic)
        
        Args:
            docs: List of document chunks
            num_topics: Number of topic clusters to extract
            
        Returns:
            Formatted string of topic clusters with keywords, or empty string on failure.
        """
        logger.info(f"Phase 1 (NMF): Extracting {num_topics} topic clusters...")
        
        # Step 1: TF-IDF Vectorization
        vectorizer = TfidfVectorizer(
            max_df=0.95,           # Ignore terms appearing in >95% of docs (too common)
            min_df=2,              # Ignore terms appearing in <2 docs (too rare)
            stop_words=self.stop_words,
            max_features=2000      # Limit vocabulary size
        )
        
        try:
            tfidf_matrix = vectorizer.fit_transform(docs)
        except ValueError as e:
            logger.warning(f"Insufficient data for TF-IDF vectorization: {e}")
            return ""
        
        # Step 2: NMF Decomposition
        nmf = NMF(
            n_components=num_topics,
            random_state=42,
            init='nndsvd'  # Improved initialization for better convergence
        )
        nmf.fit(tfidf_matrix)
        
        feature_names = vectorizer.get_feature_names_out()
        
        # Step 3: Extract Top Keywords per Topic
        topics_summary = []
        for topic_idx, topic in enumerate(nmf.components_):
            # Get indices of top 10 keywords (sorted by weight)
            top_indices = topic.argsort()[:-11:-1]
            keywords = [str(feature_names[i]) for i in top_indices]
            
            summary_line = f"- Topic Cluster {topic_idx + 1}: {', '.join(keywords)}"
            topics_summary.append(summary_line)
        
        result_text = "\n".join(topics_summary)
        logger.info(f"Extracted topic clusters:\n{result_text}")
        return result_text
    
    def refine_plan_with_llm(self, topic_name: str, raw_topics: str) -> Optional[Dict[str, Any]]:
        """
        Phase 2: Refine raw topic clusters into structured curriculum using LLM.
        
        The LLM:
        1. Analyzes keyword clusters to understand content themes
        2. Organizes topics into pedagogical flow (basic → advanced)
        3. Generates professional titles and subsections
        4. Returns structured JSON matching CurriculumOutline schema
        
        Args:
            topic_name: Main subject/topic from user request
            raw_topics: NMF-extracted topic clusters
            
        Returns:
            Dictionary conforming to CurriculumOutline schema, or None on parse failure.
        """
        logger.info("Phase 2 (LLM): Refining curriculum structure...")
        
        # CRITICAL FIX: Remove newlines from JSON example to avoid LangChain parsing it as variable
        system_prompt = """You are an expert curriculum designer and professor.

You will receive raw topic keywords extracted from a document corpus via NMF algorithm.

YOUR TASK:
1. Analyze the keyword clusters to understand core content themes
2. Structure topics into logical pedagogical flow (foundational → intermediate → advanced)
3. Create professional chapter titles based on the themes
4. Design 3-5 subsections for each chapter with specific learning objectives

CRITICAL CONSTRAINTS:
- Output content (titles, descriptions) MUST be in Vietnamese (Tiếng Việt)
- Output format MUST be valid JSON matching this EXACT schema (all in one line, no line breaks):

{{"topic": "Tên chủ đề chính", "chapters": [{{"title": "Tên chương 1", "subsections": [{{"title": "Tên phần 1.1", "description": "Mô tả ngắn gọn nội dung phần này", "search_query": "từ khóa tìm kiếm tiếng Anh cho RAG"}}]}}]}}

IMPORTANT FOR search_query:
- Use English keywords for better RAG retrieval
- Be specific and technical (e.g., "Python variable types scope" not just "variables")
- Include 3-5 relevant terms per query

OUTPUT ONLY THE JSON - NO MARKDOWN FENCES, NO PREAMBLE, NO LINE BREAKS IN JSON."""

        user_prompt = f"""Subject: {topic_name}

Raw Keyword Clusters (from NMF):
{raw_topics}

Generate the structured curriculum now:"""
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        
        try:
            chain = prompt | self.llm
            # FIX: Pass empty dict explicitly (no variables needed, all in messages)
            response = chain.invoke({"topic_name": topic_name, "raw_topics": raw_topics})
            
            # Parse LLM JSON response with defensive extraction
            content = response.content.strip()  # type: ignore
            
            # Remove markdown code fences if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()
            
            parsed_json = json.loads(content)
            
            # Validate basic structure
            if "chapters" not in parsed_json:
                logger.error("LLM output missing 'chapters' field")
                return None
            
            logger.info(f"Successfully parsed curriculum with {len(parsed_json['chapters'])} chapters")
            return parsed_json
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM output: {e}")
            logger.debug(f"Raw LLM output: {response.content}")  # type: ignore
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing LLM response: {e}", exc_info=True)
            return None
    
    def create_curriculum(self, topic: str, num_topics: int = 7) -> Optional[CurriculumOutline]:
        """
        Main orchestration: Run hybrid planning pipeline.
        
        Pipeline:
        1. Fetch all documents from vector DB
        2. Extract topic clusters via NMF
        3. Refine into structured curriculum via LLM
        4. Parse into Pydantic CurriculumOutline object
        
        Args:
            topic: User's requested subject
            num_topics: Number of NMF topic clusters to extract
            
        Returns:
            CurriculumOutline Pydantic object, or None on failure.
        """
        # Step 1: Get corpus
        docs = self.get_all_documents()
        if not docs:
            logger.error("No documents found in vector DB. Run ingestion first.")
            return None
        
        # Step 2: NMF topic extraction
        raw_topics = self.extract_topics_with_nmf(docs, num_topics=num_topics)
        if not raw_topics:
            logger.error("Topic extraction failed - insufficient data")
            return None
        
        # Step 3: LLM refinement
        plan_dict = self.refine_plan_with_llm(topic, raw_topics)
        if not plan_dict:
            logger.error("LLM refinement failed - could not generate valid curriculum")
            return None
        
        # Step 4: Parse into Pydantic model for type safety
        try:
            curriculum = CurriculumOutline(**plan_dict)
            logger.info(f"✓ Created curriculum: {curriculum.topic} ({len(curriculum.chapters)} chapters)")
            return curriculum
        except Exception as e:
            logger.error(f"Failed to parse curriculum into Pydantic model: {e}")
            logger.debug(f"Dict structure: {plan_dict}")
            return None


def plan_curriculum(state: AgentState) -> dict:
    """
    Planner node: Generate curriculum outline from user request.
    
    Workflow integration:
    - Input: state["request"] (user's topic request)
    - Output: state["curriculum"] (CurriculumOutline object)
    
    Also initializes workflow tracking fields:
    - current_chapter_index = 0
    - current_subsection_index = 0
    - revision_number = 0
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with curriculum and initialized tracking fields.
    """
    logger.info("=" * 60)
    logger.info("NODE: Planner - Building curriculum outline")
    logger.info("=" * 60)
    
    user_request = state["request"]
    logger.info(f"User request: {user_request}")
    
    # Run hybrid planning pipeline
    planner = HybridPlanner()
    curriculum = planner.create_curriculum(user_request)
    
    if not curriculum:
        raise ValueError("Planner failed: Could not generate curriculum")
    
    # Initialize workflow state
    return {
        "curriculum": curriculum,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "final_content": "",
        "revision_number": 0,
        "messages": [
            f"✓ Curriculum created: {curriculum.topic}",
            f"  - {len(curriculum.chapters)} chapters planned",
            f"  - Total subsections: {sum(len(ch.subsections) for ch in curriculum.chapters)}"
        ]
    }