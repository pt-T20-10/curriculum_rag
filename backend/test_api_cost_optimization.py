from __future__ import annotations

from types import SimpleNamespace


def test_registry_defaults_match_settings_class_defaults() -> None:
    from app.config import Settings
    from app.config_registry import PARAMETER_REGISTRY, get_admin_registry, get_user_registry

    for key, entry in PARAMETER_REGISTRY.items():
        if key in Settings.model_fields:
            assert entry["default"] == Settings.model_fields[key].default

    assert "API_COST_PROFILE" in get_user_registry()
    assert "API_COST_PROFILE" in get_admin_registry()
    assert "RAG_TOOL_MAX_ROUNDS" in get_user_registry()
    assert "RAG_TOOL_MAX_ROUNDS" in get_admin_registry()


def test_optimized_academic_defaults_are_registered() -> None:
    from app.config import Settings
    from app.config_registry import PARAMETER_REGISTRY

    expected = {
        "API_COST_PROFILE": "balanced_cost",
        "CHUNK_SIZE": 2000,
        "CHUNK_OVERLAP": 300,
        "MAX_CHUNKS_TO_EMBED": 1200,
        "SEARCH_QUERIES_PER_LANGUAGE": 6,
        "SEARCH_RESULTS_PER_QUERY": 20,
        "SEARCH_MAX_WORKERS": 4,
        "TARGETED_CRAWL_QUERIES_PER_CHAPTER": 2,
        "TARGETED_CRAWL_MAX_QUERIES": 16,
        "CRAWL_MAX_ROOT_URLS": 80,
        "URL_FILTER_MAX_WORKERS": 6,
        "CRAWL_MAX_WORKERS": 5,
        "VI_DOMAIN_CAP": 80,
        "EN_DOMAIN_CAP": 80,
        "MAX_CHUNKS_PER_DOMAIN": 35,
        "RAG_INITIAL_K": 8,
        "RAG_TOOL_K": 8,
        "RAG_TOP_K": 8,
        "RAG_TOOL_MAX_ROUNDS": 4,
        "CRAG_CONTEXT_QUALITY_MIN_CHARS": 3500,
        "CRAG_MAX_CONTEXT_RETRIES": 4,
        "CRAG_BEST_EFFORT_AFTER_RETRIES": True,
        "CRAG_TARGETED_RECOVERY_ENABLED": True,
        "CRAG_TARGETED_RECOVERY_RESULTS_PER_QUERY": 6,
        "CRAG_TARGETED_RECOVERY_MAX_ROOT_URLS": 5,
        "RAG_TRUSTED_DOMAIN_QUOTA": 4,
        "RAG_DEFAULT_DOMAIN_QUOTA": 2,
        "WRITER_MAX_PRIOR_SUMMARIES": 6,
        "OPENAI_RATE_LIMIT_ENABLED": True,
        "MIN_EMBEDDED_UNIQUE_SOURCES": 12,
        "MIN_EMBEDDED_UNIQUE_DOMAINS": 8,
        "TARGET_EMBEDDED_UNIQUE_SOURCES": 15,
        "MAX_CHUNKS_PER_SOURCE_DEFAULT": 180,
        "MAX_CHUNKS_PER_PRIORITY_PDF": 300,
        "MAX_SINGLE_SOURCE_CHUNK_RATIO": 0.30,
        "CUSTOM_URL_DIRECT_SOURCE_CAP": 500,
        "MIN_CITABLE_SOURCES": 10,
    }

    for key, value in expected.items():
        assert Settings.model_fields[key].default == value
        assert PARAMETER_REGISTRY[key]["default"] == value


