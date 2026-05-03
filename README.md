# Curriculum RAG — Agentic AI Textbook Generator

An end-to-end system that turns a single topic string into a complete, publication-ready Vietnamese academic textbook. The core is a **LangGraph multi-agent workflow** that couples **bilingual web crawling** with an **agentic RAG loop** to produce grounded, peer-reviewed content at scale.

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
Ingestion ──► ┌─ Researcher ─► Writer ─► Reviewer ─┐
              │                          ↑   REVISE  │
              │                          └───────────┘
              │                              APPROVE
              │                               ↓
              │                          Illustrator
              │                               ↓
              └──── check_next_step ─────────────────► Publisher ──► END
                     (next subsection / next chapter / finished)
```

### Agents

| Agent | Responsibility |
|---|---|
| **Validator** | Classifies topic suitability; extracts `content_type`, `core_topic`, `user_requirements` |
| **Planner** | Generates chapter titles → subsections → academic title + preface (3-phase LLM pipeline, no crawling) |
| **Ingestion** | Bilingual query expansion → parallel DuckDuckGo search → URL filter → deep crawl → ChromaDB |
| **Researcher** | Per-subsection semantic retrieval with 3-layer quality filtering and bilingual deduplication |
| **Writer** | Agentic RAG loop: context enrichment tool calls → draft → post-processing; enforces heading/math rules |
| **Reviewer** | 5-phase editorial pass + JSON quality gate; routes back to Writer (max 2 revisions) or advances |
| **Illustrator** | Resolves `[IMAGE: title \| hint]` tags → DRAW (gpt-image-1) / SEARCH / DIAGRAM (Serper) |
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

`SearchEngine` runs all six queries concurrently (`SEARCH_MAX_WORKERS = 6`, `SEARCH_RESULTS_PER_QUERY = 30`) via `duckduckgo-search`, returns deduplicated URL + title + snippet dicts.

### 3. URL Filtering (Two Stages)

**Static filter** (`url_filter.py`):
- Blocklisted domains (social media, CDN, shopping, paywalls)
- Rejected extensions (`.zip`, `.exe`, `.mp4`, …)
- Snippet pre-filter: topic relevance score must exceed threshold before any HTTP request

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
RecursiveCharacterTextSplitter (2000 chars, 400 overlap)
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
        ↓
ChromaDB embed + store  (batch = 200 embeddings, 100 docs/insert)
  Language-aware domain cap:
    VI sources  → VI_DOMAIN_CAP = 50 chunks/domain
    EN sources  → EN_DOMAIN_CAP = 35 chunks/domain
    Academic    → unlimited (arxiv, ieee, acm, stanford, mit, …)
  MAX_CHUNKS_TO_EMBED = 1000 per ingestion run
```

---

## Agentic RAG Architecture

### Researcher — Retrieval with 3-Layer Quality Filtering

Each subsection triggers an independent retrieval call using the curriculum's `search_query` field (optionally extended with `user_requirements` keywords).

**Layer 1 — Structural heuristics** (no LLM):  
Prose density, academic metadata patterns, TOC/bibliography detection, domain trust score. Fast pass/fail before spending tokens.

**Layer 2 — LLM binary classifier** (gpt-4o-mini):  
Content-type-aware rules. E.g., for `scholarly`: rejects non-peer-reviewed opinion; for `technical`: rejects pure marketing copy. Fail-open: if classifier errors, Layer 1 result is used.

**Layer 3 — Semantic deduplication**:  
Cosine similarity threshold = 0.85 between accepted chunks. Deduplication also runs at the source level: max 3 chunks per trusted domain, 1 chunk per other domain.

**Bilingual detection**: Vietnamese content identified via Unicode diacritic pattern. VI and EN chunks are tracked separately in logs (`logs/rag_context.log` — full audit trail per subsection).

**Output field**: `state["rag_context"]` — a formatted string of accepted chunks passed to the Writer.

### Writer — Agentic Context Enrichment Loop

The Writer runs three components in sequence:

**Component 1: ContextRetrievalAgent** (gpt-4o-mini + tool calling)  
Assesses whether initial `rag_context` is sufficient. If not, calls `retrieve_context_tool` (up to **2 rounds**) with new queries, tracking already-used queries to prevent repeats. Returns enriched context.

**Component 2: ContentWriter** (gpt-4o)  
Generates Vietnamese academic prose. Key mechanics:

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

- **Section continuity**: `state["section_summaries"]` (one line per completed subsection) is injected as a `[PRIOR SECTIONS — do not repeat]` block to prevent thematic drift across a long textbook.

- **Image tagging**: Writer emits `[IMAGE_NEEDED: hint]` placeholders.

**Component 3: ImageDescriptionGenerator** (gpt-4o-mini)  
Batch-replaces `[IMAGE_NEEDED: hint]` → `[IMAGE: Vietnamese title | full description]` tags that Illustrator later resolves.

### Chapter Header Enforcement (3-layer defence)

