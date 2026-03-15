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
from src.config import CHROMA_DB_DIR, LLM_MODEL_CHEAP
from src.log_config import setup_logger, setup_prompt_logger

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
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0.3)
        
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=get_embedding_model(),
            collection_name="dynamic_context"
        )

        self.prompt_logger = setup_prompt_logger("planner")

        # Multilingual stopwords (Vietnamese + English)
        self.stop_words = [
            # Vietnamese
            'là', 'của', 'và', 'các', 'những', 'cái', 'trong', 'khi', 'bằng', 'người', 'kèo', 'soi', 'bàn', 'city', 'united',
            'được', 'thì', 'mà', 'này', 'nọ', 'với', 'như', 'có', 'cho', 'về', 'tại', 'ng', 'th', 'tr', 'nh', 'ch', 'ph', 'kh', 'gh', 'gi',
            # English
            'the', 'is', 'and', 'to', 'of', 'in', 'for', 'on', 'with', 'as', 'by', 'it',
            'this', 'that', 'are', 'be', 'or', 'from', 'at', 'obj', 'endobj', 'stream', 'endstream', 'flatedecode',
            'xobject', 'colorspace', 'length', 'filter', 'type',
            'endstream', 'startxref', 'xref', 'trailer'

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
            max_features=2000,
            token_pattern=r'\b[a-zA-ZÀ-ỹ]{3,}\b',
            ngram_range=(1, 2)
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
            if attempt == 1:
                self.prompt_logger.log(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    context_label=f"Chapter titles | {num_chapters} chapters | {topic_name[:40]}",
                )
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
        max_subsections: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Phase 2b: Generate subsections for ONE chapter — small focused JSON output.

        Each call produces ~400-600 tokens output → never truncated.
        The structure adapts to the subject domain; section_type controls word count.

        Args:
            max_subsections: Upper bound on subsections (from user depth control)

        Returns:
            List of subsection dicts, or None on failure.
        """
        system_prompt = f"""You are an expert curriculum designer.
Generate between 3 and {max_subsections} subsections for ONE chapter of a Vietnamese textbook.
Choose as many subsections as the chapter NATURALLY needs — do not pad unnecessarily.

OUTPUT: A JSON array of subsection objects. Each object must have:
- "title": string (in Vietnamese — descriptive title suited to the subject domain)
- "description": string (in Vietnamese, 1-2 sentences)
- "search_query": string (in English, 3-5 specific keywords for RAG)
- "section_type": one of "light", "medium", "deep", "applied"

DEPTH LEVEL GUIDE (controls character count — pick what fits the content):
- "light"   → orientation, motivation, recap, bridge to next chapter (~1500-2500 chars)
- "medium"  → explanation, demonstration, illustration, case study (~3000-4500 chars)
- "deep"    → sustained theory, critical analysis, complex technique (~4500-6500 chars)
- "applied" → exercises, hands-on tasks, problems the reader solves (~2500-3500 chars)

IMPORTANT: Choose depth based on HOW MUCH analytical work the section requires,
NOT based on a rigid intro→concept→practice→summary template.
Adapt freely to the subject domain — a cooking chapter differs from a philosophy chapter.

STRUCTURE GUIDANCE:
- Adapt the section structure to the SUBJECT DOMAIN — a history chapter differs from a coding chapter
- Choose an order and mix of depth levels that makes pedagogical sense for THIS chapter
- Subsection titles should reflect actual content (e.g. "Bối cảnh lịch sử", "Phân tích học thuyết")

OUTPUT ONLY THE JSON ARRAY — no markdown, no explanation."""

        user_prompt = (
            f"Textbook topic: {topic_name}\n"
            f"This is Chapter {chapter_index + 1} of {num_chapters}: \"{chapter_title}\"\n\n"
            f"Relevant topic clusters:\n{raw_topics}\n\n"
            f"Generate 3–{max_subsections} subsections appropriate for this chapter:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        chain = prompt | self.llm

        valid_types = {"light", "medium", "deep", "applied"}
        MAX_RETRIES = 3

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt == 1:
                self.prompt_logger.log(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    context_label=f"Ch{chapter_index+1} subsections | {chapter_title[:40]}",
                )
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

                # Enforce max limit (trim if LLM exceeded it)
                if len(subsections) > max_subsections:
                    logger.warning(
                        f"Chapter {chapter_index + 1}: LLM returned {len(subsections)} subsections "
                        f"(limit {max_subsections}) — trimming"
                    )
                    subsections = subsections[:max_subsections]

                # Normalize and validate each subsection
                for sub in subsections:
                    sub.setdefault("title", "Untitled")
                    sub.setdefault("description", "")
                    sub.setdefault("search_query", topic_name)
                    if sub.get("section_type", "") not in valid_types:
                        sub["section_type"] = "medium"

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

    def _generate_textbook_title(self, topic: str, curriculum: CurriculumOutline) -> str:
        """
        Generate a formal academic Vietnamese textbook title from the user request.

        Returns a concise title string (max ~12 words).
        Falls back to "Giáo trình {topic}" on any error.
        """
        logger.info("Generating academic textbook title...")
        chapter_list = "\n".join(
            f"  - {ch.title}" for ch in curriculum.chapters
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "You are a Vietnamese academic textbook editor. "
                "Given a user request and a list of chapter titles, generate ONE formal academic "
                "textbook title. No explanation, no markdown, maximum 12 words. "
                "Output MUST be in Vietnamese. "
                'Example: "Giáo trình Hóa học Đại cương"'
            )),
            ("human", (
                f"User request: {topic}\n\n"
                f"Chapters:\n{chapter_list}\n\n"
                "Output the Vietnamese textbook title:"
            ))
        ])
        try:
            self.prompt_logger.log(
                system_prompt="[Title generator — formal Vietnamese academic title]",
                user_prompt=f"Topic: {topic}\nChapters:\n{chapter_list}",
                context_label="Textbook title generation",
            )
            response = (prompt | self.llm).invoke({})
            title = str(response.content).strip().strip('"').strip("'")  # type: ignore
            logger.info(f"✓ Textbook title: {title}")
            return title
        except Exception as e:
            logger.warning(f"Title generation failed: {e}")
            return f"Giáo trình {topic}"

    def _generate_preface(
        self, topic: str, title: str, curriculum: CurriculumOutline
    ) -> str:
        """
        Generate a Lời nói đầu (preface) page as raw Markdown with LaTeX header.

        Covers: target audience, purpose, chapter structure, unique features, usage guide.
        Returns empty string on failure (preface is optional).
        """
        logger.info("Generating preface (Lời nói đầu)...")
        chapter_summary = "\n".join(
            f"  - Chương {i + 1}: {ch.title}"
            for i, ch in enumerate(curriculum.chapters)
        )
        system_prompt = """You are the author of a Vietnamese university textbook writing the "Lời nói đầu" (Preface).

Write a natural, flowing academic preface. Output raw Markdown — no outer code fences.

REQUIRED — start with exactly these LaTeX commands:

\\begin{{center}}
\\Large\\textbf{{LỜI NÓI ĐẦU}}
\\end{{center}}

\\vspace{{0.5cm}}

Then write 4-6 paragraphs that naturally cover these aspects (in any order, without rigid labels):
- Who the textbook is intended for and what prerequisite knowledge is assumed
- The purpose and learning objectives of the textbook
- How the content is structured across chapters (reference the provided chapter list)
- What makes this textbook distinctive or valuable for students
- How to use the textbook effectively for best results

Style rules:
- Formal academic Vietnamese (văn phong học thuật trang trọng)
- Each paragraph 3-5 sentences, flowing naturally without bolded section labels
- No conversational filler or generic phrases
- Tailor the content specifically to the topic and chapter structure provided

All output MUST be in formal Vietnamese."""

        user_prompt = (
            f"Textbook title: {title}\n"
            f"Topic: {topic}\n\n"
            f"Chapter list:\n{chapter_summary}\n\n"
            "Write the Vietnamese preface now:"
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        try:
            self.prompt_logger.log(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_label=f"Preface | {title[:40]}",
            )
            response = (prompt | self.llm).invoke({})
            preface = str(response.content).strip()  # type: ignore
            logger.info("✓ Preface generated")
            return preface
        except Exception as e:
            logger.warning(f"Preface generation failed: {e}")
            return ""

    def refine_plan_with_llm(
        self,
        topic_name: str,
        raw_topics: str,
        num_chapters: int = 3,
        max_subsections: int = 5,
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
            max_subsections: Upper bound on subsections per chapter

        Returns:
            Dictionary conforming to CurriculumOutline schema, or None on failure.
        """
        logger.info(
            f"Phase 2 (LLM): 2-phase curriculum build — {num_chapters} chapters "
            f"({num_chapters + 1} total LLM calls, max {max_subsections} subsections/chapter)"
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
                raw_topics=raw_topics,
                max_subsections=max_subsections,
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
        num_topics: int = 7,
        max_subsections: int = 5,
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
        plan_dict = self.refine_plan_with_llm(topic, raw_topics, num_chapters=num_chapters, max_subsections=max_subsections)
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
    
    user_request   = state["request"]
    num_chapters   = state.get("num_chapters", 3)             # type: ignore[call-overload]
    max_subsections = state.get("max_subsections_per_chapter", 5)  # type: ignore[call-overload]

    logger.info(f"User request       : {user_request}")
    logger.info(f"Num chapters       : {num_chapters}")
    logger.info(f"Max subsections/ch : {max_subsections}")

    planner = HybridPlanner()
    curriculum = planner.create_curriculum(
        user_request, num_chapters=num_chapters, max_subsections=max_subsections
    )
    
    if not curriculum:
        raise ValueError("Planner failed: Could not generate curriculum")
    
    total_subsections = sum(len(ch.subsections) for ch in curriculum.chapters)

    textbook_title = planner._generate_textbook_title(user_request, curriculum) or f"Giáo trình {user_request}"
    preface_content = planner._generate_preface(user_request, textbook_title, curriculum)

    return {
        "curriculum": curriculum,
        "textbook_title": textbook_title,
        "preface_content": preface_content,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "final_content": "",
        "revision_number": 0,
        "messages": [
            f"✓ Curriculum created: {curriculum.topic}",
            f"  - {len(curriculum.chapters)} chapters planned",
            f"  - Total subsections: {total_subsections}",
            f"  - Textbook title: {textbook_title}",
        ]
    }