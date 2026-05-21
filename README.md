# Curriculum RAG — Agentic AI Textbook Generator

An end-to-end system that turns a single topic string into a complete, publication-ready Vietnamese academic textbook. The core is a **LangGraph multi-agent workflow** that couples **bilingual web crawling** with a **CRAG (Corrective RAG) agentic loop** to produce grounded, peer-reviewed content at scale.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange)
![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-purple)
![Status](https://img.shields.io/badge/Status-Active-success)

---

## System Architecture

The workflow is split into two phases separated by a human-in-the-loop curriculum review gate.

```
Phase 1 — Planning
──────────────────
Validator ──► Planner ──► [REVIEW GATE] (user edits & confirms curriculum)

Phase 2 — Content Generation  (triggered after confirmation)
─────────────────────────────
generate_preface ──► Ingestion ──► [ingestion gate]
                                        ↓
                               ┌─ QueryFormulator ◄──────────────────────┐
                               │        ↓                                 │ RETRY_RETRIEVAL
                               │   RetrieverNode                          │ (missing_context
                               │        ↓                                 │  or insufficient
                               │  ContextEvaluator                        │  context)
                               │    ↓ sufficient    ↓ insufficient        │
                               │    │           (retry once) ─────────────┘
                               │    ↓
                               │  ContentWriter ◄── REVISE (formatting_error)
                               │        ↓
                               │    Reviewer ──► APPROVE ──► Illustrator
                               │                                  ↓ [check_next_step]
                               │              ┌─── update_subsection ─────────────┐
                               │              ├─── update_chapter    ─────────────┤
                               └──────────────┘                                   │
                                                     Publisher ◄── FINISHED ───────┘
                                                         ↓
                                                        END
```

### Agents

| Agent | Responsibility |
|---|---|
| **Validator** | Classifies topic suitability; extracts `content_type`, `core_topic`, `user_requirements` |
| **Planner** | Generates chapter titles → subsections → academic title + preface (3-phase LLM pipeline, no crawling) |
| **Ingestion** | Bilingual query expansion → parallel DuckDuckGo search → URL filter → deep crawl → ChromaDB |
| **QueryFormulator** | Formulates/reformulates ChromaDB retrieval queries per subsection; shifts query angle on retry |
| **RetrieverNode** | Semantic retrieval from ChromaDB using formulated queries; 3-layer quality filtering |
| **ContextEvaluator** | Assesses retrieved context quality; triggers supplemental tool-call fetch rounds (CRAG loop) |
| **ContentWriter** | Generates academic Vietnamese prose (gpt-4.1); enforces heading/math rules and section continuity |
| **Reviewer** | 5-phase editorial pass + JSON quality gate; True Dynamic Routing (missing_context → re-fetch, formatting_error → rewrite) |
| **Illustrator** | Resolves `[IMAGE: title \| hint]` tags → DRAW (gpt-image-1-mini / gpt-image-1.5) / SEARCH / DIAGRAM (Serper) |
| **Publisher** | Merges all sections, applies math/heading fixes, builds Typst front matter, exports PDF + Word |

---

## Search-Crawl Architecture

### 1. Bilingual Query Expansion

`QueryExpansionAgent` (gpt-4o-mini) generates six queries from the curriculum `search_query` field:

```
3 × Vietnamese  →  DuckDuckGo region "vn-vn"
3 × English     →  DuckDuckGo region "us-en"
```

Queries are shaped by `content_type` to target appropriate source kinds:

| content_type | Source hints injected |
|---|---|
| `scholarly` | Wikipedia, academic papers, textbook sites |
| `technical` | GeeksForGeeks, GitHub, official docs |
| `practical` | How-to guides, industry blogs |
| `lifestyle` | wikihow, niche forums |

### 2. Parallel Web Search

`SearchEngine` runs all six queries concurrently (`SEARCH_MAX_WORKERS = 6`, `SEARCH_RESULTS_PER_QUERY = 30`) via `ddgs` (DuckDuckGo Search), returns deduplicated URL + title + snippet dicts.

### 3. URL Filtering (Two Stages)

**Static filter** (`url_filter.py`):
- Blocklisted domains (social media, CDN, shopping, paywalls)
- Rejected extensions (`.zip`, `.exe`, `.mp4`, …)
- Snippet pre-filter: `MIN_SNIPPET_SCORE = 0.3` relevance threshold before any HTTP request

**Dynamic filter** (parallel HTTP HEAD, `URL_FILTER_MAX_WORKERS = 5`):
- Accept `text/html` → HTML crawl pipeline
- Accept `application/pdf` → PDF extraction pipeline
- Reject all other content-type headers

### 4. Deep Crawl

**HTML pipeline** (`crawler.py` / BeautifulSoup4):
1. Fetch page, strip nav/footer/sidebar/ads
2. Extract main prose (`<article>`, `<main>`, largest `<div>`)
3. Follow up to `CRAWL_MAX_SUB_LINKS = 5` internal links at depth-1 (breadth-first)
4. Optionally follow up to `CRAWL_MAX_DEPTH2_LINKS = 3` depth-2 links on high-value domains

**PDF pipeline** (PyMuPDF / pypdf fallback):
1. Extract text page-by-page
2. Detect and skip TOC pages, reference pages, header/footer noise
3. Rejoin broken line breaks from column layouts

### 5. Chunk Quality Pipeline

Every extracted document goes through a 4-step funnel before reaching ChromaDB:

```
RecursiveCharacterTextSplitter (1500 chars, 300 overlap)
        ↓
Heuristic filter
  • MIN_CHUNK_CHARS = 200
  • MIN_ALPHA_RATIO = 0.55   (rejects code dumps, tables of numbers)
  • MAX_DIGIT_RATIO = 0.40
  • MAX_DUPLICATE_LINE_RATIO = 0.4
  • MAX_CITATION_LINE_RATIO = 0.3
  • MAX_BOOKING_SIGNALS = 2  (rejects hotel/e-commerce noise)
        ↓
Relevance scoring  (MIN_RELEVANCE_SCORE = 0.22)
  Weighted by: length · trusted-domain · structure · education-keyword density
  Scoring weights (configurable):
    HEURISTIC_LENGTH_WEIGHT = 0.2
    HEURISTIC_DOMAIN_WEIGHT = 0.25
    HEURISTIC_STRUCTURE_WEIGHT = 0.15
    HEURISTIC_EDUCATION_WEIGHT = 0.15
        ↓
ChromaDB embed + store  (EMBEDDING_BATCH_SIZE = 200, CHROMADB_BATCH_SIZE = 100)
  Language-aware domain cap:
    VI sources  → VI_DOMAIN_CAP = 80 chunks/domain
    EN sources  → EN_DOMAIN_CAP = 35 chunks/domain
    Academic    → unlimited (arxiv, ieee, acm, stanford, mit, …)
  MAX_CHUNKS_TO_EMBED = 1000 per ingestion run
```

---

## CRAG Pipeline Architecture

The content generation loop uses a Corrective RAG (CRAG) pattern with four nodes:

```
QueryFormulator → RetrieverNode → ContextEvaluator → ContentWriter
       ↑                                  |
       └──── RETRY_RETRIEVAL ─────────────┘  (if insufficient, first attempt only)
```

### QueryFormulator

Formulates a ChromaDB retrieval query from the current subsection context. On retry (second pass), shifts the query angle to avoid repeating the same failed search.

### RetrieverNode — Retrieval with 3-Layer Quality Filtering

**Layer 1 — Structural heuristics** (no LLM):  
Prose density, academic metadata patterns, TOC/bibliography detection, domain trust score. Fast pass/fail before spending tokens.
- `RAG_MIN_SUBSTANTIVE_SENTENCES = 2` — minimum sentences per chunk
- `RAG_MIN_AVG_SENTENCE_LEN = 30` — minimum avg sentence length (chars)

**Layer 2 — LLM binary classifier** (gpt-4o-mini):  
Content-type-aware rules. E.g., for `scholarly`: rejects non-peer-reviewed opinion; for `technical`: rejects pure marketing copy. Fail-open: if classifier errors, Layer 1 result is used.

**Layer 3 — Semantic deduplication**:  
Cosine similarity threshold = `RAG_SEMANTIC_DEDUP_THRESHOLD = 0.85` between accepted chunks.  
Domain quotas: max `RAG_TRUSTED_DOMAIN_QUOTA = 3` chunks per trusted edu domain (arxiv, wikipedia…), `RAG_DEFAULT_DOMAIN_QUOTA = 1` chunk per other domain.

**Bilingual detection**: Vietnamese content identified via Unicode diacritic pattern. VI and EN chunks tracked separately in `logs/rag_context.log`.

**Output field**: `state["rag_context"]` — formatted string of accepted chunks.

### ContextEvaluator — CRAG Quality Gate

Assesses whether retrieved context is sufficient to write the section:
- Minimum total chars threshold: `CRAG_CONTEXT_QUALITY_MIN_CHARS = 3000`
- Executes up to `WRITER_RETRIEVAL_MAX_ROUNDS = 3` supplemental tool-call fetch rounds
- If still insufficient after one retry: **fail open** — ContentWriter proceeds regardless

### ContentWriter

Generates Vietnamese academic prose using `LLM_MODEL_PREMIUM` (default: `gpt-4.1`). Key mechanics:

- **Character target** = `SECTION_TYPE_CHAR_TARGETS[section_type]` × `CONTENT_LEVEL_SCALES[content_level]`

  | section_type | base range (chars) |
  |---|---|
  | `light` | 1 500 – 2 500 |
  | `medium` | 3 000 – 4 500 |
  | `deep` | 4 500 – 6 500 |
  | `applied` | 2 500 – 3 500 |

  | content_level | scale |
  |---|---|
  | Ngắn | 0.55× |
  | Trung Bình | 1.0× |
  | Dài | 1.6× |
  | Rất Dài | 2.3× |

- **Section continuity**: `state["section_summaries"]` (one line per completed subsection, truncated to `WRITER_SUMMARY_PREVIEW_CHARS = 200` chars each) is injected as a `[PRIOR SECTIONS — do not repeat]` block. Max `WRITER_MAX_PRIOR_SUMMARIES = 6` entries to guard token budget.

- **Image tagging**: ContentWriter emits `[IMAGE_NEEDED: hint]` placeholders, then `ImageDescriptionGenerator` (gpt-4o-mini) batch-replaces them with `[IMAGE: Vietnamese title | full description]` tags.

### Chapter Header Enforcement (3-layer defence)

Chapter headings (`# CHƯƠNG N: TIÊU ĐỀ`) must appear exactly once at the start of the first subsection of each chapter and never elsewhere.

| Layer | Mechanism |
|---|---|
| **Layer 1** | Prompt directive: explicit `EMIT`/`PROHIBIT` instruction with chapter index context |
| **Layer 2b** | Post-processing: if `# CHƯƠNG` is missing and `emit_header=True`, prepend it deterministically |
| **Layer 2c** | Post-processing: `re.sub` forces title text to `.upper()` even when LLM uses title-case |
| **Layer 3** | State flag: `chapter_header_written = True` prevents re-emission on revision loops |

---

## Reviewer — True Dynamic Routing

Two-step pipeline per subsection:

**Editorial pass** (deterministic):  
LaTeX → Typst math conversion (`\[...\]` → `$$...$$`, inline `\(` → `$`), Unicode subscript normalization, heading level safety (`####` → `###`), blank line enforcement.

**Quality gate** (gpt-4o-mini JSON classifier):  
Six failure rules: character count, naked math, wrong delimiters, tone, paragraph depth, blank lines.

Returns `{needs_revision: bool, feedback: str, rejection_type: str}` with True Dynamic Routing:

| rejection_type | Route | Effect |
|---|---|---|
| *(empty)* | **APPROVE** | → Illustrator |
| `formatting_error` | **REVISE** | → ContentWriter (same context, fix structure) |
| `missing_context` | **RETRY_RETRIEVAL** | → QueryFormulator (full re-retrieval cycle) |

- `revision_number` increments on REVISE; resets to 0 on APPROVE
- **`REVIEWER_MAX_REVISIONS = 2`** — after two failures the section is force-approved to prevent workflow deadlock

---

## Illustrator — Image Resolution Pipeline

```
[IMAGE: title | description]
        ↓
LLM classifier → route_image_request()
   ├── DRAW    → gpt-image-1-mini (default) / gpt-image-1.5 (deep/applied sections)
   │             retry loop (max 2 attempts) + vision validation
   ├── DIAGRAM → Serper Google Images (technical structure requiring precise layout)
   └── SEARCH  → Serper Google Images (real entity: logo, map, photo)
                 candidate retry: max 3 URLs, vision validation per candidate
                 fallback chain: last-downloaded → DRAW result → last-resort DALL-E
        ↓
Download → resize to A4 constraints (max 800×500 px) → RGB PNG conversion
        ↓
Save → outputs/images/<hash>.png  (hash-based deduplication)
        ↓
Replace tag → ![Vietnamese caption](relative/path.png){width=70%}
```

Cross-drive path issue (Typst exit 43): Publisher redirects Pandoc TEMP to `BASE_DIR/.pandoc_tmp` (same drive as `.typ` file) and passes `--pdf-engine-opt=--root` + `--pdf-engine-opt=D:\`.

---

## Publisher — Assembly and Export

1. Merge `final_content` (all committed subsections) + `current_content` (last subsection buffer)
2. Fix passes (deterministic, in order):
   - `fix_unicode_math` → Unicode sub/superscripts to `$...$`
   - `fix_markdown_headings` → headings on own lines
   - `fix_inline_display_math` → trivial `$$x$$` → `$x$`
   - `fix_math_formatting` → Typst-compatible math cleanup
   - `fix_typst_deprecated_symbols` → `times.circle` → `times.o`
   - `fix_chapter_pagebreaks` → `#pagebreak()` before each `# CHƯƠNG`
   - `add_figure_numbers` → prefix captions with "Hình X.Y.N:"
3. Assemble Typst front matter: title page → Mục lục → [Danh mục hình] → body (Lời nói đầu = page 1)
4. Export via **Pandoc + Typst** (PDF) and **python-docx** (Word)
   - Word: strip Typst blocks, inject OpenXML page breaks, Times New Roman via `reference.docx`

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Orchestration** | LangGraph, LangChain |
| **LLM (cheap slot)** | `gpt-4o-mini` — validator, planner (Phase 1–2), query expansion, reviewer gate, context evaluation, image description |
| **LLM (premium slot)** | `gpt-4.1` — planner (Phase 3 metadata), content writer |
| **Image generation** | `gpt-image-1-mini` (default) / `gpt-image-1.5` (premium, deep/applied) |
| **Embeddings** | `text-embedding-3-small` (OpenAI, default) or `BAAI/bge-m3` (local HuggingFace) |
| **Vector store** | ChromaDB (persistent, `data/chroma_db/`) |
| **Web search** | DuckDuckGo Search (`ddgs`) — bilingual `vn-vn` + `us-en` regions |
| **Image search** | Serper Google Images API |
| **HTML scraping** | Requests, BeautifulSoup4, lxml, fake-useragent |
| **PDF extraction** | PyMuPDF (`fitz`), pypdf (fallback) |
| **Document export** | Pandoc + Typst engine (PDF), python-docx (Word) |
| **Task queue** | Celery + Redis |
| **API** | FastAPI, SQLAlchemy (async), MySQL, Alembic |

---

## Configuration Reference

All settings live in `backend/app/config.py` as a Pydantic `Settings` class and can be overridden via `.env`. A startup validator logs warnings for critical settings that deviate from recommended defaults.

```env
# ── API Keys ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY=...          # Required — LLM + embeddings + image generation
ANTHROPIC_API_KEY=...       # Required — langchain-anthropic backend
GROQ_API_KEY=...            # Required — Groq LLM backend
GEMINI_API_KEY=...          # Required — Google GenAI backend
SERPER_API_KEY=             # Optional — enables SEARCH/DIAGRAM image modes

# ── LLM Models (configurable per deployment) ──────────────────────────────────
LLM_MODEL_CHEAP=gpt-4o-mini         # Validator, planner ph1-2, reviewer gate
LLM_MODEL_PREMIUM=gpt-4.1           # Planner ph3 (metadata), ContentWriter
IMAGE_MODEL_DEFAULT=gpt-image-1-mini # Default image generation model
IMAGE_MODEL_PREMIUM=gpt-image-1.5   # Premium image generation (deep/applied)

# ── Embedding ─────────────────────────────────────────────────────────────────
EMBEDDING_PROVIDER=openai           # "openai" (fast, API) or "local" (BAAI/bge-m3, free)
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_MODEL_NAME=BAAI/bge-m3    # Used only when EMBEDDING_PROVIDER=local
EMBEDDING_BATCH_SIZE=200            # Embedding API batch size
CHROMADB_BATCH_SIZE=100             # ChromaDB insertion batch size

# ── RAG Retrieval ─────────────────────────────────────────────────────────────
RAG_INITIAL_K=5             # Researcher first retrieval (RetrieverNode)
RAG_TOOL_K=5                # Tool-call retrieval per supplemental round
RAG_TOP_K=5                 # Total top-k after merging rounds
RAG_TOOL_MAX_ROUNDS=4       # Max EvaluatorAgent tool-call rounds per subsection
WRITER_RETRIEVAL_MAX_ROUNDS=3  # Max ContextRetrievalAgent loop rounds

# ── CRAG Quality Gate ─────────────────────────────────────────────────────────
CRAG_CONTEXT_QUALITY_MIN_CHARS=3000  # Min chars for context to be "sufficient"
                                      # ⚠️ Lowering causes ContentWriter to write with sparse context
CRAG_MAX_CONTEXT_RETRIES=2           # Max retries before ContentWriter proceeds (fail-open)
                                      # ⚠️ Raising increases per-subsection latency ~3-5s per retry

# ── Content Generation ────────────────────────────────────────────────────────
REVIEWER_MAX_REVISIONS=2             # Max revision cycles before force-approve
                                      # ⚠️ 0 disables quality gate; >3 significantly increases time
WRITER_SUMMARY_PREVIEW_CHARS=200     # Chars per section summary entry in context
WRITER_MAX_PRIOR_SUMMARIES=6         # Max prior summaries in Writer prompt (token budget)
                                      # ⚠️ Raising may cause context overflow

# ── Chunking ──────────────────────────────────────────────────────────────────
CHUNK_SIZE=1500             # ⚠️ Affects all downstream RAG quality
CHUNK_OVERLAP=300

# ── Crawl Speed ───────────────────────────────────────────────────────────────
SEARCH_RESULTS_PER_QUERY=30
SEARCH_MAX_WORKERS=6
CRAWL_MAX_WORKERS=5
URL_FILTER_MAX_WORKERS=5
CRAWL_MAX_SUB_LINKS=5       # Depth-1 internal links per page
CRAWL_MAX_DEPTH2_LINKS=3    # Depth-2 links on high-value domains
INDICATE_LINKS_FOR_PICS=12  # Links scanned specifically for image candidates
TARGETED_CRAWL_QUERIES_PER_CHAPTER=2   # Curriculum-grounded queries per chapter
TARGETED_CRAWL_MAX_QUERIES=12          # Hard cap on total targeted queries

# ── Chunk Quality Filters ─────────────────────────────────────────────────────
MIN_CHUNK_CHARS=200
MIN_ALPHA_RATIO=0.55
MAX_DIGIT_RATIO=0.40
MIN_RELEVANCE_SCORE=0.22    # ⚠️ Controls ChromaDB post-filter richness
MAX_BOOKING_SIGNALS=2
MAX_DUPLICATE_LINE_RATIO=0.4
MAX_CITATION_LINE_RATIO=0.3
MIN_SNIPPET_SCORE=0.3       # Pre-filter before any HTTP request
                             # ⚠️ Too low floods ingestion; too high starves niche topics

# ── Heuristic Scoring Weights ─────────────────────────────────────────────────
HEURISTIC_LENGTH_WEIGHT=0.2
HEURISTIC_DOMAIN_WEIGHT=0.25
HEURISTIC_STRUCTURE_WEIGHT=0.15
HEURISTIC_EDUCATION_WEIGHT=0.15

# ── RAG Chunk Quality ─────────────────────────────────────────────────────────
RAG_MIN_SUBSTANTIVE_SENTENCES=2
RAG_MIN_AVG_SENTENCE_LEN=30
RAG_TRUSTED_DOMAIN_QUOTA=3          # Max chunks from a single trusted edu domain
                                     # ⚠️ Controls single-source dominance
RAG_DEFAULT_DOMAIN_QUOTA=1          # Max chunks from non-trusted domains
RAG_SEMANTIC_DEDUP_THRESHOLD=0.85   # Cosine similarity ceiling for deduplication
                                     # ⚠️ Lowering removes more; raising allows near-duplicates
RAG_CHUNK_SWEET_SPOT_MIN=300
RAG_CHUNK_SWEET_SPOT_MAX=1500
RAG_CHUNK_SENT_LEN_MIN=40
RAG_CHUNK_SENT_LEN_MAX=200

# ── Domain Caps ───────────────────────────────────────────────────────────────
VI_DOMAIN_CAP=80            # VI sources: more chunks/domain (scarcer content)
EN_DOMAIN_CAP=35            # EN sources: moderate restriction
MAX_CHUNKS_PER_DOMAIN=25    # Base cap for unlisted domains
MAX_CHUNKS_TO_EMBED=1000    # Per ingestion run

# ── Database ──────────────────────────────────────────────────────────────────
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=textbook_user
MYSQL_PASSWORD=...
MYSQL_DATABASE=ai_textbook_db

# ── Redis (Celery broker) ─────────────────────────────────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379

# ── SMTP (email verification) ────────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
EMAIL_FROM=...

# ── Authentication & Security ────────────────────────────────────────────────
SECRET_KEY=...                              # Min 32 chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_HOURS=24
REMEMBER_ME_EXPIRE_DAYS=30

# ── Google OAuth ─────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

# ── Payment (SePay) ───────────────────────────────────────────────────────────
SEPAY_API_KEY=
SEPAY_ACCOUNT_NUMBER=

# ── Application URLs ─────────────────────────────────────────────────────────
FRONTEND_URL=http://localhost:5173
BACKEND_URL=http://localhost:8000
ENVIRONMENT=development

# ── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR=data/chroma_db
CHROMA_COLLECTION_NAME=curriculum_knowledge
```

> **Critical settings**: `config.py` logs a startup warning for any of these deviating from defaults:
> `REVIEWER_MAX_REVISIONS`, `CRAG_CONTEXT_QUALITY_MIN_CHARS`, `MIN_SNIPPET_SCORE`,
> `RAG_TOP_K`, `CHUNK_SIZE`, `MIN_RELEVANCE_SCORE`, `RAG_TRUSTED_DOMAIN_QUOTA`, `WRITER_MAX_PRIOR_SUMMARIES`

---

## Installation

### Prerequisites

```bash
# Pandoc
winget install pandoc          # Windows
brew install pandoc            # macOS

# Typst (PDF engine — UTF-8 native, no extra font packages needed)
winget install typst.typst     # Windows
brew install typst             # macOS
```

### Backend

```bash
git clone <repo>
cd curriculum_rag/backend

python -m venv venv
venv\Scripts\activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp ../.env.example .env        # fill in API keys

# Database
alembic upgrade head

# Start services (separate terminals)
uvicorn app.main:app --reload --port 8000
celery -A app.celery_app worker --loglevel=info
```

### Frontend

```bash
cd curriculum_rag/frontend
npm install
npm run dev                    # http://localhost:5173
```

---

## Project Structure (Core)

```
curriculum_rag/
├── backend/
│   ├── app/
│   │   ├── config.py                        # Settings singleton, embedding model factory
│   │   ├── ingestion/
│   │   │   ├── crawler.py                   # HTML + PDF extraction, depth-1/2 link following
│   │   │   ├── search_engine.py             # DuckDuckGo bilingual wrapper (ddgs)
│   │   │   ├── url_filter.py                # Static + dynamic URL filter (parallel HEAD)
│   │   │   └── query_expansion.py           # LLM bilingual query generator
│   │   └── services/textbook/
│   │       ├── orchestrator.py              # LangGraph graph builders + routing functions
│   │       ├── workflow_runner.py           # Graph execution + DB progress updates
│   │       ├── validator.py                 # Topic classification → content_type, core_topic
│   │       ├── planner.py                   # HybridPlanner: 3-phase LLM curriculum generation
│   │       ├── ingester.py                  # 5-step ingestion pipeline
│   │       ├── query_formulator.py          # CRAG: ChromaDB query formulation / reformulation
│   │       ├── retriever.py                 # CRAG: ChromaDB semantic retrieval + 3-layer filter
│   │       ├── evaluator.py                 # CRAG: context quality assessment + supplemental fetch
│   │       ├── writer.py                    # ContentWriter: academic prose + image tag generation
│   │       ├── reviewer.py                  # ReviewerAgent: editorial pass + True Dynamic Routing
│   │       ├── illustrator.py               # IllustratorAgent: DRAW / SEARCH / DIAGRAM routing
│   │       └── publisher.py                 # Math/heading fix passes + Typst/Word export
│   ├── alembic/                             # DB migrations
│   └── logs/                               # Per-agent log files + logs/prompts/ audit trail
│
├── data/chroma_db/                          # Persistent vector store (auto-created)
└── outputs/                                 # Generated .md / .pdf / .docx + images/
```

---

## License

MIT
