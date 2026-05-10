"""
Illustrator Agent for AI Textbook Generator.

This agent processes `> [IMAGE: title | description]` tags injected by the
Writer and replaces them with locally-saved PNG images embedded as Pandoc
Markdown figure blocks.

Tag processing pipeline per tag:
    1. Parse title + description from `> [IMAGE: title | description]`
    2. Route to DRAW / DIAGRAM / SEARCH via LLM classifier
    3. Acquire image:
         DRAW    → DALL-E 3 generation (fallback to SEARCH on failure)
         DIAGRAM → Serper Google Images search
         SEARCH  → Serper Google Images search
    4. Download + resize + convert to PNG (saved locally under outputs/images/)
    5. Replace tag with Pandoc figure block:
         ![Vietnamese caption](relative/path.png){width=70%}

Images are saved locally rather than referenced by URL so that Pandoc does
not need to fetch remote resources at compile time, and the Typst sandbox
has guaranteed access to every image file.

Legacy `> [IMAGE SUGGESTION: description]` tags from older Writer versions
are auto-converted to the current format on-the-fly.
"""

import json
import re
import io
import hashlib
import uuid
import textwrap
from xmlrpc import client
import requests

from openai import OpenAI
from langchain_openai import ChatOpenAI
from urllib.parse import urlparse
from pathlib import Path
from PIL import Image

from app.config import settings
from app.utils.log_config import setup_logger, setup_prompt_logger

OPENAI_API_KEY = settings.OPENAI_API_KEY
SERPER_API_KEY = settings.SERPER_API_KEY
BASE_DIR = settings.BASE_DIR
INDICATE_LINKS_FOR_PICS = settings.INDICATE_LINKS_FOR_PICS
IMAGE_MODEL_DEFAULT = settings.IMAGE_MODEL_DEFAULT
IMAGE_MODEL_PREMIUM = settings.IMAGE_MODEL_PREMIUM
LLM_MODEL_CHEAP = settings.LLM_MODEL_CHEAP
from app.schemas.curriculum import AgentState

logger = setup_logger(name="IllustratorAgent", logfile="logs/agents.log")

# ---------------------------------------------------------------------------
# A4 image size constraints
# Max 800px width (~14cm at 150dpi) and 500px height ensures the caption
# stays on the same page as the image without forced page breaks.
# ---------------------------------------------------------------------------
IMAGE_MAX_WIDTH  = 800
IMAGE_MAX_HEIGHT = 500

# Output directory for downloaded/generated images (relative to BASE_DIR).
# Cleaned up by Publisher after PDF export.
IMAGE_OUTPUT_DIR = BASE_DIR / "outputs" / "images"

# ---------------------------------------------------------------------------

