# Curriculum RAG - AI Textbook Generator

Hệ thống web tạo giáo trình tiếng Việt hoặc tiếng Anh từ một chủ đề đầu vào. Sản phẩm hiện tại gồm frontend React song ngữ VI/EN, backend FastAPI, hàng đợi Celery/Redis, MySQL, và một workflow LangGraph nhiều tác nhân để nhận diện ngôn ngữ, lập dàn ý, cho người dùng duyệt curriculum, crawl dữ liệu song ngữ, sinh nội dung theo CRAG, kiểm duyệt, minh họa và xuất Markdown/PDF/Word.

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
  |-- Textbooks: create planning draft, progress polling, edit/confirm curriculum, stop
  |-- Support: public request form forwarded to the configured admin email
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
  - locked target language (vi/en)
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

1. Người dùng tạo textbook từ UI hoặc `POST /api/v1/textbooks`; frontend gửi thêm `ui_language` (`vi` hoặc `en`).
2. `ValidatorAgent` kiểm tra topic, suy luận ngôn ngữ input/ngôn ngữ được yêu cầu, khóa `target_language`, rồi tách topic thành `content_type`, `core_topic`, và `user_requirements`. Feedback validation luôn theo ngôn ngữ UI.
3. Backend kiểm tra user còn ít nhất 1 credit, tạo planning draft với `credits_used=0`, rồi đẩy Celery task `generate_textbook`. Chưa trừ credit ở bước này.
4. Phase 1 chỉ chạy planner. Planner sinh chapter titles và subsections từ LLM, không crawl web ở bước này.
5. Frontend hiển thị curriculum để người dùng sửa/xóa/thêm chapter và subsection. Stop hoặc Reset trong planning/review sẽ revoke task, xóa draft khỏi database và không trừ credit.
6. Khi người dùng xác nhận, `POST /api/v1/textbooks/{id}/confirm-curriculum` validate curriculum, trừ đúng 1 credit trong transaction, đồng bộ các progress counters và đẩy task `continue_textbook_generation`. Request xác nhận lặp lại không trừ credit lần hai.
7. Phase 2 sinh tiêu đề thật và lời nói đầu, crawl dữ liệu, populate ChromaDB, rồi lặp qua từng subsection để sinh nội dung.
8. Publisher ghép toàn bộ nội dung, chạy các pass sửa Markdown/math/heading, rồi export `.md`, `.pdf`, `.docx` vào `backend/outputs`.

## Language Handling

Hệ thống chỉ tạo giáo trình bằng tiếng Việt (`vi`) hoặc tiếng Anh (`en`). Ngôn ngữ UI quyết định ngôn ngữ của label, validation feedback và lỗi; ngôn ngữ giáo trình được suy luận riêng theo thứ tự ưu tiên:

1. Yêu cầu ngôn ngữ rõ ràng trong query thắng, ví dụ `Lập trình Python cơ bản bằng tiếng Anh` hoặc `Python Programming Vietnamese Curriculum`.
2. Nếu không có yêu cầu rõ ràng, dùng ngôn ngữ của query.
3. Query quá ngắn hoặc mơ hồ mới fallback về `ui_language`.

Query bằng ngôn ngữ khác VI/EN chỉ được chấp nhận khi nội dung yêu cầu rõ đầu ra bằng tiếng Việt hoặc tiếng Anh. Các trường hợp còn lại bị chặn trước planning và trả message theo ngôn ngữ UI. Kết quả nhận diện gồm `input_language`, `requested_language`, `target_language`, `language_source`; `target_language` được lưu ở `textbooks.language` và truyền xuyên suốt state/progress.

`backend/app/services/textbook/language.py` định nghĩa language profile dùng chung cho Planner, Writer, Reviewer, Illustrator và Publisher. Profile kiểm soát academic tone, chapter/front-matter labels, caption và quy tắc định dạng tương ứng với từng ngôn ngữ. UI không có selector ngôn ngữ giáo trình riêng trong Advanced settings; query là nguồn quyết định chính.

