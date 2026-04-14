"""
Planner Agent for AI Textbook Generator.

This module implements a hybrid planning approach:
1. Unsupervised ML (NMF) for cost-effective topic discovery from documents
2. LLM for semantic structuring and curriculum design

The planner generates a complete CurriculumOutline that serves as the
blueprint for the entire content generation workflow.

Pipeline overview:
    Phase 1 (NMF):  TF-IDF + Non-negative Matrix Factorization extracts topic
                    clusters from ChromaDB documents without LLM cost.
                    Adaptive min_df and Jaccard deduplication ensure cluster
                    diversity before the LLM sees them.
    Phase 2a (LLM): One small call generates N chapter titles following a
                    progressive 3-zone learning arc (foundations → core → advanced).
    Phase 2b (LLM): N calls generate subsections per chapter, each receiving
                    the already-assigned chapters as context to prevent overlap.
    Phase 2c (LLM): Title + preface generated from the completed curriculum.
"""

import json
from typing import Any, List, Dict, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_chroma import Chroma
from src.config import get_embedding_model
from langchain_anthropic import ChatAnthropic
from src.graph.state import AgentState, CurriculumOutline
from src.config import CHROMA_DB_DIR, LLM_MODEL_CHEAP, ANTHROPIC_API_KEY
from src.log_config import setup_logger, setup_prompt_logger

logger = setup_logger(name="PlannerAgent", logfile="logs/agents.log")


