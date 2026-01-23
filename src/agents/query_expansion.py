import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sympy import EX

from src.config import LLM_MODEL_NAME
from src.log_config import setup_logger

logger = setup_logger(name="QueryExpansion", logfile="logs/agents.log")

class QueryExpansionAgent:
    def __init__(self) -> None:
        self.llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0.5)
        
    def expand_query(self, user_input: str) -> list[str]: # type: ignore
        
        system_prompt = """You are a Search Query Optimizer for an Academic Textbook Generator System.
        The user will provide a possibly vague topic (e.g., "Cooking", "Python", "Marketing").
        
        YOUR TASK:
        1. Analyze the user's intent: Assume they want to write a comprehensive University-level Textbook or Course.
        2. Generate 3 specific, academic search queries that will help find *Syllabus*, *Curriculum*, or *Textbooks* on this topic.
        3. If the topic is too broad (like "Cooking"), default to "Basic/Fundamental" level (Cơ bản/Đại cương).
        
        OUTPUT FORMAT:
        Return ONLY a JSON list of strings. No markdown.
        Example: ["Giáo trình Kỹ thuật Chế biến món ăn", "Lý thuyết Ẩm thực cơ bản", "Tài liệu nhập môn Nấu ăn"]
        """
        user_prompt = f"User Input: {user_input}"
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", user_prompt)
            
        ])
        
        chain = prompt | self.llm
        
        response = chain.invoke({})
        
        try:
            content = response.content.strip() # type: ignore
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()
                
            queries = json.loads(content)
            
            logger.info(f"      Expanded to: {queries}")
            return queries
        except Exception as e:
            logger.error(f"Error parsing query expansion: {e}")
            
            return [f"Giáo trình {user_input} cơ bản"]
        
        