## Core Agents

| Agent / module | File | Vai trò hiện tại |
|---|---|---|
| Validator | `backend/app/services/textbook/validator.py` | Validate topic ở API layer bằng Groq `llama-3.3-70b-versatile`; nhận diện/yêu cầu ngôn ngữ và phân loại `scholarly`, `technical`, `practical`, `lifestyle` |
| Planner | `backend/app/services/textbook/planner.py` | Sinh curriculum theo target language bằng `LLM_MODEL_PREMIUM`; Phase 1 không crawl, không RAG |
| Metadata | `generate_metadata_node` trong `planner.py` | Sau khi user confirm, sinh textbook title và Preface/Lời nói đầu theo target language |
| Ingester | `backend/app/services/textbook/ingester.py` | Xóa ChromaDB cũ, query expansion song ngữ, search, filter URL, crawl, chunk, embed, lưu Chroma |
| QueryFormulator | `backend/app/services/textbook/query_formulator.py` | Tạo query retrieval cho subsection hiện tại, có enrichment theo user requirements |
| RetrieverNode | `backend/app/services/textbook/retriever.py` | MMR search trên Chroma collection `dynamic_context`, lọc chunk nhiều tầng, log context |
| ContextEvaluator | `backend/app/services/textbook/evaluator.py` | Dùng LLM có tool `retrieve_context_tool` để bổ sung context khi cần |
| ContentWriter | `backend/app/services/textbook/writer.py` | Sinh nội dung VI/EN bằng `LLM_MODEL_PREMIUM`, enforce depth/length/paragraph flow/heading/continuity/image tags |
| Reviewer | `backend/app/services/textbook/reviewer.py` | Hai pass review language-aware bằng cheap LLM: format/math pass, content-quality pass, JSON quality gate |
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

`ContentWriter` nhận context đã chuẩn bị sẵn, không tự gọi tool. Writer enforce theo target language:

- heading chapter `# CHƯƠNG N: ...` hoặc `# CHAPTER N: ...` chỉ ở subsection đầu mỗi chapter
- section heading `## X.Y Title`
- subsection heading `### X.Y.Z Title`
- blank lines quanh heading, paragraph, list, code, math block
- continuity bằng `section_summaries` và paragraph flow phù hợp văn phong học thuật
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

Writer tạo tag với caption theo target language và mô tả hình bằng tiếng Anh để tối ưu search/generation:

```text
> [IMAGE: Localized title | English visual description]
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
![Localized figure label X.Y.N: Caption](outputs/images/img_xxx.png){width=70%}
```

Nếu `enable_images=False` hoặc thiếu cả `SERPER_API_KEY` và `OPENAI_API_KEY`, Illustrator strip image tags để PDF không chứa placeholder hỏng. Publisher cleanup thư mục ảnh tạm sau export; PDF/DOCX là artefact chính, Markdown được giữ như source/audit.

## Publisher

Publisher xử lý cuối workflow:

1. Ghép `final_content` và `current_content`.
2. Prepend `# Lời nói đầu` hoặc `# Preface` nếu có `preface_content`.
3. Normalize line endings.
4. Chạy fix passes:
   - `fix_unicode_math`
   - `fix_markdown_headings`
   - `fix_inline_display_math`
   - `fix_math_formatting`
   - `fix_typst_deprecated_symbols`
   - `fix_chapter_pagebreaks`
   - `add_figure_numbers`
5. Assemble Typst front matter theo target language: title page, mục lục/table of contents, danh mục hình/list of figures nếu bật ảnh, rồi body.
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

Config bootstrap nằm trong `backend/app/config.py` dưới dạng Pydantic `Settings`. File `.env` được đọc từ project root.

Các external/API secrets được resolve theo thứ tự:

```text
system_config trong database -> .env / Settings -> lỗi rõ ràng nếu key bắt buộc bị thiếu
```

Vì vậy trên máy mới, chỉ cần cấu hình bootstrap cho MySQL/Redis/JWT trong `.env`, đăng nhập bằng admin mặc định, rồi nhập API keys tại Admin System Config. `.env` vẫn có thể giữ API keys như fallback, nhưng không còn là nơi bắt buộc duy nhất.

