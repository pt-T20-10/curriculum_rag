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
from langchain_anthropic import ChatAnthropic

from src.config import LLM_MODEL_CHEAP,ANTHROPIC_API_KEY
from src.log_config import setup_logger, setup_prompt_logger

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
        self.llm = ChatAnthropic(
            model_name=LLM_MODEL_CHEAP,
            api_key=ANTHROPIC_API_KEY,        # type: ignore[arg-type]
            temperature=0.5,
            max_tokens_to_sample=1024,
        )
        self.prompt_logger = setup_prompt_logger("query_expansion")

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

    def expand_query_bilingual(self, user_input: str) -> dict[str, list[str]]:
        """
        Expand user topic into 3 academic search queries per language.

        The LLM is prompted to assume the user wants to write a university-level
        textbook and generates queries targeting syllabi, textbooks, and academic
        papers in each language.

        Fallback behaviour:
            On JSON parse error or any LLM exception, returns a 3-query fallback
            dict so the Ingester still has meaningful queries for both regions
            rather than failing outright.

        Args:
            user_input: User's topic (possibly vague, any language).

        Returns:
            Dict with two keys:
                "vi": list of 3 Vietnamese queries (for vn-vn region searches)
                "en": list of 3 English queries (for us-en region searches)
        """
        logger.info(f"Expanding query: '{user_input}'")

        system_prompt = """You are a Search Query Optimizer for an Academic Textbook Generator System.
The user will provide a possibly vague topic (e.g., "Cooking", "Python", "Chuyển đổi số").

YOUR TASK:
1. Analyze the user's intent: Assume they want to write a comprehensive University-level Textbook or Course.
2. Generate 3 Vietnamese search queries to find Vietnamese syllabi, curricula, or textbooks.
3. Generate 3 English search queries to find English academic papers, textbooks, or courses on the same topic.
4. If the topic is too broad, default to "Basic/Fundamental" level.

OUTPUT FORMAT:
Return ONLY a JSON object with keys "vi" and "en". No markdown, no preamble.
Example for input "Nấu ăn":
{{"vi": ["Giáo trình Kỹ thuật Chế biến món ăn", "Tài liệu nhập môn Nấu ăn cơ bản", "Giáo trình Ẩm thực học đại cương"], "en": ["culinary arts fundamentals textbook", "food science and cooking academic course", "gastronomy introduction university syllabus"]}}"""

        user_prompt = f"User Input: {user_input}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human",  user_prompt),
        ])

        # 3-query fallback per language — matches the expected parallel search
        # count in ingester.py (3 VI + 3 EN = 6 concurrent searches).
        fallback: dict[str, list[str]] = {
            "vi": [
                f"Giáo trình {user_input} cơ bản",
                f"Tài liệu nhập môn {user_input}",
                f"Giáo trình {user_input} đại học",
            ],
            "en": [
                f"{user_input} fundamentals textbook",
                f"introduction to {user_input} university course",
                f"{user_input} academic syllabus",
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