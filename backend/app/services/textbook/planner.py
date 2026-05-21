"""
Planner Agent for AI Textbook Generator.

Generates curriculum directly from topic using LLM training knowledge.
No ChromaDB or NMF needed — content crawling happens AFTER user confirms.

Pipeline:
    Phase 1 (LLM):  One call generates N chapter titles following a
                    progressive 3-zone learning arc (foundations → core → advanced).
    Phase 2 (LLM):  N calls generate subsections per chapter, each receiving
                    the already-assigned chapters as context to prevent overlap.
    Phase 3 (LLM):  Title + preface generated from the completed curriculum.
"""

import json
from typing import Any, List, Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.schemas.curriculum import AgentState, CurriculumOutline
from app.config import settings
from app.utils.log_config import setup_logger, setup_prompt_logger

LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
LLM_MODEL_PREMIUM = settings.LLM_MODEL_PREMIUM
OPENAI_API_KEY = settings.OPENAI_API_KEY

logger = setup_logger(name="PlannerAgent", logfile="logs/agents.log")


class HybridPlanner:
    """
    LLM-based curriculum planner.

    Generates curriculum directly from topic string using LLM training knowledge.
    No ChromaDB or NMF — content crawling happens after user confirms curriculum.

    Architecture:
        Phase 1 — LLM:  Generate N chapter titles (one call, ~300 tokens output)
        Phase 2 — LLM:  Build subsections per chapter (N calls, ~500 tokens each)
        Phase 3 — LLM:  Textbook title + preface (two calls)
    """

    def __init__(self) -> None:
        """
        Initialize LLM client for curriculum generation.

        Temperature=0.3 balances creativity with consistency for curriculum design.
        No ChromaDB connection needed — planner generates curriculum from topic only.
        """
        self.llm = ChatOpenAI(
            model=LLM_MODEL_PREMIUM,
            api_key=OPENAI_API_KEY,  # type: ignore[arg-type]
            temperature=0.3,
        )
        self.prompt_logger = setup_prompt_logger("planner")

    # ------------------------------------------------------------------
    # Phase 1 — Chapter title planning
    # ------------------------------------------------------------------

    def _plan_chapter_titles(
        self,
        core_topic: str,
        user_requirements: str,  
        num_chapters: int,
    ) -> Optional[List[str]]:
        """
        Generate chapter titles directly from topic.

        No topic clusters needed — LLM generates curriculum structure
        based on its training knowledge of the subject domain.
        """
        logger.info(f"Phase 1: Planning {num_chapters} chapter titles...")

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
            f"Subject: {core_topic}\n"
            f"Number of chapters: {num_chapters}\n"
            f"User Requirements: {user_requirements or 'None - standard textbook structure'}\n\n"
            f"Generate a JSON array of exactly {num_chapters} distinct, progressive chapter titles.\n"
            f"If user requirements exist, ensure some chapters address those requirements.\n"
            f"For example:\n"
            f"  - If requirements mention 'bài tập' or 'exercises', include practice-focused chapters\n"
            f"  - If requirements mention 'ví dụ' or 'examples', include demonstration chapters\n"
            f"  - If requirements mention 'ứng dụng thực tế', include application chapters"
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
                        f"Chapter titles | {num_chapters} chapters | {core_topic[:40]}"
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
                        titles.append(f"Chương {len(titles) + 1}: {core_topic}")

                logger.info(f"✓ Phase 1: {len(titles)} chapter titles planned")
                return [str(t) for t in titles]

            except Exception as e:
                logger.warning(f"Phase 1 attempt {attempt}/{MAX_RETRIES} failed: {e}")

        logger.error("Phase 1: Failed to generate chapter titles after all retries")
        return None

    # ------------------------------------------------------------------
    # Phase 2 — Per-chapter subsection generation
    # ------------------------------------------------------------------

    def _generate_chapter_subsections(
        self,
        core_topic: str,
        user_requirements: str,
        chapter_title: str,
        chapter_index: int,
        num_chapters: int,
        max_subsections: int = 3,
        assigned_chapters: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Generate subsections for a single chapter.

        Uses only topic name and chapter context — no topic clusters needed.
        LLM relies on training knowledge to structure subsections appropriately.

        To prevent content overlap across chapters, `assigned_chapters` injects
        an "ALREADY COVERED" block listing every subsection title from prior chapters.
        """
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
Generate 1 to {max_subsections} subsections for ONE chapter of a Vietnamese textbook.
Choose as many subsections as the chapter NATURALLY needs.

CRITICAL: Do NOT force a minimum of 3 subsections if the chapter naturally needs fewer.
Some chapters may only need 1-2 focused subsections. Quality over quantity.

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
        requirements_section = ""
        if user_requirements:
            requirements_section = f"\n\nUser Requirements: {user_requirements}\n"
            requirements_section += "IMPORTANT: If requirements mention:\n"
            requirements_section += "  - 'bài tập'/'exercises' → include section_type='applied' subsections\n"
            requirements_section += "  - 'ví dụ'/'examples' → include demonstration subsections\n"
            requirements_section += "  - 'ứng dụng thực tế'/'real-world' → include practical application subsections\n"
        
        user_prompt = (
            f"Textbook topic: {core_topic}\n"
            f"This is Chapter {chapter_index + 1} of {num_chapters}: \"{chapter_title}\"\n"
            f"{requirements_section}"
            f"{already_covered_section}\n\n"
            f"Generate 1–{max_subsections} subsections (as many as needed, NOT forced to 3) "
            "that are UNIQUE to this chapter and cover the essential content:"
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

                for sub in subsections:
                    sub.setdefault("title", "Untitled")
                    sub.setdefault("description", "")
                    sub.setdefault("search_query", core_topic)
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
    # Phase 3 — Title and preface generation
    # ------------------------------------------------------------------

    def _generate_textbook_title(self, topic: str, curriculum: CurriculumOutline) -> str:
        """
        Generate a Vietnamese textbook title adapted to the subject domain.

        Examples by domain:
            Academic:  "Giáo trình Hóa học Đại cương"
            Practical: "Nghệ thuật Làm bánh — Từ Cơ bản đến Nâng cao"
            Lifestyle: "Kỹ thuật Làm Nail Chuyên nghiệp"
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

        4-6 paragraphs covering target audience, objectives, chapter structure,
        distinctive features, and usage guidance — tone adapted to the domain.
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
        core_topic: str,  
        user_requirements: str,  
        num_chapters: int = 3,
        max_subsections: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """
        Build full curriculum from topic name only.

        Phase 1 — one call  → chapter titles
        Phase 2 — N calls   → subsections per chapter

        No topic extraction needed — LLM uses training knowledge.
        Each Phase 2 call receives already-assigned chapters to prevent overlap.
        """
        logger.info(
            f"Building curriculum — {num_chapters} chapters "
            f"({num_chapters + 1} total LLM calls, max {max_subsections} subsections/chapter)"
        )

        chapter_titles = self._plan_chapter_titles(core_topic, user_requirements, num_chapters)
        if not chapter_titles:
            return None

        chapters: List[Dict[str, Any]] = []
        failed_chapters = 0

        for idx, title in enumerate(chapter_titles):
            subsections = self._generate_chapter_subsections(
                core_topic=core_topic,
                user_requirements=user_requirements,
                chapter_title=title,
                chapter_index=idx,
                num_chapters=num_chapters,
                max_subsections=max_subsections,
                assigned_chapters=chapters,
            )

            if subsections:
                chapters.append({"title": title, "subsections": subsections})
            else:
                failed_chapters += 1
                logger.warning(f"Skipping chapter {idx + 1} due to generation failure")
                chapters.append({
                    "title": title,
                    "subsections": [{
                        "title":        f"Giới thiệu về {title}",
                        "description":  f"Tổng quan về {title}",
                        "search_query": f"{core_topic} {title} introduction",
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
        return {"topic": core_topic, "chapters": chapters}

    def create_curriculum(
        self,
        core_topic: str,
        user_requirements: str,
        num_chapters: int = 3,
        max_subsections: int = 5,
    ) -> Optional[CurriculumOutline]:
        """
        Main entry point: generate curriculum directly from topic.

        No ChromaDB needed — curriculum is created from topic string only.
        Content crawling happens AFTER user confirms the curriculum.

        Pipeline:
            1. Generate chapter titles (1 LLM call)
            2. Generate subsections per chapter (N LLM calls)
            3. Generate title and preface (2 LLM calls)
            4. Parse into CurriculumOutline
        """
        logger.info(f"Creating curriculum for topic: {core_topic}")
        logger.info(f"Chapters: {num_chapters}, Max subsections: {max_subsections}")

        plan_dict = self.refine_plan_with_llm(
            core_topic,
            user_requirements,
            num_chapters=num_chapters,  
            max_subsections=max_subsections,
        )

        if not plan_dict:
            logger.error("LLM curriculum generation failed after all retries")
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
    Planner node: generate curriculum outline from topic only.


    Reads from state:
        request                      — user's topic string
        num_chapters                 — how many chapters to generate (default 3)
        max_subsections_per_chapter  — subsection upper bound per chapter (default 5)

     Writes to state:
        curriculum               — CurriculumOutline Pydantic object
        textbook_title           — formal Vietnamese academic title (≤ 12 words)
        current_chapter_index    = 0
        current_subsection_index = 0
        final_content            = ""
        revision_number          = 0
        messages                 — milestone log entries

    Note:
        preface_content is NOT generated here. It is produced by
        generate_preface_node() which runs AFTER the user confirms
        the curriculum (Human-in-the-Loop gate, Target 3).
    """
    logger.info("=" * 60)
    logger.info("NODE: Planner - Building curriculum outline")
    logger.info("=" * 60)


    core_topic = state.get("core_topic", state["request"])  # Fallback to full request
    user_requirements = state.get("user_requirements", "")
    num_chapters = state.get("num_chapters", 3)
    max_subsections = state.get("max_subsections_per_chapter", 5)

    logger.info(f"Core topic         : {core_topic}")
    logger.info(f"User requirements  : {user_requirements or '(none)'}")
    logger.info(f"Num chapters       : {num_chapters}")
    logger.info(f"Max subsections/ch : {max_subsections}")

    planner = HybridPlanner()
    curriculum = planner.create_curriculum(
        core_topic, 
        user_requirements,  
        num_chapters=num_chapters, 
        max_subsections=max_subsections
    )

    if not curriculum:
        raise ValueError("Planner failed: Could not generate curriculum")

    total_subsections = sum(len(ch.subsections) for ch in curriculum.chapters)


    return {
        "curriculum":               curriculum,
        "textbook_title":           core_topic,
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "final_content":            "",
        "revision_number":          0,
        "messages": [
            f"✓ Curriculum created: {curriculum.topic}",
            f"  - {len(curriculum.chapters)} chapters planned",
            f"  - Total subsections: {total_subsections}",
            f"  - Textbook title: {core_topic}",
        ],
    }



def generate_metadata_node(state: AgentState) -> dict:
    """
    Metadata generation node: produce textbook title + Lời nói đầu from
    confirmed curriculum. Runs as the first node in the content-generation
    workflow, immediately after the Human-in-the-Loop gate.

    Generating both title and preface post-confirmation:
        (a) Reduces planning phase latency by ~2 LLM calls.
        (b) Ensures title and preface reflect the user-confirmed structure.
        (c) Only the curriculum outline is shown at the review gate.

    Reads:  core_topic, curriculum
    Writes: textbook_title, preface_content
    """
    logger.info("=" * 60)
    logger.info("NODE: GenerateMetadata - Building title + Lời nói đầu")
    logger.info("=" * 60)

    core_topic = state.get("core_topic", state["request"])
    curriculum = state.get("curriculum")

    if not curriculum:
        logger.warning("generate_metadata_node: curriculum is None — skipping")
        return {
            "textbook_title":  f"Giáo trình {core_topic}",
            "preface_content": "",
            "messages": ["⚠️ Metadata skipped: curriculum not available"],
        }

    planner = HybridPlanner()

    textbook_title = (
        planner._generate_textbook_title(core_topic, curriculum)
        or f"Giáo trình {core_topic}"
    )
    preface_content = planner._generate_preface(core_topic, textbook_title, curriculum)

    logger.info(f"✓ Title: {textbook_title}")
    logger.info(f"✓ Preface: {len(preface_content)} chars")
    return {
        "textbook_title":  textbook_title,
        "preface_content": preface_content,
        "messages": [
            f"✓ Title generated: {textbook_title}",
            f"✓ Preface generated ({len(preface_content)} chars)",
        ],
    }