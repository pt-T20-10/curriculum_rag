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

# Image size constraints for A4 textbook
# Max 800px width (~14cm at 150dpi) and 500px height ensures caption stays on same page
IMAGE_MAX_WIDTH = 800
IMAGE_MAX_HEIGHT = 500

# Output directory for downloaded images (relative to BASE_DIR)
IMAGE_OUTPUT_DIR = BASE_DIR / "outputs" / "images"


class IllustratorAgent:
    """
    Illustrator Agent: Finds real images to enhance content.
    
    Uses SerpAPI to search Google Images and replace
    `> [IMAGE SUGGESTION: ...]` tags with actual images.
    
    Images are:
    - Downloaded locally (avoids Pandoc fetching URLs at compile time)
    - Resized to fit A4 page (max 800x500px)
    - Converted to PNG (xelatex compatible)
    - Rendered as centered LaTeX figure with Vietnamese caption
    """
    
    def __init__(self) -> None:
        """Initialize with SerpAPI key."""
        self.api_key = SERPAPI_API_KEY
        if not self.api_key:
            logger.warning("⚠️ SERPAPI_API_KEY is missing. Images will not be generated.")

    def build_image_query(self, description: str) -> str:
        """
        Compress verbose description into a focused 5-7 word image search query.
        
        Args:
            description: Full IMAGE SUGGESTION description (often 20-30 words)
            
        Returns:
            Short, specific search query optimized for image search.
        """
        from langchain_openai import ChatOpenAI
        from src.config import LLM_MODEL_CHEAP
        
        try:
            llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0)
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
            return ' '.join(description.split()[:6])

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
            
            # Loop top 3 candidates, return first one that passes validation
            for i, candidate in enumerate(images_results[:3]):
                image_url = candidate.get("original", "")
                
                if not image_url or not isinstance(image_url, str):
                    logger.debug(f"Candidate {i+1}: Invalid or missing URL, skipping")
                    continue
                
                if not image_url.startswith(('http://', 'https://')):
                    logger.debug(f"Candidate {i+1}: Invalid protocol, skipping")
                    continue
                
                if any(image_url.lower().endswith(ext) for ext in REJECTED_EXTENSIONS):
                    logger.warning(f"Candidate {i+1}: Unsupported format, skipping: {image_url[:60]}")
                    continue
                
                parsed = urlparse(image_url)
                if any(domain in parsed.netloc for domain in REJECTED_DOMAINS):
                    logger.warning(f"Candidate {i+1}: Blocked domain '{parsed.netloc}', skipping")
                    continue
                
                logger.info(f"✓ Selected candidate {i+1}: {image_url[:60]}...")
                return image_url
            
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
        
        Args:
            english_description: Original English description from IMAGE SUGGESTION tag
            
        Returns:
            Vietnamese caption string, or original on error.
        """
        from langchain_openai import ChatOpenAI
        from src.config import LLM_MODEL_CHEAP
        
        try:
            llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0)
            response = llm.invoke(
                f"Translate this image caption to Vietnamese. "
                f"Return ONLY the translation, no explanation:\n\n{english_description}"
            )
            translated = response.content.strip()  # type: ignore
            logger.info(f"Caption translated: '{english_description[:40]}' → '{translated[:40]}'")
            return translated
        except Exception as e:
            logger.warning(f"Caption translation failed: {e}")
            return english_description

    def illustrate_content(self, content: str) -> str:
        """
        Scan content for image suggestion tags and replace with LaTeX figure blocks.
        
        Each image is:
        - Downloaded and resized to max 800x500px
        - Rendered as a centered LaTeX figure with Vietnamese caption
        - Guaranteed to keep image and caption on the same page via [H] float
        
        Args:
            content: Markdown content with `> [IMAGE SUGGESTION: ...]` tags
            
        Returns:
            Content with tags replaced by LaTeX figure blocks, or tags removed if failed.
        """
        pattern = r"> \[IMAGE SUGGESTION: (.*?)\]"
        matches = re.findall(pattern, content)
        
        if not matches:
            logger.debug("No image suggestion tags found in content")
            return content

        logger.info(f"Found {len(matches)} image suggestion(s)")
        new_content = content
        images_inserted = 0

        for description in matches:
            old_tag = f"> [IMAGE SUGGESTION: {description}]"
            image_url = self.find_image_url(description)
            
            if image_url:
                local_path = download_and_convert_image(image_url, IMAGE_OUTPUT_DIR)
                
                if local_path:
                    vietnamese_caption = self.translate_caption(description)
                    
                    # Use forward slashes for LaTeX compatibility on Windows
                    latex_path = local_path.replace("\\", "/")
                    
                    # LaTeX figure environment:
                    # - [H] forces image to appear HERE (not float to next page)
                    # - \centering centers both image and caption
                    # - width=0.7\textwidth fits A4 with margins while allowing caption space
                    # - \caption*{} renders caption without "Figure N:" prefix
                    latex_figure = (
                        "\n\n"
                        "\\begin{figure}[H]\n"
                        "\\centering\n"
                        f"\\includegraphics[width=0.7\\textwidth]{{{latex_path}}}\n"
                        f"\\caption*{{{vietnamese_caption}}}\n"
                        "\\end{figure}\n\n"
                    )
                    
                    new_content = new_content.replace(old_tag, latex_figure)
                    images_inserted += 1
                    logger.info(f"✓ Inserted image {images_inserted}/{len(matches)}: {local_path}")
                else:
                    # Download failed → remove tag cleanly
                    new_content = new_content.replace(old_tag, "")
                    logger.warning(f"✗ Removed failed image tag: {description[:50]}...")
            else:
                new_content = new_content.replace(old_tag, "")
                logger.warning(f"✗ No image found for: {description[:50]}...")

        logger.info(f"Image insertion complete: {images_inserted}/{len(matches)} successful")
        return new_content


def download_and_convert_image(image_url: str, output_dir: Path) -> str:
    """
    Download remote image, resize to fit A4 page, convert to PNG, save locally.
    
    Resize constraints (IMAGE_MAX_WIDTH x IMAGE_MAX_HEIGHT):
    - Ensures image fits within A4 page margins
    - Ensures caption stays on same page as image
    - Uses thumbnail() which preserves aspect ratio
    
    Args:
        image_url: Remote image URL
        output_dir: Local directory to save the processed image
        
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
        
        # Reject non-image content types
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
        
        original_size = img.size
        
       
        if img.width > IMAGE_MAX_WIDTH or img.height > IMAGE_MAX_HEIGHT:
           
            try:
                resample_filter = Image.Resampling.LANCZOS  
            except AttributeError:
                resample_filter = Image.ANTIALIAS  # type: ignore
            img.thumbnail((IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT), resample_filter)
            logger.info(
                f"Resized image: {original_size} → {img.size} "
                f"(max {IMAGE_MAX_WIDTH}x{IMAGE_MAX_HEIGHT})"
            )
        
        # Convert sang RGB PNG (loại bỏ RGBA, palette modes gây lỗi LaTeX)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Tên file từ hash URL — tránh trùng lặp
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
        output_dir.mkdir(parents=True, exist_ok=True)
        local_path = output_dir / f"img_{url_hash}.png"
        
        img.save(local_path, 'PNG')
        logger.info(f"✓ Image saved: {local_path.name} ({img.size[0]}x{img.size[1]}px)")
        return str(local_path)
        
    except Exception as e:
        logger.warning(f"Failed to download/convert image: {e}")
        return ""


def illustrate_section(state: AgentState) -> dict:
    """
    Illustrator node: Add images to content.
    
    Workflow integration:
    - Input: state["current_content"] with image suggestion tags
    - Output: state["current_content"] with LaTeX figure blocks (or tags removed if failed)
    
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
    enable_images = state.get("enable_images", True)
    
    if not enable_images:
        logger.info("Images disabled by user — removing all image suggestion tags")
        cleaned_content = re.sub(r"> \[IMAGE SUGGESTION: .*?\]", "", current_content)
        return {"current_content": cleaned_content}
    
    # Graceful degradation: remove tags if SerpAPI not configured
    if not SERPAPI_API_KEY:
        logger.warning("SerpAPI not configured - removing all image suggestion tags")
        cleaned_content = re.sub(r"> \[IMAGE SUGGESTION: .*?\]", "", current_content)
        return {"current_content": cleaned_content}
    
    agent = IllustratorAgent()
    illustrated_content = agent.illustrate_content(current_content)
    
    return {"current_content": illustrated_content}