class HybridPlanner:
    """
    Hybrid planning agent combining unsupervised ML with LLM refinement.

    Architecture:
        Phase 1 — NMF:  Extract diverse topic clusters from vector DB documents.
                        Produces a formatted cluster string used as grounding
                        context for all Phase 2 LLM calls.
        Phase 2 — LLM:  Build the full curriculum in small, focused calls to
                        avoid output truncation:
                          2a: chapter titles (one call, ~300 tokens output)
                          2b: subsections per chapter (N calls, ~500 tokens each)
                          2c: textbook title + preface (two calls)

    The final output is a Pydantic CurriculumOutline object that enforces type
    safety and provides a validated schema for all downstream agent nodes.
    """

    def __init__(self) -> None:
        """
        Initialize LLM client, ChromaDB connection, and stopword set.

        temperature=0.3 gives the LLM moderate creativity for curriculum design
        while keeping chapter titles and subsection structures stable across
        runs on the same topic.

        ChromaDB is connected here (not lazily) because HybridPlanner is
        instantiated once per workflow run — the connection cost is paid once
        and shared across get_all_documents() and any future vector queries.
        """
        self.llm = ChatAnthropic(
            model_name=LLM_MODEL_CHEAP,
            api_key=ANTHROPIC_API_KEY,        # type: ignore[arg-type]
            temperature=0.3,
            max_tokens_to_sample=1024,
        )

        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=get_embedding_model(),
            collection_name="dynamic_context",
        )

        self.prompt_logger = setup_prompt_logger("planner")

        # Multilingual stopwords passed to TfidfVectorizer.
        # Using a set (not list) for O(1) lookup and explicit deduplication —
        # TfidfVectorizer accepts both, but set is semantically correct here.
        # Covers:
        #   - Vietnamese function words (là, của, và, ...)
        #   - Noise tokens from sports/social content surviving URL filtering
        #   - English function words
        #   - PDF binary stream artifacts (endobj, flatedecode, xref, ...)
        self.stop_words: set[str] = {
            # Vietnamese function words
            'là', 'của', 'và', 'các', 'những', 'cái', 'trong', 'khi', 'bằng', 'người',
            'được', 'thì', 'mà', 'này', 'nọ', 'với', 'như', 'có', 'cho', 'về', 'tại',
            # Vietnamese noise tokens (sports/social media surviving URL filter)
            'kèo', 'soi', 'bàn', 'city', 'united',
            # Vietnamese consonant clusters (tokenisation artifacts from PDF extraction)
            'ng', 'th', 'tr', 'nh', 'ch', 'ph', 'kh', 'gh', 'gi',
            # English function words
            'the', 'is', 'and', 'to', 'of', 'in', 'for', 'on', 'with', 'as', 'by', 'it',
            'this', 'that', 'are', 'be', 'or', 'from', 'at',
            # PDF binary stream artifacts (from PDF text extraction noise)
            'obj', 'endobj', 'stream', 'endstream', 'flatedecode',
            'xobject', 'colorspace', 'length', 'filter', 'type',
            'startxref', 'xref', 'trailer',
        }

    # ------------------------------------------------------------------
    # Phase 1 — NMF topic extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _jaccard(a: List[str], b: List[str]) -> float:
        """
        Compute Jaccard similarity between two keyword lists using their top-5 items.

        Used by extract_topics_with_nmf() to deduplicate near-identical NMF
        clusters before passing them to the LLM. Two clusters sharing ≥ 3 of
        their top-5 keywords are considered semantically duplicate.

        Args:
            a: First keyword list (top-N terms from an NMF component).
            b: Second keyword list.

        Returns:
            Float in [0, 1]. Returns 1.0 if both lists are empty.
        """
        sa, sb = set(a[:5]), set(b[:5])
        if not sa and not sb:
            return 1.0
        return len(sa & sb) / len(sa | sb)

    def get_all_documents(self) -> List[str]:
        """
        Retrieve all document chunk texts from ChromaDB for NMF topic modeling.

        Returns:
            List of text strings, one per chunk. Empty list on error.
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
        Phase 1: Extract diverse topic clusters via TF-IDF + NMF.

        Pipeline:
            1. TF-IDF vectorization with adaptive min_df (scales with corpus size)
               and max_df=0.90 to eliminate ultra-common domain terms (e.g.
               "gradient" appearing in every DL chunk).
            2. NMF decomposition into `num_topics` latent topic components.
            3. Top-10 keyword extraction per component.
            4. Jaccard deduplication: clusters sharing ≥ 3 of their top-5
               keywords are merged — only the first is kept. This prevents the
               LLM from receiving near-identical clusters and generating
               repetitive chapter content.

        Adaptive min_df thresholds:
            corpus < 50 chunks  → min_df=2 (lenient; small corpus needs coverage)
            corpus 50-200       → min_df=3
            corpus > 200        → min_df=5 (strict; large corpus can afford pruning)

        Args:
            docs:       List of text chunks from ChromaDB.
            num_topics: Number of NMF components to extract (before dedup).

        Returns:
            Formatted string of unique topic clusters with top-10 keywords each.
            Empty string if vectorization fails (insufficient data).
        """
        logger.info(f"Phase 1 (NMF): Extracting {num_topics} topic clusters...")

        n_docs = len(docs)
        if n_docs < 50:
            min_df = 2
        elif n_docs < 200:
            min_df = 3
        else:
            min_df = 5
        logger.info(f"NMF adaptive min_df={min_df} for corpus size={n_docs}")

        vectorizer = TfidfVectorizer(
            max_df=0.90,             # cut terms appearing in > 90% of chunks
            min_df=min_df,           # adaptive floor (see docstring)
            stop_words=list(self.stop_words), # convert to list at call site
            max_features=2000,
            token_pattern=r'\b[a-zA-ZÀ-ỹ]{3,}\b',
            ngram_range=(1, 2),
        )

        try:
            tfidf_matrix = vectorizer.fit_transform(docs)
        except ValueError as e:
            logger.warning(f"Insufficient data for TF-IDF vectorization: {e}")
            return ""

        nmf = NMF(n_components=num_topics, random_state=42, init='nndsvd')
        nmf.fit(tfidf_matrix)

        feature_names = vectorizer.get_feature_names_out()

        # Extract top-10 keywords per NMF component
        raw_clusters: List[List[str]] = []
        for topic in nmf.components_:
            top_indices = topic.argsort()[:-11:-1]
            keywords    = [str(feature_names[i]) for i in top_indices]
            raw_clusters.append(keywords)

        # Deduplicate: keep only the first cluster when Jaccard ≥ 0.60
        JACCARD_THRESHOLD = 0.60
        unique_clusters: List[List[str]] = []
        for candidate in raw_clusters:
            is_dup = any(
                self._jaccard(candidate, kept) >= JACCARD_THRESHOLD
                for kept in unique_clusters
            )
            if not is_dup:
                unique_clusters.append(candidate)

        removed = len(raw_clusters) - len(unique_clusters)
        if removed:
            logger.info(
                f"NMF dedup: removed {removed} near-identical clusters "
                f"→ {len(unique_clusters)} unique"
            )

        return "\n".join(
            f"- Topic Cluster {i + 1}: {', '.join(kws)}"
            for i, kws in enumerate(unique_clusters)
        )

    # ------------------------------------------------------------------
    # Phase 2a — Chapter title planning
    # ------------------------------------------------------------------

    def _plan_chapter_titles(
        self,
        topic_name: str,
        raw_topics: str,
        num_chapters: int,
    ) -> Optional[List[str]]:
        logger.info(f"Phase 2a: Planning {num_chapters} chapter titles...")

        zone_a = max(1, num_chapters // 3)
        zone_b = max(1, num_chapters // 3)

        system_prompt = f"""
    [CONTEXT]
    You are a curriculum designer building a Vietnamese university textbook.
    Your task is to plan chapter titles that form a coherent, progressive learning arc.
    [/CONTEXT]

    [TASK]
    Generate EXACTLY {num_chapters} chapter titles for the subject provided.
    [/TASK]

    [CRITERION]
    Each title must:
    (a) Cover a DISTINCT aspect of the subject — no two chapters may overlap
        in their primary topic.
    (b) Be specific and descriptive rather than generic.
        Good: "Mạng nơ-ron tích chập CNN"
        Bad:  "Học sâu"
    (c) Follow a progressive learning arc across three zones:
        - Chapters 1–{zone_a}: Foundations (concepts, definitions, basic theory)
        - Chapters {zone_a + 1}–{zone_a + zone_b}: Core techniques and mechanisms
        - Chapters {zone_a + zone_b + 1}–{num_chapters}: Applications, advanced topics, integration
    [/CRITERION]

    [CONSTRAINT]
    Rule 1 — NO OVERLAP: Do not repeat or rephrase the same concept across different chapters.
    Rule 2 — EXACT COUNT: Output EXACTLY {num_chapters} titles — no more, no less.
    Rule 3 — LANGUAGE: All titles must be in Vietnamese.
    [/CONSTRAINT]

    [FORMAT]
    Output a JSON array of exactly {num_chapters} Vietnamese chapter title strings.
    No explanation, no markdown — ONLY the JSON array.
    Example: ["Tiêu đề chương 1", "Tiêu đề chương 2"]
    [/FORMAT]
    """

        user_prompt = (
            f"Subject: {topic_name}\n"
            f"Number of chapters: {num_chapters}\n\n"
            f"Topic clusters discovered from course materials:\n{raw_topics}\n\n"
            f"Output a JSON array of exactly {num_chapters} distinct, progressive chapter titles:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        chain = prompt | self.llm

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt == 1:
                self.prompt_logger.log(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    context_label=(
                        f"Chapter titles | {num_chapters} chapters | {topic_name[:40]}"
                    ),
                )
            try:
                response = chain.invoke({})
                raw      = str(response.content).strip()  # type: ignore

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
                        "padding/trimming to match"
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

    # ------------------------------------------------------------------
    # Phase 2b — Per-chapter subsection generation
    # ------------------------------------------------------------------

    def _generate_chapter_subsections(
        self,
        topic_name: str,
        chapter_title: str,
        chapter_index: int,
        num_chapters: int,
        raw_topics: str,
        max_subsections: int = 4,
        assigned_chapters: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Phase 2b: Generate subsections for a single chapter.

        To prevent content overlap across chapters, `assigned_chapters` injects
        an "ALREADY COVERED" block into the user prompt listing every subsection
        title assigned to previous chapters. The LLM uses this to deliberately
        generate non-overlapping content for the current chapter.

        On the first chapter (assigned_chapters=None or []) no such block is
        injected — there is nothing to avoid yet.

        Subsection schema (one JSON object per subsection):
            title        — Vietnamese descriptive title unique to this chapter
            description  — 1-2 sentence Vietnamese overview
            search_query — 3-5 English keywords for RAG retrieval
            section_type — one of "light" | "medium" | "deep" | "applied"

        Args:
            topic_name:        Main textbook subject.
            chapter_title:     Title of the chapter being populated.
            chapter_index:     0-indexed position of this chapter.
            num_chapters:      Total chapter count (for LLM context).
            raw_topics:        NMF cluster string from Phase 1.
            max_subsections:   Upper bound on subsections (user-controlled).
            assigned_chapters: Chapters generated so far, each a dict with
                               "title" and "subsections" keys. Grows with each
                               call in refine_plan_with_llm().

        Returns:
            List of validated subsection dicts, or None after all retries fail.
        """
        # Build the "already covered" context block for overlap prevention
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

        already_covered_section = (
            f"\n\n{already_covered_block}" if already_covered_block else ""
        )
        user_prompt = (
            f"Textbook topic: {topic_name}\n"
            f"This is Chapter {chapter_index + 1} of {num_chapters}: \"{chapter_title}\"\n\n"
            f"Relevant topic clusters:\n{raw_topics}"
            f"{already_covered_section}\n\n"
            f"Generate 3–{max_subsections} subsections that are UNIQUE to this chapter "
            "and not covered by any previous chapter:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt),
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
                raw      = str(response.content).strip()  # type: ignore

                start = raw.find("[")
                end   = raw.rfind("]")
                if start == -1 or end == -1:
                    raise ValueError("No JSON array in response")
                subsections = json.loads(raw[start:end + 1])

                if not isinstance(subsections, list) or len(subsections) == 0:
                    raise ValueError("Empty subsection list")

                if len(subsections) > max_subsections:
                    logger.warning(
                        f"Chapter {chapter_index + 1}: LLM returned "
                        f"{len(subsections)} subsections (limit {max_subsections}) — trimming"
                    )
                    subsections = subsections[:max_subsections]

                # Normalise and validate each subsection object
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

    # ------------------------------------------------------------------
    # Phase 2c — Title and preface generation
    # ------------------------------------------------------------------

    def _generate_textbook_title(self, topic: str, curriculum: CurriculumOutline) -> str:
        """
        Generate a Vietnamese textbook title adapted to the subject domain.

        Unlike a fixed academic title generator, this method infers the domain
        tone from the topic and chapter list, then produces a title that fits
        naturally — formal academic style for scholarly subjects, engaging and
        descriptive style for practical or lifestyle subjects.

        Examples by domain:
            Academic:  "Giáo trình Hóa học Đại cương"
            Practical: "Nghệ thuật Làm bánh — Từ Cơ bản đến Nâng cao"
            Lifestyle: "Kỹ thuật Làm Nail Chuyên nghiệp"

        Called after the full CurriculumOutline is built so the LLM can base
        the title on the actual chapter list rather than the raw topic string.

        Args:
            topic:      User's original topic request.
            curriculum: Completed CurriculumOutline with all chapter titles.

        Returns:
            Vietnamese title string adapted to the subject domain.
            Falls back to "Giáo trình {topic}" on any LLM error.
        """
        logger.info("Generating textbook title...")
        chapter_list = "\n".join(f"  - {ch.title}" for ch in curriculum.chapters)

        system_prompt = (
            "[CONTEXT]\n"
            "You are a neutral title specialist for an educational content platform\n"
            "that covers all learning domains — from university-level academics to\n"
            "practical crafts, cooking, beauty, sports, and lifestyle skills.\n"
            "Your task is to produce a Vietnamese title that feels natural and\n"
            "appropriate for the specific domain, not uniformly academic.\n"
            "[/CONTEXT]\n\n"

            "[CRITERION]\n"
            "The title must:\n"
            "  (a) Accurately reflect the subject and scope of the chapter list.\n"
            "  (b) Match the tone appropriate for the domain:\n"
            "      - Scholarly/scientific → formal academic style\n"
            "        e.g. \"Giáo trình Hóa học Đại cương\"\n"
            "      - Technical/engineering → clear and professional\n"
            "        e.g. \"Lập trình Python Ứng dụng Thực tế\"\n"
            "      - Practical/lifestyle → engaging and descriptive\n"
            "        e.g. \"Nghệ thuật Làm bánh — Từ Cơ bản đến Nâng cao\"\n"
            "        e.g. \"Kỹ thuật Làm Nail Chuyên nghiệp\"\n"
            "  (c) Be concise — maximum 12 words.\n"
            "[/CRITERION]\n\n"

            "[CONSTRAINT]\n"
            "Rule 1 — LANGUAGE: Output must be in Vietnamese only.\n"
            "Rule 2 — LENGTH: Maximum 12 words.\n"
            "Rule 3 — FORMAT: Output the title string only — no explanation,\n"
            "  no markdown, no surrounding quotes.\n"
            "[/CONSTRAINT]\n\n"

            "[FORMAT]\n"
            "A single Vietnamese title string. Nothing else.\n"
            "[/FORMAT]"
        )

        user_prompt = (
            f"User request: {topic}\n\n"
            f"Chapter list:\n{chapter_list}\n\n"
            "Output the Vietnamese title:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        try:
            self.prompt_logger.log(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_label=f"Title generation | {topic[:40]}",
            )
            response = (prompt | self.llm).invoke({})
            title    = str(response.content).strip().strip('"').strip("'")  # type: ignore
            logger.info(f"✓ Textbook title: {title}")
            return title
        except Exception as e:
            logger.warning(f"Title generation failed: {e}")
            return f"Giáo trình {topic}"


    def _generate_preface(
        self,
        topic: str,
        title: str,
        curriculum: CurriculumOutline,
    ) -> str:
        """
        Generate the Lời nói đầu (Preface) adapted to the subject domain.

        Unlike a fixed academic preface template, this method adapts tone and
        framing to the domain — a chemistry textbook preface reads differently
        from a baking guide or a nail art course introduction, yet both serve
        the same structural purpose: orient the reader, state objectives, and
        explain how to use the material.

        The prompt requests plain Markdown with no LaTeX commands because the
        Publisher prepends the "# Lời nói đầu" heading itself and strips any
        LaTeX artifacts that older LLM responses produced.

        Content covers: target audience, prerequisites, learning objectives,
        chapter structure overview, distinctive features, and usage guidance —
        expressed in a voice appropriate to the domain.

        Args:
            topic:      User's original topic request.
            title:      Generated title from _generate_textbook_title().
            curriculum: Completed CurriculumOutline for chapter reference.

        Returns:
            Preface Markdown string (4–6 paragraphs, domain-appropriate Vietnamese).
            Empty string on failure — preface is optional; Publisher handles absence.
        """
        logger.info("Generating preface (Lời nói đầu)...")
        chapter_summary = "\n".join(
            f"  - Chương {i + 1}: {ch.title}"
            for i, ch in enumerate(curriculum.chapters)
        )

        system_prompt = (
            "[CONTEXT]\n"
            "You are a neutral academic writing specialist producing a Vietnamese\n"
            "preface (Lời nói đầu) for an educational content platform that covers\n"
            "all learning domains — university academics, technical skills, practical\n"
            "crafts, cooking, beauty, sports, and lifestyle topics.\n"
            "The preface must feel natural and fitting for the specific domain,\n"
            "not uniformly stiff or academic.\n"
            "[/CONTEXT]\n\n"

            "[TASK]\n"
            "Write a Lời nói đầu (Preface) in plain Markdown — no LaTeX commands,\n"
            "no outer code fences, no \\begin or \\end tags.\n"
            "Write 4–6 paragraphs that naturally cover these aspects\n"
            "(in any order, without rigid section labels):\n"
            "  - Who this material is intended for and what prior knowledge is assumed\n"
            "  - The purpose and learning objectives\n"
            "  - How the content is structured across chapters\n"
            "    (reference the provided chapter list naturally in prose)\n"
            "  - What makes this material distinctive or valuable for the learner\n"
            "  - How to use it effectively for best results\n"
            "[/TASK]\n\n"

            "[CRITERION]\n"
            "Adapt tone to the domain:\n"
            "  - Scholarly/scientific → formal, precise, third-person academic voice\n"
            "  - Technical/engineering → clear, professional, practical\n"
            "  - Practical/lifestyle → warm, encouraging, direct — still structured\n"
            "    but not stiff; a baking guide preface should feel like it was written\n"
            "    by someone who loves teaching the craft, not a committee\n\n"
            "Quality standards (apply to all domains):\n"
            "  - Each paragraph 3–5 sentences, flowing naturally\n"
            "  - No bolded section labels inside paragraphs\n"
            "  - No conversational filler (\"Chúng ta hãy cùng...\", \"Bạn sẽ thấy...\")\n"
            "  - Tailor content specifically to the topic and chapter structure provided\n"
            "  - Output starts directly with the first paragraph — no title, no heading\n"
            "[/CRITERION]\n\n"

            "[CONSTRAINT]\n"
            "Rule 1 — LANGUAGE: All output must be in Vietnamese.\n"
            "Rule 2 — FORMAT: Plain Markdown only — no LaTeX, no code fences,\n"
            "  no outer wrappers. Blank line between each paragraph.\n"
            "Rule 3 — LENGTH: 4–6 paragraphs. Do not pad with generic filler\n"
            "  to reach the count — fewer strong paragraphs beat more weak ones.\n"
            "[/CONSTRAINT]\n\n"

            "[FORMAT]\n"
            "Plain Markdown paragraphs separated by blank lines.\n"
            "Start directly with the first sentence — no heading, no preamble.\n"
            "[/FORMAT]"
        )

        user_prompt = (
            f"Title: {title}\n"
            f"Topic: {topic}\n\n"
            f"Chapter list:\n{chapter_summary}\n\n"
            "Write the Vietnamese preface now:"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        try:
            self.prompt_logger.log(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_label=f"Preface | {title[:40]}",
            )
            response = (prompt | self.llm).invoke({})
            preface  = str(response.content).strip()  # type: ignore
            logger.info("✓ Preface generated")
            return preface
        except Exception as e:
            logger.warning(f"Preface generation failed: {e}")
            return ""

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def refine_plan_with_llm(
        self,
        topic_name: str,
        raw_topics: str,
        num_chapters: int = 3,
        max_subsections: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """
        Phase 2 orchestration: build the full curriculum via the 2-phase LLM approach.

        Phase 2a — one call  → chapter titles  (~300 output tokens, never truncated)
        Phase 2b — N calls   → subsections     (~500 output tokens per call)

        Each Phase 2b call receives `assigned_chapters` (the list of chapters
        completed so far) so the LLM can see what topics are already covered
        and generate non-overlapping subsections for the current chapter.

        Fallback behaviour: if a chapter's subsection generation fails all
        retries, a single "light" orientation subsection is inserted so the
        chapter slot is not empty and the curriculum remains structurally valid.

        Args:
            topic_name:      Main subject string.
            raw_topics:      NMF cluster string from Phase 1.
            num_chapters:    Exact number of chapters to build.
            max_subsections: Upper bound on subsections per chapter.

        Returns:
            Dict conforming to CurriculumOutline schema, or None if all chapters fail.
        """
        logger.info(
            f"Phase 2 (LLM): 2-phase curriculum build — {num_chapters} chapters "
            f"({num_chapters + 1} total LLM calls, max {max_subsections} subsections/chapter)"
        )

        chapter_titles = self._plan_chapter_titles(topic_name, raw_topics, num_chapters)
        if not chapter_titles:
            return None

        chapters: List[Dict[str, Any]] = []
        failed_chapters = 0

        for idx, title in enumerate(chapter_titles):
            subsections = self._generate_chapter_subsections(
                topic_name=topic_name,
                chapter_title=title,
                chapter_index=idx,
                num_chapters=num_chapters,
                raw_topics=raw_topics,
                max_subsections=max_subsections,
                assigned_chapters=chapters,    # grows with each iteration
            )

            if subsections:
                chapters.append({"title": title, "subsections": subsections})
            else:
                failed_chapters += 1
                logger.warning(f"Skipping chapter {idx + 1} due to generation failure")
                # Fallback: single orientation subsection keeps the slot structurally valid.
                # "light" is used — it is a valid section_type unlike the former "intro".
                chapters.append({
                    "title": title,
                    "subsections": [{
                        "title":        f"Giới thiệu về {title}",
                        "description":  f"Tổng quan về {title}",
                        "search_query": f"{topic_name} {title} introduction",
                        "section_type": "light",
                    }],
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
        Main entry point: run the full hybrid planning pipeline.

        Pipeline:
            1. Fetch all document chunks from ChromaDB.
            2. Extract topic clusters via NMF with adaptive min_df and dedup.
               Falls back to progressively fewer clusters if the corpus is too
               small for the requested num_topics.
            3. Build curriculum via two-phase LLM approach (progressive arc +
               anti-overlap context).
            4. Parse the result dict into a Pydantic CurriculumOutline.

        Args:
            topic:           User's requested subject.
            num_chapters:    Number of chapters to generate.
            num_topics:      Initial NMF cluster count (auto-scaled to num_chapters+2).
            max_subsections: Upper bound on subsections per chapter.

        Returns:
            Validated CurriculumOutline Pydantic object, or None on failure.
        """
        # Always extract at least (num_chapters + 2) clusters so the LLM has
        # more signal variety than chapter slots to fill.
        effective_num_topics = max(num_topics, num_chapters + 2)

        docs = self.get_all_documents()
        if not docs:
            logger.error("No documents found in vector DB. Run ingestion first.")
            return None

        # NMF with graceful fallback to fewer clusters for small corpora
        raw_topics = ""
        for n_topics in [effective_num_topics, max(3, effective_num_topics // 2), 3]:
            raw_topics = self.extract_topics_with_nmf(docs, num_topics=n_topics)
            if raw_topics:
                if n_topics < effective_num_topics:
                    logger.warning(
                        f"NMF scaled down: {effective_num_topics} → {n_topics} topics "
                        "(corpus may be too small)"
                    )
                break

        if not raw_topics:
            logger.error("Topic extraction failed at all fallback levels — insufficient data")
            return None

        plan_dict = self.refine_plan_with_llm(
            topic, raw_topics, num_chapters=num_chapters, max_subsections=max_subsections
        )
        if not plan_dict:
            logger.error("LLM refinement failed after all retries")
            return None

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


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------

def plan_curriculum(state: AgentState) -> dict:
    """
    Planner node: generate the complete curriculum outline from the user request.

    Reads from state:
        request                      — user's topic string
        num_chapters                 — how many chapters to generate (default 3)
        max_subsections_per_chapter  — subsection upper bound per chapter (default 5)

    Writes to state:
        curriculum               — CurriculumOutline Pydantic object
        textbook_title           — formal Vietnamese academic title (≤ 12 words)
        preface_content          — Lời nói đầu Markdown (4-6 paragraphs)
        current_chapter_index    = 0  (initialise loop counters)
        current_subsection_index = 0
        final_content            = ""
        revision_number          = 0
        messages                 — milestone log entries

    Raises:
        ValueError: if HybridPlanner.create_curriculum() returns None (all
                    fallback levels exhausted). The LangGraph runtime treats
                    this as a terminal error for the current run.

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict.
    """
    logger.info("=" * 60)
    logger.info("NODE: Planner - Building curriculum outline")
    logger.info("=" * 60)

    user_request    = state["request"]
    num_chapters    = state.get("num_chapters", 3)                  # type: ignore[call-overload]
    max_subsections = state.get("max_subsections_per_chapter", 5)   # type: ignore[call-overload]

    logger.info(f"User request       : {user_request}")
    logger.info(f"Num chapters       : {num_chapters}")
    logger.info(f"Max subsections/ch : {max_subsections}")

    planner    = HybridPlanner()
    curriculum = planner.create_curriculum(
        user_request, num_chapters=num_chapters, max_subsections=max_subsections
    )

    if not curriculum:
        raise ValueError("Planner failed: Could not generate curriculum")

    total_subsections = sum(len(ch.subsections) for ch in curriculum.chapters)

    textbook_title  = (
        planner._generate_textbook_title(user_request, curriculum)
        or f"Giáo trình {user_request}"
    )
    preface_content = planner._generate_preface(user_request, textbook_title, curriculum)

    return {
        "curriculum":               curriculum,
        "textbook_title":           textbook_title,
        "preface_content":          preface_content,
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "final_content":            "",
        "revision_number":          0,
        "messages": [
            f"✓ Curriculum created: {curriculum.topic}",
            f"  - {len(curriculum.chapters)} chapters planned",
            f"  - Total subsections: {total_subsections}",
            f"  - Textbook title: {textbook_title}",
        ],
    }