def test_cost_profile_selects_auxiliary_model() -> None:
    from app.services.cost_profile import auxiliary_chat_model, get_rag_chunk_llm_filter_mode

    assert auxiliary_chat_model(
        cheap_model="cheap",
        premium_model="premium",
        advanced_config={"API_COST_PROFILE": "quality_current"},
    ) == "premium"
    assert auxiliary_chat_model(
        cheap_model="cheap",
        premium_model="premium",
        advanced_config={"API_COST_PROFILE": "balanced_cost"},
    ) == "cheap"
    assert get_rag_chunk_llm_filter_mode({"API_COST_PROFILE": "quality_current"}) == "always"
    assert get_rag_chunk_llm_filter_mode({"API_COST_PROFILE": "balanced_cost"}) == "auto"
    assert get_rag_chunk_llm_filter_mode({
        "API_COST_PROFILE": "balanced_cost",
        "RAG_CHUNK_LLM_FILTER_MODE": "off",
    }) == "off"


def test_api_usage_telemetry_records_summary(monkeypatch) -> None:
    from app.services import api_rate_limiter

    monkeypatch.setattr(api_rate_limiter, "_runtime_bool", lambda key, default: False)
    run_id = "test-run"
    api_rate_limiter.reset_api_usage_summary(run_id)

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    )
    with api_rate_limiter.api_usage_context(run_id=run_id, agent="Unit", node="test"):
        api_rate_limiter.rate_limited_call(
            lambda: response,
            bucket="chat",
            model="gpt-4o-mini",
        )

    summary = api_rate_limiter.get_api_usage_summary(run_id)
    assert summary["total_calls"] == 1
    assert summary["cheap_chat_calls"] == 1
    assert summary["by_agent"]["Unit"]["calls"] == 1
    assert summary["by_node"]["test"]["calls"] == 1
    assert summary["total_estimated_usd"] > 0


def _minimal_state(*, advanced_config=None, rag_context="context", rag_source_audit=None):
    from app.schemas.curriculum import Chapter, CurriculumOutline, SubSection

    return {
        "curriculum": CurriculumOutline(
            topic="AI",
            chapters=[
                Chapter(
                    title="Intro",
                    subsections=[
                        SubSection(
                            title="Basics",
                            description="AI basics",
                            search_query="artificial intelligence basics",
                            section_type="medium",
                        )
                    ],
                )
            ],
        ),
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "rag_context": rag_context,
        "section_summaries": [],
        "review_feedback": "",
        "used_rag_queries": ["q1"],
        "rag_collection_name": "dynamic_context_test",
        "rag_source_audit": rag_source_audit or {},
        "rag_retrieval_attempts": 1,
        "rag_best_effort_context": "",
        "rag_best_effort_audit": {},
        "rag_best_effort_score": 0.0,
        "advanced_config": advanced_config or {},
    }


def test_evaluator_skips_llm_when_balanced_cost_context_is_strong(monkeypatch) -> None:
    from app.services.textbook import evaluator

    def fail_if_instantiated(*args, **kwargs):
        raise AssertionError("EvaluatorAgent should not be instantiated")

    monkeypatch.setattr(evaluator, "EvaluatorAgent", fail_if_instantiated)
    context = "x" * (evaluator.settings.CRAG_CONTEXT_QUALITY_MIN_CHARS + 100)
    state = _minimal_state(
        advanced_config={"API_COST_PROFILE": "balanced_cost"},
        rag_context=context,
        rag_source_audit={
            "valid_chunks": 3,
            "total_chunks": 3,
            "unique_sources": 2,
            "sources": [
                {"url": "https://a.example", "avg_score": 0.7},
                {"url": "https://b.example", "avg_score": 0.6},
            ],
        },
    )

    result = evaluator.evaluate_context(state)

    assert result["context_quality"] == "sufficient"
    assert "skipped LLM" in result["messages"][0]


