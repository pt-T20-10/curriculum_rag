# Curriculum RAG - AI Textbook Generator

Hệ thống web tạo giáo trình tiếng Việt hoặc tiếng Anh từ một chủ đề đầu vào. Sản phẩm hiện tại gồm frontend React song ngữ VI/EN, backend FastAPI, hàng đợi Celery/Redis, MySQL, và một workflow LangGraph nhiều tác nhân để nhận diện ngôn ngữ, lập dàn ý, cho người dùng duyệt curriculum, crawl dữ liệu song ngữ, sinh nội dung theo CRAG, kiểm duyệt, minh họa và xuất PDF/Word.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/API-FastAPI-teal)
![LangGraph](https://img.shields.io/badge/Workflow-LangGraph-orange)
![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-purple)
![Frontend](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61dafb)

## Deploy Quickstart

Đọc phần này trước nếu bạn hoặc một AI agent khác cần deploy hệ thống trên
server mới. Các phần kiến trúc, workflow và agent được đặt phía sau như tài liệu
tham khảo kỹ thuật.

### Chọn Kiểu Deploy

| Option | Khi nào dùng | Dịch vụ cần có | Ghi chú |
|---|---|---|---|
| Docker Compose VPS | Khuyến nghị mặc định khi chưa biết OS/server cụ thể | Docker, Docker Compose, domain HTTPS | Ít phụ thuộc Ubuntu/Debian/RHEL; app chạy bằng container |
| Railway / Managed | Muốn dùng MySQL/Redis managed và deploy nhanh | Railway services hoặc provider tương đương | Cần map đúng `MYSQL_URL`, `REDIS_URL`, `FRONTEND_URL`, `BACKEND_URL` |
| Manual Linux | Server tự quản, muốn tách từng process | Python 3.11, Node, MySQL, Redis, Caddy/Nginx, Celery | Phù hợp khi có người vận hành Linux/systemd |
| Local Dev | Chạy và test trên máy dev | Python, Node, Docker cho MySQL/Redis | ChromaDB dùng local persistent path, không dành cho multi-worker production |

Nếu chưa chắc server chạy công nghệ gì, chọn **Docker Compose VPS** trước. Miễn
server cài được Docker và mount được volume persistent, hệ điều hành phía dưới
không còn quá quan trọng.

### Dịch Vụ Bắt Buộc

| Service | Vai trò | Persistent data |
|---|---|---|
| `web` / Caddy | Serve frontend React, HTTPS, proxy API, Basic Auth demo | Caddy data/config |
| `api` / FastAPI | Auth, textbook API, admin config, progress polling | Không lưu state dài hạn trong container |
| `worker` / Celery | Chạy planning/content generation dài hạn | Cần truy cập `outputs`, logs, Chroma |
| MySQL 8 | Users, textbooks, credits, config, credentials | Bắt buộc backup |
| Redis 7 | Celery broker/result, stop signal, task registry, shared rate limiter | Nên persistent append-only |
| ChromaDB | Vector store cho RAG theo từng textbook/run | Local path trong branch hiện tại; server riêng khi scale |
| Outputs volume | Markdown/PDF/DOCX/image sinh ra | Bắt buộc backup nếu cần giữ giáo trình |

### Docker Compose VPS

Cấu hình hiện tại trong `docker-compose.prod.yml` dành cho demo production nhỏ:
MySQL, Redis, API, worker, web/Caddy chạy trên cùng VPS. Backend image đã đóng
gói Typst `0.13.1`, Pandoc `3.6.4` và font Liberation Serif để export PDF/Word
ổn định mà không cần cài thêm trên host.

1. Trỏ domain về VPS và mở cổng `80`, `443`.
2. Copy `.env.production.example` thành `.env.production`, thay toàn bộ
   `REPLACE_*`, URL/email mẫu, rồi đặt quyền file secret:

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

3. Tạo secret:

```bash
openssl rand -hex 32
docker run --rm caddy:2.10-alpine caddy hash-password --plaintext 'demo-password'
python -c "import bcrypt; print(bcrypt.hashpw(b'admin-password', bcrypt.gensalt()).decode())"
```

Đặt Caddy hash và bcrypt hash trong dấu nháy đơn ở `.env.production` để ký tự
`$` không bị Docker Compose nội suy. Google OAuth callback phải là:

```text
https://<domain>/api/v1/auth/google/callback
```

4. Kiểm tra config, migrate, chạy service:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

5. Kiểm tra log và smoke test:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api worker
DEMO_URL=https://<domain> \
DEMO_BASIC_AUTH_USER=<user> \
DEMO_BASIC_AUTH_PASSWORD=<password> \
bash deploy/smoke.sh
```

Sau mỗi lần đổi image/code/config, chạy migration rồi recreate process dài hạn
để Uvicorn/Celery không giữ singleton settings cũ:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d \
  --force-recreate api worker web
```

### Environment Checklist

Những biến quan trọng cần kiểm tra trước khi deploy:

| Nhóm | Biến |
|---|---|
| URL/security | `ENVIRONMENT=production`, `FRONTEND_URL`, `BACKEND_URL`, `CORS_ORIGINS`, `SECRET_KEY` |
| MySQL | `MYSQL_URL` hoặc `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` |
| Redis | `REDIS_URL` hoặc `REDIS_HOST`, `REDIS_PORT` |
| Generation mode | `TEXTBOOK_GENERATION_MODE=user_provided_api_keys` hoặc `system_credit_billing` |
| BYOK | `BYOK_ENCRYPTION_KEY` bắt buộc khi user tự nhập/lưu API key |
| Provider keys | `OPENAI_API_KEY` hoặc `OPENAI_API_KEYS` bắt buộc nếu dùng credit hệ thống; `SERPER_API_KEY` hoặc `SERPER_API_KEYS` tùy chọn |
| OAuth/email/payment | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, SMTP/Resend, `SEPAY_ACCOUNT_NUMBER` |
| Worker profile | `CELERY_POOL`, `CELERY_CONCURRENCY`, `CHROMA_MODE`, `GENERATION_GLOBAL_CONCURRENCY`, `GENERATION_PER_USER_CONCURRENCY`, `SEARCH_MAX_WORKERS`, `CRAWL_MAX_WORKERS`, `MAX_CHUNKS_TO_EMBED`, `EMBEDDING_BATCH_SIZE` |

API keys hệ thống có thể nhập trong Admin System Config sau khi đăng nhập. Field
`OPENAI_API_KEYS` và `SERPER_API_KEYS` nhận nhiều key, mỗi dòng một key, và
runtime sẽ xoay vòng qua Redis khi Redis khả dụng. Nếu Admin DB chưa có key thì
runtime fallback về `.env`. `BYOK_ENCRYPTION_KEY` là secret gốc, không nhập qua
Admin UI.

### First Admin Setup

Ở lần backend đầu tiên kết nối database, bootstrap admin được tạo từ các biến
`DEFAULT_ADMIN_*`. Production validator từ chối email/mật khẩu mẫu, nên phải
thay `DEFAULT_ADMIN_EMAIL` và `DEFAULT_ADMIN_PASSWORD_HASH` trước khi deploy
công khai.

Sau khi login, frontend gọi:

```text
GET /api/v1/config/admin/setup-status
```

Nếu thiếu cấu hình bắt buộc, Admin được chuyển tới `/admin/config?setup=1` để
nhập ngay SMTP, OpenAI key cho credit mode, Google OAuth hoặc tài khoản nhận
tiền. Checklist tính giá trị theo thứ tự Admin DB rồi tới `.env`.

### ChromaDB Modes

| Mode | Trạng thái | Khi nào dùng | Cảnh báo |
|---|---|---|---|
| Local persistent path | Đang dùng trong branch hiện tại qua `persist_directory` | Local dev, demo 1 worker | Không tăng Celery concurrency khi nhiều worker cùng mở path này |
| Local per-job path | Railway smoke test 2 user | `CHROMA_MODE=local_per_job`, mỗi textbook có thư mục riêng dưới `CHROMA_RUNS_DIR` | Phù hợp test nhỏ; không dùng cho 5-10 job lâu dài |
| Chroma server / HTTP | Hướng scale production | 5-10 generation song song trở lên | Cần thêm service Chroma riêng và đặt `CHROMA_HTTP_HOST`/`CHROMA_HTTP_PORT` |

Workflow hiện tại đã tạo collection riêng cho mỗi textbook/run
(`dynamic_context_<textbook_id>_<timestamp>`) và cleanup best-effort sau export.
Điều này tránh lẫn dữ liệu, nhưng chưa thay thế được Chroma server khi chạy
nhiều worker generation thật sự.

### Scale And Concurrency Notes

Deployment profile hiện tại được hiển thị trong Admin Dashboard/Admin Config sau
khi Admin đăng nhập. Popup lần đầu và banner nhỏ sẽ nói rõ hệ thống đang ở
`small_safe`, `railway_test_2`, `medium_ready` hay `misconfigured`.

#### Biến Nào Cần Redeploy

`CELERY_POOL` và `CELERY_CONCURRENCY` là cấu hình **process-level** của Celery
worker. Hai biến này phải đặt trong `.env.production`, Railway Variables, hoặc
biến môi trường của service worker trước khi process khởi động. Sau khi đổi,
bạn cần restart/redeploy worker thì số job chạy song song mới thật sự thay đổi.

`GENERATION_GLOBAL_CONCURRENCY`, `GENERATION_PER_USER_CONCURRENCY`,
`GENERATION_QUEUE_RETRY_SECONDS`, `CHROMA_MODE`, `CHROMA_RUNS_DIR` và
`CHROMA_HTTP_*` là cấu hình runtime mà Admin Config có thể hiển thị/ghi đè trong
database. Tuy nhiên nếu tăng runtime limit cao hơn số worker Celery đang chạy,
hệ thống vẫn không chạy nhanh hơn vì Celery chưa có thêm process/thread để xử
lý job.

Trạng thái mặc định:

- `docker-compose.prod.yml` chạy API `--workers 1`.
- Worker production mặc định chạy `celery --pool=solo --concurrency=1`; Railway
  start script có đọc `CELERY_POOL`/`CELERY_CONCURRENCY`.
- Production validator cho phép `CELERY_CONCURRENCY=2` khi
  `CHROMA_MODE=local_per_job`; vẫn từ chối tăng worker nếu còn
  `CHROMA_MODE=local_shared`.
- Mỗi user vẫn chỉ chạy 1 giáo trình active tại một thời điểm. Job mới của cùng
  user sẽ vào hàng đợi và retry bằng Celery.

Profile khuyến nghị:

| Profile | Mục tiêu | Cấu hình phù hợp |
|---|---|---|
| Minimum/demo | 1 giáo trình đang generate toàn hệ thống | Compose hiện tại, Chroma local path, Redis/MySQL cùng VPS |
| Railway test 2 | 2 user khác nhau generate cùng lúc | `CELERY_POOL=threads`, `CELERY_CONCURRENCY=2`, `CHROMA_MODE=local_per_job`, `GENERATION_GLOBAL_CONCURRENCY=2`, `GENERATION_PER_USER_CONCURRENCY=1` |
| Medium | 5-10 giáo trình song song từ nhiều user | Chroma server, Redis shared limiter, key pool, global generation semaphore, per-user active limit |

#### Scale Ladder

1. **Small safe**: giữ mặc định `CELERY_CONCURRENCY=1`,
   `GENERATION_GLOBAL_CONCURRENCY=1`, `CHROMA_MODE=local_shared`. Phù hợp demo,
   ít tài nguyên, ít rủi ro.
2. **Railway test 2 tài khoản**: đặt `CELERY_POOL=threads`,
   `CELERY_CONCURRENCY=2`, `CHROMA_MODE=local_per_job`,
   `GENERATION_GLOBAL_CONCURRENCY=2`, `GENERATION_PER_USER_CONCURRENCY=1`.
   Cấu hình này cho 2 user khác nhau chạy cùng lúc, nhưng cùng 1 user vẫn chỉ 1
   giáo trình active; giáo trình tiếp theo vào hàng đợi.
3. **Medium production 5-10 user/job**: chuyển sang `CHROMA_MODE=http`, thêm
   Chroma server riêng, giữ Redis chung cho queue/limiter, rồi tăng
   `CELERY_CONCURRENCY` và `GENERATION_GLOBAL_CONCURRENCY` theo benchmark thật.

Để lên medium profile:

- Tách Chroma thành service/server và đặt `CHROMA_MODE=http`.
- Tăng `GENERATION_GLOBAL_CONCURRENCY` sau khi benchmark worker/RAM/quota.
- Với `system_credit_billing`, nhập nhiều OpenAI/Serper key của Admin bằng
  `OPENAI_API_KEYS`/`SERPER_API_KEYS`; mỗi dòng một key.
- Giữ `SEARCH_MAX_WORKERS`, `CRAWL_MAX_WORKERS`, `MAX_CHUNKS_TO_EMBED` thấp lúc
  mới scale, rồi benchmark tăng dần.

Không tăng `CELERY_CONCURRENCY` lên 5-10 nếu vẫn dùng
`CHROMA_MODE=local_shared`. Khi nhiều worker cùng mở một local Chroma path, rủi
ro lock/crash/corrupt state cao hơn nhiều so với lợi ích. Với Railway test nhỏ,
`local_per_job` cô lập dữ liệu theo từng textbook; với production lớn, dùng
Chroma HTTP server.

### Backup And Restore

Backup trước mỗi deploy hoặc migration:

```bash
bash deploy/backup.sh
```

Tối thiểu cần giữ:

- MySQL dump: users, textbooks, credits, config, encrypted credentials.
- `outputs` volume: Markdown/PDF/DOCX/image đã sinh.
- Chroma volume/path: chỉ cần nếu muốn giữ corpus RAG tạm; workflow hiện có thể
  crawl lại, nhưng backup giúp debug và audit.

Kiểm tra restore trên staging trước khi xem backup là đáng tin.

### Troubleshooting

| Triệu chứng | Kiểm tra |
|---|---|
| API không lên | `docker compose logs api`, `SECRET_KEY`, `FRONTEND_URL`, `CORS_ORIGINS`, migration |
| Worker không nhận job | Redis URL/healthcheck, `celery_task_id`, `docker compose logs worker` |
| Tạo giáo trình fail vì key | Admin System Config, `.env`, generation mode, BYOK credentials |
| Bị 429/Too Many Requests | Bật Redis shared limiter, tăng sleep/backoff, giảm worker/crawl/image concurrency |
| Export thiếu PDF/DOCX | Log publisher, Pandoc/Typst trong image, quyền ghi `outputs` volume |
| RAG/Chroma lỗi khi scale | Đừng tăng worker nếu còn dùng local persistent path; chuyển sang Chroma server trước |

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
| Ingester | `backend/app/services/textbook/ingester.py` | Chuẩn bị ChromaDB per-run collection, query expansion song ngữ, search, filter URL, crawl, chunk, embed, lưu Chroma |
| QueryFormulator | `backend/app/services/textbook/query_formulator.py` | Tạo query retrieval cho subsection hiện tại, có enrichment theo user requirements |
| RetrieverNode | `backend/app/services/textbook/retriever.py` | MMR search trên Chroma collection của textbook hiện tại, lọc chunk nhiều tầng, log context |
| ContextEvaluator | `backend/app/services/textbook/evaluator.py` | Dùng LLM có tool `retrieve_context_tool` để bổ sung context khi cần |
| ContentWriter | `backend/app/services/textbook/writer.py` | Sinh nội dung VI/EN bằng `LLM_MODEL_PREMIUM`, enforce depth/length/paragraph flow/heading/continuity/image tags |
| Reviewer | `backend/app/services/textbook/reviewer.py` | Hai pass review language-aware bằng cheap LLM: format/math pass, content-quality pass, JSON quality gate |
| Illustrator | `backend/app/services/textbook/illustrator.py` | Resolve `[IMAGE: ...]` tags bằng GPT Image hoặc Serper Google Images |
| Publisher | `backend/app/services/textbook/publisher.py` | Ghép nội dung, fix Markdown/math, tạo front matter Typst, export PDF và Word |
| Workflow runner | `backend/app/services/textbook/workflow_runner.py` | Stream LangGraph events, update `progress_data` vào MySQL |
| Orchestrator | `backend/app/services/textbook/orchestrator.py` | Định nghĩa graph nodes, edges, routing, stop checks |

## Ingestion And RAG

Ingestion chạy sau khi curriculum đã được xác nhận. Mỗi lượt generation dùng một collection riêng trong ChromaDB để tránh lẫn dữ liệu giữa các textbook:

```text
prepare backend/data/chroma_db
  -> create/use per-textbook Chroma collection
  -> QueryExpansionAgent
  -> source policy routing (system/default/custom)
  -> parallel DuckDuckGo search
  -> URL filter
  -> deep crawl HTML/PDF
  -> chunk + quality filter
  -> relevance scoring with embeddings
  -> language-aware domain caps
  -> save to the current run collection
```

### Query Expansion

`QueryExpansionAgent` tạo:

- với `technical`/`scholarly`: mặc định dùng 3 Vietnamese queries và 6 English queries để ưu tiên nguồn học thuật tiếng Anh
- với nhóm khác: dùng `SEARCH_QUERIES_PER_LANGUAGE`
- thêm curriculum-targeted queries lấy từ `search_query` của subsection sau khi user confirm
- thêm site-scoped queries dạng `site:<domain> <topic>` cho whitelist học thuật mặc định hoặc nguồn người dùng chọn

Các targeted query bị giới hạn bởi:

| Setting | Default | Ý nghĩa |
|---|---:|---|
| `TARGETED_CRAWL_QUERIES_PER_CHAPTER` | `2` | Số query lấy từ mỗi chapter |
| `TARGETED_CRAWL_MAX_QUERIES` | `12` | Tổng số targeted query tối đa |

### URL Filtering

`url_filter.py` lọc URL theo nhiều lớp:

- whitelist theo `content_type` và `source_preferences` để giữ nguồn đáng tin cậy như OpenStax, LibreTexts, MIT OCW, arXiv, university domains, official docs, `.edu.vn`
- snippet score bằng `MIN_SNIPPET_SCORE`
- direct custom URLs bỏ qua snippet score nhưng vẫn qua static/dynamic validation
- static blocklist domain/path/extension
- dynamic content-type probe qua HTTP để chỉ nhận `text/html` và `application/pdf`

`source_preferences` lưu theo từng textbook:

- `system_default`: dùng whitelist học thuật mặc định, EN-heavy cho `technical`/`scholarly`
- `custom_hybrid`: crawl URL/domain user chọn trước, thiếu thì bổ sung nguồn mặc định
- `custom_only`: chỉ crawl URL/domain hoặc nhóm nguồn user chọn

### Crawler

`crawler.py` xử lý:

- PDF bằng PyMuPDF (`fitz`), fallback `pypdf`
- priority textbook PDF: PDF trusted có tín hiệu `textbook`, `course notes`, `lecture notes`, `giáo trình`, `bài giảng` được giữ trọn sau quality/relevance filter và bỏ qua domain cap
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
  - priority textbook PDF chunks không bị cap theo domain

Sau mỗi lần lưu ChromaDB, crawler append một JSON record vào
`backend/logs/embedded_sources_audit.jsonl`. File này ghi `run_id`,
`collection_name`, `trusted_chunk_ratio`, `top_domains` và danh sách `sources`
cuối cùng đã được embedding để audit nhanh nguồn có chủ yếu đến từ whitelist hay
không.

### Retrieval

Retriever mở ChromaDB tại `backend/data/chroma_db`, collection của textbook hiện tại, và dùng MMR search:

- initial retrieval: `RAG_INITIAL_K`
- tool-call retrieval: `RAG_TOOL_K`
- source quota: `RAG_TRUSTED_DOMAIN_QUOTA` hoặc `RAG_DEFAULT_DOMAIN_QUOTA`
- layer 1: structural heuristic
- layer 2: cheap LLM binary classifier `KEEP` / `DISCARD`
- layer 3: semantic deduplication và quality scoring

Mọi retrieval được log đầy đủ vào `backend/logs/rag_context.log`.

Lưu ý: `backend/app/services/rag_service.py` vẫn tồn tại như singleton Chroma cũ dùng `CHROMA_COLLECTION_NAME`, nhưng workflow textbook hiện hành đang ingest/retrieve bằng collection riêng được lưu trong state/progress của từng textbook.

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
| API keys | `TEXTBOOK_GENERATION_MODE`, `BYOK_ENCRYPTION_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `SERPER_API_KEY`, Google OAuth, SMTP, SePay |
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

Tạo `.env` ở project root từ file mẫu. Các API keys dưới đây là fallback tùy chọn nếu chưa nhập trong Admin System Config:

```bash
cp .env.example .env
```

```env
OPENAI_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
SERPER_API_KEY=
TEXTBOOK_GENERATION_MODE=user_provided_api_keys
BYOK_ENCRYPTION_KEY=

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=textbook_user
MYSQL_PASSWORD=change_me_local_password
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
IMAGE_MODEL_DEFAULT=gpt-image-2
IMAGE_MODEL_PREMIUM=gpt-image-2
IMAGE_VALIDATION_MODEL=gpt-5.4-mini
```

`TEXTBOOK_GENERATION_MODE` có 2 giá trị: `user_provided_api_keys` tương ứng “Người dùng tự nhập API key” và `system_credit_billing` tương ứng “Nạp tiền bằng credit hệ thống”. Production mặc định nên dùng `user_provided_api_keys`; khi đó người dùng nhập OpenAI key bắt buộc, Serper key tùy chọn, hệ thống không trừ credit khi tạo giáo trình. Nếu bật `system_credit_billing`, admin cần cấu hình `OPENAI_API_KEY` hệ thống và flow credit giữ như trước.

`BYOK_ENCRYPTION_KEY` là Fernet key dùng để mã hóa API key cá nhân và snapshot key theo job. Tạo bằng:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`MYSQL_*`, `REDIS_*`, `SECRET_KEY`, URL app và model/config vận hành vẫn nên nằm trong `.env`. API keys hệ thống có thể nhập bằng Admin UI; nếu DB chưa có key thì runtime fallback về `.env`.

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

Migration `backend/alembic/versions/add_textbook_language.py` thêm cột `textbooks.language` và backfill textbook cũ thành `vi`; migration `backend/alembic/versions/add_textbook_mode.py` thêm mode textbook hiện tại; migration `backend/alembic/versions/add_byok_credentials.py` thêm bảng lưu API key cá nhân đã mã hóa và snapshot key theo job; migration `backend/alembic/versions/set_default_textbook_generation_mode.py` chuyển default sang “Người dùng tự nhập API key”. Nếu bỏ qua migration, các API đọc/tạo textbook hoặc chức năng người dùng tự nhập API key có thể lỗi thiếu schema/config.

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

`docker-compose.yml` khởi tạo MySQL; sau đó, ở lần backend kết nối vào database
mới, backend sẽ tự tạo/kiểm tra tài khoản Admin development mặc định:

```text
Username: admin
Email: admin@example.com
Password: password123@
```

Sau khi backend và frontend chạy, có thể đăng nhập bằng username hoặc email ở
trên. Tài khoản được cấu hình qua các biến `DEFAULT_ADMIN_*` trong `.env`. Chỉ
dùng thông tin này khi chạy local; phải thay email và password/hash mặc định
trước khi triển khai demo công khai hoặc production.

Trên Railway/production, pre-deploy chạy `python -m app.bootstrap_admin` sau
Alembic. Đặt `DEFAULT_ADMIN_ENABLED=true`, dùng email thật và một bcrypt hash
mới; hash/mật khẩu development phía trên bị production validator từ chối.

Service backend cần một persistent volume mount tại `/app/outputs` để giữ
Markdown/PDF/DOCX qua các lần deploy. Docker entrypoint tự sửa ownership của
volume mới rồi hạ quyền về `appuser` (UID `10001`); ứng dụng không chạy bằng
root. Cơ chế này cũng áp dụng cho các named volume trong Docker Compose.

Tạo bcrypt hash mới mà không đưa plaintext password vào command history:

```powershell
.\venv\Scripts\python.exe backend\scripts\generate_admin_password_hash.py
```

Việc cần làm đầu tiên trong Admin UI:

1. Vào trang Admin System Config.
2. Mở nhóm `API Keys` và chọn rõ chế độ tạo giáo trình:
   - `Người dùng tự nhập API key`: production mặc định; cần `BYOK_ENCRYPTION_KEY`, người dùng nhập OpenAI/Serper key ở trang tạo giáo trình, không trừ credit.
   - `Nạp tiền bằng credit hệ thống`: admin nhập `OPENAI_API_KEY` hệ thống; credit/top-up/trừ credit chạy như trước.
3. Nếu dùng chế độ nạp tiền bằng credit hệ thống, nhập tối thiểu `OPENAI_API_KEY`; nếu bật ảnh/search thì thêm `SERPER_API_KEY`.
4. Nếu dùng Google OAuth, email reset password hoặc thanh toán thì nhập thêm Google OAuth, SMTP và SePay tương ứng.

Sau khi đăng nhập bằng tài khoản Admin bootstrap, frontend gọi `GET /api/v1/config/admin/setup-status`. Nếu còn thiếu cấu hình bắt buộc, Admin được chuyển tới `/admin/config?setup=1` để điền ngay các mục như SMTP, OpenAI key trong chế độ credit, hoặc tài khoản nhận tiền. Checklist tính giá trị theo thứ tự Admin DB rồi tới `.env`; giá trị đã có trong `.env` được xem là đã cấu hình nhưng vẫn hiển thị rõ nguồn. `BYOK_ENCRYPTION_KEY` không nhập qua Admin UI vì đây là secret gốc phải nằm trong biến môi trường/secret manager.

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

## Operational Notes

- ChromaDB dùng chung persist path `backend/data/chroma_db`, nhưng mỗi generation dùng collection riêng theo textbook/run và có cleanup best-effort sau export. Vẫn nên giữ một worker generation cho bản demo cho tới khi kiểm thử concurrent jobs đầy đủ.
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
