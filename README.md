# Curriculum RAG - AI Textbook Generator

Hệ thống web tạo giáo trình tiếng Việt từ một chủ đề đầu vào. Sản phẩm hiện tại gồm frontend React, backend FastAPI, hàng đợi Celery/Redis, MySQL, và một workflow LangGraph nhiều tác nhân để lập dàn ý, cho người dùng duyệt curriculum, crawl dữ liệu song ngữ, sinh nội dung theo CRAG, kiểm duyệt, minh họa và xuất PDF/Word.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-teal)
![LangGraph](https://img.shields.io/badge/Workflow-LangGraph-orange)
![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-purple)
![Frontend](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61dafb)

## System Architecture

```text
React/Vite UI
  |
  |  /api/v1
  v
FastAPI backend
  |-- Auth: local login, Google OAuth, JWT, password reset
  |-- Textbooks: create, progress polling, confirm curriculum, stop
  |-- Plans/payments/admin/config APIs
  |
  |-- MySQL: users, textbooks, plans, transactions, config overrides
  |-- Redis: Celery broker/result backend, task registry, stop signals
  |
  v
Celery worker
  |
  |-- Phase 1 task: generate_textbook
  |     planner -> curriculum_json -> review gate in UI
  |
  |-- Phase 2 task: continue_textbook_generation
        generate_metadata -> ingestion -> CRAG section loop -> publisher
```

LangGraph được tách thành hai workflow chính:

```text
Phase 1 - Planning only

planner -> END

Output:
  - curriculum_json
  - progress phase = reviewing
  - user edits/confirms curriculum in the UI
```

```text
Phase 2 - After curriculum confirmation

generate_preface
  -> ingestion
  -> [ingestion gate]
  -> query_formulator
  -> retriever_node
  -> context_evaluator
  -> content_writer
  -> reviewer
       |-- approve -> illustrator
       |-- formatting_error -> content_writer
       |-- missing_context -> query_formulator
  -> illustrator
  -> check_next_step
       |-- update_subsection -> query_formulator
       |-- update_chapter    -> query_formulator
       |-- finished          -> publisher -> END
```

## End-to-End Workflow

1. Người dùng tạo textbook từ UI hoặc `POST /api/v1/textbooks`.
2. Backend validate topic bằng `ValidatorAgent` trước khi trừ credit. Topic hợp lệ sẽ được tách thành `content_type`, `core_topic`, và `user_requirements`.
3. Backend tạo record `textbooks`, trừ 1 credit, rồi đẩy Celery task `generate_textbook`.
4. Phase 1 chỉ chạy planner. Planner sinh chapter titles và subsections từ LLM, không crawl web ở bước này.
5. Frontend hiển thị curriculum để người dùng sửa/xóa/thêm chapter và subsection.
6. Khi người dùng xác nhận, `POST /api/v1/textbooks/{id}/confirm-curriculum` đẩy task `continue_textbook_generation`.
7. Phase 2 sinh tiêu đề thật và lời nói đầu, crawl dữ liệu, populate ChromaDB, rồi lặp qua từng subsection để sinh nội dung.
8. Publisher ghép toàn bộ nội dung, chạy các pass sửa Markdown/math/heading, rồi export `.md`, `.pdf`, `.docx` vào `backend/outputs`.

## Core Agents

| Agent / module | File | Vai trò hiện tại |
|---|---|---|
| Validator | `backend/app/services/textbook/validator.py` | Validate topic ở API layer bằng Groq `llama-3.3-70b-versatile`; phân loại `scholarly`, `technical`, `practical`, `lifestyle` |
| Planner | `backend/app/services/textbook/planner.py` | Sinh curriculum bằng `LLM_MODEL_PREMIUM`; Phase 1 không crawl, không RAG |
| Metadata | `generate_metadata_node` trong `planner.py` | Sau khi user confirm, sinh textbook title và `Lời nói đầu` từ curriculum đã duyệt |
| Ingester | `backend/app/services/textbook/ingester.py` | Xóa ChromaDB cũ, query expansion song ngữ, search, filter URL, crawl, chunk, embed, lưu Chroma |
| QueryFormulator | `backend/app/services/textbook/query_formulator.py` | Tạo query retrieval cho subsection hiện tại, có enrichment theo user requirements |
| RetrieverNode | `backend/app/services/textbook/retriever.py` | MMR search trên Chroma collection `dynamic_context`, lọc chunk nhiều tầng, log context |
| ContextEvaluator | `backend/app/services/textbook/evaluator.py` | Dùng LLM có tool `retrieve_context_tool` để bổ sung context khi cần |
| ContentWriter | `backend/app/services/textbook/writer.py` | Sinh nội dung tiếng Việt bằng `LLM_MODEL_PREMIUM`, enforce length/heading/continuity/image tags |
| Reviewer | `backend/app/services/textbook/reviewer.py` | Hai pass review bằng cheap LLM: format/math pass, content-quality pass, JSON quality gate |
| Illustrator | `backend/app/services/textbook/illustrator.py` | Resolve `[IMAGE: ...]` tags bằng GPT Image hoặc Serper Google Images |
| Publisher | `backend/app/services/textbook/publisher.py` | Ghép nội dung, fix Markdown/math, tạo front matter Typst, export PDF và Word |
| Workflow runner | `backend/app/services/textbook/workflow_runner.py` | Stream LangGraph events, update `progress_data` vào MySQL |
| Orchestrator | `backend/app/services/textbook/orchestrator.py` | Định nghĩa graph nodes, edges, routing, stop checks |

## Ingestion And RAG

Ingestion chạy sau khi curriculum đã được xác nhận. Mỗi lượt generation dùng một ChromaDB sạch:

```text
clear backend/data/chroma_db
  -> QueryExpansionAgent
  -> parallel DuckDuckGo search
  -> URL filter
  -> deep crawl HTML/PDF
  -> chunk + quality filter
  -> relevance scoring with embeddings
  -> language-aware domain caps
  -> save to Chroma collection dynamic_context
```

### Query Expansion

`QueryExpansionAgent` tạo:

- 6 Vietnamese queries cho DuckDuckGo region `vn-vn`
- 6 English queries cho region `us-en`
- thêm curriculum-targeted queries lấy từ `search_query` của subsection sau khi user confirm

Các targeted query bị giới hạn bởi:

| Setting | Default | Ý nghĩa |
|---|---:|---|
| `TARGETED_CRAWL_QUERIES_PER_CHAPTER` | `2` | Số query lấy từ mỗi chapter |
| `TARGETED_CRAWL_MAX_QUERIES` | `12` | Tổng số targeted query tối đa |

### URL Filtering

`url_filter.py` lọc URL theo nhiều lớp:

- whitelist theo `content_type` để giữ nguồn đáng tin cậy như Wikipedia, OpenStax, arXiv, docs chính thức, wikiHow
- snippet score bằng `MIN_SNIPPET_SCORE`
- static blocklist domain/path/extension
- dynamic content-type probe qua HTTP để chỉ nhận `text/html` và `application/pdf`

### Crawler

`crawler.py` xử lý:

- PDF bằng PyMuPDF (`fitz`), fallback `pypdf`
- HTML bằng Requests + BeautifulSoup
- phân loại trang thành `educational`, `navigation`, `junk`
- trang educational được lưu và crawl sublinks
- trang navigation không lưu nội dung root nhưng có thể crawl sublinks
- trang junk bị bỏ cả nội dung lẫn sublinks

Sau khi crawl:

- `RecursiveCharacterTextSplitter` dùng `CHUNK_SIZE=1500`, `CHUNK_OVERLAP=300`
- heuristic filter loại chunk ngắn, nhiễu, quá nhiều số, citation/reference, TOC, commercial/booking content
- relevance scoring dùng embedding song ngữ: embedding topic tiếng Việt + một English query đại diện
- content-type threshold hiện tại:
  - `scholarly`: `0.30`
  - `technical`: `0.25`
  - `practical`: `0.22`
  - `lifestyle`: `0.22`
- domain caps:
  - Vietnamese chunks: `VI_DOMAIN_CAP=80`
  - English chunks: `EN_DOMAIN_CAP=35`
  - academic trusted domains trong `UNLIMITED_CAP_DOMAINS` không bị cap

### Retrieval

Retriever mở ChromaDB tại `backend/data/chroma_db`, collection `dynamic_context`, và dùng MMR search:

- initial retrieval: `RAG_INITIAL_K`
- tool-call retrieval: `RAG_TOOL_K`
- source quota: `RAG_TRUSTED_DOMAIN_QUOTA` hoặc `RAG_DEFAULT_DOMAIN_QUOTA`
- layer 1: structural heuristic
- layer 2: cheap LLM binary classifier `KEEP` / `DISCARD`
- layer 3: semantic deduplication và quality scoring

Mọi retrieval được log đầy đủ vào `backend/logs/rag_context.log`.

Lưu ý: `backend/app/services/rag_service.py` vẫn tồn tại như singleton Chroma cũ dùng `CHROMA_COLLECTION_NAME`, nhưng workflow textbook hiện hành đang ingest/retrieve bằng collection `dynamic_context`.

## CRAG Content Loop

Mỗi subsection đi qua:

```text
QueryFormulator -> RetrieverNode -> ContextEvaluator -> ContentWriter -> Reviewer -> Illustrator
```

`ContextEvaluator` dùng LLM có tool `retrieve_context_tool` để lấy thêm context tối đa `WRITER_RETRIEVAL_MAX_ROUNDS`. Nếu context vẫn mỏng, workflow ưu tiên fail-open để writer vẫn có thể tiếp tục, và reviewer có thể route lại về QueryFormulator nếu feedback được phân loại là `missing_context`.

`ContentWriter` nhận context đã chuẩn bị sẵn, không tự gọi tool. Writer enforce:

- heading chapter `# CHƯƠNG N: ...` chỉ ở subsection đầu mỗi chapter
- section heading `## X.Y Title`
- subsection heading `### X.Y.Z Title`
- blank lines quanh heading, paragraph, list, code, math block
- continuity bằng `section_summaries`
- image placeholders nếu `enable_images=True`

Character target được tính từ `section_type` và `content_level`:

| section_type | Base target |
|---|---:|
| `light` | 1,500 - 2,500 chars |
| `medium` | 3,000 - 4,500 chars |
| `deep` | 4,500 - 6,500 chars |
| `applied` | 2,500 - 3,500 chars |

| content_level | Scale |
|---|---:|
| `Ngắn` | `0.55x` |
| `Trung Bình` | `1.0x` |
| `Dài` | `1.6x` |
| `Rất Dài` | `2.3x` |

## Reviewer And Dynamic Routing

Reviewer chạy hai pass:

1. Format pass: sửa math delimiter, Unicode sub/superscript, heading level, blank lines, code fence language.
2. Content pass: chỉnh tone học thuật, depth, visual tags, tránh làm ngắn nội dung.

Sau đó quality gate trả JSON. Nếu nội dung đủ dài hơn `char_min * 1.2`, gate sẽ approve nhanh để tránh LLM đếm ký tự sai.

Routing sau review:

| rejection_type | Route | Ý nghĩa |
|---|---|---|
| `None` hoặc feedback rỗng | `APPROVE` -> Illustrator | Section được duyệt |
| `formatting_error` | `REVISE` -> ContentWriter | Viết lại/sửa cấu trúc với cùng context |
| `missing_context` | `RETRY_RETRIEVAL` -> QueryFormulator | Lấy context theo góc khác rồi viết lại |

`REVIEWER_MAX_REVISIONS=2` là trần số vòng revision mỗi subsection. Khi chạm trần, section được force-approve để workflow không kẹt vô hạn.

## Image Pipeline

Writer tạo tag:

```text
> [IMAGE: Vietnamese title | English visual description]
```

Illustrator xử lý từng tag:

```text
route_image_request
  |-- DRAW    -> GPT Image API
  |-- SEARCH  -> Serper Google Images
  |-- DIAGRAM -> Serper Google Images
```

Ảnh được download/generate, validate bằng vision model, resize tối đa `800x500`, convert RGB PNG, lưu tạm trong `backend/outputs/images`, rồi thay bằng Pandoc figure:

```markdown
![Hình X.Y.N: Caption](outputs/images/img_xxx.png){width=70%}
```

Nếu `enable_images=False` hoặc thiếu cả `SERPER_API_KEY` và `OPENAI_API_KEY`, Illustrator strip image tags để PDF không chứa placeholder hỏng. Publisher cleanup thư mục ảnh tạm sau export; PDF/DOCX là artefact chính, Markdown được giữ như source/audit.

## Publisher

Publisher xử lý cuối workflow:

1. Ghép `final_content` và `current_content`.
2. Prepend `# Lời nói đầu` nếu có `preface_content`.
3. Normalize line endings.
4. Chạy fix passes:
   - `fix_unicode_math`
   - `fix_markdown_headings`
   - `fix_inline_display_math`
   - `fix_math_formatting`
   - `fix_typst_deprecated_symbols`
   - `fix_chapter_pagebreaks`
   - `add_figure_numbers`
5. Assemble Typst front matter: title page, mục lục, danh mục hình nếu bật ảnh, rồi body.
6. Lưu Markdown.
7. Export PDF bằng Pandoc + Typst.
8. Export Word bằng Pandoc docx với page breaks và `reference.docx` auto-generated nếu chưa có.

Output mặc định:

```text
backend/outputs/<topic>_<timestamp>.md
backend/outputs/<topic>_<timestamp>.pdf
backend/outputs/<topic>_<timestamp>.docx
```

FastAPI mount thư mục này tại:

```text
http://localhost:8000/outputs/...
```

## Configuration

Config tĩnh nằm trong `backend/app/config.py` dưới dạng Pydantic `Settings`. File `.env` được đọc từ project root.

Các nhóm config chính:

| Nhóm | Setting tiêu biểu |
|---|---|
| API keys | `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `SERPER_API_KEY` |
| Database | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| Redis | `REDIS_HOST`, `REDIS_PORT` |
| LLM | `LLM_MODEL_CHEAP`, `LLM_MODEL_PREMIUM`, `IMAGE_MODEL_DEFAULT`, `IMAGE_MODEL_PREMIUM` |
| Embeddings | `EMBEDDING_PROVIDER`, `OPENAI_EMBEDDING_MODEL`, `EMBEDDING_MODEL_NAME` |
| RAG | `RAG_INITIAL_K`, `RAG_TOOL_K`, `RAG_TOP_K`, `RAG_TRUSTED_DOMAIN_QUOTA`, `RAG_SEMANTIC_DEDUP_THRESHOLD` |
| CRAG | `CRAG_CONTEXT_QUALITY_MIN_CHARS`, `CRAG_MAX_CONTEXT_RETRIES`, `WRITER_RETRIEVAL_MAX_ROUNDS` |
| Generation | `REVIEWER_MAX_REVISIONS`, `WRITER_SUMMARY_PREVIEW_CHARS`, `WRITER_MAX_PRIOR_SUMMARIES` |
| Ingestion | `SEARCH_RESULTS_PER_QUERY`, `SEARCH_MAX_WORKERS`, `CRAWL_MAX_WORKERS`, `URL_FILTER_MAX_WORKERS` |
| Chunking | `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MIN_CHUNK_CHARS`, `MIN_RELEVANCE_SCORE` |
| Domain caps | `MAX_CHUNKS_PER_DOMAIN`, `VI_DOMAIN_CAP`, `EN_DOMAIN_CAP`, `MAX_CHUNKS_TO_EMBED` |
| App URLs | `FRONTEND_URL`, `BACKEND_URL`, `ENVIRONMENT` |
| Security | `SECRET_KEY`, `ALGORITHM`, token expiry settings |
| OAuth/email/payment | Google OAuth, SMTP, SePay settings |

Tạo `.env` ở project root. Repo hiện không có `.env.example`, nên cần tạo thủ công:

```env
OPENAI_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
SERPER_API_KEY=

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=admin
MYSQL_PASSWORD=<match docker-compose.yml or your MySQL user>
MYSQL_DATABASE=ai_textbook_db

REDIS_HOST=localhost
REDIS_PORT=6379

SECRET_KEY=change-me-minimum-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_HOURS=24
REMEMBER_ME_EXPIRE_DAYS=30

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM=

SEPAY_API_KEY=
SEPAY_ACCOUNT_NUMBER=

FRONTEND_URL=http://localhost:5173
BACKEND_URL=http://localhost:8000
ENVIRONMENT=development

EMBEDDING_PROVIDER=openai
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_MODEL_NAME=BAAI/bge-m3

LLM_MODEL_CHEAP=gpt-4o-mini
LLM_MODEL_PREMIUM=gpt-4.1
IMAGE_MODEL_DEFAULT=gpt-image-1-mini
IMAGE_MODEL_PREMIUM=gpt-image-1.5
```

`GEMINI_API_KEY` và `ANTHROPIC_API_KEY` hiện là required fields trong `Settings` dù workflow chính không gọi trực tiếp hai provider này. Nếu thiếu, app có thể fail ngay khi load config.

### Advanced Settings API

`backend/app/config_registry.py` và `backend/app/routers/config.py` cung cấp registry/override cho UI:

- user overrides: `/api/v1/config/user/advanced`
- effective config: `/api/v1/config/effective`
- admin system config: `/api/v1/config/admin/system`
- audit log và override counts cho admin

Lưu ý hiện trạng: các agent trong workflow đang import và đọc trực tiếp `settings` từ `config.py`. DB overrides hiện có API/UI quản lý nhưng chưa được inject vào Celery workflow theo từng textbook/user. Nếu muốn per-user runtime config thật sự ảnh hưởng generation, cần wiring thêm phần merge effective config trước khi chạy task hoặc trước khi build graph.

## Installation

### Prerequisites

- Python 3.11+
- Node.js 20+
- MySQL 8
- Redis 7
- Pandoc
- Typst

Windows:

```powershell
winget install pandoc
winget install typst.typst
```

macOS:

```bash
brew install pandoc typst
```

### Start MySQL And Redis

Repo có `docker-compose.yml` cho MySQL, Redis và phpMyAdmin:

```bash
docker compose up -d mysql redis
```

Nếu dùng compose mặc định, đảm bảo `.env` và `backend/alembic.ini` dùng cùng credential/database. `alembic.ini` hiện chứa một local MySQL URL hard-coded, nên chỉnh lại nếu DB của bạn khác.

### Backend

Từ project root:

```bash
python -m venv venv
```

Windows PowerShell:

```powershell
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

Chạy migration và API từ thư mục `backend`:

```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Chạy Celery worker ở terminal khác. Trên Windows nên dùng `--pool=solo`:

```bash
cd backend
celery -A app.celery_app worker --loglevel=info --pool=solo
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend mặc định chạy tại:

```text
http://localhost:5173
```

Backend docs:

```text
http://localhost:8000/docs
```

## API Overview

Textbooks:

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/v1/textbooks` | Validate topic, trừ credit, tạo textbook, start planning task |
| `GET` | `/api/v1/textbooks` | Danh sách textbook của user |
| `GET` | `/api/v1/textbooks/{id}` | Chi tiết textbook |
| `GET` | `/api/v1/textbooks/{id}/progress` | Poll progress, curriculum, file paths |
| `POST` | `/api/v1/textbooks/{id}/confirm-curriculum` | Xác nhận curriculum và start generation task |
| `POST` | `/api/v1/textbooks/{id}/stop` | Set Redis stop flag và revoke Celery task |
| `DELETE` | `/api/v1/textbooks/{id}` | Xóa textbook |

Auth:

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/google/login`
- `GET /api/v1/auth/google/callback`
- `POST /api/v1/auth/forgot-password`
- `POST /api/v1/auth/reset-password`
- `PATCH /api/v1/auth/change-password`

Plans/payments:

- `GET /api/v1/plans`
- `GET /api/v1/plans/bank-config`
- `GET /api/v1/user/credits`
- `POST /api/v1/transactions`
- `GET /api/v1/user/transactions`

Admin:

- dashboard stats
- user lock/unlock/role management
- textbook listing
- plan CRUD
- transaction confirm/reject
- bank config
- system config registry and audit

## Project Structure

```text
curriculum_rag/
|-- README.md
|-- requirements.txt
|-- docker-compose.yml
|-- backend/
|   |-- run_api.py
|   |-- alembic.ini
|   |-- alembic/
|   |-- app/
|   |   |-- main.py
|   |   |-- config.py
|   |   |-- config_registry.py
|   |   |-- database.py
|   |   |-- celery_app.py
|   |   |-- routers/
|   |   |   |-- auth.py
|   |   |   |-- textbook.py
|   |   |   |-- plans.py
|   |   |   |-- admin.py
|   |   |   |-- config.py
|   |   |-- models/
|   |   |-- schemas/
|   |   |-- security/
|   |   |-- tasks/
|   |   |   |-- textbook_tasks.py
|   |   |-- ingestion/
|   |   |   |-- query_expansion.py
|   |   |   |-- search_engine.py
|   |   |   |-- url_filter.py
|   |   |   |-- crawler.py
|   |   |-- services/
|   |   |   |-- auth_service.py
|   |   |   |-- email_service.py
|   |   |   |-- rag_service.py
|   |   |   |-- textbook/
|   |   |       |-- orchestrator.py
|   |   |       |-- workflow_runner.py
|   |   |       |-- validator.py
|   |   |       |-- planner.py
|   |   |       |-- ingester.py
|   |   |       |-- query_formulator.py
|   |   |       |-- retriever.py
|   |   |       |-- evaluator.py
|   |   |       |-- writer.py
|   |   |       |-- reviewer.py
|   |   |       |-- illustrator.py
|   |   |       |-- publisher.py
|   |   |-- utils/
|   |       |-- log_config.py
|   |       |-- stop_signal.py
|   |       |-- task_registry.py
|   |-- data/chroma_db/       # auto-created
|   |-- logs/                 # agents, prompts, RAG context
|   |-- outputs/              # generated md/pdf/docx
|-- frontend/
|   |-- package.json
|   |-- src/
|       |-- App.jsx
|       |-- api/
|       |-- pages/
|       |-- components/
|       |   |-- textbooks/
|       |   |-- settings/
|       |   |-- topup/
|       |   |-- common/
```

## Operational Notes

- ChromaDB là global theo process/path và ingestion xóa `backend/data/chroma_db` ở đầu mỗi generation run. Nên chạy một generation worker hoặc bổ sung isolation theo `textbook_id` nếu cần concurrent generation thật sự.
- Celery stop dùng Redis key `textbook_stop:{id}` và task registry `task:{id}`. LangGraph node được bọc bởi `_with_stop_check`.
- `backend/logs/prompts/*_prompts.log` lưu prompt theo agent để audit.
- `backend/logs/rag_context.log` lưu full context chunk mà writer đã thấy.
- Nếu `pypandoc`, Pandoc hoặc Typst không khả dụng, Publisher fallback giữ Markdown/artefact còn tạo được thay vì crash toàn bộ.
- Frontend dùng `VITE_API_URL`, mặc định `http://localhost:8000`.

## License

MIT
