from __future__ import annotations

from pydantic import ValidationError

from app.schemas.curriculum import build_initial_state
from app.schemas.textbook import TextbookCreate


def test_textbook_create_source_preferences_default_and_validation() -> None:
    payload = TextbookCreate(topic="Machine Learning đại cương")

    assert payload.source_preferences.source_mode == "system_default"
    assert payload.source_preferences.custom_urls == []

    custom = TextbookCreate(
        topic="Machine Learning",
        source_preferences={
            "source_mode": "custom_hybrid",
            "selected_source_ids": ["en_academic_open_textbooks"],
            "custom_urls": ["https://openstax.org/details/books/example.pdf"],
            "custom_domains": ["ocw.mit.edu"],
        },
    )
    assert custom.source_preferences.custom_domains == ["ocw.mit.edu"]

    try:
        TextbookCreate(
            topic="Python",
            source_preferences={
                "source_mode": "custom_hybrid",
                "custom_urls": ["openstax.org/not-a-url"],
            },
        )
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("invalid source URL should fail validation")


def test_build_initial_state_carries_source_preferences() -> None:
    source_preferences = {
        "source_mode": "custom_only",
        "selected_source_ids": ["en_academic_universities"],
        "custom_urls": [],
        "custom_domains": ["stanford.edu"],
    }

    state = build_initial_state(
        request="Artificial Intelligence",
        source_preferences=source_preferences,
    )

    assert state["source_preferences"] == source_preferences


def test_ingestion_custom_hybrid_prioritizes_custom_sources(monkeypatch) -> None:
    from app.services.textbook import ingester

    calls = {"queries": [], "filter_checked": False}

    class FakeQueryExpansionAgent:
        def expand_query_bilingual(self, topic, content_type="technical"):
            return {
                "vi": [f"vi {i}" for i in range(6)],
                "en": [f"en {i}" for i in range(6)],
            }

    def fake_search_web(query, max_results, region, min_snippet_score=0.3):
        calls["queries"].append((query, region))
        return [
            {
                "href": f"https://example.edu/{len(calls['queries'])}",
                "title": "Course notes",
                "body": "A useful academic course notes snippet about AI and textbooks.",
            }
        ]

    def fake_filter(urls, **kwargs):
        calls["filter_checked"] = True
        assert urls[0] == "https://custom.example.edu/textbook.pdf"
        assert "custom.example.edu" in kwargs["trusted_domains"]
        assert "https://custom.example.edu/textbook.pdf" in kwargs["skip_snippet_urls"]
        return [{"url": urls[0], "type": "pdf", "trusted_source": "true"}]

    monkeypatch.setattr(ingester, "QueryExpansionAgent", lambda: FakeQueryExpansionAgent())
    monkeypatch.setattr(ingester, "search_web", fake_search_web)
    monkeypatch.setattr(ingester, "filter_and_classify_urls", fake_filter)
    monkeypatch.setattr(ingester, "ingest_dynamic_data", lambda *args, **kwargs: True)

    result = ingester.perform_ingestion(
        {
            "request": "AI",
            "core_topic": "AI",
            "content_type": "technical",
            "rag_collection_name": "dynamic_context_test",
            "advanced_config": {},
            "source_preferences": {
                "source_mode": "custom_hybrid",
                "selected_source_ids": [],
                "custom_urls": ["https://custom.example.edu/textbook.pdf"],
                "custom_domains": ["custom.example.edu"],
            },
        }
    )

    assert calls["filter_checked"] is True
    assert any(q.startswith("site:custom.example.edu") for q, _ in calls["queries"])
    assert any(region == "us-en" for _, region in calls["queries"])
    assert result["messages"][0].startswith("✓ Ingestion complete")


def test_ingestion_custom_only_without_sources_fails(monkeypatch) -> None:
    from app.services.textbook import ingester

    class FakeQueryExpansionAgent:
        def expand_query_bilingual(self, topic, content_type="technical"):
            return {"vi": ["vi"], "en": ["en"]}

    monkeypatch.setattr(ingester, "QueryExpansionAgent", lambda: FakeQueryExpansionAgent())

    result = ingester.perform_ingestion(
        {
            "request": "AI",
            "core_topic": "AI",
            "content_type": "technical",
            "rag_collection_name": "dynamic_context_test",
            "advanced_config": {},
            "source_preferences": {
                "source_mode": "custom_only",
                "selected_source_ids": [],
                "custom_urls": [],
                "custom_domains": [],
            },
        }
    )

    assert "No custom sources" in result["messages"][0]


def test_domain_cap_bypasses_priority_textbook_pdf() -> None:
    from langchain_core.documents import Document

    from app.ingestion.crawler import _apply_domain_diversity_cap

    chunks = [
        Document(
            page_content="Priority textbook content " * 20,
            metadata={
                "source": "https://example.edu/book.pdf",
                "source_quality": "priority_textbook_pdf",
            },
        )
        for _ in range(40)
    ]

    capped = _apply_domain_diversity_cap(chunks, max_per_domain=5)

    assert len(capped) == 40


def test_priority_pdf_rejects_administrative_bulletins() -> None:
    from app.ingestion.crawler import _is_priority_textbook_pdf

    assert _is_priority_textbook_pdf(
        "http://stanford.edu/dept/registrar/bulletin_past/bulletin03-04/pdf/ElectrEng.pdf",
        "School of Engineering Electrical Engineering degree requirements and program requirements.",
        {
            "type": "pdf",
            "trusted_source": "true",
            "search_title": "Stanford Registrar Bulletin Electrical Engineering",
            "source_query": "electrical engineering textbook",
        },
    ) is False


