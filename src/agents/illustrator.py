"""
Illustrator Agent for AI Textbook Generator.

This agent searches for real images from Google Images via SerpAPI
and replaces image suggestion placeholders with actual image URLs.
"""

import re
import requests
import io
import hashlib


from src.config import SERPAPI_API_KEY, BASE_DIR
from src.log_config import setup_logger
from src.graph.state import AgentState
from urllib.parse import urlparse
from PIL import Image
from pathlib import Path

logger = setup_logger(name="IllustratorAgent", logfile="logs/agents.log")


class IllustratorAgent:
    """
    Illustrator Agent: Finds real images to enhance content.
    
    Uses SerpAPI to search Google Images and replace
    `> [IMAGE SUGGESTION: ...]` tags with actual images.
    """
    
    def __init__(self) -> None:
        """Initialize with SerpAPI key."""
        self.api_key = SERPAPI_API_KEY
        if not self.api_key:
            logger.warning("⚠️ SERPAPI_API_KEY is missing. Images will not be generated.")

    def find_image_url(self, query: str) -> str:
        """
        Find the best image on Google Images for a given query.
        Optimizes query, fetches top 3 candidates, validates each one.
        
        Args:
            query: Search description (will be optimized internally)
            
        Returns:
            Valid image URL, or empty string if not found or API error.
        """
        if not self.api_key:
            logger.warning("SerpAPI key not configured - skipping image search")
            return ""
        
        optimized_query = self.build_image_query(query)
        logger.info(f"Searching Google Images for: '{optimized_query}'")
        
        url = "https://serpapi.com/search"
        params = {
            "engine": "google_images",
            "q": optimized_query,
            "api_key": self.api_key,
            "num": 3,
            "safe": "active",
            "isz": "m",
            "ijn": "0"
        }
        
        REJECTED_EXTENSIONS = ('.svg', '.shtml', '.html', '.php', '.webp', '.gif')
        REJECTED_DOMAINS = ('wikipedia.org', 'wikimedia.org')
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            results = response.json()
            
            if "error" in results:
                logger.error(f"SerpAPI error: {results['error']}")
                return ""
            
            images_results = results.get("images_results", [])
            
            if not images_results:
                logger.warning(f"No images found for '{optimized_query[:40]}'")
                return ""
            
            # Loop qua top 3 candidates, trả về cái đầu tiên pass validation
            for i, candidate in enumerate(images_results[:3]):
                image_url = candidate.get("original", "")
                
                # Check 1: URL tồn tại và đúng kiểu string
                if not image_url or not isinstance(image_url, str):
                    logger.debug(f"Candidate {i+1}: Invalid or missing URL, skipping")
                    continue
                
                # Check 2: Phải là http/https
                if not image_url.startswith(('http://', 'https://')):
                    logger.debug(f"Candidate {i+1}: Invalid protocol, skipping")
                    continue
                
                # Check 3: Reject unsupported formats
                if any(image_url.lower().endswith(ext) for ext in REJECTED_EXTENSIONS):
                    logger.warning(f"Candidate {i+1}: Unsupported format, skipping: {image_url[:60]}")
                    continue
                
                # Check 4: Reject blocked domains
                parsed = urlparse(image_url)
                if any(domain in parsed.netloc for domain in REJECTED_DOMAINS):
                    logger.warning(f"Candidate {i+1}: Blocked domain '{parsed.netloc}', skipping")
                    continue
                
                # All checks passed
                logger.info(f"✓ Selected candidate {i+1}: {image_url[:60]}...")
                return image_url
            
            # Tất cả 3 candidates đều fail validation
            logger.warning(f"All candidates rejected for query: '{optimized_query[:40]}'")
            return ""
            
        except requests.exceptions.Timeout:
            logger.error(f"SerpAPI request timeout for '{optimized_query[:40]}'")
            return ""
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error calling SerpAPI: {e}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected error calling SerpAPI: {e}", exc_info=True)
            return ""

    def translate_caption(self, english_description: str) -> str:
        """
        Translate image description from English to Vietnamese for caption.
        Uses LLM for accurate technical translation.
        
        Args:
            english_description: Original English description from IMAGE SUGGESTION tag
            
        Returns:
            Vietnamese caption string.
        """
        from langchain_openai import ChatOpenAI
        from src.config import LLM_MODEL_NAME
        
        try:
            llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0)
            response = llm.invoke(
                f"Translate this image caption to Vietnamese. "
                f"Return ONLY the translation, no explanation:\n\n{english_description}"
            )
            translated = response.content.strip()  # type: ignore
            logger.info(f"Caption translated: '{english_description[:40]}' → '{translated[:40]}'")
            return translated
        except Exception as e:
            logger.warning(f"Caption translation failed: {e}")
            return english_description  # Fallback: giữ tiếng Anh nếu lỗi


    def build_image_query(self, description: str) -> str:
        """
        Compress verbose description into a focused 5-7 word image search query.
        
        Args:
            description: Full IMAGE SUGGESTION description (often 20-30 words)
            
        Returns:
            Short, specific search query optimized for image search.
        """
        from langchain_openai import ChatOpenAI
        from src.config import LLM_MODEL_NAME
        
        try:
            llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0)
            response = llm.invoke(
                f"Convert this image description into a short, specific Google Image search query "
                f"(5-7 words max, English, no quotes).\n"
                f"Focus on the KEY VISUAL ELEMENT only.\n\n"
                f"Description: {description}\n\n"
                f"Examples:\n"
                f"- 'Diagram showing chess piece movements on board' → 'chess pieces movement diagram'\n"
                f"- 'Heisenberg uncertainty principle position momentum relationship' → "
                f"'Heisenberg uncertainty principle diagram physics'\n\n"
                f"Query:"
            )
            query = response.content.strip()  # type: ignore
            logger.info(f"Optimized query: '{description[:40]}...' → '{query}'")
            return query
        except Exception as e:
            logger.warning(f"Query optimization failed: {e}")
            # Fallback: lấy 6 từ đầu của description
            return ' '.join(description.split()[:6])

    def illustrate_content(self, content: str) -> str:
        pattern = r"> \[IMAGE SUGGESTION: (.*?)\]"
        matches = re.findall(pattern, content)
        
        if not matches:
            return content
        
        # Output dir cho ảnh local (publisher sẽ cleanup sau)
        image_dir = BASE_DIR / "outputs" / "images"
        
        new_content = content
        for description in matches:
            old_tag = f"> [IMAGE SUGGESTION: {description}]"
            image_url = self.find_image_url(description)
            
            if image_url:
                # Download về local thay vì dùng URL trực tiếp
                local_path = download_and_convert_image(image_url, image_dir)
                
                if local_path:
                    # Dùng đường dẫn local — Pandoc không cần ra ngoài internet
                    vietnamese_caption = self.translate_caption(description)
                    markdown_image = f"\n\n![]({local_path})\n\n*{vietnamese_caption}*\n\n"
                    new_content = new_content.replace(old_tag, markdown_image)
                else:
                    # Download thất bại → xóa tag
                    new_content = new_content.replace(old_tag, "")
            else:
                new_content = new_content.replace(old_tag, "")
        
        return new_content
    
    
