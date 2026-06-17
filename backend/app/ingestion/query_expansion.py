"""
Query Expansion Agent for AI Textbook Generator.

This agent is called as the first step inside perform_ingestion() (ingester.py).
It transforms a possibly vague user topic into targeted academic search queries
in two languages, enabling the Ingester to retrieve relevant content from both
Vietnamese and English web sources in parallel.

Bilingual strategy:
    VI queries — designed for vn-vn region searches:
                 Vietnamese syllabi, textbooks, course materials
    EN queries — designed for us-en region searches:
                 English academic papers, textbooks, university courses

Output is consumed directly by ingester.py which routes each query to the
matching region: VI → vn-vn, EN → us-en.
"""

import json
import warnings

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings
from app.services.runtime_config import get_api_key
LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
from app.utils.log_config import setup_logger, setup_prompt_logger

logger = setup_logger(name="QueryExpansion", logfile="logs/agents.log")


class QueryExpansionAgent:
    """
    Transforms a vague user topic into targeted academic search queries for
    both Vietnamese (vn-vn region) and English (us-en region) web searches.

    The LLM assumes the user intends to write a university-level textbook and
    generates queries that target syllabi, curricula, and academic sources
    rather than general-purpose web results.

    Example:
        Input:  "Chuyển đổi số"
        VI out: ["Giáo trình Chuyển đổi số trong doanh nghiệp",
                 "Tài liệu nhập môn Chuyển đổi số",
                 "Giáo trình Chuyển đổi số đại cương"]
        EN out: ["Digital transformation enterprise textbook",
                 "introduction to digital transformation course syllabus",
                 "digital transformation fundamentals academic paper"]

    On LLM failure or JSON parse error, a 3-query fallback is returned for
    each language so the Ingester can still perform meaningful searches.
    """

    def __init__(self) -> None:
        """
        Initialize LLM with temperature=0.5.

        temperature=0.5 provides moderate creativity so the three generated
        queries per language cover different angles of the topic (e.g. one
        targeting textbooks, one targeting syllabi, one targeting papers)
        rather than producing near-identical phrasings.
        """
        
        self.llm = ChatOpenAI(
            model=LLM_MODEL_CHEAP,
            api_key=get_api_key("OPENAI_API_KEY"), # type: ignore[arg-type]
            temperature=0.5,
     )
    
        
        self.prompt_logger = setup_prompt_logger("query_expansion")



    _SOURCE_HINTS: dict[str, dict[str, str]] = {
            "scholarly": {
                "vi": "Ưu tiên: Wikipedia tiếng Việt, sách giáo khoa đại học, tài liệu .edu.vn",
                "en": "Prioritize: Wikipedia, OpenStax, arXiv, MIT OpenCourseWare, encyclopedia.com",
            },
            "technical": {
                "vi": "Ưu tiên: tài liệu kỹ thuật, blog công nghệ uy tín, docs chính thức",
                "en": "Prioritize: GeeksForGeeks, official documentation, arXiv, cs.cmu.edu, university course pages",
            },
            "practical": {
                "vi": "Ưu tiên: hướng dẫn thực hành từng bước, blog dạy nghề, tài liệu vocational",
                "en": "Prioritize: wikihow.com, instructables.com, step-by-step tutorial sites",
            },
            "lifestyle": {
                "vi": "Ưu tiên: hướng dẫn thực hành, trang sức khỏe/phong cách sống uy tín",
                "en": "Prioritize: wikihow.com, health/wellness sites, practical lifestyle guides",
            },
        }
    
    
    def expand_query(self, user_input: str) -> list[str]:
        """
        Return Vietnamese-only expanded queries.

        .. deprecated::
            Use expand_query_bilingual() instead. This wrapper exists only
            for backward compatibility with code that predates the bilingual
            search strategy. New callers should use expand_query_bilingual()
            directly to also get English queries for us-en region searches.

        Args:
            user_input: User's topic string (possibly vague, any language).

        Returns:
            List of Vietnamese expanded query strings.
        """
        warnings.warn(
            "expand_query() returns Vietnamese queries only. "
            "Use expand_query_bilingual() to get both VI and EN queries.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.expand_query_bilingual(user_input)["vi"]

    def expand_query_bilingual(self, user_input: str, content_type: str = "technical") -> dict[str, list[str]]:
        """
    Expand user topic into 3 academic search queries per language.

    Queries include source hints tailored to content_type:
        scholarly  → Wikipedia, OpenStax, arXiv, MIT OCW, encyclopedia
        technical  → GeeksForGeeks, arXiv, cs.cmu.edu, official docs
        practical  → wikihow, instructables, step-by-step guides
        lifestyle  → wikihow, health/wellness sites, practical guides

    Args:
        user_input:   User's topic (possibly vague, any language).
        content_type: One of "scholarly"|"technical"|"practical"|"lifestyle"
                      from ValidatorAgent — controls source hint strategy.

    Returns:
        Dict with two keys:
            "vi": list of 3 Vietnamese queries (for vn-vn region searches)
            "en": list of 3 English queries (for us-en region searches)
    """
        logger.info(f"Expanding query: '{user_input}'")

        # Build source hints block
        hints     = self._SOURCE_HINTS.get(content_type, self._SOURCE_HINTS["technical"])
        hint_vi   = hints["vi"]
        hint_en   = hints["en"]

        system_prompt = """
[CONTEXT]
You are a search query optimizer for an educational content platform covering all learning domains.
Users submit topics ranging from formal academics to practical skills. Your job: generate diverse,
targeted search queries that capture content from multiple source types and angles.
[/CONTEXT]

[TASK]
Given the user's topic, generate 6 search queries per language:
- 6 Vietnamese queries (for vn-vn region)
- 6 English queries (for us-en region)

Each set of 6 must cover DIFFERENT content types and angles:
1. Academic textbook/syllabus
2. Practical tutorial/how-to guide
3. Wiki/encyclopedia entry
4. Technical documentation/reference
5. Case study/example/application
6. Community content (forum, blog, Q&A)

Content type detected: """ + content_type + """
If topic is vague, default to beginner/fundamental level.
[/TASK]

[CRITERION]
Each query must:
✓ Target a DIFFERENT source type (textbook ≠ tutorial ≠ wiki ≠ docs ≠ case study ≠ forum)
✓ Be specific enough to return relevant results
✓ Match domain tone:
  - scholarly/technical → formal terminology
  - practical/lifestyle → action-oriented language

AVOID repetitive patterns like:
✗ "Giáo trình X cơ bản", "Tài liệu X nhập môn", "Giáo trình X đại cương" (too similar!)
✓ "Giáo trình X", "Hướng dẫn thực hành X", "X là gì", "Tài liệu tham khảo X", "Ví dụ ứng dụng X", "Thảo luận X"

Source guidance for """ + content_type + """:
VI: """ + hint_vi + """
EN: """ + hint_en + """
[/CRITERION]

[FORMAT]
Return ONLY valid JSON with this structure:
- Key "vi": array of 6 Vietnamese query strings
- Key "en": array of 6 English query strings
No markdown, no preamble, no explanation.

Example format (without actual content):
The response should be pure JSON starting with opening brace, containing "vi" and "en" keys with arrays of strings, ending with closing brace.
[/FORMAT]"""
        user_prompt = f"User Input: {user_input}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human",  user_prompt),
        ])

        # 3-query fallback per language — matches the expected parallel search
        # count in ingester.py (3 VI + 3 EN = 6 concurrent searches).
        fallback: dict[str, list[str]] = {
            "vi": [
                f"Giáo trình {user_input}",
                f"Hướng dẫn {user_input} thực hành",
                f"{user_input} là gì",
                f"Tài liệu tham khảo {user_input}",
                f"Ví dụ {user_input}",
                f"Kinh nghiệm học {user_input}",
            ],
            "en": [
                f"{user_input} textbook",
                f"{user_input} tutorial",
                f"{user_input} wikipedia",
                f"{user_input} documentation",
                f"{user_input} examples",
                f"{user_input} forum",
            ],
        }

        self.prompt_logger.log(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_label=f"Expand | {user_input[:40]}",
        )

        try:
            chain    = prompt | self.llm
            response = chain.invoke({})
            content  = str(response.content).strip()  # type: ignore

            # Strip markdown fences if present, then fall back to bare-object
            # extraction to handle LLM responses with leading prose.
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()
            else:
                # Bare JSON object: find first { and last } to skip any prose
                start = content.find("{")
                end   = content.rfind("}")
                if start != -1 and end > start:
                    content = content[start:end + 1]

            parsed = json.loads(content)

            vi_queries: list[str] = parsed.get("vi", [])
            en_queries: list[str] = parsed.get("en", [])

            # Validate — both must be non-empty lists of strings
            if not isinstance(vi_queries, list) or not vi_queries:
                logger.warning("Missing or empty 'vi' queries — using fallback")
                vi_queries = fallback["vi"]
            if not isinstance(en_queries, list) or not en_queries:
                logger.warning("Missing or empty 'en' queries — using fallback")
                en_queries = fallback["en"]

            result: dict[str, list[str]] = {
                "vi": [str(q) for q in vi_queries],
                "en": [str(q) for q in en_queries],
            }
            logger.info(f"VI queries: {result['vi']}")
            logger.info(f"EN queries: {result['en']}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from query expansion: {e}")
            return fallback
        except Exception as e:
            logger.error(f"Error in query expansion: {e}", exc_info=True)
            return fallback