#
# _REJECTED_EXTENSIONS: file types that Typst/Pandoc cannot render or that
#   cause parse errors in the compilation pipeline.
# _REJECTED_DOMAINS: domains that consistently block direct downloads (403/401)
#   or serve watermarked / low-quality images.
# ---------------------------------------------------------------------------
_REJECTED_EXTENSIONS: tuple[str, ...] = (
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

_REJECTED_DOMAINS: tuple[str, ...] = (
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

# ---------------------------------------------------------------------------
# Vietnamese character detection helper (BUG-09 fix)
#
# Used by translate_caption() to skip the LLM call when the title is already
# in Vietnamese — Writer generates titles in Vietnamese by default.
# ---------------------------------------------------------------------------
_VIETNAMESE_CHARS: frozenset[str] = frozenset(
    'àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩị'
    'òóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ'
)


def _is_vietnamese(text: str) -> bool:
    """
    Return True if `text` contains at least one Vietnamese diacritic character.

    Used as a fast heuristic to skip unnecessary LLM translation calls when
    the caption title is already in Vietnamese.
    """
    return any(c in _VIETNAMESE_CHARS for c in text.lower())


class IllustratorAgent:
    """
    Illustrator Agent: resolves `> [IMAGE: title | description]` tags into
    locally-saved PNG figures embedded as Pandoc Markdown figure blocks.

    Image acquisition strategy (per tag):
        DRAW    → DALL-E 3 (conceptual/artistic illustrations)
        DIAGRAM → Serper Google Images (technical diagrams requiring precise layout)
        SEARCH  → Serper Google Images (real entities: logos, photos, screenshots)

    All acquired images are:
        - Downloaded and saved locally (Typst sandbox compatibility)
        - Resized to fit A4 margins (max 800×500px, aspect ratio preserved)
        - Converted to PNG (eliminates RGBA/palette modes that break rendering)
        - Referenced via relative path from BASE_DIR

    The LLM client (self.llm) is instantiated once in __init__ and reused
    across all method calls — no per-call instantiation overhead.
    """

    def __init__(self) -> None:
        """
        Initialize API keys, LLM client, and prompt logger.

        Warns at startup if SERPER_API_KEY or OPENAI_API_KEY are missing so
        degraded mode (tags stripped without replacement) is visible in logs
        rather than silently failing per-image later.
        """
        self.api_key = SERPER_API_KEY
        if not self.api_key:
            logger.warning("⚠️ SERPER_API_KEY is missing — image search disabled.")
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set — DRAW mode disabled, SEARCH only.")

        self.prompt_logger = setup_prompt_logger("illustrator")
        # temperature=0 for classification and query tasks — determinism is
        # preferred over creativity for routing and short-form outputs.
        self.llm = ChatOpenAI(model=LLM_MODEL_CHEAP, temperature=0)

    # ------------------------------------------------------------------
    # LLM helper methods
    # ------------------------------------------------------------------

    

    def build_image_query(self, description: str) -> str:
        """
        Compress a verbose image description into a focused 5-7 word search query.

        The description from the Writer is often 20-30 words with structural
        detail useful for DALL-E but too verbose for Serper's image search.
        This method extracts the key visual element as a short English query.

        Falls back to the first 6 words of the description on LLM error.

        Args:
            description: Full image description from the IMAGE tag.

        Returns:
            Short English search query (5-7 words, no quotes, no Vietnamese).
        """
        try:
            self.prompt_logger.log(
                system_prompt="Convert image description to 5-7 word Google Image search query",
                user_prompt=f"Description: {description}",
                context_label=f"Query builder | {description[:40]}",
            )
            response = self.llm.invoke(
                "Convert this image description into a short, specific Google Image "
                "search query (5-7 words max, English only, no quotes).\n"
                "Focus on the KEY VISUAL ELEMENT only — ignore structural details.\n\n"
                "Description: " + description + "\n\n"
                "Good examples:\n"
                "  'Diagram showing chess piece movements on board' → 'chess pieces movement diagram'\n"
                "  'Heisenberg uncertainty principle relationship' → 'Heisenberg uncertainty principle physics'\n"
                "  'Kiến trúc microservices với API gateway' → 'microservices architecture API gateway'\n\n"
                "Bad examples (do NOT do this):\n"
                "  Adding quotes around the query\n"
                "  Including Vietnamese words\n"
                "  Repeating the full description verbatim\n\n"
                "Query:"
            )
            query = str(response.content).strip()
            logger.info(f"Optimized query: '{description[:40]}...' → '{query}'")
            return query
        except Exception as e:
            logger.warning(f"Query optimization failed: {e}")
            return ' '.join(description.split()[:6])

    def translate_caption(self, caption: str) -> str:
        """
        Translate an image caption to Vietnamese for use in the PDF figure block.

        Skips the LLM call if the caption already contains Vietnamese diacritic
        characters (BUG-09 fix) — Writer generates titles in Vietnamese by default,
        so translation is only needed for purely English descriptions.

        Args:
            caption: Caption string (may be Vietnamese or English).

        Returns:
            Vietnamese caption string, or the original on error.
        """
        # Fast path — skip LLM call if already Vietnamese
        if _is_vietnamese(caption):
            logger.debug(f"Caption already Vietnamese — skipping translation: '{caption[:40]}'")
            return caption

        try:
            response = self.llm.invoke(
                "Translate this image caption to Vietnamese. "
                "Return ONLY the translation, no explanation:\n\n" + caption
            )
            translated = str(response.content).strip()
            logger.info(f"Caption translated: '{caption[:40]}' → '{translated[:40]}'")
            return translated
        except Exception as e:
            logger.warning(f"Caption translation failed: {e}")
            return caption

    def sanitize_description_for_dalle(self, description: str) -> str:
        """
        Rewrite an image description for DALL-E by removing specific enumeration
        labels while preserving structural meaning.

        DALL-E attempts to render text labels it recognises in the image, which
        produces cluttered outputs with visible text artifacts. Replacing named
        items (layer names, node labels, step titles) with structural counts
        (e.g. "7 stacked layers") avoids this while keeping the diagram intent.

        Example:
            "OSI model with layers (Physical, Data Link, Network, Transport,
             Session, Presentation, Application)"
            → "OSI model showing 7 distinct stacked layers with directional arrows"

        Falls back to the original description on LLM error.

        Args:
            description: Raw image description from the IMAGE tag.

        Returns:
            Rewritten description safe for DALL-E prompt injection.
        """
        try:
            self.prompt_logger.log(
                system_prompt="Rewrite description: remove enumerations, keep structural info",
                user_prompt=f"Original: {description}",
                context_label=f"Sanitize | {description[:40]}",
            )
            response = self.llm.invoke(
            "Rewrite this image description for a GPT Image API call.\n\n"
            "Output format — use EXACTLY this structure:\n"
            "Caption: [one sentence describing the overall scene and style]\n"
            "Elements: [comma-separated list of key visual objects with their attributes]\n\n"
            "Rules:\n"
            "- Caption: focus on scene, atmosphere, composition\n"
            "- Elements: list each object with color/size/position — NO numbered labels\n"
            "- Remove enumeration prefixes (Step 1:, Layer A:, Phase 2:)\n"
            "- Replace with structural counts (3 sequential steps, 4 layers)\n"
            "- Keep proper nouns, conceptual terms, and compositional details\n"
            "- CRITICAL: No text, words, numbers visible in the image\n\n"
            "Original: " + description
        )
            sanitized = str(response.content).strip()
            logger.info(f"Description sanitized: '{description[:50]}' → '{sanitized[:50]}'")
            return sanitized
        except Exception as e:
            logger.warning(f"Description sanitize failed ({e}), using original")
            return description



    def route_image_request(self, description: str) -> str:
        """
        Classify an image description into one of three acquisition routes.

        Classification categories:
            SEARCH  — real-world entities that exist as photographs or official
                      assets: logos, product photos, maps, UI screenshots.
            DRAW    — illustrative or artistic concepts with no precise structure:
                      metaphors, abstract ideas, atmosphere, non-technical scenes.
            DIAGRAM — technical structures requiring precise spatial layout:
                      flowcharts, architecture diagrams, layer models, graphs,
                      decision trees, circuit schematics.

        Defaults to 'SEARCH' on JSON parse error or unexpected LLM output.

        Args:
            description: English image description from the IMAGE tag.

        Returns:
            One of: 'SEARCH', 'DRAW', 'DIAGRAM'.
        """
        # Prompt defined at call site (not module level) because it contains
        # a {description} placeholder that must be formatted per call.
        # textwrap.dedent removes the method-body indentation from the string.
        prompt = textwrap.dedent("""
            Classify this image description for an educational textbook.

            DIAGRAM — requires precise spatial layout (route here if ANY of these apply):
            - Specific quantity of objects (e.g. "3 nodes", "5 layers")
            - Attribute binding: multiple objects each with distinct properties
            - Explicit spatial relationships (left/right/above/below/inside)
            - Multi-subject scenes with positional constraints
            e.g. "OSI 7-layer model", "microservices architecture", "binary search tree"

            DRAW — conceptual illustration, no strict layout constraints:
            - Style/atmosphere focus, single subject, abstract metaphor
            e.g. "DevOps culture scene", "abstract neural network art"

            SEARCH — real entities with authoritative visual form:
            e.g. "Docker whale logo", "Vietnam map", "IBM quantum computer photo"

            Respond ONLY with one of these JSON objects:
            {{"action": "DIAGRAM"}}
            {{"action": "DRAW"}}
            {{"action": "SEARCH"}}

            Description: {description}
        """).strip()

        try:
            self.prompt_logger.log(
                system_prompt=prompt.split("Description:")[0].strip(),
                user_prompt=f"Description: {description}",
                context_label=f"Router | {description[:50]}",
            )
            response = self.llm.invoke(prompt.format(description=description))
            data   = json.loads(str(response.content).strip())
            action = data.get("action", "SEARCH").upper()
            if action not in ("SEARCH", "DRAW", "DIAGRAM"):
                action = "SEARCH"
            logger.info(f"Router → {action}: '{description[:50]}'")
            return action

        except Exception as e:
            logger.warning(f"Router failed ({e}), defaulting to SEARCH")
            return "SEARCH"

    # ------------------------------------------------------------------
    # Image acquisition methods
    # ------------------------------------------------------------------

    def generate_image_openai(
        self,
        description: str,
        is_search_fallback: bool = False,
        section_type: str = "medium",
        ) -> str:
        """
        Generate an educational illustration via OpenAI GPT Image API.

        Uses the project-wide OPENAI_API_KEY (same key as Writer/Reviewer).
        Model is selected dynamically based on section_type:
            deep / applied → gpt-image-1.5  (flagship, higher fidelity)
            light / medium → gpt-image-1-mini (cost-efficient, lower latency)

        Flow:
            1. Select image model based on section_type
            2. Sanitize description (remove enumeration labels)
            3. Call GPT Image API → receive temporary CDN URL (TTL ~1 hour)
            4. Download image bytes (timeout=15s)
            5. Resize to A4 constraints and save as PNG
            6. Return absolute local path, or "" on any failure

        An empty string return triggers automatic fallback to SEARCH in
        illustrate_content().

        Args:
            description:       English image description from the IMAGE tag.
            is_search_fallback: True when called as last-resort after Serper fails.
            section_type:      One of 'light'|'medium'|'deep'|'applied' — controls
                            which GPT Image model is selected.

        Returns:
            Absolute path string to the saved PNG, or "" on any failure.
        """
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set — cannot generate image, triggering fallback")
            return ""

        try:
            

            client = OpenAI(api_key=OPENAI_API_KEY)

            image_model = (
                IMAGE_MODEL_PREMIUM
                if section_type in ("deep", "applied")
                else IMAGE_MODEL_DEFAULT
            )
            logger.info(f"GPT Image model selected: {image_model} (section_type='{section_type}')")

            if is_search_fallback:
                dalle_prompt = (
                    "Educational illustration for a university textbook.\n"
                    "CRITICAL: No text, words, numbers, or labels anywhere in the image.\n"
                    "Depict accurately: " + description
                )
            else:
                sanitized = self.sanitize_description_for_dalle(description)
                dalle_prompt = (
                    "Educational illustration for a university textbook.\n"
                    "CRITICAL: No text, words, numbers, or labels anywhere in the image.\n"
                    "Illustrate: " + sanitized
                )

            response = client.images.generate(
                model=image_model,
                prompt=dalle_prompt,
                size="1024x1024",
                quality="medium",
                n=1,
            )

            # gpt-image-1 returns base64 by default, not a URL.
            # Use b64_json response format and decode directly to avoid
            # empty URL issues that occur when the model omits the URL field.
            image_data = response.data[0] # type: ignore
 
            if image_data.b64_json:
                # Decode base64 directly — no download step needed.
                import base64
                img_bytes = base64.b64decode(image_data.b64_json)
            elif image_data.url:
                # Fallback: some model versions may still return a URL.
                dl_response = requests.get(image_data.url, timeout=15)
                if dl_response.status_code != 200:
                    logger.warning(
                        f"{image_model} image download failed "
                        f"({dl_response.status_code}) — triggering fallback"
                    )
                    return ""
                img_bytes = dl_response.content
            else:
                logger.warning(f"{image_model} returned neither URL nor b64_json — triggering fallback")
                return ""

            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img.thumbnail((IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT))

            uid = uuid.uuid4().hex[:12]
            IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            local_path: Path = IMAGE_OUTPUT_DIR / f"gen_{uid}.png"
            img.save(local_path, "PNG")

            logger.info(f"✓ {image_model} image saved: {local_path.name}")
            return str(local_path)

        except Exception as e:
            logger.warning(f"GPT Image generation failed ({e}) — triggering fallback")
            return ""

    def find_image_urls(self, query: str) -> list[str]:
        """
        Search Google Images via Serper and return a list of validated URLs.

        Validates each candidate URL for protocol, file extension, and domain
        without downloading — callers handle per-URL download retry.

        Validation pipeline per candidate:
            1. Must be a non-empty string
            2. Must start with http:// or https://
            3. Extension must not be in _REJECTED_EXTENSIONS
            4. Domain must not be in _REJECTED_DOMAINS

        Args:
            query: Raw image description — compressed internally via
                   build_image_query() before sending to Serper.

        Returns:
            List of validated URLs in Serper relevance rank order.
            Empty list if API unavailable, no results, or all candidates rejected.
        """
        if not self.api_key:
            logger.warning("SERPER_API_KEY not configured — skipping image search")
            return []

        optimized_query = self.build_image_query(query)
        logger.info(f"Searching Google Images for: '{optimized_query}'")

        url     = "https://google.serper.dev/images"
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        payload = {"q": optimized_query, "num": INDICATE_LINKS_FOR_PICS}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()

            images_results = response.json().get("images", [])
            if not images_results:
                logger.warning(f"No images returned by Serper for '{optimized_query[:40]}'")
                return []

            valid_urls: list[str] = []

            for i, candidate in enumerate(images_results[:INDICATE_LINKS_FOR_PICS]):
                image_url = candidate.get("imageUrl", "")

                # Check 1 — non-empty string
                if not image_url or not isinstance(image_url, str):
                    logger.debug(f"Candidate {i+1}: missing or invalid URL — skipping")
                    continue

                # Check 2 — http/https protocol
                if not image_url.startswith(('http://', 'https://')):
                    logger.debug(f"Candidate {i+1}: unsupported protocol — skipping")
                    continue

                # Check 3 — extension blocklist
                if any(image_url.lower().endswith(ext) for ext in _REJECTED_EXTENSIONS):
                    logger.warning(f"Candidate {i+1}: rejected extension — {image_url[:60]}")
                    continue

                # Check 4 — domain blocklist
                parsed = urlparse(image_url)
                if any(domain in parsed.netloc for domain in _REJECTED_DOMAINS):
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
        Backward-compatible wrapper: return the first validated URL or "".

        Prefer find_image_urls() directly when retry-on-download-failure is needed.

        Args:
            query: Raw image description.

        Returns:
            First validated image URL, or "" if none available.
        """
        urls = self.find_image_urls(query)
        return urls[0] if urls else ""

    def _validate_image_relevance(
        self,
        local_path: str,
        description: str,
    ) -> bool:
        """
        Verify downloaded image matches the intended description using vision API.

        Calls gpt-4o-mini with the image + description and asks for a pass/fail
        judgment. Returns True (use image) or False (try next candidate).
        Fails open — returns True on any API error to avoid blocking pipeline.

        Args:
            local_path:  Absolute path to the locally saved PNG.
            description: Original English description from the IMAGE tag.

        Returns:
            True if image is relevant to description, False otherwise.
        """
        try:
            import base64
            with open(local_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

            validator = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            response = validator.invoke([
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Does this image match the following description for an "
                                f"educational textbook?\n\nDescription: {description}\n\n"
                                "Reply ONLY with 'PASS' if the image is relevant and appropriate, "
                                "or 'FAIL' if it is wrong, irrelevant, or low quality."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                    ],
                }
            ])
            result = str(response.content).strip().upper()
            passed = result.startswith("PASS")
            logger.info(
                f"Image validation: {'✓ PASS' if passed else '✗ FAIL'} — "
                f"'{description[:50]}'"
            )
            return passed
        except Exception as e:
            logger.warning(f"Image validation failed ({e}) — defaulting to PASS")
            return True  # Fail open

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    def illustrate_content(self, content: str, section_type: str = "medium") -> str:
        """
        Process all image tags in `content` and replace them with figure blocks.

        Supported input formats:
            Current:  > [IMAGE: Short title | Detailed English description]
            Legacy:   > [IMAGE SUGGESTION: Description]  (auto-converted on-the-fly)

        Per-tag pipeline:
            1. Parse title and description from the tag
            2. Route to DRAW / DIAGRAM / SEARCH via route_image_request()
            3. Acquire image (DALL-E or Serper + download with candidate retry)
            4. Translate title to Vietnamese (skip if already Vietnamese)
            5. Build Pandoc Markdown figure block with relative path

        Tags for which no image could be acquired are silently removed to
        prevent broken `> [IMAGE: ...]` placeholders appearing in the PDF.

        Args:
            content: Markdown section content containing image tags.

        Returns:
            Content with all image tags replaced by figure blocks (or removed).
        """
        # -- Backward compatibility: convert legacy tags to current format ------
        OLD_PATTERN = r"> \[IMAGE SUGGESTION: (.*?)\]"
        old_matches = re.findall(OLD_PATTERN, content)
        if old_matches:
            logger.info(f"Found {len(old_matches)} legacy IMAGE SUGGESTION tag(s) — converting")
            for desc in old_matches:
                old_tag = f"> [IMAGE SUGGESTION: {desc}]"
                # Use the description as both title and description (best-effort)
                content = content.replace(old_tag, f"> [IMAGE: {desc} | {desc}]")

        # -- Find all current-format tags --------------------------------------
        pattern = r"> \[IMAGE: (.*?)\]"
        matches = re.findall(pattern, content)

        if not matches:
            logger.debug("No image tags found in content")
            return content

        logger.info(f"Found {len(matches)} image tag(s) to process")
        new_content     = content
        images_inserted = 0

        for match in matches:
            old_tag    = f"> [IMAGE: {match}]"
            local_path = ""

            # -- Parse title | description -------------------------------------
            # Format: "Short Vietnamese/English title | Detailed English description"
            # Fallback when no pipe: treat entire match as description, title empty.
            if "|" in match:
                title, description = match.split("|", 1)
                title       = title.strip()
                description = description.strip()
            else:
                title       = ""
                description = match.strip()

            label = title if title else description  # used only for log messages

            # -- Route ---------------------------------------------------------
            action = self.route_image_request(description)

            # ── DRAW ──────────────────────────────────────────────────────────
            if action == "DRAW":
                local_path = self.generate_image_openai(
                    description, is_search_fallback=False, section_type=section_type
                )
                if local_path:
                    if not self._validate_image_relevance(local_path, description):
                        logger.info("DRAW attempt 1 failed validation — retrying once")
                        retry_path = self.generate_image_openai(
                            description, is_search_fallback=False, section_type=section_type
                        )
                        if retry_path:
                            if self._validate_image_relevance(retry_path, description):
                                local_path = retry_path   # retry tốt hơn → dùng retry
                                logger.info("✓ DRAW retry passed validation")
                            else:
                                logger.info(
                                    "DRAW retry also failed validation — "
                                    "falling back to SEARCH (keeping retry as last resort)"
                                )
                                last_resort = retry_path  # giữ lại phòng SEARCH fail
                                local_path  = ""
                                action      = "SEARCH"
                        else:
                            logger.info("DRAW retry generation failed — falling back to SEARCH")
                            last_resort = local_path  # giữ attempt 1 phòng SEARCH fail
                            local_path  = ""
                            action      = "SEARCH"
                else:
                    logger.info("DRAW attempt 1 generation failed — falling back to SEARCH")
                    last_resort = ""
                    action      = "SEARCH"

            # ── SEARCH / DIAGRAM (bao gồm fallback từ DRAW) ───────────────────
            if action in ("SEARCH", "DIAGRAM"):
                _MAX_SEARCH_ROUNDS = 3   # số lần thử tối đa với các candidate khác nhau
                candidate_urls     = self.find_image_urls(description)
                

                round_path   = ""
                last_valid   = ""   # ảnh cuối cùng download được dù chưa pass validate

                for attempt, image_url in enumerate(candidate_urls, 1):
                    if attempt > _MAX_SEARCH_ROUNDS:
                        logger.info(
                            f"Reached max search rounds ({_MAX_SEARCH_ROUNDS}) — "
                            f"keeping last downloaded result"
                        )
                        break

                    dl_path = download_and_convert_image(image_url, IMAGE_OUTPUT_DIR)
                    if not dl_path:
                        logger.warning(f"✗ Download failed candidate {attempt}: {image_url[:60]}")
                        continue

                    last_valid = dl_path  # lưu lại mọi ảnh download được

                    if self._validate_image_relevance(dl_path, description):
                        logger.info(f"✓ Download + validated on candidate {attempt}")
                        round_path = dl_path
                        break
                    else:
                        logger.warning(
                            f"✗ Validation failed candidate {attempt} — trying next"
                        )

                # Resolve kết quả theo ưu tiên:
                # 1. Ảnh pass validate
                # 2. Ảnh download được nhưng chưa pass (last_valid)
                # 3. DRAW result giữ lại từ trước (last_resort)
                if round_path:
                    local_path = round_path
                elif last_valid:
                    logger.info(
                        "No candidate passed validation — using last downloaded result"
                    )
                    local_path = last_valid
                elif last_resort:
                    logger.info(
                        "All SEARCH candidates failed — falling back to DRAW result"
                    )
                    local_path = last_resort
                else:
                    # Serper hoàn toàn thất bại → thử DALL-E lần cuối
                    logger.info(
                        f"All candidates failed for '{label[:50]}' — "
                        f"last-resort DALL-E DRAW"
                    )
                    local_path = self.generate_image_openai(
                        description, is_search_fallback=True, section_type=section_type
                    )
            # -- Build figure block --------------------------------------------
            if local_path:
                # Caption: prefer TITLE (short, often already Vietnamese).
                # translate_caption() skips the LLM call when already Vietnamese.
                vietnamese_caption = self.translate_caption(title if title else description)

                # Relative path from BASE_DIR — Typst sandbox requires paths
                # relative to the document root, not absolute system paths.
                rel_path             = Path(local_path).relative_to(BASE_DIR)
                img_path_for_markdown = str(rel_path).replace("\\", "/")

                # Pandoc Markdown figure syntax — Pandoc converts this to
                # #figure() in Typst output. width=70% fits A4 margins and
                # leaves room for the caption without overflow.
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
                # All candidates exhausted — remove tag rather than leaving a
                # broken placeholder that would appear verbatim in the PDF.
                new_content = new_content.replace(old_tag, "")
                logger.warning(f"✗ No image found for: '{label[:50]}'")

        logger.info(f"Image insertion complete: {images_inserted}/{len(matches)} successful")
        return new_content


# ---------------------------------------------------------------------------
# Module-level image processing function
# ---------------------------------------------------------------------------

def download_and_convert_image(image_url: str, output_dir: Path) -> str:
    """
    Download a remote image, resize to A4 constraints, convert to PNG, save locally.

    Processing pipeline:
        1. HTTP GET with stream=True (headers-only check before body download)
        2. Reject non-image Content-Type and SVG (not supported by Typst)
        3. Open with Pillow and resize via thumbnail() (preserves aspect ratio)
        4. Convert to RGB if needed (eliminates RGBA/palette render failures)
        5. Save as PNG with MD5-hash filename (deduplication across sections)

    Args:
        image_url:  Remote image URL to download.
        output_dir: Local directory to save the processed PNG.

    Returns:
        Absolute path string to the saved PNG, or "" on any failure.
    """
    try:
        headers  = {'User-Agent': 'Mozilla/5.0 (compatible; TextbookBot/1.0)'}
        response = requests.get(image_url, headers=headers, timeout=10, stream=True)

        if response.status_code != 200:
            logger.warning(f"Image download failed ({response.status_code}): {image_url[:60]}")
            return ""

        # Reject non-image content types (e.g. HTML error pages returned as 200)
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            logger.warning(
                f"URL returned non-image content-type '{content_type}': {image_url[:60]}"
            )
            return ""

        # Reject SVG — Typst does not support SVG natively; conversion at
        # compile time is unreliable across platforms.
        if 'svg' in content_type or image_url.lower().endswith('.svg'):
            logger.warning(f"SVG not supported by Typst — skipping: {image_url[:60]}")
            return ""

        img_bytes = io.BytesIO(response.content)
        img       = Image.open(img_bytes)
        original_size = img.size

        # Resize if the image exceeds A4 margins.
        # thumbnail() shrinks proportionally — never upscales.
        if img.width > IMAGE_MAX_WIDTH or img.height > IMAGE_MAX_HEIGHT:
            try:
                resample_filter = Image.Resampling.LANCZOS   # Pillow ≥ 9.1
            except AttributeError:
                resample_filter = Image.ANTIALIAS            # type: ignore  # Pillow < 9.1
            img.thumbnail((IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT), resample_filter)
            logger.info(
                f"Resized image: {original_size} → {img.size} "
                f"(max {IMAGE_MAX_WIDTH}×{IMAGE_MAX_HEIGHT})"
            )

        # Convert to RGB PNG — eliminates RGBA alpha channels and palette modes
        # that cause rendering failures in the Typst/Pandoc pipeline.
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')

        # Hash-based filename prevents re-downloading the same URL across sections
        url_hash   = hashlib.md5(image_url.encode()).hexdigest()[:12]
        output_dir.mkdir(parents=True, exist_ok=True)
        local_path = output_dir / f"img_{url_hash}.png"

        img.save(local_path, 'PNG')
        logger.info(f"✓ Image saved: {local_path.name} ({img.size[0]}×{img.size[1]}px)")
        return str(local_path)

    except Exception as e:
        logger.warning(f"Failed to download/convert image: {e}")
        return ""


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------

def illustrate_section(state: AgentState) -> dict:
    """
    Illustrator node: resolve image tags in the current subsection content.

    Reads state["current_content"] (polished Markdown from Reviewer),
    processes all `> [IMAGE: ...]` tags via IllustratorAgent.illustrate_content(),
    and returns the updated content with Pandoc figure blocks.

    Graceful degradation:
        - enable_images=False → strip all image tags, return clean Markdown
        - Both SERPER and OPENAI keys missing → strip tags, log warning
        - Per-image failures → tag removed silently, other images unaffected

    Workflow integration:
        Input:  state["current_content"] — polished content from Reviewer
        Output: state["current_content"] — content with figure blocks

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict with "current_content".
    """
    logger.info("=" * 60)
    logger.info("NODE: Illustrator - Processing image suggestions")
    logger.info("=" * 60)

    current_content = state.get("current_content", "")

    if not current_content or len(current_content) < 50:
        logger.info("Content too short — skipping illustration")
        return {"current_content": current_content}

    enable_images = state.get("enable_images", True)

    if not enable_images:
        logger.info("Images disabled by user — removing all image tags")
        cleaned = re.sub(r"> \[IMAGE(?:\s+SUGGESTION)?: .*?\]", "", current_content)
        return {"current_content": cleaned}

    # Graceful degradation when both image APIs are unavailable.
    # Tags are stripped so the PDF does not contain broken placeholders.
    if not SERPER_API_KEY and not OPENAI_API_KEY:
        logger.warning("No image API configured (SERPER + OPENAI both missing) — removing tags")
        cleaned = re.sub(r"> \[IMAGE(?:\s+SUGGESTION)?: .*?\]", "", current_content)
        return {"current_content": cleaned}

    sec_type = "medium"
    try:
            from app.schemas.curriculum import get_chapter_and_subsection
            curriculum = state.get("curriculum")
            if curriculum:
                _, subsection = get_chapter_and_subsection(
                    curriculum,
                    state.get("current_chapter_index", 0),
                    state.get("current_subsection_index", 0),
                )
                sec_type = (
                    subsection.section_type
                    if hasattr(subsection, "section_type")
                    else subsection.get("section_type", "medium")
                )
    except Exception:
            pass

    agent = IllustratorAgent()
    illustrated_content = agent.illustrate_content(current_content, section_type=sec_type)
    return {"current_content": illustrated_content}