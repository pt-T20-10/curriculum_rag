import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from PIL import Image

from app.services.textbook import illustrator


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_wikimedia_image_candidates_parse_url_credit_and_license(monkeypatch) -> None:
    payload = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Ada Lovelace portrait.jpg",
                    "imageinfo": [
                        {
                            "thumburl": "https://upload.wikimedia.org/thumb/ada.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Ada_Lovelace_portrait.jpg",
                            "extmetadata": {
                                "Artist": {"value": "<span>Alfred Edward Chalon</span>"},
                                "LicenseShortName": {"value": "Public domain"},
                            },
                        }
                    ],
                }
            }
        }
    }

    monkeypatch.setattr(illustrator, "get_api_key", lambda key, required=False: "")
    monkeypatch.setattr(
        illustrator.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(payload),
    )

    agent = illustrator.IllustratorAgent()
    candidates = agent.find_wikimedia_image_candidates("Ada Lovelace portrait")

    assert len(candidates) == 1
    assert candidates[0].source == "wikimedia"
    assert candidates[0].url == "https://upload.wikimedia.org/thumb/ada.jpg"
    assert candidates[0].credit == "Alfred Edward Chalon"
    assert candidates[0].license == "Public domain"


def test_illustrate_section_does_not_strip_when_serper_and_openai_missing(monkeypatch) -> None:
    class FakeAgent:
        def illustrate_content(
            self,
            content: str,
            section_type: str = "medium",
            language: str = "vi",
            **kwargs,
        ) -> str:
            return content.replace(
                "> [IMAGE: Ada Lovelace | Ada Lovelace portrait]",
                "![Ada Lovelace](outputs/images/ada.png){width=70%}",
            )

    monkeypatch.setattr(illustrator, "get_api_key", lambda key, required=False: "")
    monkeypatch.setattr(illustrator, "IllustratorAgent", lambda: FakeAgent())

    result = illustrator.illustrate_section(
        {
            "current_content": (
                "Đoạn văn đủ dài để đi qua bước illustrator trong bài kiểm thử.\n\n"
                "> [IMAGE: Ada Lovelace | Ada Lovelace portrait]\n\n"
                "Nội dung sau ảnh."
            ),
            "enable_images": True,
            "language": "vi",
        } #type: ignore
    )

    assert "![Ada Lovelace]" in result["current_content"]


def test_image_candidates_prefer_serper_before_wikimedia(monkeypatch) -> None:
    monkeypatch.setattr(illustrator, "get_api_key", lambda key, required=False: "serper-key")
    agent = illustrator.IllustratorAgent()
    monkeypatch.setattr(
        agent,
        "find_serper_image_candidates",
        lambda query: [
            illustrator.ImageCandidate(
                url="https://example.com/serper.jpg",
                source="serper",
            )
        ],
    )

    def fail_wikimedia(query: str):
        raise AssertionError("Wikimedia should not run when Serper has candidates")

    monkeypatch.setattr(agent, "find_wikimedia_image_candidates", fail_wikimedia)

    candidates = agent.find_image_candidates("Ada Lovelace portrait")

    assert [candidate.source for candidate in candidates] == ["serper"]


def test_search_fallback_uses_openai_before_wikimedia(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(illustrator, "get_api_key", lambda key, required=False: "")
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "route_image_request",
        lambda self, description: "SEARCH",
    )
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "find_serper_image_candidates",
        lambda self, query: [],
    )
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "generate_image_openai",
        lambda self, description, is_search_fallback=False, section_type="medium", **kwargs: calls.append("openai") or "",
    )
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "find_wikimedia_image_candidates",
        lambda self, query: calls.append("wikimedia") or [],
    )

    agent = illustrator.IllustratorAgent()
    result = agent.illustrate_content(
        "Đủ dài để xử lý.\n\n> [IMAGE: Ada Lovelace | Ada Lovelace portrait]\n",
        language="vi",
    )

    assert calls == ["openai", "wikimedia"]
    assert "IMAGE:" not in result


def test_wikimedia_skipped_for_generic_technical_query_after_serper_and_openai_fail(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(illustrator, "get_api_key", lambda key, required=False: "")
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "route_image_request",
        lambda self, description: "SEARCH",
    )
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "find_serper_image_candidates",
        lambda self, query: [],
    )
    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "generate_image_openai",
        lambda self, description, is_search_fallback=False, section_type="medium", **kwargs: calls.append("openai") or "",
    )

    def fail_wikimedia(self, query: str):
        raise AssertionError("Wikimedia should not run for generic technical query")

    monkeypatch.setattr(
        illustrator.IllustratorAgent,
        "find_wikimedia_image_candidates",
        fail_wikimedia,
    )

    agent = illustrator.IllustratorAgent()
    result = agent.illustrate_content(
        "Đủ dài để xử lý.\n\n> [IMAGE: Ma trận điểm ảnh | pixel matrix diagram]\n",
        language="vi",
    )

    assert calls == ["openai"]
    assert "IMAGE:" not in result


def test_manual_download_multiple_wikimedia_images_for_quality_review(monkeypatch) -> None:
    if os.getenv("RUN_WIKIMEDIA_IMAGE_DOWNLOAD_TEST") != "1":
        pytest.skip(
            "Manual network test. Set RUN_WIKIMEDIA_IMAGE_DOWNLOAD_TEST=1 "
            "to download Wikimedia images for visual review."
        )

    queries = [
        "Ada Lovelace portrait",
        "Isaac Newton portrait",
        "Ha Long Bay Vietnam landscape",
        "Eiffel Tower photograph",
        "OSI model diagram",
        "human heart anatomy diagram",
    ]
    output_dir = illustrator.BASE_DIR / "outputs" / "wikimedia_quality_check"
    output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(illustrator, "get_api_key", lambda key, required=False: "")
    agent = illustrator.IllustratorAgent()
    manifest: list[dict] = []

    for query in queries:
        candidates = agent.find_wikimedia_image_candidates(query)
        saved_path = ""
        selected = None
        error = ""

        if not candidates:
            error = "No Wikimedia candidates"
        else:
            for candidate in candidates[:8]:
                saved_path = illustrator.download_and_convert_image(candidate.url, output_dir)
                if saved_path:
                    selected = candidate
                    break
                time.sleep(1.0)

        if saved_path and selected:
            with Image.open(saved_path) as img:
                width, height = img.size

            manifest.append(
                {
                    "query": query,
                    "status": "downloaded",
                    "file": str(Path(saved_path).relative_to(illustrator.BASE_DIR)).replace("\\", "/"),
                    "width": width,
                    "height": height,
                    "wikimedia_title": selected.title,
                    "wikimedia_page": selected.page_url,
                    "credit": selected.credit,
                    "license": selected.license,
                    "source_url": selected.url,
                }
            )
        else:
            manifest.append(
                {
                    "query": query,
                    "status": "failed",
                    "error": error or "Could not download any candidate, likely rate-limited",
                    "candidate_count": len(candidates),
                    "candidate_urls": [candidate.url for candidate in candidates[:8]],
                }
            )

        time.sleep(1.0)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    downloaded = [item for item in manifest if item["status"] == "downloaded"]
    assert len(downloaded) >= 3, f"Only downloaded {len(downloaded)} images; see {manifest_path}"