def test_evaluator_calls_llm_when_context_is_missing(monkeypatch) -> None:
    from app.services.textbook import evaluator

    calls = {"count": 0}

    class FakeEvaluator:
        def __init__(self, advanced_config=None):
            self.advanced_config = advanced_config

        def enrich_context(self, **kwargs):
            calls["count"] += 1
            return (
                "Document 1 (Source: https://a.example | Score: 0.700):\n"
                + ("A" * 4000)
            ), ["q2"]

    monkeypatch.setattr(evaluator, "EvaluatorAgent", FakeEvaluator)
    monkeypatch.setattr(
        evaluator,
        "build_source_audit_summary",
        lambda *args, **kwargs: {
            "valid_chunks": 2,
            "total_chunks": 2,
            "unique_sources": 2,
            "sources": [
                {"url": "https://a.example", "avg_score": 0.7},
                {"url": "https://b.example", "avg_score": 0.6},
            ],
            "warnings": [],
        },
    )

    result = evaluator.evaluate_context(
        _minimal_state(advanced_config={"API_COST_PROFILE": "balanced_cost"})
    )

    assert calls["count"] == 1
    assert result["context_quality"] == "sufficient"
    assert result["used_rag_queries"] == ["q1", "q2"]


def test_orchestrator_continues_with_best_effort_after_retry_budget() -> None:
    from app.services.textbook.orchestrator import (
        WorkflowDecision,
        route_after_context_evaluation,
    )

    decision = route_after_context_evaluation(
        {
            "context_quality": "insufficient",
            "rag_retrieval_attempts": 4,
            "used_rag_queries": ["q1", "q2"],
            "rag_recovery_attempted": True,
            "rag_best_effort_context": "Document 1 (Source: https://a.edu): useful context",
        }
    )

    assert decision == WorkflowDecision.CONTINUE_SUBSECTION


def test_ingestion_reuses_query_expansion_in_balanced_cost(monkeypatch) -> None:
    from app.services.textbook import ingester

    calls = {"expand": 0, "ingest_received_reuse": False}

    class FakeQueryExpansionAgent:
        def expand_query_bilingual(self, topic, content_type="technical"):
            calls["expand"] += 1
            return {"vi": ["vi query"], "en": ["en query"]}

    monkeypatch.setattr(ingester, "QueryExpansionAgent", lambda: FakeQueryExpansionAgent())
    monkeypatch.setattr(
        ingester,
        "search_web",
        lambda query, max_results, region, min_snippet_score=0.3: [
            {"href": f"https://example.com/{region}", "title": "ok", "body": "ok"}
        ],
    )
    monkeypatch.setattr(
        ingester,
        "filter_and_classify_urls",
        lambda *args, **kwargs: [{"url": "https://example.com", "type": "html"}],
    )

    def fake_ingest_dynamic_data(*args, **kwargs):
        calls["ingest_received_reuse"] = kwargs.get("query_expansion") == {
            "vi": ["vi query"],
            "en": ["en query"],
        }
        return True

    monkeypatch.setattr(ingester, "ingest_dynamic_data", fake_ingest_dynamic_data)

    result = ingester.perform_ingestion(
        {
            "request": "AI",
            "core_topic": "AI",
            "content_type": "technical",
            "rag_collection_name": "dynamic_context_test",
            "advanced_config": {"API_COST_PROFILE": "balanced_cost"},
        }
    )

    assert calls["expand"] == 1
    assert calls["ingest_received_reuse"] is True
    assert result["messages"][0].startswith("✓ Ingestion complete")


def _reviewer_state(*, advanced_config=None, content="", source_audit=None, enable_images=True):
    from app.schemas.curriculum import Chapter, CurriculumOutline, SubSection

    return {
        "curriculum": CurriculumOutline(
            topic="AI",
            chapters=[
                Chapter(
                    title="Intro",
                    subsections=[
                        SubSection(
                            title="Basics",
                            description="AI basics",
                            search_query="artificial intelligence basics",
                            section_type="medium",
                        )
                    ],
                )
            ],
        ),
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "current_content": content or "## 1.1 Basics\n\nDraft content.",
        "chapter_header_written": False,
        "content_level": "Ngắn",
        "min_chars_per_section": 0,
        "rag_source_audit": source_audit or {},
        "advanced_config": advanced_config or {},
        "enable_images": enable_images,
        "revision_number": 0,
    }


