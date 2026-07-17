import inspect

from app.services.textbook import reviewer as reviewer_module
from app.services.textbook import writer as writer_module
from app.services.textbook.illustrator import (
    ImageCandidate,
    IllustratorAgent,
    _image_plan_cap,
    illustrate_section,
)


class _DummyPromptLogger:
    def log(self, **kwargs):
        return None


class _FakeResponse:
    content = (
        '[{"paragraph": 1, "title": "Sơ đồ quy trình", '
        '"description": "A university textbook workflow visual showing image input data moving through preprocessing, feature extraction, model decision, and reviewed output as distinct connected objects. The composition uses a clean left to right viewpoint with arrows and simple visual blocks, without visible text, labels, or numbers.", '
        '"visual_type": "workflow", '
        '"why_here": "The paragraph explains connected process stages.", '
        '"avoid_duplicates_key": "image processing workflow stages"}]'
    )


class _FakeLLM:
    def invoke(self, _input):
        return _FakeResponse()


def test_writer_prompt_no_longer_contains_image_rules(monkeypatch) -> None:
    captured = {}

    def fake_rate_limited_invoke(_llm, messages, **_kwargs):
        captured["system_prompt"] = messages[0].content
        return type("Response", (), {"content": "## 1.1 Title\n\nContent"})()

    writer = writer_module.ContentWriter.__new__(writer_module.ContentWriter)
    writer._llm = object()
    writer._prompt_logger = _DummyPromptLogger()
    monkeypatch.setattr(writer_module, "rate_limited_invoke", fake_rate_limited_invoke)

    writer.generate(
        course_topic="Python",
        chapter_num=1,
        chapter_title="Basics",
        section_num="1.1",
        section_title="Title",
        section_description="Description",
        enriched_context="Context",
        chapter_instruction="Your very first line MUST be: ## 1.1 Title",
        section_type="medium",
        char_target=(1200, 1800),
        content_level="Trung Bình",
        enable_images=True,
        review_feedback="",
        section_summaries=[],
        language="vi",
        target_pages=2,
        layout_profile="technical",
        formula_density="contextual",
        expansion_strategy="models_metrics_examples",
    )

    system_prompt = captured["system_prompt"]
    assert "IMAGE_NEEDED" not in system_prompt
    assert "Insert image" not in system_prompt
    assert "PAGE-BUDGET EXPANSION STRATEGY" in system_prompt
    assert system_prompt.count("structured-tool") <= 1


def test_reviewer_content_pass_no_longer_adds_image_suggestions() -> None:
    source = inspect.getsource(reviewer_module.ReviewerAgent._content_pass)

    assert "ADD new image suggestions" not in source
    assert "PRESERVE all existing > [IMAGE" not in source
    assert "visual_criterion" not in source


def test_illustrator_balanced_image_caps() -> None:
    assert _image_plan_cap("medium", 1, None) == 1
    assert _image_plan_cap("deep", 2, None) == 1
    assert _image_plan_cap("deep", 8, None) == 3
    assert _image_plan_cap("applied", 8, None) == 2
    assert _image_plan_cap("medium", 8, "code") == 1
    assert _image_plan_cap("medium", 8, "formula") == 1


def test_illustrator_plans_tags_without_rewriting_section() -> None:
    agent = IllustratorAgent.__new__(IllustratorAgent)
    agent.llm = _FakeLLM()
    agent.prompt_logger = _DummyPromptLogger()

    content = (
        "## 1.1 Quy trình phát triển\n\n"
        "Quy trình phát triển phần mềm gồm nhiều bước liên kết với nhau, từ phân tích "
        "yêu cầu, thiết kế, lập trình, kiểm thử đến triển khai. Mỗi bước tạo ra một "
        "kết quả trung gian và ảnh hưởng trực tiếp đến chất lượng của bước tiếp theo, "
        "vì vậy người học cần nhìn thấy dòng chảy tổng thể của hệ thống trước khi đi "
        "vào từng kỹ thuật cụ thể.\n\n"
        "Đoạn cuối giữ nguyên để kiểm tra rằng planner không viết lại nội dung."
    )

    planned = agent.plan_image_tags(
        content,
        section_type="medium",
        language="vi",
        target_pages=4,
        layout_profile="technical",
    )

    assert "Đoạn cuối giữ nguyên" in planned
    assert planned.count("> [IMAGE:") == 1
    assert "Sơ đồ quy trình" in planned


