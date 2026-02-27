"""
Query Expansion Agent for AI Textbook Generator.

This agent analyzes vague user queries and expands them into
specific, academic search queries to improve document retrieval.
"""

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.config import LLM_MODEL_NAME
from src.log_config import setup_logger

logger = setup_logger(name="QueryExpansion", logfile="logs/agents.log")


class QueryExpansionAgent:
    """
    Query Expansion Agent: Transforms vague topics into academic search queries.
    
    Example:
    - Input: "Cooking"
    - Output: ["Giáo trình Kỹ thuật Chế biến món ăn", "Lý thuyết Ẩm thực cơ bản"]
    """
    
    def __init__(self) -> None:
        """Initialize LLM with moderate creativity (temperature=0.5)."""
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.5)
        
    def expand_query(self, user_input: str) -> list[str]:  # type: ignore
        """
        Expand user query into 3 specific academic search queries.
        
        Args:
            user_input: User's topic (possibly vague)
            
        Returns:
            List of 3 expanded search queries, or fallback query on error.
        """
        logger.info(f"Expanding query: '{user_input}'")
        
        system_prompt = """You are a Search Query Optimizer for an Academic Textbook Generator System.
The user will provide a possibly vague topic (e.g., "Cooking", "Python", "Marketing").

YOUR TASK:
1. Analyze the user's intent: Assume they want to write a comprehensive University-level Textbook or Course.
2. Generate 3 specific, academic search queries that will help find *Syllabus*, *Curriculum*, or *Textbooks* on this topic.
3. If the topic is too broad (like "Cooking"), default to "Basic/Fundamental" level (Cơ bản/Đại cương).

OUTPUT FORMAT:
Return ONLY a JSON list of strings. No markdown, no preamble.
Example: ["Giáo trình Kỹ thuật Chế biến món ăn", "Lý thuyết Ẩm thực cơ bản", "Tài liệu nhập môn Nấu ăn"]
"""
        
        user_prompt = f"User Input: {user_input}"
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        
        try:
            chain = prompt | self.llm
            response = chain.invoke({})
            
            # Parse JSON response
            content = response.content.strip()  # type: ignore
            
            # Remove markdown code fences if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()
            
            queries = json.loads(content)
            
            logger.info(f"Expanded to: {queries}")
            return queries
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from query expansion: {e}")
            logger.debug(f"Raw response: {response.content}")  # type: ignore
            return [f"Giáo trình {user_input} cơ bản"]
        
        except Exception as e:
            logger.error(f"Error in query expansion: {e}", exc_info=True)
            return [f"Giáo trình {user_input} cơ bản"]