def _balanced_config(**extra):
    return {"API_COST_PROFILE": "balanced_cost", **extra}


def test_reviewer_skips_polish_when_source_audit_insufficient(monkeypatch) -> None:
    from app.services.textbook import reviewer

    def fail_if_instantiated(*args, **kwargs):
        raise AssertionError("ReviewerAgent should not be instantiated")

    monkeypatch.setattr(reviewer, "ReviewerAgent", fail_if_instantiated)
    result = reviewer.review_section(
        _reviewer_state(
            advanced_config=_balanced_config(),
            content="## 1.1 Basics\n\nDraft content.",
            source_audit={"context_quality": "insufficient"},
        )
    )

    assert result["current_content"].startswith("## 1.1 Basics")
    assert result["rejection_type"] == "missing_context"
    assert result["review_feedback"]


def test_reviewer_image_disabled_prompt_and_postprocess(monkeypatch) -> None:
    from app.services.textbook import reviewer

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    class FakePrompt:
        def __or__(self, other):
            return "fake-chain"

    def fake_rate_limited_invoke(chain, payload, **kwargs):
        captured["visual_criterion"] = payload["visual_criterion"]
        return SimpleNamespace(
            content=payload["draft"] + "\n\n> [IMAGE: Bad | should be removed]"
        )

    monkeypatch.setattr(reviewer, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        reviewer.ChatPromptTemplate,
        "from_messages",
        lambda messages: FakePrompt(),
    )
    monkeypatch.setattr(reviewer, "rate_limited_invoke", fake_rate_limited_invoke)

    agent = reviewer.ReviewerAgent()
    output = agent._content_pass(
        draft="## 1.1 Basics\n\n" + ("Academic paragraph. " * 30),
        course_topic="AI",
        chapter_num="1",
        chapter_title="Intro",
        section_num="1.1",
        section_title="Basics",
        section_description="AI basics",
        enable_images=False,
    )

    assert "ADD new image suggestions" not in captured["visual_criterion"]
    assert "[IMAGE:" not in output


def test_balanced_formatting_reject_self_repairs_without_writer(monkeypatch) -> None:
    from app.services.textbook import reviewer

    class FakeReviewerAgent:
        def review_content(self, **kwargs):
            return "## 1.1 Basics\nText without blank line after heading."

        def should_revise(self, *args, **kwargs):
            return True, "Heading format and blank line violation."

        def _format_pass(self, draft, section_num, section_title, chapter_cmd, language="vi"):
            return "## 1.1 Basics\n\n" + ("Fixed academic paragraph. " * 80)

        def _fix_heading_levels(self, content, section_num, section_title):
            return content

    monkeypatch.setattr(reviewer, "ReviewerAgent", FakeReviewerAgent)
    result = reviewer.review_section(
        _reviewer_state(
            advanced_config=_balanced_config(),
            content="## 1.1 Basics\nBad draft.",
        )
    )

    assert result["review_feedback"] == ""
    assert result["rejection_type"] is None
    assert "self-repair" in result["messages"][0]


def test_balanced_deterministic_gate_skips_llm(monkeypatch) -> None:
    from app.services.textbook import reviewer

    paragraph = (
        "Artificial intelligence basics are explained through definitions, examples, "
        "and careful academic analysis that supports learners across the section. "
    )
    good_content = (
        "## 1.1 Basics\n\n"
        "### 1.1.1 Foundations\n\n"
        f"{paragraph * 4}\n\n"
        f"{paragraph * 4}\n\n"
        "### 1.1.2 Applications\n\n"
        f"{paragraph * 4}\n\n"
        f"{paragraph * 4}"
    )

    class FakeReviewerAgent:
        def review_content(self, **kwargs):
            return good_content

        def should_revise(self, *args, **kwargs):
            raise AssertionError("LLM quality gate should be skipped")

    monkeypatch.setattr(reviewer, "ReviewerAgent", FakeReviewerAgent)
    result = reviewer.review_section(
        _reviewer_state(
            advanced_config=_balanced_config(),
            content=good_content,
        )
    )

    assert result["review_feedback"] == ""
    assert "deterministic balanced gate" in result["messages"][0]