def test_illustrator_rejects_duplicate_planned_visuals() -> None:
    class DuplicateLLM:
        def invoke(self, _input):
            return type("Response", (), {"content": (
                '['
                '{"paragraph": 1, "title": "Sơ đồ quy trình", '
                '"description": "A university textbook workflow visual showing source image data moving through preprocessing, transformation, comparison, and output review as connected visual objects. The composition uses a clean left to right viewpoint with arrows and concrete processing blocks, without visible text, labels, or numbers.", '
                '"visual_type": "workflow", "why_here": "The paragraph describes a process.", '
                '"avoid_duplicates_key": "processing workflow"},'
                '{"paragraph": 2, "title": "Sơ đồ quy trình", '
                '"description": "A university textbook workflow visual showing source image data moving through preprocessing, transformation, comparison, and output review as connected visual objects. The composition uses a clean left to right viewpoint with arrows and concrete processing blocks, without visible text, labels, or numbers.", '
                '"visual_type": "workflow", "why_here": "The paragraph describes another process.", '
                '"avoid_duplicates_key": "processing workflow"}'
                ']'
            )})()

    agent = IllustratorAgent.__new__(IllustratorAgent)
    agent.llm = DuplicateLLM()
    agent.prompt_logger = _DummyPromptLogger()
    paragraph = (
        "Quy trình xử lý ảnh trong học phần này gồm dữ liệu ảnh đầu vào, bước tiền "
        "xử lý, thao tác biến đổi, bước đánh giá và kết quả đầu ra. Các bước có "
        "quan hệ nối tiếp nên người học cần hình dung dòng chảy xử lý trước khi "
        "đọc từng thuật toán cụ thể trong phần sau."
    )
    content = f"## 1.1 Quy trình\n\n{paragraph}\n\n{paragraph}"

    planned = agent.plan_image_tags(content, section_type="medium", language="vi", target_pages=4)

    assert planned.count("> [IMAGE:") == 1


def test_illustrator_disabled_strips_all_image_marker_variants() -> None:
    result = illustrate_section(
        {
            "current_content": (
                "## 1.1 Title\n\n"
                "> [IMAGE: Title | Description]\n\n"
                "> [IMAGE SUGGESTION: Old description]\n\n"
                "> [IMAGE_NEEDED: Old hint]\n\n"
                "Body."
            ),
            "enable_images": False,
        }
    )

    assert "IMAGE:" not in result["current_content"]
    assert "IMAGE SUGGESTION" not in result["current_content"]
    assert "IMAGE_NEEDED" not in result["current_content"]
    assert "Body." in result["current_content"]


def test_illustrator_validation_exception_fails_closed(monkeypatch) -> None:
    agent = IllustratorAgent.__new__(IllustratorAgent)
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")))

    assert agent._validate_image_relevance("missing.png", "A specific visual description") is False


def test_illustrator_search_does_not_use_unvalidated_last_download(monkeypatch) -> None:
    agent = IllustratorAgent.__new__(IllustratorAgent)
    agent.llm = None
    agent.route_image_request = lambda _description: "SEARCH"
    agent.find_serper_image_candidates = lambda _description: [
        ImageCandidate(url="https://example.edu/a.png", source="serper"),
        ImageCandidate(url="https://example.edu/b.png", source="serper"),
        ImageCandidate(url="https://example.edu/c.png", source="serper"),
    ]
    agent.generate_image_openai = lambda *_args, **_kwargs: ""
    agent.find_wikimedia_image_candidates = lambda _description: []
    agent._validate_image_relevance = lambda *_args, **_kwargs: False
    monkeypatch.setattr(
        "app.services.textbook.illustrator.download_and_convert_image",
        lambda url, _output_dir: f"D:/Thesis/curriculum_rag/backend/outputs/images/{url.rsplit('/', 1)[-1]}",
    )

    result = agent.illustrate_content(
        "## 1.1 Title\n\n> [IMAGE: Sơ đồ kiểm thử | A university textbook workflow visual showing source image data moving through preprocessing and output review as connected concrete objects. The composition uses a left to right viewpoint with arrows and visual blocks, without visible text, labels, or numbers.]\n\nBody.",
        section_type="medium",
        language="vi",
    )

    assert "![Sơ đồ kiểm thử]" not in result
    assert "[IMAGE:" not in result
    assert "Body." in result