Các nhóm config chính:

| Nhóm | Setting tiêu biểu |
|---|---|
| API keys | `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `SERPER_API_KEY`, Google OAuth, SMTP, SePay |
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

Tạo `.env` ở project root. Repo hiện không có `.env.example`, nên cần tạo thủ công. Các API keys dưới đây là fallback tùy chọn nếu chưa nhập trong Admin System Config:

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

DEFAULT_ADMIN_ENABLED=true
DEFAULT_ADMIN_EMAIL=admin@example.com
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_FULL_NAME=System Administrator
DEFAULT_ADMIN_PASSWORD_HASH="$2b$12$oHvFFApYhi6yUrJfVVORkuG2oQWumTsc37Qr6o9FLV5sqUO8nDvjy"

EMBEDDING_PROVIDER=openai
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_MODEL_NAME=BAAI/bge-m3

LLM_MODEL_CHEAP=gpt-4o-mini
LLM_MODEL_PREMIUM=gpt-4.1
IMAGE_MODEL_DEFAULT=gpt-image-1-mini
IMAGE_MODEL_PREMIUM=gpt-image-1.5
```

`MYSQL_*`, `REDIS_*`, `SECRET_KEY`, URL app và model/config vận hành vẫn nên nằm trong `.env`. API keys có thể nhập bằng Admin UI; nếu DB chưa có key thì runtime fallback về `.env`.

### Advanced Settings API

`backend/app/config_registry.py` và `backend/app/routers/config.py` cung cấp registry/override cho UI:

- user overrides: `/api/v1/config/user/advanced`
- effective config: `/api/v1/config/effective`
- admin system config: `/api/v1/config/admin/system`
- audit log và override counts cho admin

Nhóm `API Keys` trong Admin System Config lưu secret vào bảng `system_config`. GET response sẽ mask sensitive values bằng `••••••••`; nếu admin không nhập giá trị mới thì mask không overwrite secret đang lưu.

## Installation

### Prerequisites

- Python 3.11+
- Node.js 20+
- MySQL 8
- Redis 7
- Pandoc 3.6.4+ (cần bản hỗ trợ Typst PDF engine)
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

Nếu dùng compose mặc định, cấu hình credential/database trong `.env`. Alembic và
backend cùng đọc URL từ `Settings`, nên không cần sửa credential trong
`backend/alembic.ini`.

`docker-compose.yml` chỉ khởi tạo database service. Khi backend kết nối vào database này ở lần chạy đầu, backend sẽ tạo/verify tables và seed tài khoản admin mặc định nếu chưa tồn tại.

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

Chạy API từ thư mục `backend`. Ở fresh local database, backend startup sẽ tự tạo/verify tables bằng SQLAlchemy metadata và seed admin mặc định:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Với database đã có schema cũ và đang được Alembic quản lý, chạy migration trước khi start API:

```bash
cd backend
alembic upgrade head
```

Migration `backend/alembic/versions/add_textbook_language.py` thêm cột `textbooks.language` và backfill textbook cũ thành `vi`. Nếu bỏ qua bước này, các API đọc textbook sẽ lỗi `Unknown column 'textbooks.language'`.

### Standalone CLI

CLI chạy toàn bộ pipeline mà không cần khởi động FastAPI, MySQL, Redis hay
Celery. Validator vẫn kiểm tra và chuẩn hóa query trước khi planner chạy; cấu
trúc được tự động chấp nhận và sản phẩm được lưu trong `backend/outputs`.

CLI chỉ đọc API key và cấu hình mặc định từ `.env` ở project root. Tối thiểu
cần `GROQ_API_KEY` cho Validator và `OPENAI_API_KEY` cho các agent/embedding.
`SERPER_API_KEY` là tùy chọn khi bật hình ảnh. Pandoc và Typst phải có trong
`PATH` để xuất đủ PDF và Word; Markdown luôn được giữ lại.

