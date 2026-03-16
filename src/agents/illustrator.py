"""
Illustrator Agent for AI Textbook Generator.

This agent searches for real images from Google Images via SerpAPI
and replaces image suggestion placeholders with actual image URLs.
"""

import re
import requests
import io
import hashlib
import uuid
from openai import OpenAI
from langchain_openai import ChatOpenAI
from src.config import OPENAI_API_KEY, SERPER_API_KEY, BASE_DIR, LLM_MODEL_CHEAP
from src.log_config import setup_logger, setup_prompt_logger
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
    - Converted to PNG
    - Rendered as a Pandoc Markdown figure (engine-agnostic, works with Typst)
    """
    
    def __init__(self) -> None:
        """Initialize with SerpAPI key."""
        self.api_key = SERPER_API_KEY
        if not self.api_key:
            logger.warning("⚠️ SERPER_API_KEY is missing. Images will not be generated.")
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set — DRAW mode disabled, SEARCH only.")
        self.prompt_logger = setup_prompt_logger("illustrator")
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0)

    def build_image_query(self, description: str) -> str:
        """
        Compress verbose description into a focused 5-7 word image search query.
        
        Args:
            description: Full IMAGE SUGGESTION description (often 20-30 words)
            
        Returns:
            Short, specific search query optimized for image search.
        """
        try:
            self.prompt_logger.log(
                system_prompt="Convert image description to 5-7 word Google Image search query",
                user_prompt=f"Description: {description}",
                context_label=f"Query builder | {description[:40]}",
            )
            response = self.llm.invoke(
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


    def translate_caption(self, english_description: str) -> str:
        """
        Translate image description from English to Vietnamese for caption.
        
        Args:
            english_description: Original English description from IMAGE SUGGESTION tag
            
        Returns:
            Vietnamese caption string, or original on error.
        """
        try:
            response = self.llm.invoke(
                f"Translate this image caption to Vietnamese. "
                f"Return ONLY the translation, no explanation:\n\n{english_description}"
            )
            translated = response.content.strip()  # type: ignore
            logger.info(f"Caption translated: '{english_description[:40]}' → '{translated[:40]}'")
            return translated
        except Exception as e:
            logger.warning(f"Caption translation failed: {e}")
            return english_description


    def generate_image_openai(self, description: str) -> str:
            """
            Generate an educational diagram via OpenAI DALL-E 3.
            Reuses the project-wide OPENAI_API_KEY (same key as Writer/Reviewer agents).

            Flow:
                1. Call DALL-E 3 → receive temporary CDN URL (TTL ~1 hour)
                2. Download image bytes via requests.get (timeout=15s)
                3. Resize to fit A4 (IMAGE_MAX_WIDTH x IMAGE_MAX_HEIGHT)
                4. Save as PNG to IMAGE_OUTPUT_DIR
                5. Return local path string, or "" on any failure → triggers SEARCH fallback

            Args:
                description: Image suggestion text from Writer (already in English)

            Returns:
                Absolute path string to saved PNG, or "" on failure.
            """
            if not OPENAI_API_KEY:
                logger.warning("OPENAI_API_KEY not set — cannot generate image, triggering fallback")
                return ""

            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                sanitized = self.sanitize_description_for_dalle(description)
                response = client.images.generate(
                    model="dall-e-3",
                    prompt=(
                        f"An educational illustration for a university textbook. "
                        f"Clean, professional style. White or very light background. "
                        f"Conceptual and visually engaging — NOT a technical diagram with boxes and arrows. "
                        f"No text, no labels, no captions inside the image. "
                        f"Topic: {sanitized}"
                    ),
                    size="1024x1024",
                    quality="standard",
                    n=1,
                )

                image_url = response.data[0].url #type: ignore
                if not image_url:
                    logger.warning("DALL-E 3 returned empty URL — triggering fallback")
                    return ""

                # Download image — timeout=15s to handle CDN TTL safely
                dl_response = requests.get(image_url, timeout=15)
                if dl_response.status_code != 200:
                    logger.warning(
                        f"DALL-E 3 image download failed "
                        f"({dl_response.status_code}) — triggering fallback"
                    )
                    return ""

                img = Image.open(io.BytesIO(dl_response.content)).convert("RGB")
                img.thumbnail((IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT))

                uid = uuid.uuid4().hex[:12]
                IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                local_path: Path = IMAGE_OUTPUT_DIR / f"gen_{uid}.png"
                img.save(local_path, "PNG")

                logger.info(f"✓ DALL-E 3 image saved: {local_path.name}")
                return str(local_path)

            except Exception as e:
                logger.warning(f"DALL-E 3 generation failed ({e}) — triggering fallback")
                return ""


    def sanitize_description_for_dalle(self, description: str) -> str:
        """
        Loại bỏ các enumeration label trong description trước khi gửi DALL-E.
        Giữ lại ý nghĩa cấu trúc, bỏ tên cụ thể mà model sẽ cố render thành text.

        Ví dụ:
        "OSI model with layers (Physical, Data Link, Network, Transport,
        Session, Presentation, Application)"
        → "OSI model showing 7 distinct stacked layers with arrows"
        """
        try:
            self.prompt_logger.log(
                system_prompt="Rewrite description: remove enumerations, keep structural info",
                user_prompt=f"Original: {description}",
                context_label=f"Sanitize | {description[:40]}",
            )
            response = self.llm.invoke(
                f"Rewrite this image description for a diagram generator. "
                f"REMOVE all specific names, labels, and enumerations (e.g. layer names, "
                f"step names, node names). REPLACE them with structural descriptions "
                f"(e.g. '7 stacked layers', '4 connected nodes', '3 recursive levels'). "
                f"Keep the overall structure and flow. Return ONLY the rewritten description.\n\n"
                f"Original: {description}"
            )
            sanitized = response.content.strip()  # type: ignore
            logger.info(f"Description sanitized: '{description[:50]}' → '{sanitized[:50]}'")
            return sanitized
        except Exception as e:
            logger.warning(f"Description sanitize failed ({e}), using original")
            return description


    def find_image_urls(self, query: str) -> list[str]:
        """
        Find all valid image URLs from Google Images for a given query.
 
        Validates each candidate for format, protocol, extension, and domain
        but does NOT attempt to download — callers handle retry on download failure.
 
        Validation pipeline per candidate:
        1. URL must be a non-empty string
        2. Must start with http:// or https://
        3. Extension must not be in REJECTED_EXTENSIONS
        4. Domain must not be in REJECTED_DOMAINS
 
        Args:
            query: Raw image description (will be compressed internally via LLM)
 
        Returns:
            List of validated URLs in ranked order (Serper relevance rank preserved).
            Empty list if API unavailable, no results, or all candidates rejected.
        """
        if not self.api_key:
            logger.warning("SERPER_API_KEY not configured — skipping image search")
            return []
 
        optimized_query = self.build_image_query(query)
        logger.info(f"Searching Google Images for: '{optimized_query}'")
 
        url = "https://google.serper.dev/images"
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"q": optimized_query, "num": 5}
 
        # File extensions that cannot be rendered by Typst/Pandoc or cause parse errors
        REJECTED_EXTENSIONS = (
            '.svg',    # vector — Typst does not support SVG natively
            '.webp',   # lossy format — inconsistent Pillow support across versions
            '.gif',    # animated — only first frame usable, unexpected behavior
            '.shtml',  # server-side HTML, not an image
            '.html',   # HTML page returned as image URL
            '.php',    # dynamic PHP page, rarely an actual image
            '.asp',    # ASP page
            '.aspx',   # ASPX page
            '.cfm',    # ColdFusion page
        )
 
        # Domains that consistently block direct image downloads (403/401)
        # or serve low-quality/watermarked images
        REJECTED_DOMAINS = (
            'wikipedia.org',       # images often redirect or require attribution
            'wikimedia.org',       # same as above
            'researchgate.net',    # 403 on all direct downloads
            'shutterstock.com',    # watermarked
            'gettyimages.com',     # watermarked
            'istockphoto.com',     # watermarked
            'alamy.com',           # watermarked
            'dreamstime.com',      # watermarked
            'stock.adobe.com',     # watermarked
            'pond5.com',           # watermarked
            'depositphotos.com',   # watermarked
        )
 
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
 
            images_results = response.json().get("images", [])
 
            if not images_results:
                logger.warning(f"No images returned by Serper for '{optimized_query[:40]}'")
                return []
 
            valid_urls: list[str] = []
 
            for i, candidate in enumerate(images_results[:5]):
                image_url = candidate.get("imageUrl", "")
 
                # Check 1: must be a non-empty string
                if not image_url or not isinstance(image_url, str):
                    logger.debug(f"Candidate {i+1}: missing or invalid URL — skipping")
                    continue
 
                # Check 2: must use http/https
                if not image_url.startswith(('http://', 'https://')):
                    logger.debug(f"Candidate {i+1}: unsupported protocol — skipping")
                    continue
 
                # Check 3: extension not in blocklist
                if any(image_url.lower().endswith(ext) for ext in REJECTED_EXTENSIONS):
                    logger.warning(
                        f"Candidate {i+1}: rejected extension — {image_url[:60]}"
                    )
                    continue
 
                # Check 4: domain not in blocklist
                parsed = urlparse(image_url)
                if any(domain in parsed.netloc for domain in REJECTED_DOMAINS):
                    logger.warning(
                        f"Candidate {i+1}: blocked domain '{parsed.netloc}' — skipping"
                    )
                    continue
 
                valid_urls.append(image_url)
                logger.debug(f"Candidate {i+1} validated: {image_url[:60]}")
 
            logger.info(
                f"Validation complete: {len(valid_urls)}/5 candidates passed "
                f"for '{optimized_query[:40]}'"
            )
            return valid_urls
 
        except requests.exceptions.Timeout:
            logger.error(f"Serper request timed out for '{optimized_query[:40]}'")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Serper network error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in find_image_urls: {e}", exc_info=True)
            return []
 
 
    def find_image_url(self, query: str) -> str:
        """
        Backward-compatible wrapper around find_image_urls().
 
        Returns the first validated URL, or empty string if none found.
        Prefer using find_image_urls() directly when retry-on-download is needed.
 
        Args:
            query: Raw image description
 
        Returns:
            First validated image URL, or "" if none available.
        """
        urls = self.find_image_urls(query)
        return urls[0] if urls else ""
    
    def illustrate_content(self, content: str) -> str:
        """
        Scan content for image tags and replace with Pandoc Markdown figure blocks.
 
        Supported tag formats:
            New:     > [IMAGE: Short title | Detailed English description]
            Legacy:  > [IMAGE SUGGESTION: Description]  (auto-converted on-the-fly)
 
        Processing pipeline per tag:
        1. Parse title + description from tag
        2. Route to DRAW / DIAGRAM / SEARCH via LLM router
        3. DRAW  → DALL-E 3 generation, fallback to SEARCH on failure
           DIAGRAM → SEARCH directly (no DALL-E attempt)
           SEARCH  → Serper → download with retry across all validated candidates
        4. Build Pandoc figure block with Vietnamese caption
           Caption source: TITLE (preferred, short) → fallback translate DESCRIPTION
 
        Args:
            content: Markdown content with image tags
 
        Returns:
            Content with tags replaced by Pandoc figure blocks.
            Tags with no successful image are removed (empty string replacement).
        """
        # ── Backward compat: convert legacy tags to new format ──────────────────
        OLD_PATTERN = r"> \[IMAGE SUGGESTION: (.*?)\]"
        old_matches = re.findall(OLD_PATTERN, content)
        if old_matches:
            logger.info(
                f"Found {len(old_matches)} legacy IMAGE SUGGESTION tag(s) — converting"
            )
            for desc in old_matches:
                old_tag = f"> [IMAGE SUGGESTION: {desc}]"
                # Use same text for both title and description as best-effort fallback
                content = content.replace(old_tag, f"> [IMAGE: {desc} | {desc}]")
 
        # ── Find all new-format tags ─────────────────────────────────────────────
        pattern = r"> \[IMAGE: (.*?)\]"
        matches = re.findall(pattern, content)
 
        if not matches:
            logger.debug("No image tags found in content")
            return content
 
        logger.info(f"Found {len(matches)} image tag(s) to process")
        new_content = content
        images_inserted = 0
 
        for match in matches:
            old_tag = f"> [IMAGE: {match}]"
            local_path = ""
 
            # ── Parse title | description ────────────────────────────────────────
            # Format: "Short title | Detailed English description"
            # Fallback (no pipe): treat entire match as description, title empty
            if "|" in match:
                title, description = match.split("|", 1)
                title = title.strip()
                description = description.strip()
            else:
                title = ""
                description = match.strip()
 
            label = title if title else description  # for logging
 
            # ── Route: DRAW / DIAGRAM / SEARCH ───────────────────────────────────
            action = self.route_image_request(description)
 
            # DRAW → DALL-E 3, fallback to SEARCH if generation fails
            if action == "DRAW":
                local_path = self.generate_image_openai(description)
                if not local_path:
                    logger.info(
                        f"DRAW failed — falling back to SEARCH for: '{label[:50]}'"
                    )
                    action = "SEARCH"
 
            # DIAGRAM and SEARCH (+ DRAW fallback) → Serper with retry-on-download
            if action in ("SEARCH", "DIAGRAM"):
                candidate_urls = self.find_image_urls(description)
 
                for attempt, image_url in enumerate(candidate_urls, 1):
                    local_path = download_and_convert_image(image_url, IMAGE_OUTPUT_DIR)
                    if local_path:
                        logger.info(
                            f"✓ Download succeeded on candidate "
                            f"{attempt}/{len(candidate_urls)}: {image_url[:60]}"
                        )
                        break
                    logger.warning(
                        f"✗ Download failed candidate "
                        f"{attempt}/{len(candidate_urls)}: {image_url[:60]}"
                    )
 
            # ── Build Pandoc figure block ─────────────────────────────────────────
            if local_path:
                # Caption: use TITLE (short, already meaningful) if available.
                # Translate to Vietnamese — title may already be Vietnamese.
                if title:
                    vietnamese_caption = self.translate_caption(title)
                else:
                    vietnamese_caption = self.translate_caption(description)
 
                # Relative path from BASE_DIR — required by Pandoc when CWD = BASE_DIR.
                # Typst sandbox reads images relative to the .md file's directory,
                # so this must be a consistent relative path, not absolute.
                rel_path = Path(local_path).relative_to(BASE_DIR)
                img_path_for_markdown = str(rel_path).replace("\\", "/")
 
                # Pandoc Markdown figure syntax — engine-agnostic (Typst, xelatex).
                # Pandoc converts this to #figure() in Typst output.
                # width=70% fits within A4 margins and leaves room for the caption.
                figure_block = (
                    "\n\n"
                    f"![{vietnamese_caption}]({img_path_for_markdown}){{width=70%}}\n\n"
                )
 
                new_content = new_content.replace(old_tag, figure_block)
                images_inserted += 1
                logger.info(
                    f"✓ Inserted image {images_inserted}/{len(matches)}: "
                    f"{Path(local_path).name}"
                )
            else:
                # All candidates exhausted — remove tag to avoid broken placeholder in PDF
                new_content = new_content.replace(old_tag, "")
                logger.warning(f"✗ No image found for: '{label[:50]}'")
 
        logger.info(
            f"Image insertion complete: {images_inserted}/{len(matches)} successful"
        )
        return new_content
 
    def route_image_request(self, description: str) -> str:
        """Returns 'SEARCH' or 'DRAW' """
        import json

        PROMPT = """Classify this image description for an educational textbook.

            - SEARCH: real entities — logos, photos, maps, screenshots, real products
            - DRAW: illustrative/artistic concept with no precise structure needed
            (metaphors, abstract ideas, atmosphere, non-technical scenarios)
            - DIAGRAM: any technical structure requiring precise layout
            (flowcharts, architecture diagrams, layer models, graphs, trees, circuits)

            Respond ONLY: {{"action": "SEARCH"}} or {{"action": "DRAW"}} or {{"action": "DIAGRAM"}}

            Description: {description} """
        try:
            self.prompt_logger.log(
                system_prompt=PROMPT.split("Description:")[0].strip(),
                user_prompt=f"Description: {description}",
                context_label=f"Router | {description[:50]}",
            )
            response = self.llm.invoke(PROMPT.format(description=description))
            data = json.loads(response.content.strip())  # type: ignore
            action = data.get("action", "SEARCH").upper()
            if action not in ("SEARCH", "DRAW", "DIAGRAM"):
                action = "SEARCH"
            logger.info(f"Router -> {action}: '{description[:50]}...'")
            return action
            
        except Exception as e:
            logger.warning(f"Router failed ({e}), defaulting to SEARCH")
            return "SEARCH"



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
        logger.info("Images disabled by user — removing all image tags")
        cleaned_content = re.sub(r"> \[IMAGE(?:\s+SUGGESTION)?: .*?\]", "", current_content)
        return {"current_content": cleaned_content}

    # Graceful degradation: remove tags only if BOTH APIs are unavailable
    if not SERPER_API_KEY and not OPENAI_API_KEY:
        logger.warning("No image API configured (SERPER + OPENAI both missing) — removing tags")
        cleaned_content = re.sub(r"> \[IMAGE(?:\s+SUGGESTION)?: .*?\]", "", current_content)
        return {"current_content": cleaned_content}
    
    agent = IllustratorAgent()
    illustrated_content = agent.illustrate_content(current_content)
    
    return {"current_content": illustrated_content}

