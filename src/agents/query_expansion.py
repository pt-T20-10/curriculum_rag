"""
Query Expansion Agent for AI Textbook Generator.

This agent analyzes vague user queries and expands them into
specific, academic search queries in both Vietnamese and English
to improve document retrieval across multiple regions.
"""

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.config import LLM_MODEL_CHEAP
from src.log_config import setup_logger, setup_prompt_logger

logger = setup_logger(name="QueryExpansion", logfile="logs/agents.log")


class QueryExpansionAgent:
    """
    Query Expansion Agent: Transforms vague topics into academic search queries
    in both Vietnamese (for vn-vn region) and English (for us-en region).
    
    Example:
    - Input: "Chuyển đổi số"
    - Output vi: ["Giáo trình Chuyển đổi số trong doanh nghiệp", ...]
    - Output en: ["Digital transformation enterprise textbook", ...]
    """
    
    def __init__(self) -> None:
        """Initialize LLM with moderate creativity (temperature=0.5)."""
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0.5)
        self.prompt_logger = setup_prompt_logger("query_expansion")
        
    def expand_query(self, user_input: str) -> list[str]:
        """
        Expand user query into Vietnamese academic search queries only.
        Convenience wrapper around expand_query_bilingual() for backward compatibility.
        
        Args:
            user_input: User's topic (possibly vague)
            
        Returns:
            List of Vietnamese expanded queries.
        """
        result = self.expand_query_bilingual(user_input)
        return result["vi"]

    def expand_query_bilingual(self, user_input: str) -> dict[str, list[str]]:
        """
        Expand user query into 3 academic search queries per language.

        Args:
            user_input: User's topic (possibly vague, any language)

        Returns:
            Dict with keys:
            - "vi": list of 3 Vietnamese queries (for vn-vn region)
            - "en": list of 3 English queries (for us-en region)
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
            ("human", user_prompt)
        ])

        fallback: dict[str, list[str]] = {
            "vi": [f"Giáo trình {user_input} cơ bản"],
            "en": [f"{user_input} fundamentals textbook"]
        }

        self.prompt_logger.log(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_label=f"Expand | {user_input[:40]}",
        )

        try:
            chain = prompt | self.llm
            response = chain.invoke({})

            content = str(response.content).strip()  # type: ignore

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()

            parsed = json.loads(content)

            vi_queries = parsed.get("vi", [])
            en_queries = parsed.get("en", [])

            # Validate — must be non-empty lists of strings
            if not isinstance(vi_queries, list) or not vi_queries:
                logger.warning("Missing or empty 'vi' queries, using fallback")
                vi_queries = fallback["vi"]
            if not isinstance(en_queries, list) or not en_queries:
                logger.warning("Missing or empty 'en' queries, using fallback")
                en_queries = fallback["en"]

            result = {
                "vi": [str(q) for q in vi_queries],
                "en": [str(q) for q in en_queries]
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