def download_and_convert_image(image_url: str, output_dir: Path) -> str:
    """
    Download remote image, convert to PNG, save locally.
    
    Returns:
        Local file path (str) if success, empty string if failed.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; TextbookBot/1.0)'
        }
        response = requests.get(image_url, headers=headers, timeout=10, stream=True)
        
        if response.status_code != 200:
            logger.warning(f"Image download failed ({response.status_code}): {image_url[:60]}")
            return ""
        
        # Check content-type — reject HTML/SVG/non-image
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            logger.warning(f"URL returned non-image content-type '{content_type}': {image_url[:60]}")
            return ""
        
        # Reject SVG (xelatex không hỗ trợ)
        if 'svg' in content_type or image_url.lower().endswith('.svg'):
            logger.warning(f"SVG not supported by xelatex, skipping: {image_url[:60]}")
            return ""
        
        # Load image với Pillow
        img_bytes = io.BytesIO(response.content)
        img = Image.open(img_bytes)
        
        # Convert sang RGB PNG (loại bỏ RGBA, palette modes gây lỗi)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Tạo tên file từ hash URL (tránh trùng)
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
        output_dir.mkdir(parents=True, exist_ok=True)
        local_path = output_dir / f"img_{url_hash}.png"
        
        img.save(local_path, 'PNG')
        logger.info(f"✓ Image saved locally: {local_path.name}")
        return str(local_path)
        
    except Exception as e:
        logger.warning(f"Failed to download/convert image: {e}")
        return ""
    
def illustrate_section(state: AgentState) -> dict:
    """
    Illustrator node: Add images to content.
    
    Workflow integration:
    - Input: state["current_content"] with image suggestion tags
    - Output: state["current_content"] with actual images (or tags removed if failed)
    
    Args:
        state: Current workflow state
        
    Returns:
        Partial state update with illustrated content.
    """
    logger.info("=" * 60)
    logger.info("NODE: Illustrator - Processing image suggestions")
    logger.info("=" * 60)
    
    current_content = state.get("current_content", "")
    
    if not current_content or len(current_content) < 50:
        logger.info("Content too short - skipping illustration")
        return {"current_content": current_content}
    
    # Check if SerpAPI is configured
    if not SERPAPI_API_KEY:
        logger.warning("SerpAPI not configured - removing all image suggestion tags")
        # Remove all image suggestion tags since we can't process them
        import re
        cleaned_content = re.sub(r"> \[IMAGE SUGGESTION: .*?\]", "", current_content)
        return {"current_content": cleaned_content}
    
    agent = IllustratorAgent()
    illustrated_content = agent.illustrate_content(current_content)
    
    return {"current_content": illustrated_content}