def test_illustrator_semantic_validation_uses_caption_and_source_excerpt(monkeypatch) -> None:
    agent = IllustratorAgent.__new__(IllustratorAgent)
    agent.llm = None
    agent._image_plan_metadata = {
        "> [IMAGE: Tham số dòng điện | A university textbook waveform visual showing sinusoidal current amplitude and cycle relationships as connected visual elements without visible text.]": {
            "caption": "Tham số dòng điện",
            "description": "A university textbook waveform visual showing sinusoidal current amplitude and cycle relationships as connected visual elements without visible text.",
            "source_excerpt": "Đoạn nguồn nói về tham số dòng điện xoay chiều, biên độ, chu kỳ và pha.",
            "visual_type": "diagram",
        }
    }
    agent.route_image_request = lambda _description: "SEARCH"
    agent.find_serper_image_candidates = lambda _description: [
        ImageCandidate(url="https://example.edu/wave.png", source="serper"),
    ]
    agent.generate_image_openai = lambda *_args, **_kwargs: ""
    agent.find_wikimedia_image_candidates = lambda _description: []
    captured = {}

    def fake_validate(_path, description, caption="", source_excerpt=""):
        captured["description"] = description
        captured["caption"] = caption
        captured["source_excerpt"] = source_excerpt
        return False

    agent._validate_image_relevance = fake_validate
    monkeypatch.setattr(
        "app.services.textbook.illustrator.download_and_convert_image",
        lambda _url, _output_dir: "D:/Thesis/curriculum_rag/backend/outputs/images/wave.png",
    )

    result = agent.illustrate_content(
        "## 2.1 Sóng\n\n"
        "> [IMAGE: Tham số dòng điện | A university textbook waveform visual showing sinusoidal current amplitude and cycle relationships as connected visual elements without visible text.]\n\n"
        "Body.",
        section_type="medium",
        language="vi",
    )

    assert captured["caption"] == "Tham số dòng điện"
    assert "tham số dòng điện xoay chiều" in captured["source_excerpt"]
    assert "Visual type: diagram" in captured["description"]
    assert "[IMAGE:" not in result
    assert "Body." in result


def test_illustrator_draw_retry_passes_semantic_validation() -> None:
    agent = IllustratorAgent.__new__(IllustratorAgent)
    agent.llm = None
    agent._image_plan_metadata = {}
    agent.route_image_request = lambda _description: "DRAW"
    generated = [
        "D:/Thesis/curriculum_rag/backend/outputs/images/first.png",
        "D:/Thesis/curriculum_rag/backend/outputs/images/retry.png",
    ]
    validations = [False, True]
    retry_args = []

    def fake_generate(*_args, **kwargs):
        retry_args.append(kwargs)
        return generated.pop(0)

    agent.generate_image_openai = fake_generate
    agent._validate_image_relevance = lambda *_args, **_kwargs: validations.pop(0)
    agent.translate_caption = lambda caption, language="vi": caption

    result = agent.illustrate_content(
        "## 1.1 Title\n\n"
        "> [IMAGE: Sơ đồ mạch | A university textbook circuit visual showing a battery, resistor, lamp, and current path as connected concrete electrical components. The composition uses a clean circuit viewpoint without visible text, labels, or numbers.]\n\n"
        "Body.",
        section_type="medium",
        language="vi",
    )

    assert "![Sơ đồ mạch](outputs/images/retry.png){width=70%}" in result
    assert retry_args[1]["validation_feedback"]


def test_illustrator_draw_fail_then_search_fail_strips_tag() -> None:
    agent = IllustratorAgent.__new__(IllustratorAgent)
    agent.llm = None
    agent.route_image_request = lambda _description: "DRAW"
    generated = []

    def fake_generate(*_args, **_kwargs):
        generated.append("called")
        return "D:/Thesis/curriculum_rag/backend/outputs/images/generated.png"

    agent.generate_image_openai = fake_generate
    agent.find_serper_image_candidates = lambda _description: []
    agent.find_wikimedia_image_candidates = lambda _description: []
    agent._validate_image_relevance = lambda *_args, **_kwargs: False

    result = agent.illustrate_content(
        "## 1.1 Title\n\n> [IMAGE: Hình kiểm thử | A university textbook workflow visual showing input records, validation steps, fallback decision points, and output review as connected concrete objects. The composition uses a left to right viewpoint with arrows and visual blocks, without visible text, labels, or numbers.]\n\nBody.",
        section_type="medium",
        language="vi",
    )

    assert len(generated) >= 2
    assert "[IMAGE:" not in result
    assert "Body." in result
