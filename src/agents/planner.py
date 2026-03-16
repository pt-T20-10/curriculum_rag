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
            'là', 'của', 'và', 'các', 'những', 'cái', 'trong', 'khi', 'bằng', 'người',
            'kèo', 'soi', 'bàn', 'city', 'united',
            'được', 'thì', 'mà', 'này', 'nọ', 'với', 'như', 'có', 'cho', 'về', 'tại',
            'ng', 'th', 'tr', 'nh', 'ch', 'ph', 'kh', 'gh', 'gi',
            # English
            'the', 'is', 'and', 'to', 'of', 'in', 'for', 'on', 'with', 'as', 'by', 'it',
            'this', 'that', 'are', 'be', 'or', 'from', 'at', 'obj', 'endobj', 'stream',
            'endstream', 'flatedecode', 'xobject', 'colorspace', 'length', 'filter', 'type',
            'endstream', 'startxref', 'xref', 'trailer',
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

    # =========================================================================
    # FIX 1 — NMF signal quality
    #
    # BEFORE: min_df=2 hardcoded → accepted hapax-legomena noise on small corpora,
    #         near-identical clusters were passed directly to the LLM.
    #
    # AFTER:
    #   1. min_df is computed adaptively from corpus size:
    #      corpus < 50 docs  → min_df=2 (lenient, small corpus)
    #      corpus 50-200     → min_df=3
    #      corpus > 200      → min_df=5 (strict, large corpus)
    #   2. max_df lowered 0.95 → 0.90 to cut ultra-common domain terms that
    #      appear in almost every chunk (e.g. "mạng nơ-ron" in a DL corpus).
    #   3. After NMF, deduplicate near-identical topic clusters by computing
    #      Jaccard similarity on their top-5 keyword sets. If two clusters share
    #      ≥ 3 keywords they are considered duplicates; only the first is kept.
    #      This prevents the LLM from receiving 8 variations of "gradient descent"
    #      and generating the same chapter content in every slot.
    # =========================================================================

    def extract_topics_with_nmf(self, docs: List[str], num_topics: int = 8) -> str:
        """
        Phase 1: Extract topic clusters using Non-negative Matrix Factorization (NMF).

        Pipeline:
        1. TF-IDF vectorization (term importance weighting, adaptive min_df)
        2. NMF decomposition (dimensionality reduction to topics)
        3. Keyword extraction (top-N terms per topic)
        4. Near-duplicate cluster deduplication (Jaccard on top-5 keywords)

        Args:
            docs: List of document chunks
            num_topics: Number of topic clusters to extract

        Returns:
            Formatted string of unique topic clusters with keywords, or "" on failure.
        """
        logger.info(f"Phase 1 (NMF): Extracting {num_topics} topic clusters...")

        # FIX 1a — adaptive min_df based on corpus size
        n_docs = len(docs)
        if n_docs < 50:
            min_df = 2
        elif n_docs < 200:
            min_df = 3
        else:
            min_df = 5
        logger.info(f"NMF adaptive min_df={min_df} for corpus size={n_docs}")

        vectorizer = TfidfVectorizer(
            max_df=0.90,       # FIX 1b — was 0.95; cut ultra-common domain terms
            min_df=min_df,     # FIX 1a — adaptive instead of hardcoded 2
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

        # Extract top-10 keywords per cluster
        raw_clusters: List[List[str]] = []
        for topic in nmf.components_:
            top_indices = topic.argsort()[:-11:-1]
            keywords = [str(feature_names[i]) for i in top_indices]
            raw_clusters.append(keywords)

        # FIX 1c — deduplicate near-identical clusters via Jaccard on top-5 keywords
        def jaccard(a: List[str], b: List[str]) -> float:
            sa, sb = set(a[:5]), set(b[:5])
            if not sa and not sb:
                return 1.0
            return len(sa & sb) / len(sa | sb)

        JACCARD_THRESHOLD = 0.60  # ≥ 3 of 5 shared keywords → duplicate
        unique_clusters: List[List[str]] = []
        for candidate in raw_clusters:
            is_dup = any(
                jaccard(candidate, kept) >= JACCARD_THRESHOLD
                for kept in unique_clusters
            )
            if not is_dup:
                unique_clusters.append(candidate)

        removed = len(raw_clusters) - len(unique_clusters)
        if removed:
            logger.info(f"NMF dedup: removed {removed} near-identical clusters → {len(unique_clusters)} unique")

        topics_summary = [
            f"- Topic Cluster {i + 1}: {', '.join(kws)}"
            for i, kws in enumerate(unique_clusters)
        ]
        return "\n".join(topics_summary)

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

    # =========================================================================
  
    #
    # BEFORE: Prompt asked for N chapter titles with no structural guidance.
    #         LLM produced titles that sounded different but covered the same
    #         content space (e.g. 3 "intro to MLP" chapters in a DL book).
    #
    # AFTER:  System prompt now enforces a 3-zone progressive arc:
    #           Zone A (first ~third):  foundations, concepts, terminology
    #           Zone B (middle ~third): core techniques, mechanisms, analysis
    #           Zone C (last ~third):   applications, advanced topics, integration
    #         Each title must cover a DISTINCT aspect not covered by any other.
    #         The prompt also explicitly forbids repeating the same concept
    #         across multiple chapter slots.
    # =========================================================================

    def _plan_chapter_titles(
        self,
        topic_name: str,
        raw_topics: str,
        num_chapters: int
    ) -> Optional[List[str]]:
        """
        Phase 2a: Generate chapter titles with progressive structural constraint.

        Returns:
            List of chapter title strings, or None on failure.
        """
        logger.info(f"Phase 2a: Planning {num_chapters} chapter titles...")

        # FIX 2 — compute zone sizes for the progressive arc instruction
        zone_a = max(1, num_chapters // 3)
        zone_b = max(1, num_chapters // 3)
        zone_c = num_chapters - zone_a - zone_b

        system_prompt = (
            "You are a curriculum designer building a Vietnamese university textbook.\n\n"
            f"Generate EXACTLY {num_chapters} chapter titles for the subject below.\n\n"
            "CRITICAL RULES:\n"
            "1. Every chapter must cover a DISTINCT aspect of the subject — no two chapters "
            "may overlap in their primary topic.\n"
            "2. Follow a progressive learning arc:\n"
            f"   - Chapters 1–{zone_a}: Foundations (concepts, definitions, basic theory)\n"
            f"   - Chapters {zone_a + 1}–{zone_a + zone_b}: Core techniques and mechanisms\n"
            f"   - Chapters {zone_a + zone_b + 1}–{num_chapters}: Applications, advanced topics, integration\n"
            "3. DO NOT repeat or rephrase the same concept in different chapters.\n"
            "4. Titles should be specific and descriptive (e.g. 'Mạng nơ-ron tích chập CNN' "
            "not just 'Học sâu').\n\n"
            "OUTPUT: A JSON array of exactly {n} Vietnamese chapter titles. "
            "No explanation, no markdown — ONLY the JSON array.\n"
            'Example: ["Tiêu đề chương 1", "Tiêu đề chương 2"]'
        ).format(n=num_chapters)

        user_prompt = (
            f"Subject: {topic_name}\n"
            f"Number of chapters: {num_chapters}\n\n"
            f"Topic clusters discovered from course materials:\n{raw_topics}\n\n"
            f"Output a JSON array of exactly {num_chapters} distinct, progressive chapter titles:"
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
                    titles = titles[:num_chapters]
                    while len(titles) < num_chapters:
                        titles.append(f"Chương {len(titles) + 1}: {topic_name}")

                logger.info(f"✓ Phase 2a: {len(titles)} chapter titles planned")
                return [str(t) for t in titles]

            except Exception as e:
                logger.warning(f"Phase 2a attempt {attempt}/{MAX_RETRIES} failed: {e}")

        logger.error("Phase 2a: Failed to generate chapter titles after all retries")
        return None

    # =========================================================================
    # FIX 3 — Pass already-assigned chapter context into subsection generation
    #
    # BEFORE: Each chapter's subsections were generated in isolation. The LLM
    #         had no awareness of what other chapters covered, causing every
    #         chapter to independently produce MLP → Backprop → Optimizer.
    #
    # AFTER:  _generate_chapter_subsections now accepts `assigned_chapters`
    #         (a list of {title, subsection_titles} dicts for all chapters
    #         generated so far). This context is injected into the user prompt
    #         so the LLM can see what's already been covered and deliberately
    #         generate non-overlapping subsections for the current chapter.
    #
    #         refine_plan_with_llm accumulates this list after each chapter
    #         and passes it forward.
    # =========================================================================

    def _generate_chapter_subsections(
        self,
        topic_name: str,
        chapter_title: str,
        chapter_index: int,
        num_chapters: int,
        raw_topics: str,
        max_subsections: int = 5,
        assigned_chapters: Optional[List[Dict[str, Any]]] = None,  # FIX 3
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Phase 2b: Generate subsections for ONE chapter.

        FIX 3: accepts `assigned_chapters` — a list of already-generated
        chapters with their subsection titles. This is injected into the
        prompt so the LLM avoids generating duplicate content.

        Args:
            assigned_chapters: Chapters already planned (title + subsection titles).
                               None or [] on the first chapter.

        Returns:
            List of subsection dicts, or None on failure.
        """
        # FIX 3 — build "already covered" context string
        already_covered_block = ""
        if assigned_chapters:
            lines = ["ALREADY COVERED in previous chapters (DO NOT repeat these topics):"]
            for prev in assigned_chapters:
                sub_titles = ", ".join(
                    s.get("title", "") for s in prev.get("subsections", [])
                )
                lines.append(f"  • {prev['title']}: {sub_titles}")
            already_covered_block = "\n".join(lines)

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
Adapt freely to the subject domain.

STRUCTURE GUIDANCE:
- Adapt the section structure to the SUBJECT DOMAIN
- Each subsection title must reflect UNIQUE content specific to THIS chapter
- DO NOT generate subsections that duplicate topics already covered in other chapters

OUTPUT ONLY THE JSON ARRAY — no markdown, no explanation."""

        # FIX 3 — inject already_covered_block into user_prompt when present
        already_covered_section = (
            f"\n\n{already_covered_block}" if already_covered_block else ""
        )

        user_prompt = (
            f"Textbook topic: {topic_name}\n"
            f"This is Chapter {chapter_index + 1} of {num_chapters}: \"{chapter_title}\"\n\n"
            f"Relevant topic clusters:\n{raw_topics}"
            f"{already_covered_section}\n\n"
            f"Generate 3–{max_subsections} subsections that are UNIQUE to this chapter "
            f"and not covered by any previous chapter:"
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

                start = raw.find("[")
                end   = raw.rfind("]")
                if start == -1 or end == -1:
                    raise ValueError("No JSON array in response")
                subsections = json.loads(raw[start:end + 1])

                if not isinstance(subsections, list) or len(subsections) == 0:
                    raise ValueError("Empty subsection list")

                if len(subsections) > max_subsections:
                    logger.warning(
                        f"Chapter {chapter_index + 1}: LLM returned {len(subsections)} subsections "
                        f"(limit {max_subsections}) — trimming"
                    )
                    subsections = subsections[:max_subsections]

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
        Generate a Lời nói đầu (preface) page as raw Markdown.

        Covers: target audience, purpose, chapter structure, unique features, usage guide.
        Returns empty string on failure (preface is optional).
        """
        logger.info("Generating preface (Lời nói đầu)...")
        chapter_summary = "\n".join(
            f"  - Chương {i + 1}: {ch.title}"
            for i, ch in enumerate(curriculum.chapters)
        )

        # NOTE: Preface prompt deliberately uses plain Markdown formatting now
        # (no LaTeX \begin{center} etc.) because publisher.py strips LaTeX
        # artifacts. The Publisher prepends "# Lời nói đầu" heading itself.
        system_prompt = """You are the author of a Vietnamese university textbook writing the "Lời nói đầu" (Preface).

Write a natural, flowing academic preface in plain Markdown — no LaTeX commands, no outer code fences, no \\begin or \\end tags.

Write 4-6 paragraphs that naturally cover these aspects (in any order, without rigid labels):
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
- Output starts directly with the first paragraph — no title, no heading

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
                   FIX 3: each call receives list of already-assigned chapters
                   to prevent subsection overlap across chapters.

        Returns:
            Dictionary conforming to CurriculumOutline schema, or None on failure.
        """
        logger.info(
            f"Phase 2 (LLM): 2-phase curriculum build — {num_chapters} chapters "
            f"({num_chapters + 1} total LLM calls, max {max_subsections} subsections/chapter)"
        )

        # Phase 2a: chapter titles
        chapter_titles = self._plan_chapter_titles(topic_name, raw_topics, num_chapters)
        if not chapter_titles:
            return None

        # Phase 2b: subsections — accumulate context as we go (FIX 3)
        chapters: List[Dict[str, Any]] = []
        failed_chapters = 0

        for idx, title in enumerate(chapter_titles):
            # FIX 3 — pass all chapters generated so far as already-assigned context
            subsections = self._generate_chapter_subsections(
                topic_name=topic_name,
                chapter_title=title,
                chapter_index=idx,
                num_chapters=num_chapters,
                raw_topics=raw_topics,
                max_subsections=max_subsections,
                assigned_chapters=chapters,  # FIX 3: grows with each iteration
            )

            if subsections:
                chapters.append({"title": title, "subsections": subsections})
            else:
                failed_chapters += 1
                logger.warning(f"Skipping chapter {idx + 1} due to generation failure")
                # FIX 4 — use "light" not "intro" (invalid section_type)
                chapters.append({
                    "title": title,
                    "subsections": [
                        {
                            "title": f"Giới thiệu về {title}",
                            "description": f"Tổng quan về {title}",
                            "search_query": f"{topic_name} {title} introduction",
                            "section_type": "light",   # FIX 4: was "intro"
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
        2. Extract topic clusters via NMF (adaptive min_df + dedup)
        3. Refine into structured curriculum via LLM (progressive + non-overlapping)
        4. Parse into Pydantic CurriculumOutline object

        Args:
            topic: User's requested subject
            num_chapters: Number of chapters to generate (from user config)
            num_topics: Number of NMF topic clusters to extract (auto-scaled)

        Returns:
            CurriculumOutline Pydantic object, or None on failure.
        """
        effective_num_topics = max(num_topics, num_chapters + 2)

        # Step 1: corpus
        docs = self.get_all_documents()
        if not docs:
            logger.error("No documents found in vector DB. Run ingestion first.")
            return None

        # Step 2: NMF topic extraction with adaptive fallback
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

        # Step 3: LLM refinement
        plan_dict = self.refine_plan_with_llm(
            topic, raw_topics, num_chapters=num_chapters, max_subsections=max_subsections
        )
        if not plan_dict:
            logger.error("LLM refinement failed after all retries")
            return None

        # Step 4: Pydantic parse
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

    user_request    = state["request"]
    num_chapters    = state.get("num_chapters", 3)                 # type: ignore[call-overload]
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

    textbook_title = (
        planner._generate_textbook_title(user_request, curriculum)
        or f"Giáo trình {user_request}"
    )
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