def test_reviewer_does_not_reject_over_target_length() -> None:
    from app.services.textbook import reviewer

    paragraph = (
        "Artificial intelligence basics are explained through definitions, examples, "
        "and careful academic analysis that supports learners across the section. "
    )
    long_content = (
        "## 1.1 Basics\n\n"
        "### 1.1.1 Foundations\n\n"
        f"{paragraph * 12}\n\n"
        f"{paragraph * 12}"
    )

    assert reviewer.deterministic_quality_gate_passes(
        long_content,
        char_min=300,
        char_max=500,
        section_num="1.1",
        section_title="Basics",
        section_type="medium",
        language="en",
    ) is True

    agent = reviewer.ReviewerAgent.__new__(reviewer.ReviewerAgent)
    needs_revision, feedback = agent.should_revise(
        long_content,
        char_min=300,
        char_max=500,
        language="en",
    )

    assert needs_revision is False
    assert feedback == ""


class _FakeVectorDb:
    def __init__(self, docs):
        self.docs = docs
        self._embedding_function = None

    def max_marginal_relevance_search(self, *args, **kwargs):
        return self.docs


def _fake_retriever_with_docs(docs):
    from app.services.textbook.retriever import Retriever

    retriever = Retriever.__new__(Retriever)
    retriever.collection_name = "test"
    retriever.vector_db = _FakeVectorDb(docs)
    retriever._retrieved_ids = set()
    retriever.last_retrieval_audit = {}
    return retriever


def _doc(text, source="https://example.com/page", relevance="0.45"):
    return SimpleNamespace(
        page_content=text,
        metadata={"source": source, "relevance_score": relevance, "language": "en"},
    )


def test_retriever_filter_mode_off_skips_llm_classifier(monkeypatch) -> None:
    from app.services.textbook import retriever as retriever_module

    def fail_classifier(*args, **kwargs):
        raise AssertionError("LLM classifier should be skipped")

    monkeypatch.setattr(retriever_module, "_llm_classify_chunk", fail_classifier)
    doc = _doc(
        "Artificial intelligence basics explain how artificial systems learn. "
        "Artificial intelligence examples show definitions, steps, and practical because patterns.",
        relevance="0.70",
    )
    retriever = _fake_retriever_with_docs([doc])

    context = retriever.retrieve_context(
        query="artificial intelligence basics",
        k=1,
        advanced_config=_balanced_config(RAG_CHUNK_LLM_FILTER_MODE="off"),
    )

    assert "Document 1" in context
    assert retriever.last_retrieval_audit["llm_classifier_calls"] == 0


def test_retriever_auto_calls_classifier_for_borderline_chunks(monkeypatch) -> None:
    from app.services.textbook import retriever as retriever_module

    calls = {"count": 0}

    def fake_classifier(*args, **kwargs):
        calls["count"] += 1
        return True

    monkeypatch.setattr(retriever_module, "_llm_classify_chunk", fake_classifier)
    doc = _doc(
        "Artificial intelligence appears in a general overview. "
        "This educational passage has definitions and examples because learners need context.",
        relevance="0.45",
    )
    retriever = _fake_retriever_with_docs([doc])

    context = retriever.retrieve_context(
        query="artificial intelligence basics applications systems",
        k=1,
        advanced_config=_balanced_config(),
    )

    assert "Document 1" in context
    assert calls["count"] == 1
    assert retriever.last_retrieval_audit["llm_classifier_calls"] == 1
