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
from app.services.api_rate_limiter import rate_limited_invoke
from app.services.runtime_config import get_api_key
from app.services.textbook.language import get_language_profile
from app.utils.log_config import setup_logger, setup_prompt_logger

LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
LLM_MODEL_PREMIUM = settings.LLM_MODEL_PREMIUM

logger = setup_logger(name="PlannerAgent", logfile="logs/agents.log")


def _is_practice_mode(textbook_mode: str | None) -> bool:
    return str(textbook_mode or "standard").strip().lower() == "practice"


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
            api_key=get_api_key("OPENAI_API_KEY"),  # type: ignore[arg-type]
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
        language: str = "vi",
        textbook_mode: str = "standard",
    ) -> Optional[List[str]]:
        """
        Generate chapter titles directly from topic.

        No topic clusters needed — LLM generates curriculum structure
        based on its training knowledge of the subject domain.
        """
        logger.info(f"Phase 1: Planning {num_chapters} chapter titles...")

        zone_a = max(1, num_chapters // 3)
        zone_b = max(1, num_chapters // 3)
        profile = get_language_profile(language)
        if _is_practice_mode(textbook_mode):
            chapter_good_example = (
                "Thực hành xây dựng bộ phân loại ảnh với CNN"
                if language == "vi"
                else "Lab: Building an Image Classifier with CNNs"
            )
            chapter_bad_example = "Tổng quan CNN" if language == "vi" else "CNN Overview"
            system_prompt = f"""
    [CONTEXT]
    You are a curriculum designer building a {profile.prompt_name} university
    practice-course textbook. The material is for hands-on lab work, not a
    theory textbook.
    [/CONTEXT]

    [TASK]
    Generate EXACTLY {num_chapters} practice-oriented chapter titles for the
    subject provided.
    [/TASK]

    [CRITERION]
    Each title must:
    (a) Cover a DISTINCT hands-on topic, lab session, workflow, or deliverable.
    (b) Be specific, action-oriented, and suitable for university practice hours.
        Good: "{chapter_good_example}"
        Bad:  "{chapter_bad_example}"
    (c) Progress from guided practice to similar tasks, then slightly more
        advanced practice. Do not use a theory-first learning arc.
    [/CRITERION]

    [CONSTRAINT]
    Rule 1 — PRACTICE MODE: Every title must imply doing, building, configuring,
    analysing a concrete artifact, solving a task, or completing a lab.
    Rule 2 — NO THEORY CHAPTERS: Do not create titles focused on theory,
    concepts, definitions, overview, summary, conclusion, or recap.
    Rule 3 — NO OVERLAP: Do not repeat or rephrase the same practice task.
    Rule 4 — EXACT COUNT: Output EXACTLY {num_chapters} titles.
    Rule 5 — LANGUAGE: All titles must be in {profile.prompt_name}.
    [/CONSTRAINT]

    [FORMAT]
    Output a JSON array of exactly {num_chapters} {profile.prompt_name} chapter title strings.
    No explanation, no markdown — ONLY the JSON array.
    Example: ["{chapter_good_example}", "{profile.title_example}"]
    [/FORMAT]
    """
        else:
            chapter_good_example = (
                "Mạng nơ-ron tích chập CNN"
                if language == "vi"
                else "Convolutional Neural Networks"
            )
            chapter_bad_example = "Học sâu" if language == "vi" else "Deep Learning"

            system_prompt = f"""
    [CONTEXT]
    You are a curriculum designer building a {profile.prompt_name} university textbook.
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
        Good: "{chapter_good_example}"
        Bad:  "{chapter_bad_example}"
    (c) Follow a progressive learning arc across three zones:
        - Chapters 1–{zone_a}: Foundations (concepts, definitions, basic theory)
        - Chapters {zone_a + 1}–{zone_a + zone_b}: Core techniques and mechanisms
        - Chapters {zone_a + zone_b + 1}–{num_chapters}: Applications, advanced topics, integration
    [/CRITERION]

    [CONSTRAINT]
    Rule 1 — NO OVERLAP: Do not repeat or rephrase the same concept across different chapters.
    Rule 2 — EXACT COUNT: Output EXACTLY {num_chapters} titles — no more, no less.
    Rule 3 — LANGUAGE: All titles must be in {profile.prompt_name}.
    [/CONSTRAINT]

    [FORMAT]
    Output a JSON array of exactly {num_chapters} {profile.prompt_name} chapter title strings.
    No explanation, no markdown — ONLY the JSON array.
    Example: ["{profile.subsection_example}", "{profile.title_example}"]
    [/FORMAT]
    """

        if _is_practice_mode(textbook_mode):
            user_prompt = (
                f"Subject: {core_topic}\n"
                f"Number of practice chapters/labs: {num_chapters}\n"
                f"User Requirements: {user_requirements or 'None - standard practice course'}\n\n"
                f"Generate a JSON array of exactly {num_chapters} distinct hands-on titles.\n"
                "Prioritize guided labs, repeatable practice tasks, and slightly advanced tasks."
            )
        else:
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
                response = rate_limited_invoke(
                    chain,
                    {},
                    bucket="chat",
                    metadata={
                        "agent": "Planner",
                        "node": "planner",
                        "model": LLM_MODEL_PREMIUM,
                    },
                )
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
                        titles.append(f"{profile.chapter_label.title()} {len(titles) + 1}: {core_topic}")

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
        language: str = "vi",
        textbook_mode: str = "standard",
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

        profile = get_language_profile(language)

        if _is_practice_mode(textbook_mode):
            system_prompt = f"""
[CONTEXT]
You are an expert university practice-course curriculum designer.
You design hands-on lab subsections for a {profile.prompt_name} textbook.
[/CONTEXT]

[TASK]
Generate 1 to {max_subsections} subsections for ONE practice chapter.
Choose as many subsections as the chapter naturally needs.
[/TASK]

[CRITERION]
Each subsection must:
- Represent a concrete practice task, lab activity, guided procedure, worked
  exercise, similar exercise set, or slightly advanced challenge.
- Include a description that tells the Writer what the student must do and
  what artifact/output they should produce.
- Use an English search_query containing practical retrieval terms such as
  lab, hands-on, tutorial, exercise, worked example, implementation, practice.
[/CRITERION]

[CONSTRAINT]
Rule 1 — PRACTICE ONLY: section_type must be exactly "applied" for every item.
Rule 2 — NO THEORY: Do not create subsections focused on theory, concepts,
definitions, overview, summary, conclusion, or recap.
Rule 3 — UNIQUE TASKS: Do not duplicate tasks already covered in other chapters.
Rule 4 — COUNT: Return 1 to {max_subsections} subsection objects.
Rule 5 — LANGUAGE: title and description must be in {profile.prompt_name}.
[/CONSTRAINT]

[FORMAT]
Output ONLY a JSON array. No markdown, no explanation.
Each object must have:
- "title": string
- "description": string
- "search_query": English string, 4-8 practical retrieval keywords
- "section_type": "applied"
[/FORMAT]"""
        else:
            system_prompt = f"""
[CONTEXT]
You are an expert curriculum designer generating subsection metadata for a
{profile.prompt_name} university textbook.
[/CONTEXT]

[TASK]
Generate 1 to {max_subsections} subsections for ONE chapter.
Choose as many subsections as the chapter naturally needs.
[/TASK]

[CRITERION]
Each subsection must:
- Have a descriptive title suited to the subject domain.
- Have a {profile.prompt_name} description of 1-2 sentences.
- Have an English search_query of 3-5 specific keywords for RAG.
- Choose section_type based on the amount of analytical or applied work needed.

Depth guide:
- "light"   -> orientation, motivation, recap, bridge to next chapter.
- "medium"  -> explanation, demonstration, illustration, case study.
- "deep"    -> sustained theory, critical analysis, complex technique.
- "applied" -> exercises, hands-on tasks, problems the reader solves.
[/CRITERION]

[CONSTRAINT]
Rule 1 — NATURAL COUNT: Do not force a minimum of 3 subsections if fewer is better.
Rule 2 — NO OVERLAP: Do not duplicate topics already covered in other chapters.
Rule 3 — UNIQUE TITLES: Each subsection title must reflect content specific to this chapter.
Rule 4 — VALID TYPES: section_type must be one of "light", "medium", "deep", "applied".
Rule 5 — LANGUAGE: title and description must be in {profile.prompt_name}.
[/CONSTRAINT]

[FORMAT]
Output ONLY a JSON array. No markdown, no explanation.
Each object must have:
- "title": string
- "description": string
- "search_query": English string
- "section_type": one of "light", "medium", "deep", "applied"
[/FORMAT]"""

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

        practice_mode = _is_practice_mode(textbook_mode)
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
                response = rate_limited_invoke(
                    chain,
                    {},
                    bucket="chat",
                    metadata={
                        "agent": "Planner",
                        "node": "planner",
                        "model": LLM_MODEL_PREMIUM,
                    },
                )
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
                    if practice_mode:
                        sub["section_type"] = "applied"
                        query = str(sub.get("search_query") or core_topic)
                        sub["search_query"] = (
                            f"{query} lab hands-on tutorial exercise worked example practice"
                        )
                    elif sub.get("section_type", "") not in valid_types:
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

    def _generate_textbook_title(
        self,
        topic: str,
        curriculum: CurriculumOutline,
        language: str = "vi",
    ) -> str:
        """
        Generate a textbook title adapted to the subject domain and language.

        Examples by domain:
            Academic:  "Giáo trình Hóa học Đại cương"
            Practical: "Nghệ thuật Làm bánh — Từ Cơ bản đến Nâng cao"
            Lifestyle: "Kỹ thuật Làm Nail Chuyên nghiệp"
        """
        profile = get_language_profile(language)
        technical_example = (
            "Lập trình Python Ứng dụng Thực tế"
            if language == "vi"
            else "Practical Python Programming"
        )
        practical_example = (
            "Nghệ thuật Làm bánh — Từ Cơ bản đến Nâng cao"
            if language == "vi"
            else "The Art of Baking: From Basics to Advanced Practice"
        )
        lifestyle_example = (
            "Kỹ thuật Làm Nail Chuyên nghiệp"
            if language == "vi"
            else "Professional Nail Care Techniques"
        )
        logger.info("Generating textbook title...")
        chapter_list = "\n".join(f"  - {ch.title}" for ch in curriculum.chapters)

        system_prompt = (
            "[CONTEXT]\n"
            "You are a neutral title specialist for an educational content platform\n"
            "that covers all learning domains — from university-level academics to\n"
            "practical crafts, cooking, beauty, sports, and lifestyle skills.\n"
            f"Your task is to produce a {profile.prompt_name} title that feels natural and\n"
            "appropriate for the specific domain, not uniformly academic.\n"
            "[/CONTEXT]\n\n"

            "[CRITERION]\n"
            "The title must:\n"
            "  (a) Accurately reflect the subject and scope of the chapter list.\n"
            "  (b) Match the tone appropriate for the domain:\n"
            "      - Scholarly/scientific → formal academic style\n"
            f"        e.g. \"{profile.title_example}\"\n"
            "      - Technical/engineering → clear and professional\n"
            f"        e.g. \"{technical_example}\"\n"
            "      - Practical/lifestyle → engaging and descriptive\n"
            f"        e.g. \"{practical_example}\"\n"
            f"        e.g. \"{lifestyle_example}\"\n"
            "  (c) Be concise — maximum 12 words.\n"
            "[/CRITERION]\n\n"

            "[CONSTRAINT]\n"
            f"Rule 1 — LANGUAGE: Output must be in {profile.prompt_name} only.\n"
            "Rule 2 — LENGTH: Maximum 12 words.\n"
            "Rule 3 — FORMAT: Output the title string only — no explanation,\n"
            "  no markdown, no surrounding quotes.\n"
            + (
                "Rule 4 — ENGLISH PUNCTUATION: Do NOT use em dash or en dash "
                "characters (—, –). Use a colon, comma, parentheses, or ASCII "
                "hyphen-minus (-) instead.\n"
                if language == "en"
                else ""
            )
            + "[/CONSTRAINT]\n\n"

            "[FORMAT]\n"
            f"A single {profile.prompt_name} title string. Nothing else.\n"
            "[/FORMAT]"
        )

        user_prompt = (
            f"User request: {topic}\n\n"
            f"Chapter list:\n{chapter_list}\n\n"
            f"Output the {profile.prompt_name} title:"
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
            response = rate_limited_invoke(
                prompt | self.llm,
                {},
                bucket="chat",
                metadata={
                    "agent": "Planner",
                    "node": "generate_metadata",
                    "model": LLM_MODEL_PREMIUM,
                },
            )
            title    = str(response.content).strip().strip('"').strip("'")  # type: ignore
            logger.info(f"✓ Textbook title: {title}")
            return title
        except Exception as e:
            logger.warning(f"Title generation failed: {e}")
            return f"{profile.default_title_prefix} {topic}"

    def _generate_preface(
        self,
        topic: str,
        title: str,
        curriculum: CurriculumOutline,
        language: str = "vi",
    ) -> str:
        """
        Generate the preface adapted to the subject domain and language.

        4-6 paragraphs covering target audience, objectives, chapter structure,
        distinctive features, and usage guidance — tone adapted to the domain.
        """
        profile = get_language_profile(language)
        style_rule = (
            "  - Do NOT use em dash or en dash characters (—, –); use commas, "
            "parentheses, semicolons, or ASCII hyphen-minus (-) instead\n"
            if language == "en"
            else ""
        )
        logger.info(f"Generating preface ({profile.preface_heading})...")
        chapter_summary = "\n".join(
            f"  - {profile.chapter_label.title()} {i + 1}: {ch.title}"
            for i, ch in enumerate(curriculum.chapters)
        )

        system_prompt = (
            "[CONTEXT]\n"
            f"You are a neutral academic writing specialist producing a {profile.prompt_name}\n"
            f"preface ({profile.preface_heading}) for an educational content platform that covers\n"
            "all learning domains — university academics, technical skills, practical\n"
            "crafts, cooking, beauty, sports, and lifestyle topics.\n"
            "The preface must feel natural and fitting for the specific domain,\n"
            "not uniformly stiff or academic.\n"
            "[/CONTEXT]\n\n"

            "[TASK]\n"
            f"Write a {profile.preface_heading} in plain Markdown — no LaTeX commands,\n"
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
            f"  - No conversational filler ({profile.filler_examples})\n"
            "  - Tailor content specifically to the topic and chapter structure provided\n"
            "  - Output starts directly with the first paragraph — no title, no heading\n"
            f"{style_rule}"
            "[/CRITERION]\n\n"

            "[CONSTRAINT]\n"
            f"Rule 1 — LANGUAGE: All output must be in {profile.prompt_name}.\n"
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
            f"Write the {profile.prompt_name} preface now:"
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
            response = rate_limited_invoke(
                prompt | self.llm,
                {},
                bucket="chat",
                metadata={
                    "agent": "Planner",
                    "node": "generate_metadata",
                    "model": LLM_MODEL_PREMIUM,
                },
            )
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
        language: str = "vi",
        textbook_mode: str = "standard",
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

        chapter_titles = self._plan_chapter_titles(
            core_topic,
            user_requirements,
            num_chapters,
            language=language,
            textbook_mode=textbook_mode,
        )
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
                language=language,
                textbook_mode=textbook_mode,
            )

            if subsections:
                chapters.append({"title": title, "subsections": subsections})
            else:
                failed_chapters += 1
                logger.warning(f"Skipping chapter {idx + 1} due to generation failure")
                if _is_practice_mode(textbook_mode):
                    fallback_title = (
                        f"Thực hành {title}" if language == "vi" else f"Practice: {title}"
                    )
                    fallback_description = (
                        f"Thực hiện một bài thực hành có hướng dẫn về {title}, "
                        f"sau đó hoàn thành bài tập tương tự và một bài nâng cao."
                        if language == "vi"
                        else (
                            f"Complete a guided hands-on task about {title}, "
                            "then solve a similar exercise and a slightly advanced challenge."
                        )
                    )
                    chapters.append({
                        "title": title,
                        "subsections": [{
                            "title": fallback_title,
                            "description": fallback_description,
                            "search_query": (
                                f"{core_topic} {title} lab hands-on tutorial "
                                "exercise worked example practice"
                            ),
                            "section_type": "applied",
                        }],
                    })
                else:
                    chapters.append({
                        "title": title,
                        "subsections": [{
                            "title":        f"Giới thiệu về {title}" if language == "vi" else f"Introduction to {title}",
                            "description":  f"Tổng quan về {title}" if language == "vi" else f"Overview of {title}",
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

    def _fallback_section_type(self, title: str, user_requirements: str) -> str:
        text = f"{title} {user_requirements}".lower()
        applied_markers = (
            "bài tập", "thực hành", "bài thực hành", "exercise", "practice",
            "lab", "project", "dự án", "case study", "worked solution",
        )
        deep_markers = ("phân tích", "analysis", "theory", "lý thuyết", "mô hình")
        if any(marker in text for marker in applied_markers):
            return "applied"
        if any(marker in text for marker in deep_markers):
            return "deep"
        return "medium"

    def _fallback_structured_metadata(
        self,
        core_topic: str,
        user_requirements: str,
        chapter_title: str,
        subsection_title: str,
        language: str,
        textbook_mode: str = "standard",
    ) -> Dict[str, str]:
        if _is_practice_mode(textbook_mode):
            if language == "vi":
                description = (
                    f"Hướng dẫn thực hành {subsection_title} trong chương {chapter_title}; "
                    "người học cần hoàn thành thao tác, bài tập tương tự và bài nâng cao."
                )
            else:
                description = (
                    f"Guides hands-on practice for {subsection_title} in {chapter_title}; "
                    "learners complete steps, a similar exercise, and an advanced challenge."
                )
            return {
                "description": description,
                "search_query": (
                    f"{core_topic} {chapter_title} {subsection_title} "
                    "lab hands-on tutorial exercise worked example practice"
                ),
                "section_type": "applied",
            }

        if language == "vi":
            description = (
                f"Trình bày {subsection_title} trong mạch nội dung của chương "
                f"{chapter_title}, gắn với chủ đề {core_topic}."
            )
        else:
            description = (
                f"Explains {subsection_title} within the chapter {chapter_title}, "
                f"aligned with the broader topic {core_topic}."
            )
        return {
            "description": description,
            "search_query": f"{core_topic} {chapter_title} {subsection_title}",
            "section_type": self._fallback_section_type(subsection_title, user_requirements),
        }

    def _enrich_structured_chapter(
        self,
        core_topic: str,
        user_requirements: str,
        chapter_title: str,
        chapter_index: int,
        skeleton: Dict[str, Any],
        language: str = "vi",
        textbook_mode: str = "standard",
    ) -> List[Dict[str, str]]:
        profile = get_language_profile(language)
        practice_mode = _is_practice_mode(textbook_mode)
        valid_types = {"light", "medium", "deep", "applied"}
        chapters = skeleton.get("chapters") or []
        chapter = chapters[chapter_index]
        subsection_titles = [
            str(sub.get("title") or "").strip()
            for sub in chapter.get("subsections", [])
        ]
        full_outline = "\n".join(
            "\n".join(
                [f"Chapter {idx + 1}: {ch.get('title', '')}"]
                + [
                    f"  - {idx + 1}.{sub_idx + 1} {sub.get('title', '')}"
                    for sub_idx, sub in enumerate(ch.get("subsections", []))
                ]
            )
            for idx, ch in enumerate(chapters)
        )

        if practice_mode:
            system_prompt = f"""
[CONTEXT]
You are a senior university practice-course curriculum planner.
The user has already approved the chapter and subsection structure.
[/CONTEXT]

[TASK]
Enrich the provided subsections without changing their titles, order, count,
or chapter placement.
[/TASK]

[CRITERION]
For each subsection, return:
- "description": {profile.prompt_name}, 1-2 precise sentences explaining the
  hands-on task, expected student action, and expected output.
- "search_query": English, 4-8 keywords suitable for practical retrieval/RAG.
- "section_type": exactly "applied".
[/CRITERION]

[CONSTRAINT]
Rule 1 — PRESERVE STRUCTURE: Do not change titles, order, count, or placement.
Rule 2 — PRACTICE ONLY: Every subsection must be enriched as lab/practice work.
Rule 3 — NO THEORY: Do not describe the subsection as theory, concept,
definition, overview, summary, conclusion, or recap.
Rule 4 — QUERY TERMS: search_query must include practical terms such as lab,
hands-on, tutorial, exercise, worked example, implementation, or practice.
Rule 5 — LANGUAGE: descriptions must be in {profile.prompt_name}.
[/CONSTRAINT]

[FORMAT]
Output ONLY a JSON array with exactly {len(subsection_titles)} objects.
No markdown, no explanation.
Each object must have "description", "search_query", and "section_type".
[/FORMAT]"""
        else:
            system_prompt = f"""
[CONTEXT]
You are a senior university curriculum planner.
The user has already approved the chapter and subsection structure.
[/CONTEXT]

[TASK]
Enrich the provided subsections without changing their titles, order, count,
or chapter placement.
[/TASK]

[CRITERION]
For each subsection, return:
- "description": {profile.prompt_name}, 1-2 precise sentences explaining the
  role of this subsection in the whole textbook.
- "search_query": English, 4-8 specific keywords suitable for retrieval/RAG.
- "section_type": exactly one of "light", "medium", "deep", "applied".

Section type guide:
- light   -> orient/recap, accessible prose, light technical depth.
- medium  -> explain/demonstrate, definitions, worked examples.
- deep    -> analyse/theorise, sustained argument, rigorous detail.
- applied -> tasks/exercises, step-by-step guidance, worked solutions.
[/CRITERION]

[CONSTRAINT]
Rule 1 — PRESERVE STRUCTURE: Do not change titles, order, count, or placement.
Rule 2 — VALID TYPES: section_type must be one of "light", "medium", "deep", "applied".
Rule 3 — PRACTICE SIGNALS: If the outline or requirements imply practice,
labs, projects, exercises, worked examples, or hands-on university coursework,
prefer "applied" for the relevant subsections.
Rule 4 — LANGUAGE: descriptions must be in {profile.prompt_name}.
[/CONSTRAINT]

[FORMAT]
Output ONLY a JSON array with exactly {len(subsection_titles)} objects.
No markdown, no explanation.
Each object must have "description", "search_query", and "section_type".
[/FORMAT]"""

        user_prompt = (
            f"Textbook topic: {core_topic}\n"
            f"User requirements: {user_requirements or 'None'}\n"
            f"Target language for descriptions: {profile.prompt_name}\n\n"
            f"Full outline:\n{full_outline}\n\n"
            f"Enrich Chapter {chapter_index + 1}: {chapter_title}\n"
            f"Subsection titles, in fixed order:\n"
            + "\n".join(f"{idx + 1}. {title}" for idx, title in enumerate(subsection_titles))
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt == 1:
                self.prompt_logger.log(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    context_label=f"Structured enrich Ch{chapter_index+1} | {chapter_title[:40]}",
                )
            try:
                response = rate_limited_invoke(
                    prompt | self.llm,
                    {},
                    bucket="chat",
                    metadata={
                        "agent": "Planner",
                        "node": "planner_structured_enrich",
                        "model": LLM_MODEL_PREMIUM,
                    },
                )
                raw = str(response.content).strip()  # type: ignore
                start = raw.find("[")
                end = raw.rfind("]")
                if start == -1 or end == -1:
                    raise ValueError("No JSON array in structured enrichment response")
                enriched = json.loads(raw[start:end + 1])
                if not isinstance(enriched, list) or len(enriched) != len(subsection_titles):
                    raise ValueError("Structured enrichment returned the wrong count")

                normalized: List[Dict[str, str]] = []
                for idx, item in enumerate(enriched):
                    if not isinstance(item, dict):
                        raise ValueError("Structured enrichment item is not an object")
                    title = subsection_titles[idx]
                    section_type = str(item.get("section_type") or "").strip().lower()
                    if practice_mode:
                        section_type = "applied"
                    elif section_type not in valid_types:
                        section_type = self._fallback_section_type(title, user_requirements)
                    fallback = self._fallback_structured_metadata(
                        core_topic,
                        user_requirements,
                        chapter_title,
                        title,
                        language,
                        textbook_mode=textbook_mode,
                    )
                    search_query = str(item.get("search_query") or fallback["search_query"]).strip()
                    if practice_mode:
                        search_query = (
                            f"{search_query} lab hands-on tutorial exercise worked example practice"
                        )
                    normalized.append({
                        "description": str(item.get("description") or fallback["description"]).strip(),
                        "search_query": search_query,
                        "section_type": section_type,
                    })
                return normalized
            except Exception as e:
                logger.warning(
                    f"Structured enrich chapter {chapter_index + 1} attempt "
                    f"{attempt}/{MAX_RETRIES} failed: {e}"
                )

        return [
            self._fallback_structured_metadata(
                core_topic,
                user_requirements,
                chapter_title,
                title,
                language,
                textbook_mode=textbook_mode,
            )
            for title in subsection_titles
        ]

    def enrich_user_structure(
        self,
        core_topic: str,
        user_requirements: str,
        initial_structure: Dict[str, Any],
        language: str = "vi",
        textbook_mode: str = "standard",
    ) -> Optional[CurriculumOutline]:
        chapters = initial_structure.get("chapters") if isinstance(initial_structure, dict) else None
        if not isinstance(chapters, list) or not chapters:
            logger.error("Structured planner received an empty initial structure")
            return None

        enriched_chapters: List[Dict[str, Any]] = []
        for chapter_index, chapter in enumerate(chapters):
            chapter_title = str(chapter.get("title") or "").strip()
            subsection_titles = [
                str(sub.get("title") or "").strip()
                for sub in chapter.get("subsections", [])
                if str(sub.get("title") or "").strip()
            ]
            if not chapter_title or not subsection_titles:
                logger.error("Structured planner received a malformed chapter")
                return None

            metadata = self._enrich_structured_chapter(
                core_topic=core_topic,
                user_requirements=user_requirements,
                chapter_title=chapter_title,
                chapter_index=chapter_index,
                skeleton=initial_structure,
                language=language,
                textbook_mode=textbook_mode,
            )
            enriched_chapters.append({
                "title": chapter_title,
                "subsections": [
                    {
                        "title": title,
                        "description": metadata[idx]["description"],
                        "search_query": metadata[idx]["search_query"],
                        "section_type": metadata[idx]["section_type"],
                    }
                    for idx, title in enumerate(subsection_titles)
                ],
            })

        try:
            return CurriculumOutline(topic=core_topic, chapters=enriched_chapters)
        except Exception as e:
            logger.error(f"Failed to parse enriched structured curriculum: {e}")
            return None

    def create_curriculum(
        self,
        core_topic: str,
        user_requirements: str,
        num_chapters: int = 3,
        max_subsections: int = 5,
        language: str = "vi",
        textbook_mode: str = "standard",
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
            language=language,
            textbook_mode=textbook_mode,
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
        textbook_title           — formal title in the target language (≤ 12 words)
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
    language = state.get("language", "vi")
    planning_mode = state.get("planning_mode", "auto")
    textbook_mode = state.get("textbook_mode", "standard")
    formula_policy = state.get("formula_policy", "auto")
    formula_need = state.get("formula_need", "none")
    initial_structure = state.get("initial_curriculum_structure")
    planner_requirements = user_requirements
    if formula_policy == "include" and formula_need != "none":
        formula_note = (
            "Khi phù hợp, đưa các mục có công thức, phương trình hoặc ví dụ tính toán "
            "vào những phần tự nhiên của dàn ý."
            if language == "vi"
            else "When appropriate, include formula, equation, or worked-calculation sections in natural parts of the outline."
        )
        planner_requirements = (
            f"{user_requirements}\n{formula_note}" if user_requirements else formula_note
        )

    logger.info(f"Core topic         : {core_topic}")
    logger.info(f"User requirements  : {user_requirements or '(none)'}")
    logger.info(f"Num chapters       : {num_chapters}")
    logger.info(f"Max subsections/ch : {max_subsections}")
    logger.info(f"Language           : {language}")
    logger.info(f"Planning mode      : {planning_mode}")
    logger.info(f"Textbook mode      : {textbook_mode}")

    planner = HybridPlanner()
    if planning_mode == "structured" and isinstance(initial_structure, dict):
        curriculum = planner.enrich_user_structure(
            core_topic,
            planner_requirements,
            initial_structure,
            language=language,
            textbook_mode=textbook_mode,
        )
    else:
        curriculum = planner.create_curriculum(
            core_topic,
            planner_requirements,
            num_chapters=num_chapters,
            max_subsections=max_subsections,
            language=language,
            textbook_mode=textbook_mode,
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
    Metadata generation node: produce textbook title + preface from
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
    logger.info("NODE: GenerateMetadata - Building title + preface")
    logger.info("=" * 60)

    core_topic = state.get("core_topic", state["request"])
    curriculum = state.get("curriculum")
    language = state.get("language", "vi")
    textbook_mode = state.get("textbook_mode", "standard")
    profile = get_language_profile(language)

    if not curriculum:
        logger.warning("generate_metadata_node: curriculum is None — skipping")
        return {
            "textbook_title":  f"{profile.default_title_prefix} {core_topic}",
            "preface_content": "",
            "messages": ["⚠️ Metadata skipped: curriculum not available"],
        }

    planner = HybridPlanner()

    textbook_title = (
        planner._generate_textbook_title(core_topic, curriculum, language=language)
        or f"{profile.default_title_prefix} {core_topic}"
    )
    if _is_practice_mode(textbook_mode):
        logger.info("Practice textbook mode: skipping preface generation")
        preface_content = ""
    else:
        preface_content = planner._generate_preface(
            core_topic,
            textbook_title,
            curriculum,
            language=language,
        )

    logger.info(f"✓ Title: {textbook_title}")
    logger.info(f"✓ Preface: {len(preface_content)} chars")
    return {
        "textbook_title":  textbook_title,
        "preface_content": preface_content,
        "messages": [
            f"✓ Title generated: {textbook_title}",
            (
                "✓ Preface skipped for practice textbook mode"
                if _is_practice_mode(textbook_mode)
                else f"✓ Preface generated ({len(preface_content)} chars)"
            ),
        ],
    }