def test_priority_pdf_accepts_course_notes_and_giao_trinh() -> None:
    from app.ingestion.crawler import _is_priority_textbook_pdf

    assert _is_priority_textbook_pdf(
        "https://ocw.mit.edu/courses/example/course-notes.pdf",
        "These lecture notes introduce circuits with worked examples.",
        {
            "type": "pdf",
            "trusted_source": "true",
            "search_title": "MIT OCW lecture notes",
            "source_query": "electrical engineering course notes",
        },
    ) is True
    assert _is_priority_textbook_pdf(
        "https://hust.edu.vn/giao-trinh.pdf",
        "Giáo trình kỹ thuật điện dành cho sinh viên đại học.",
        {
            "type": "pdf",
            "trusted_source": "true",
            "search_title": "Giáo trình kỹ thuật điện",
            "source_query": "giáo trình kỹ thuật điện",
        },
    ) is True


def test_source_diversity_caps_dominant_pdf_and_preserves_custom_url() -> None:
    from langchain_core.documents import Document

    from app.ingestion.crawler import _apply_source_diversity_controls

    dominant = [
        Document(
            page_content=f"Dominant priority textbook chunk {i} " * 10,
            metadata={
                "source": "https://ocw.mit.edu/book.pdf",
                "source_url": "https://ocw.mit.edu/book.pdf",
                "source_quality": "priority_textbook_pdf",
                "relevance_score": f"{0.90 - (i * 0.001):.4f}",
            },
        )
        for i in range(60)
    ]
    other = [
        Document(
            page_content=f"Other academic chunk {i} " * 10,
            metadata={
                "source": f"https://example{i % 4}.edu/page",
                "source_url": f"https://example{i % 4}.edu/page",
                "relevance_score": "0.60",
            },
        )
        for i in range(40)
    ]
    custom = [
        Document(
            page_content=f"Custom source chunk {i} " * 10,
            metadata={
                "source": "https://custom.example.edu/textbook.pdf",
                "source_url": "https://custom.example.edu/textbook.pdf",
                "direct_custom_url": "true",
                "relevance_score": "0.70",
            },
        )
        for i in range(12)
    ]

    capped, status = _apply_source_diversity_controls(
        dominant + other + custom,
        {
            "MAX_CHUNKS_PER_PRIORITY_PDF": 50,
            "MAX_CHUNKS_PER_SOURCE_DEFAULT": 50,
            "CUSTOM_URL_DIRECT_SOURCE_CAP": 500,
            "MAX_SINGLE_SOURCE_CHUNK_RATIO": 0.30,
            "MIN_EMBEDDED_UNIQUE_SOURCES": 6,
            "MIN_EMBEDDED_UNIQUE_DOMAINS": 6,
        },
    )

    counts = {}
    for chunk in capped:
        counts[chunk.metadata["source_url"]] = counts.get(chunk.metadata["source_url"], 0) + 1

    assert counts["https://custom.example.edu/textbook.pdf"] == 12
    assert counts["https://ocw.mit.edu/book.pdf"] < 50
    assert status["removed_by_ratio_cap"] > 0
    assert status["meets_min_sources"] is True


def test_embedding_source_audit_record_summarizes_final_chunks() -> None:
    from langchain_core.documents import Document

    from app.ingestion.crawler import _build_embedding_source_audit_record

    chunks = [
        Document(
            page_content="English textbook content about AI.",
            metadata={
                "source": "https://openstax.org/book.pdf",
                "source_url": "https://openstax.org/book.pdf",
                "domain": "openstax.org",
                "type": "pdf",
                "language": "en",
                "trusted_source": "true",
                "source_quality": "priority_textbook_pdf",
                "relevance_score": "0.72",
            },
        ),
        Document(
            page_content="More English textbook content about AI.",
            metadata={
                "source": "https://openstax.org/book.pdf",
                "source_url": "https://openstax.org/book.pdf",
                "domain": "openstax.org",
                "type": "pdf",
                "language": "en",
                "trusted_source": "true",
                "source_quality": "priority_textbook_pdf",
                "relevance_score": "0.68",
            },
        ),
        Document(
            page_content="Vietnamese academic content về AI.",
            metadata={
                "source": "https://ptit.edu.vn/page",
                "source_url": "https://ptit.edu.vn/page",
                "domain": "ptit.edu.vn",
                "type": "html",
                "language": "vi",
                "trusted_source": "true",
                "relevance_score": "0.5",
            },
        ),
    ]

    record = _build_embedding_source_audit_record(
        topic="AI",
        content_type="technical",
        collection_name="dynamic_context_test",
        run_id="test",
        chunks=chunks,
        raw_chunk_count=5,
        quality_chunk_count=4,
        relevant_chunk_count=3,
        saved_chunk_count=3,
    )

    assert record["trusted_chunk_ratio"] == 1.0
    assert record["priority_pdf_chunk_count"] == 2
    assert record["unique_sources"] == 2
    assert record["top_domains"][0] == {"domain": "openstax.org", "chunk_count": 2}
    assert record["sources"][0]["avg_relevance_score"] == 0.7