Chapter headings (`# CHƯƠNG N: TIÊU ĐỀ`) must appear exactly once at the start of the first subsection of each chapter and never elsewhere.

| Layer | Mechanism |
|---|---|
| **Layer 1** | Prompt directive: explicit `EMIT`/`PROHIBIT` instruction with chapter index context |
| **Layer 2b** | Post-processing: if `# CHƯƠNG` is missing and `emit_header=True`, prepend it deterministically |
| **Layer 2c** | Post-processing: `re.sub` forces title text to `.upper()` even when LLM uses title-case |
| **Layer 3** | State flag: `chapter_header_written = True` prevents re-emission on revision loops |

### Reviewer — Quality Gate

Two-step pipeline per subsection:

**Editorial pass** (deterministic):  
LaTeX → Typst math conversion (`\[...\]` → `$$...$$`, inline `\(` → `$`), Unicode subscript normalization, heading level safety (`####` → `###`), blank line enforcement.

**Quality gate** (gpt-4o-mini JSON classifier):  
Six failure rules: character count, naked math, wrong delimiters, tone, paragraph depth, blank lines.

- Returns `{needs_revision: bool, feedback: str}`  
- `revision_number` increments on REVISE; resets to 0 on APPROVE  
- **MAX_REVISIONS = 2** — after two failures the section is force-approved to prevent workflow deadlock

---

## Illustrator — Image Resolution Pipeline

```
[IMAGE: title | description]
        ↓
LLM classifier → route_image_request()
   ├── DRAW    → gpt-image-1 (conceptual/artistic)
   │             model selection: deep/applied → premium, light/medium → default
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
| **LLM (cheap slot)** | `gpt-4o-mini` — validator, planner, query expansion, reviewer gate, context retrieval, image description |
| **LLM (premium slot)** | `gpt-4o` — content writer |
| **Image generation** | `gpt-image-1` / `gpt-image-1.5` |
| **Embeddings** | `text-embedding-3-small` (OpenAI, default) or `BAAI/bge-m3` (local HuggingFace) |
| **Vector store** | ChromaDB (persistent, `data/chroma_db/`) |
| **Web search** | DuckDuckGo Search — bilingual `vn-vn` + `us-en` regions |
| **Image search** | Serper Google Images API |
| **HTML scraping** | Requests, BeautifulSoup4, lxml, fake-useragent |
| **PDF extraction** | PyMuPDF (`fitz`), pypdf (fallback) |
| **Document export** | Pandoc + Typst engine (PDF), python-docx (Word) |
| **Task queue** | Celery + Redis |
| **API** | FastAPI, SQLAlchemy (async), MySQL, Alembic |

---

## Configuration Reference

Key settings in `.env` (see `backend/app/config.py` for full list):

```env
# API Keys
OPENAI_API_KEY=...          # Required
GROQ_API_KEY=...            # Required
GEMINI_API_KEY=...          # Required
SERPER_API_KEY=...          # Optional — enables SEARCH/DIAGRAM image modes

# Embedding
EMBEDDING_PROVIDER=openai   # "openai" (fast, API) or "local" (BAAI/bge-m3, free)

# RAG
RAG_INITIAL_K=3             # Researcher first retrieval
RAG_TOOL_K=3                # Tool call retrieval (Writer enrichment rounds)
RAG_TOP_K=8                 # Total top-k after merging rounds

# Chunking
CHUNK_SIZE=2000
CHUNK_OVERLAP=400

# Crawl speed
SEARCH_RESULTS_PER_QUERY=30
SEARCH_MAX_WORKERS=6
CRAWL_MAX_WORKERS=5
CRAWL_MAX_SUB_LINKS=5       # depth-1 internal links per page
CRAWL_MAX_DEPTH2_LINKS=3    # depth-2 links on high-value domains

# Quality gates
MIN_CHUNK_CHARS=200
MIN_ALPHA_RATIO=0.55
MAX_DIGIT_RATIO=0.40
MIN_RELEVANCE_SCORE=0.22

# Domain caps
VI_DOMAIN_CAP=50
EN_DOMAIN_CAP=35
MAX_CHUNKS_TO_EMBED=1000
```

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
│   │   │   ├── search_engine.py             # DuckDuckGo bilingual wrapper
│   │   │   ├── url_filter.py                # Static + dynamic URL filter (parallel HEAD)
│   │   │   └── query_expansion.py           # LLM bilingual query generator
│   │   └── services/textbook/
│   │       ├── orchestrator.py              # LangGraph graph builders (planning / content)
│   │       ├── workflow_runner.py           # Graph execution + DB progress updates
│   │       ├── validator.py                 # Topic classification → content_type, core_topic
│   │       ├── planner.py                   # HybridPlanner: 3-phase LLM curriculum generation
│   │       ├── ingester.py                  # 5-step ingestion pipeline
│   │       ├── researcher.py                # ResearcherAgent: 3-layer RAG retrieval
│   │       ├── writer.py                    # WriterAgent: agentic context loop + content draft
│   │       ├── reviewer.py                  # ReviewerAgent: editorial pass + quality gate
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
