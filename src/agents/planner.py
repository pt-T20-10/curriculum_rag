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
        
        vectorizer = TfidfVectorizer(
            max_df=0.95,
            min_df=2,
            stop_words=self.stop_words,
            max_features=2000
        )
        
        try:
            tfidf_matrix = vectorizer.fit_transform(docs)
        except ValueError as e:
            logger.warning(f"Insufficient data for TF-IDF vectorization: {e}")
            return ""
        
        nmf = NMF(
            n_components=num_topics,
            random_state=42,
            init='nndsvd'
        )
        nmf.fit(tfidf_matrix)
        
        feature_names = vectorizer.get_feature_names_out()
        
        topics_summary = []
        for topic_idx, topic in enumerate(nmf.components_):
            top_indices = topic.argsort()[:-11:-1]
            keywords = [str(feature_names[i]) for i in top_indices]
            summary_line = f"- Topic Cluster {topic_idx + 1}: {', '.join(keywords)}"
            topics_summary.append(summary_line)
        
        result_text = "\n".join(topics_summary)
        logger.info(f"Extracted topic clusters:\n{result_text}")
        return result_text
    
    @staticmethod
    def _extract_json(raw: str) -> Any:
        """
        Robust JSON extractor — handles markdown fences and leading/trailing prose.
        Raises json.JSONDecodeError if no valid JSON found.
        """
        content = raw.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].strip()
        else:
            start = content.find("{")
            end   = content.rfind("}")
            if start != -1 and end > start:
                content = content[start:end + 1]
        return json.loads(content)

    def _plan_chapter_titles(
        self,
        topic_name: str,
        raw_topics: str,
        num_chapters: int
    ) -> Optional[List[str]]:
        """
        Phase 2a: Generate ONLY chapter titles — tiny JSON output (~300 tokens).
        
        Returns:
            List of chapter title strings, or None on failure.
        """
        logger.info(f"Phase 2a: Planning {num_chapters} chapter titles...")

        system_prompt = (
            "You are a curriculum designer. "
            "Given a subject and topic clusters, output ONLY a JSON array of chapter titles in Vietnamese. "
            f"You MUST output EXACTLY {num_chapters} titles. "
            "No explanation, no markdown, no extra keys — just the JSON array.\n\n"
            'Example output: ["Chương 1 title", "Chương 2 title"]'
        )
        user_prompt = (
            f"Subject: {topic_name}\n"
            f"Number of chapters: {num_chapters}\n\n"
            f"Topic clusters:\n{raw_topics}\n\n"
            f"Output a JSON array of exactly {num_chapters} chapter titles:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        chain = prompt | self.llm

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = chain.invoke({})
                raw = str(response.content).strip()  # type: ignore

                # Extract JSON array
                start = raw.find("[")
                end   = raw.rfind("]")
                if start == -1 or end == -1:
                    raise ValueError("No JSON array found in response")
                titles = json.loads(raw[start:end + 1])

                if not isinstance(titles, list) or len(titles) == 0:
                    raise ValueError("Empty or non-list response")

                if len(titles) != num_chapters:
                    logger.warning(
                        f"Got {len(titles)} titles instead of {num_chapters} — "
                        f"padding/trimming to match"
                    )
                    # Trim if too many
                    titles = titles[:num_chapters]
                    # Pad if too few
                    while len(titles) < num_chapters:
                        titles.append(f"Chương {len(titles) + 1}: {topic_name}")

                logger.info(f"✓ Phase 2a: {len(titles)} chapter titles planned")
                return [str(t) for t in titles]

            except Exception as e:
                logger.warning(f"Phase 2a attempt {attempt}/{MAX_RETRIES} failed: {e}")

        logger.error("Phase 2a: Failed to generate chapter titles after all retries")
        return None

    def _generate_chapter_subsections(
        self,
        topic_name: str,
        chapter_title: str,
        chapter_index: int,
        num_chapters: int,
        raw_topics: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Phase 2b: Generate subsections for ONE chapter — small focused JSON output.
        
        Each call produces ~400-600 tokens output → never truncated.
        
        Returns:
            List of subsection dicts, or None on failure.
        """
        system_prompt = """You are an expert curriculum designer.
Generate 3-5 subsections for ONE chapter of a Vietnamese textbook.

OUTPUT: A JSON array of subsection objects. Each object must have:
- "title": string (in Vietnamese)
- "description": string (in Vietnamese, 1-2 sentences)
- "search_query": string (in English, 3-5 specific keywords for RAG)
- "section_type": one of "intro", "concept", "example", "practice", "summary"

SECTION TYPE RULES:
- First subsection: always "intro"
- Last subsection: always "summary"  
- Middle subsections: "concept", "example", or "practice" based on content

OUTPUT ONLY THE JSON ARRAY — no markdown, no explanation."""

        user_prompt = (
            f"Textbook topic: {topic_name}\n"
            f"This is Chapter {chapter_index + 1} of {num_chapters}: \"{chapter_title}\"\n\n"
            f"Relevant topic clusters:\n{raw_topics}\n\n"
            f"Generate 3-5 subsections for this chapter now:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        chain = prompt | self.llm

        valid_types = {"intro", "concept", "example", "practice", "summary"}
        MAX_RETRIES = 3

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = chain.invoke({})
                raw = str(response.content).strip()  # type: ignore

                # Extract JSON array
                start = raw.find("[")
                end   = raw.rfind("]")
                if start == -1 or end == -1:
                    raise ValueError("No JSON array in response")
                subsections = json.loads(raw[start:end + 1])

                if not isinstance(subsections, list) or len(subsections) == 0:
                    raise ValueError("Empty subsection list")

                # Normalize and validate each subsection
                for sub in subsections:
                    sub.setdefault("title", "Untitled")
                    sub.setdefault("description", "")
                    sub.setdefault("search_query", topic_name)
                    if sub.get("section_type", "") not in valid_types:
                        sub["section_type"] = "concept"

                # Enforce intro/summary on first/last
                subsections[0]["section_type"]  = "intro"
                subsections[-1]["section_type"] = "summary"

                logger.info(
                    f"  ✓ Chapter {chapter_index + 1} '{chapter_title}': "
                    f"{len(subsections)} subsections"
                )
                return subsections

            except Exception as e:
                logger.warning(
                    f"Chapter {chapter_index + 1} attempt {attempt}/{MAX_RETRIES} failed: {e}"
                )

        logger.error(f"Failed to generate subsections for chapter {chapter_index + 1}")
        return None

    def refine_plan_with_llm(
        self,
        topic_name: str,
        raw_topics: str,
        num_chapters: int = 3
    ) -> Optional[Dict[str, Any]]:
        """
        Phase 2: Build full curriculum via 2-phase approach to avoid token limit.

        Phase 2a — 1 small LLM call → chapter titles list  (~300 tokens output)
        Phase 2b — N small LLM calls → subsections per chapter (~500 tokens/call)

        Total output tokens = 300 + (N × 500) — never truncated regardless of N.

        Args:
            topic_name: Main subject/topic from user request
            raw_topics: NMF-extracted topic clusters
            num_chapters: Exact number of chapters to generate

        Returns:
            Dictionary conforming to CurriculumOutline schema, or None on failure.
        """
        logger.info(
            f"Phase 2 (LLM): 2-phase curriculum build — {num_chapters} chapters "
            f"({num_chapters + 1} total LLM calls)"
        )

        # Phase 2a: Get chapter titles
        chapter_titles = self._plan_chapter_titles(topic_name, raw_topics, num_chapters)
        if not chapter_titles:
            return None

        # Phase 2b: Generate subsections for each chapter independently
        chapters = []
        failed_chapters = 0

        for idx, title in enumerate(chapter_titles):
            subsections = self._generate_chapter_subsections(
                topic_name=topic_name,
                chapter_title=title,
                chapter_index=idx,
                num_chapters=num_chapters,
                raw_topics=raw_topics
            )
            if subsections:
                chapters.append({"title": title, "subsections": subsections})
            else:
                failed_chapters += 1
                logger.warning(f"Skipping chapter {idx + 1} due to generation failure")
                # Add minimal fallback chapter so curriculum is not broken
                chapters.append({
                    "title": title,
                    "subsections": [
                        {
                            "title": f"Giới thiệu về {title}",
                            "description": f"Tổng quan về {title}",
                            "search_query": f"{topic_name} {title} introduction",
                            "section_type": "intro"
                        }
                    ]
                })

        if failed_chapters == num_chapters:
            logger.error("All chapters failed to generate subsections")
            return None

        total_subsections = sum(len(c["subsections"]) for c in chapters)
        logger.info(
            f"✓ Curriculum built: {len(chapters)} chapters, "
            f"{total_subsections} subsections "
            f"({failed_chapters} chapters used fallback)"
        )

        return {"topic": topic_name, "chapters": chapters}
    
    def create_curriculum(
        self,
        topic: str,
        num_chapters: int = 3,
        num_topics: int = 7
    ) -> Optional[CurriculumOutline]:
        """
        Main orchestration: Run hybrid planning pipeline.
        
        Pipeline:
        1. Fetch all documents from vector DB
        2. Extract topic clusters via NMF
        3. Refine into structured curriculum via LLM (with num_chapters constraint)
        4. Parse into Pydantic CurriculumOutline object
        
        Args:
            topic: User's requested subject
            num_chapters: Number of chapters to generate (from user config)
            num_topics: Number of NMF topic clusters to extract (auto-scaled to num_chapters)
            
        Returns:
            CurriculumOutline Pydantic object, or None on failure.
        """
        # Scale NMF topics to at least cover the requested chapters
        # More chapters → need more topic clusters for variety
        effective_num_topics = max(num_topics, num_chapters + 2)
        
        # Step 1: Get corpus
        docs = self.get_all_documents()
        if not docs:
            logger.error("No documents found in vector DB. Run ingestion first.")
            return None
        
        # Step 2: NMF topic extraction
        # If corpus is too small for the requested num_topics, scale down gracefully
        raw_topics = ""
        for n_topics in [effective_num_topics, max(3, effective_num_topics // 2), 3]:
            raw_topics = self.extract_topics_with_nmf(docs, num_topics=n_topics)
            if raw_topics:
                if n_topics < effective_num_topics:
                    logger.warning(
                        f"NMF scaled down: {effective_num_topics} → {n_topics} topics "
                        f"(corpus may be too small)"
                    )
                break

        if not raw_topics:
            logger.error("Topic extraction failed at all fallback levels - insufficient data")
            return None
        
        # Step 3: LLM refinement — refine_plan_with_llm already retries internally
        plan_dict = self.refine_plan_with_llm(topic, raw_topics, num_chapters=num_chapters)
        if not plan_dict:
            logger.error("LLM refinement failed after all retries")
            return None
        
        # Step 4: Parse into Pydantic model
        try:
            curriculum = CurriculumOutline(**plan_dict)
            logger.info(
                f"✓ Created curriculum: '{curriculum.topic}' "
                f"({len(curriculum.chapters)} chapters)"
            )
            return curriculum
        except Exception as e:
            logger.error(f"Failed to parse curriculum into Pydantic model: {e}")
            logger.debug(f"Dict structure: {plan_dict}")
            return None


def plan_curriculum(state: AgentState) -> dict:
    """
    Planner node: Generate curriculum outline from user request.
    
    Reads user config from state:
    - num_chapters: exact number of chapters to generate
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with curriculum and initialized tracking fields.
    """
    logger.info("=" * 60)
    logger.info("NODE: Planner - Building curriculum outline")
    logger.info("=" * 60)
    
    user_request = state["request"]
    num_chapters  = state.get("num_chapters", 3)   # type: ignore[call-overload]
    
    logger.info(f"User request : {user_request}")
    logger.info(f"Num chapters : {num_chapters}")
    
    planner = HybridPlanner()
    curriculum = planner.create_curriculum(user_request, num_chapters=num_chapters)
    
    if not curriculum:
        raise ValueError("Planner failed: Could not generate curriculum")
    
    total_subsections = sum(len(ch.subsections) for ch in curriculum.chapters)
    
    return {
        "curriculum": curriculum,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "final_content": "",
        "revision_number": 0,
        "messages": [
            f"✓ Curriculum created: {curriculum.topic}",
            f"  - {len(curriculum.chapters)} chapters planned",
            f"  - Total subsections: {total_subsections}"
        ]
    }