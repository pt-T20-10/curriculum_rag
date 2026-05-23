"""
Parameter registry for the Advanced Settings system.

Defines every tunable parameter exposed to users and/or admins via the UI.
config.py remains the static fallback; this registry drives the DB layer on top of it.

Each entry carries:
  label          — human-readable name shown in the UI
  description    — short tooltip text (1 sentence)
  group          — grouping key for the UI accordion sections
  type           — "int" | "float" | "str" | "bool"
  default        — value that matches config.py default (used as UI placeholder)
  user_editable  — whether regular users may override this parameter
  admin_only     — if True, only admins can read/write; never returned to users
  sensitive      — if True, value is masked in GET responses ("sk-••••••••")
  min / max      — optional bounds for numeric types (validation)
  choices        — optional list of valid string values (renders as dropdown)
"""

from typing import Any, Dict, Optional

ParameterDef = Dict[str, Any]

PARAMETER_REGISTRY: Dict[str, ParameterDef] = {

    # =========================================================================
    # GROUP: rag — RAG & Tìm Kiếm
    # =========================================================================
    "RAG_INITIAL_K": {
        "label": "K Lấy Kết Quả Ban Đầu",
        "description": "Số chunk được lấy trong lần RAG đầu tiên trước khi làm giàu thêm ngữ cảnh.",
        "group": "rag",
        "type": "int",
        "default": 5,
        "min": 1,
        "max": 20,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "RAG_TOOL_K": {
        "label": "K Lấy Kết Quả Theo Tool",
        "description": "Số chunk được lấy mỗi vòng tool-call trong quá trình làm giàu nội dung của writer.",
        "group": "rag",
        "type": "int",
        "default": 5,
        "min": 1,
        "max": 20,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "RAG_TOOL_MAX_ROUNDS": {
        "label": "Số Vòng Làm Giàu Tối Đa",
        "description": "Số vòng tool-call tối đa writer có thể dùng để bổ sung ngữ cảnh; tăng cao làm chậm tốc độ tạo.",
        "group": "rag",
        "type": "int",
        "default": 4,
        "min": 0,
        "max": 10,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "CRAG_CONTEXT_QUALITY_MIN_CHARS": {
        "label": "Ngưỡng Chất Lượng Ngữ Cảnh (ký tự)",
        "description": "Tổng số ký tự RAG tối thiểu cần đạt trước khi bắt đầu viết; dưới ngưỡng này sẽ thử lại.",
        "group": "rag",
        "type": "int",
        "default": 3000,
        "min": 500,
        "max": 10000,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "CRAG_MAX_CONTEXT_RETRIES": {
        "label": "Số Lần Thử Lại Ngữ Cảnh Tối Đa",
        "description": "Số lần tối đa query reformulator thử lại trước khi writer tiếp tục với ngữ cảnh hiện có.",
        "group": "rag",
        "type": "int",
        "default": 2,
        "min": 0,
        "max": 5,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "MIN_RELEVANCE_SCORE": {
        "label": "Điểm Liên Quan Tối Thiểu",
        "description": "Ngưỡng lọc ChromaDB sau khi tìm kiếm; các chunk dưới điểm này bị loại bỏ.",
        "group": "rag",
        "type": "float",
        "default": 0.22,
        "min": 0.0,
        "max": 1.0,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "RAG_TRUSTED_DOMAIN_QUOTA": {
        "label": "Hạn Mức Domain Tin Cậy",
        "description": "Số chunk tối đa được lấy từ một domain tin cậy như Wikipedia hay arXiv.",
        "group": "rag",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 20,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "RAG_DEFAULT_DOMAIN_QUOTA": {
        "label": "Hạn Mức Domain Thông Thường",
        "description": "Số chunk tối đa từ một domain không tin cậy; tránh thiên lệch từ một nguồn duy nhất.",
        "group": "rag",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 10,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "RAG_SEMANTIC_DEDUP_THRESHOLD": {
        "label": "Ngưỡng Khử Trùng Ngữ Nghĩa",
        "description": "Ngưỡng cosine similarity để khử trùng; giá trị thấp hơn loại nhiều chunk hơn.",
        "group": "rag",
        "type": "float",
        "default": 0.85,
        "min": 0.5,
        "max": 1.0,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },

    # =========================================================================
    # GROUP: generation — Tạo Nội Dung
    # =========================================================================
    "LLM_MODEL_CHEAP": {
        "label": "Model Phụ Trợ",
        "description": "Model LLM dùng cho reviewer, illustrator và các agent phụ trợ; ảnh hưởng tốc độ và chi phí.",
        "group": "generation",
        "type": "str",
        "default": "gpt-4o-mini",
        "choices": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "LLM_MODEL_PREMIUM": {
        "label": "Model Chính",
        "description": "Model LLM dùng cho planner và content writer; quyết định chất lượng đầu ra chính.",
        "group": "generation",
        "type": "str",
        "default": "gpt-4.1",
        "choices": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "REVIEWER_MAX_REVISIONS": {
        "label": "Số Lần Chỉnh Sửa Tối Đa",
        "description": "Số vòng reviewer→writer tối đa mỗi mục trước khi buộc chấp nhận; 0 tắt hoàn toàn bước kiểm duyệt.",
        "group": "generation",
        "type": "int",
        "default": 2,
        "min": 0,
        "max": 5,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "WRITER_RETRIEVAL_MAX_ROUNDS": {
        "label": "Số Vòng Lấy Dữ Liệu của Writer",
        "description": "Số vòng tool-call tối đa ContextRetrievalAgent có thể dùng để bổ sung ngữ cảnh khi viết.",
        "group": "generation",
        "type": "int",
        "default": 3,
        "min": 0,
        "max": 8,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "WRITER_MAX_PRIOR_SUMMARIES": {
        "label": "Số Tóm Tắt Trước Đưa Vào Prompt",
        "description": "Số tóm tắt mục trước tối đa được đưa vào prompt của writer; tăng cao có thể vượt ngân sách token.",
        "group": "generation",
        "type": "int",
        "default": 6,
        "min": 0,
        "max": 15,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },

    # =========================================================================
    # GROUP: ingestion — Thu Thập & Phân Đoạn
    # =========================================================================
    "CHUNK_SIZE": {
        "label": "Kích Thước Chunk (ký tự)",
        "description": "Độ dài mỗi chunk văn bản trước khi embedding; thay đổi ảnh hưởng đến toàn bộ chất lượng RAG.",
        "group": "ingestion",
        "type": "int",
        "default": 1500,
        "min": 300,
        "max": 5000,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "CHUNK_OVERLAP": {
        "label": "Độ Chồng Lấp Chunk (ký tự)",
        "description": "Số ký tự chồng lấp giữa các chunk liên tiếp để bảo toàn ngữ cảnh tại vùng biên.",
        "group": "ingestion",
        "type": "int",
        "default": 300,
        "min": 0,
        "max": 2000,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "SEARCH_RESULTS_PER_QUERY": {
        "label": "Kết Quả Tìm Kiếm Mỗi Query",
        "description": "Số URL được lấy từ search engine cho mỗi query trong quá trình thu thập dữ liệu.",
        "group": "ingestion",
        "type": "int",
        "default": 30,
        "min": 5,
        "max": 100,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "MAX_CHUNKS_TO_EMBED": {
        "label": "Số Chunk Tối Đa Để Embedding",
        "description": "Giới hạn tổng số chunk được xử lý mỗi lần thu thập; bộ lọc heuristic sẽ giảm số này trước khi embedding.",
        "group": "ingestion",
        "type": "int",
        "default": 1000,
        "min": 100,
        "max": 5000,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },
    "MIN_SNIPPET_SCORE": {
        "label": "Điểm Snippet Tối Thiểu",
        "description": "Ngưỡng chất lượng snippet URL khi thu thập dữ liệu; URL dưới ngưỡng này bị bỏ qua.",
        "group": "ingestion",
        "type": "float",
        "default": 0.3,
        "min": 0.0,
        "max": 1.0,
        "user_editable": True,
        "admin_only": False,
        "sensitive": False,
    },

    # =========================================================================
    # GROUP: domain_caps — Giới Hạn Domain (chỉ admin)
    # =========================================================================
    "MAX_CHUNKS_PER_DOMAIN": {
        "label": "Giới Hạn Domain Cơ Bản",
        "description": "Số chunk tối đa mỗi domain khi không có giới hạn theo ngôn ngữ nào được áp dụng.",
        "group": "domain_caps",
        "type": "int",
        "default": 25,
        "min": 1,
        "max": 200,
        "user_editable": False,
        "admin_only": True,
        "sensitive": False,
    },
    "VI_DOMAIN_CAP": {
        "label": "Giới Hạn Domain Tiếng Việt",
        "description": "Số chunk tối đa mỗi domain cho nội dung tiếng Việt; cao hơn tiếng Anh vì nguồn tiếng Việt khan hiếm hơn.",
        "group": "domain_caps",
        "type": "int",
        "default": 80,
        "min": 10,
        "max": 500,
        "user_editable": False,
        "admin_only": True,
        "sensitive": False,
    },
    "EN_DOMAIN_CAP": {
        "label": "Giới Hạn Domain Tiếng Anh",
        "description": "Số chunk tối đa mỗi domain cho nội dung tiếng Anh.",
        "group": "domain_caps",
        "type": "int",
        "default": 35,
        "min": 5,
        "max": 300,
        "user_editable": False,
        "admin_only": True,
        "sensitive": False,
    },
}

# -------------------------------------------------------------------------
# Group metadata — labels and ordering for UI accordions
# -------------------------------------------------------------------------
PARAMETER_GROUPS: Dict[str, Dict[str, str]] = {
    "rag": {
        "label": "RAG & Tìm Kiếm",
        "description": "Kiểm soát cách tài liệu được tìm kiếm và lọc từ cơ sở tri thức.",
    },
    "generation": {
        "label": "Tạo Nội Dung",
        "description": "Kiểm soát model LLM, số vòng chỉnh sửa và hành vi của writer.",
    },
    "ingestion": {
        "label": "Thu Thập & Phân Đoạn",
        "description": "Kiểm soát cách nội dung web được thu thập, phân đoạn và lập chỉ mục.",
    },
    "domain_caps": {
        "label": "Giới Hạn Domain",
        "description": "Giới hạn số chunk tối đa từ một domain duy nhất theo từng ngôn ngữ.",
    },
}


def get_user_registry() -> Dict[str, ParameterDef]:
    """Return only parameters that users are allowed to edit."""
    return {k: v for k, v in PARAMETER_REGISTRY.items() if v["user_editable"]}


def get_admin_registry() -> Dict[str, ParameterDef]:
    """Return all parameters (users + admin-only) for the admin panel."""
    return PARAMETER_REGISTRY


def get_defaults() -> Dict[str, Any]:
    """Return a flat dict of {param_key: default_value} for all parameters."""
    return {k: v["default"] for k, v in PARAMETER_REGISTRY.items()}