Chạy từ project root:

```powershell
python backend/run_cli.py --query "Lập trình Python cơ bản" --chapters 3 --length medium --sections 5
```

Bật hình ảnh hoặc lấy kết quả JSON cho script khác:

```powershell
python backend/run_cli.py --query "Mạng máy tính cho sinh viên" --images
python backend/run_cli.py --query "Machine Learning for beginners" --json
```

Các tùy chọn chính:

- `--images/--no-images`: mặc định không dùng ảnh.
- `--chapters`: `2–12`, mặc định `3`.
- `--length`: `short`, `medium`, `long`, `very-long`; mặc định `medium`.
- `--sections`: số mục tối đa mỗi chương, `2–8`, mặc định `5`.
- `--json`: stdout chỉ chứa một JSON object; log và tiến trình đi qua stderr.

CLI trả exit code `0` khi hoàn tất, `2` khi query/tham số không hợp lệ, `1`
khi pipeline lỗi và `130` khi bị ngắt bằng bàn phím. Tóm tắt cuối cùng gồm số
chương/mục, lượng từ/ký tự, số hình, thời gian chạy và đường dẫn từng artefact
thực sự được tạo.

### First Login And API Keys

Sau khi backend và frontend chạy, đăng nhập bằng tài khoản admin development
được cấu hình qua các biến `DEFAULT_ADMIN_*` trong `.env`. Không dùng lại tài
khoản hoặc password development này cho bản demo public.

Việc cần làm đầu tiên trong Admin UI:

1. Vào trang Admin System Config.
2. Mở nhóm `API Keys`.
3. Nhập tối thiểu các key đang dùng trong workflow: `OPENAI_API_KEY`, `GROQ_API_KEY`; nếu bật ảnh/search thì thêm `SERPER_API_KEY`.
4. Nếu dùng Google OAuth, email reset password hoặc thanh toán thì nhập thêm Google OAuth, SMTP và SePay tương ứng.

Nếu chưa nhập API keys trong Admin UI và `.env` cũng không có fallback, các task gọi provider tương ứng sẽ fail với lỗi chỉ rõ key nào đang thiếu.

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
| `POST` | `/api/v1/textbooks` | Validate topic/ngôn ngữ, kiểm tra credit, tạo planning draft với `credits_used=0` |
| `GET` | `/api/v1/textbooks` | Danh sách textbook của user |
| `GET` | `/api/v1/textbooks/{id}` | Chi tiết textbook |
| `GET` | `/api/v1/textbooks/{id}/progress` | Poll progress, curriculum, file paths |
| `POST` | `/api/v1/textbooks/{id}/confirm-curriculum` | Validate curriculum, trừ 1 credit idempotently và start generation task |
| `POST` | `/api/v1/textbooks/{id}/stop` | Xóa draft chưa confirm hoặc dừng generation đã dùng credit |
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
|   |   |       |-- language.py
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
|   |-- README.md
|   |-- package.json
|   |-- src/
|       |-- App.jsx
|       |-- api/
|       |-- i18n/
|       |-- pages/
|       |-- utils/
|       |-- components/
|       |   |-- textbooks/
|       |   |-- settings/
|       |   |-- topup/
|       |   |-- common/
```

## Deploy Demo Trên VPS

Cấu hình này dành cho một VPS Linux tối thiểu 2 GB RAM + 2 GB swap. Nó giữ
nguyên API, giao diện, JWT localStorage, Celery workflow và đường dẫn
`/outputs`; Caddy thêm HTTPS và một lớp Basic Auth bao quanh toàn bộ demo.
Backend image đã khóa Typst `0.13.1` và Pandoc `3.6.4`, đồng thời có font
Liberation Serif để xuất PDF/Word nhất quán mà không cần cài chúng trên VPS.

### Chuẩn bị

1. Trỏ domain về VPS và mở cổng `80`, `443`.
2. Copy `.env.production.example` thành `.env.production`, thay toàn bộ
   `REPLACE_*`, URL và email mẫu; sau đó chạy `chmod 600 .env.production`.
3. Tạo các secret cần thiết:

```bash
openssl rand -hex 32
docker run --rm caddy:2.10-alpine caddy hash-password --plaintext 'demo-password'
python -c "import bcrypt; print(bcrypt.hashpw(b'admin-password', bcrypt.gensalt()).decode())"
```

Đặt Caddy hash và bcrypt hash trong dấu nháy đơn ở `.env.production` để ký tự
`$` không bị Docker Compose nội suy. Cấu hình Google OAuth callback phải là:

```text
https://<domain>/api/v1/auth/google/callback
```

### Build và chạy

Nên build image trên máy local/CI rồi push lên registry hoặc chuyển bằng
`docker save`/`docker load`; không nên build dependency trên VPS 2 GB. Sau khi
image có trên server:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Sau mỗi lần cập nhật image hoặc code cấu hình, recreate các process dài hạn để
Celery/Uvicorn không giữ singleton Settings cũ trong RAM:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d \
  --force-recreate api worker web
```

