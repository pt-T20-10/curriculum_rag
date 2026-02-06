import re
import logging
import requests
from src.config import SERPAPI_API_KEY
from src.log_config import setup_logger
from src.graph.state import AgentState

logger = setup_logger(name="IllustratorAgent", logfile="logs/agents.log")

class IllustratorAgent:
    """
    Illustrator Agent:
    Nhiệm vụ: Tìm kiếm ảnh minh họa thực tế từ Google Images thông qua SerpApi.
    """
    def __init__(self):
        self.api_key = SERPAPI_API_KEY
        if not self.api_key:
            logger.warning("⚠️ SERPAPI_API_KEY is missing. Images will not be generated.")

    def find_image_url(self, query: str) -> str:
        """
        Tìm 1 ảnh tốt nhất trên Google Images (Dùng requests trực tiếp).
        """
        if not self.api_key:
            return ""

        logger.info(f"   🎨 Searching Google Images for: '{query}'")
        
        # Endpoint trực tiếp của SerpApi
        url = "https://serpapi.com/search"
        
        params = {
            "engine": "google_images",
            "q": query,
            "api_key": self.api_key,
            "num": 1,
            "safe": "active",
            "isz": "m",
            "ijn": "0"
        }

        try:
            # Dùng requests có timeout để tránh treo
            response = requests.get(url, params=params, timeout=10)
            
            # Kiểm tra lỗi HTTP (401, 403, 500...)
            response.raise_for_status()
            
            results = response.json()
            images_results = results.get("images_results", [])
            
            if images_results:
                image_url = images_results[0].get("original")
                logger.info(f"      ✅ Found image: {image_url[:50]}...")
                return image_url
            else:
                logger.warning(f"      ❌ No images found for '{query}'")
                return ""
                
        except requests.exceptions.RequestException as e:
            # Bắt các lỗi mạng cụ thể
            logger.error(f"Network Error calling SerpApi: {e}")
            return ""
        except Exception as e:
            logger.error(f"Unknown Error calling SerpApi: {e}")
            return ""

    def illustrate_content(self, content: str) -> str:
        """
        Quét nội dung, tìm thẻ Image Suggestion và thay thế bằng ảnh.
        """
        pattern = r"> \[IMAGE SUGGESTION: (.*?)\]"
        matches = re.findall(pattern, content)
        
        if not matches:
            # logger.info("   ℹ️ No image suggestions found.") # Tắt log này cho đỡ rối
            return content

        new_content = content
        
        for description in matches:
            image_url = self.find_image_url(description)
            old_tag = f"> [IMAGE SUGGESTION: {description}]"
            
            if image_url:
                markdown_image = f"![{description}]({image_url})\n\n*Hình: {description}*"
                new_content = new_content.replace(old_tag, markdown_image)
            else:
                fallback_text = f"> *Minh họa: {description} (Ảnh không tìm thấy)*"
                new_content = new_content.replace(old_tag, fallback_text)
                
        return new_content

# --- NODE FUNCTION ---
def illustrate_section(state: AgentState):
    logger.info("--- ILLUSTRATOR NODE: Searching Visuals ---")
    current_content = state.get("current_content", "")
    if not current_content or len(current_content) < 50:
        return {"current_content": current_content}
    
    agent = IllustratorAgent()
    illustrated_content = agent.illustrate_content(current_content)
    return {"current_content": illustrated_content}