Service `migrate` chạy `alembic upgrade head` trước khi API và worker khởi
động. Migration `initial_schema` hỗ trợ database production mới hoàn toàn.
Nếu mang một database local cũ từng được tạo bằng `create_all()` nhưng chưa có
Alembic version sang server, phải backup và đối chiếu schema trước khi stamp;
không chạy baseline đè lên các bảng đã tồn tại. Kiểm tra log và smoke test:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api worker
DEMO_URL=https://<domain> \
DEMO_BASIC_AUTH_USER=<user> \
DEMO_BASIC_AUTH_PASSWORD=<password> \
bash deploy/smoke.sh
```

Backup thủ công trước khi cập nhật:

```bash
bash deploy/backup.sh
```

File backup MySQL và `outputs` được đặt dưới `backups/<timestamp>/`. Kiểm tra
khả năng restore trên môi trường staging trước khi xem backup là hợp lệ.

### Giới hạn scale

Demo khóa `CELERY_CONCURRENCY=1` vì ChromaDB và image workspace hiện dùng
chung. Có thể nâng CPU/RAM để một job ổn định hơn, nhưng không tăng concurrency
trước khi triển khai isolation theo `textbook_id`. API, worker, database, Redis
và web đã là các service tách biệt nên có thể chuyển sang máy khác trong phase
scale sau này.

Dependency audit hiện còn cảnh báo `CVE-2026-45829` ở `chromadb 1.5.9` và chưa
có bản vá được công bố trong package index. Đây là rủi ro được chấp nhận riêng
cho bản demo có Basic Auth; cần cập nhật ChromaDB và regression test ngay khi có
bản vá trước khi coi hệ thống là production công khai.

## Operational Notes

- ChromaDB là global theo process/path và ingestion xóa `backend/data/chroma_db` ở đầu mỗi generation run. Nên chạy một generation worker hoặc bổ sung isolation theo `textbook_id` nếu cần concurrent generation thật sự.
- Celery stop dùng Redis key `textbook_stop:{id}` và task registry `task:{id}`. LangGraph node được bọc bởi `_with_stop_check`.
- Planning/review draft có `credits_used=0`; Stop/Reset xóa record. Sau confirm, credit không được hoàn lại khi user dừng generation.
- `backend/logs/prompts/*_prompts.log` lưu prompt theo agent để audit khi
  `ENABLE_PROMPT_LOGS=true`; cấu hình demo mặc định tắt để giảm dùng ổ đĩa.
- `backend/logs/rag_context.log` lưu full context chunk mà writer đã thấy.
- Nếu `pypandoc`, Pandoc hoặc Typst không khả dụng, Publisher fallback giữ Markdown/artefact còn tạo được thay vì crash toàn bộ.
- Frontend dùng `VITE_API_URL`, mặc định `http://localhost:8000`.
- Frontend i18n lưu lựa chọn VI/EN bằng key `app_language`; xem `frontend/README.md` để biết quy ước thêm translation key.

## License

MIT
