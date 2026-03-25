# 📚 AI Textbook Generator (AI Curriculum Agent)

> An automated, multi-agent system powered by **LangGraph** and **OpenAI** that researches, plans, writes, reviews, and publishes comprehensive academic textbooks in Vietnamese based on a single user topic.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![LangChain](https://img.shields.io/badge/LangChain-v0.1-green)
![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-red)
![Status](https://img.shields.io/badge/Status-Stable-success)

---

## 📖 Overview

This project automates the entire lifecycle of educational content creation. Instead of manually writing a textbook, you simply input a topic (e.g., "Machine Learning Basics" or "Start a Bubble Tea Shop"). The system employs a team of AI Agents to browse the web, structure a curriculum, draft content with academic rigor, review for errors, and compile a final PDF.

---

## ✨ Key Features

* **Multi-Agent Architecture:** Uses **LangGraph** to orchestrate 8 specialized agents — Validator, Ingester, Planner, Researcher, Writer, Reviewer, Illustrator, Publisher.
* **RAG (Retrieval-Augmented Generation):** Bilingual web search (Vietnamese + English via DuckDuckGo) crawls real-time content and stores it in **ChromaDB** for accurate, grounded generation.
* **Curriculum Review Gate:** After planning, users can inspect, edit, and approve the chapter/subsection structure before content generation starts.
* **Academic Quality:**
    * Two-phase Planner generates an academic title (`textbook_title`) and a Lời nói đầu (`preface_content`) via dedicated LLM calls.
    * **LaTeX/Unicode math support:** Handles `$$E=mc^2$$` and Unicode math symbols in PDF output.
    * **Vietnamese-first:** Output fully optimized for Vietnamese using Typst as PDF engine (UTF-8 native, no extra font packages).
    * **Revision loop:** Reviewer enforces quality gate (max 2 revisions per section); approved sections advance automatically.
* **AI Image Pipeline:**
    * Writer tags images as `> [IMAGE: title | description]`.
    * Illustrator routes each tag to **DRAW** (DALL-E 3), **DIAGRAM**, or **SEARCH** (Serper Google Images).
    * Images saved locally; Pandoc embeds them as `![caption](path){width=70%}` figures.
* **Multi-format Export:** Generates Markdown (`.md`), PDF (`.pdf` via Pandoc + Typst), and Word (`.docx`) from a single run.
* **Modern Frontend:** **Streamlit** interface with real-time progress cards, live log streaming, curriculum editor, and one-click downloads.
* **Configurable PDF Styling:** Font sizes, TOC title, and chapter header sizes controlled via `.env` variables.

---

## 🏗️ System Architecture

### **LangGraph Workflow (10 nodes)**

```
validator → ingestion → planner ──► [Curriculum Review Gate — user edits & approves]
                                              │
                                         researcher
                                              │
                                           writer
                                              │
                                          reviewer
                                         ╱         ╲
                              (REVISE)→ writer   (APPROVE)
                                                     │
                                               illustrator
                                              ╱     │      ╲
                               next_subsection  next_chapter  finished
                                      │               │          │
                               update_subsection  update_chapter  publisher → END
                                      └──────────────┘
                                           researcher
```

### **Agent Responsibilities**

| Agent | Role |
|-------|------|
| **Validator** | Checks that the user topic is suitable for textbook generation before any costly steps run |
| **Ingester** | Runs 6 parallel DuckDuckGo searches (3 Vietnamese × `vn-vn` + 3 English × `us-en`), crawls pages, chunks text, embeds into ChromaDB |
| **Planner** | Builds chapter/subsection curriculum; generates academic `textbook_title` and `preface_content` (Lời nói đầu) via dedicated LLM calls |
| **Researcher** | Retrieves RAG context from ChromaDB for each section being written |
| **Writer** | Drafts section content in Vietnamese Markdown with word-count targets; injects `> [IMAGE: title \| description]` tags |
| **Reviewer** | Quality gate — enforces heading hierarchy, academic tone, min word count; returns JSON `{approve/revise, feedback}`; max 2 revisions |
| **Illustrator** | Routes each image tag to **DRAW** (DALL-E 3), **DIAGRAM**, or **SEARCH** (Serper); saves PNG locally; replaces tag with Pandoc figure block |
| **Publisher** | Assembles all sections, adds YAML front-matter, generates centered TOC (tocloft), converts to PDF (Pandoc + Typst) and Word (.docx) |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Orchestration** | LangGraph, LangChain |
| **LLM** | OpenAI GPT-4o-mini (cheap & premium slots) |
| **Embeddings** | `sentence-transformers/all-MiniLM-L6-v2` (local, via HuggingFace) |
| **Vector DB** | ChromaDB |
| **Web Search** | DuckDuckGo Search (`duckduckgo-search`) — bilingual VI + EN |
| **Image Search** | Serper Google Images API (`SERPER_API_KEY`) |
| **Image Generation** | DALL-E 3 (reuses `OPENAI_API_KEY`) |
| **Web Scraping** | Requests, BeautifulSoup4, lxml, fake-useragent |
| **Document Export** | Pandoc + Typst (PDF), python-docx (Word) |
| **Frontend** | Streamlit |
| **Runtime** | Python 3.10+ |

---

## ⚙️ Installation & Prerequisites

### **Step 1: System Tools (Mandatory)**

#### 1.1 Pandoc

* **Windows:** `winget install pandoc`
* **Mac/Linux:** `brew install pandoc` / `sudo apt-get install pandoc`
* **Verify:** `pandoc --version`

#### 1.2 Typst (PDF engine)

Typst is lightweight and supports UTF-8/Vietnamese natively — no extra font packages needed.

* **Windows:** `winget install typst.typst`
* **Mac:** `brew install typst`
* **Linux:** `snap install typst`
* **Verify:** `typst --version`

### **Step 2: Python Setup**

```bash
git clone <repository-url>
cd curriculum_rag

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### **Step 3: Environment Configuration**

Create a `.env` file in the project root:

```env
# Required
OPENAI_API_KEY=your_openai_api_key_here

# Optional — enables image search (Illustrator SEARCH/DIAGRAM modes)
SERPER_API_KEY=your_serper_api_key_here

# Optional — PDF styling overrides (defaults shown)
PDF_BODY_FONTSIZE=12pt
PDF_CHAPTER_FONTSIZE=Huge
PDF_TOC_TITLE=MỤC LỤC
```

> **Note:** `OPENAI_API_KEY` is required. Without `SERPER_API_KEY`, image search is disabled; DALL-E 3 image generation still works (it reuses the OpenAI key).

---

## 🖥️ Usage

### **Running the Application**

Run the Streamlit application:

```bash
streamlit run app.py
```

### **Using the Interface**

1. **Open your browser:** (Usually http://localhost:8501)

2. **Generate a Book:**
   * Enter a Topic (e.g., "Giáo trình Kỹ thuật Trồng Lan")
   * Adjust Recursion Limit if the book is long (Default: 150)
   * Click "🚀 Bắt đầu tạo sách"

3. **Download:**
   * Wait for the process to finish (Ingestion → Planning → Writing...)
   * Click the "⬇️ Download PDF" button when it appears

---

## 📂 Project Structure

```
curriculum_rag/
├── app.py                        # Streamlit entry point (UI phases: idle/planning/reviewing/generating/done)
├── backend.py                    # LangGraph runner (Phase A: ingestion+planning; Phase B: content loop)
├── requirements.txt
├── .env                          # API keys & PDF styling (not in repo)
│
├── src/
│   ├── config.py                 # API keys, paths, model names, crawl speed knobs, PDF env vars
│   ├── log_config.py
│   ├── stop_signal.py            # Graceful stop flag shared between UI and backend threads
│   │
│   ├── agents/
│   │   ├── validator.py          # Topic suitability check (runs before ingestion)
│   │   ├── ingester.py           # 6-query bilingual search + crawl + ChromaDB embed
│   │   ├── planner.py            # Curriculum structure + academic title + preface
│   │   ├── researcher.py         # RAG retrieval per section
│   │   ├── writer.py             # Section drafting with word-count targets
│   │   ├── reviewer.py           # Quality gate (JSON approve/revise, max 2 revisions)
│   │   ├── illustrator.py        # Image tag router: DRAW (DALL-E 3) / SEARCH / DIAGRAM (Serper)
│   │   ├── publisher.py          # Final assembly → Markdown, PDF (Pandoc+Typst), Word
│   │   └── query_expansion.py    # LLM-based search query expansion
│   │
│   ├── graph/
│   │   ├── state.py              # AgentState, SubSection, SECTION_TYPE_WORD_TARGETS
│   │   └── workflow.py           # LangGraph edges, route_after_review, check_next_step
│   │
│   ├── ingestion/
│   │   ├── search_engine.py      # DuckDuckGo wrapper (vn-vn + us-en regions)
│   │   ├── crawler.py            # HTML scraper with sub-link following
│   │   └── url_filter.py         # Parallel content-type probe (filters PDFs, binaries)
│   │
│   └── ui/
│       ├── components.py         # Streamlit widgets: sidebar, curriculum editor, status cards
│       ├── events.py             # Event queue processing (progress updates from backend)
│       └── styles.css
│
├── data/
│   └── chroma_db/                # Persistent vector store (auto-created)
│
├── outputs/                      # Generated files: <title>_<timestamp>.{md,pdf,docx}
│   └── images/                   # Downloaded/generated images (PNG)
│
├── logs/                         # Per-module log files + prompts/ subdirectory
│
└── tests/
    ├── test_image_insertion.py   # PDF image pipeline (no LLM required)
    ├── test_dalle3.py
    ├── test_ddgs_search.py
    └── test_planner_pipeline.py
```

---

## 🐛 Troubleshooting

### PDF generation fails (exit code 43 / images not found)

This happens when images and the `.typ` file are on different drives. The fix is already applied in `publisher.py` (TEMP redirected to `BASE_DIR/.pandoc_tmp`, `--root D:\` passed to Typst). If you still see it:

* Confirm `pandoc --version` and `typst --version` are both on PATH.
* Run `tests/test_image_insertion.py` — it reproduces the full pipeline without any LLM calls.

### Images missing in PDF

* `SERPER_API_KEY` not set → SEARCH/DIAGRAM modes are disabled; only DALL-E 3 DRAW mode works.
* Check `logs/agents.log` for `[Illustrator]` error lines.
* Verify `outputs/images/` contains the downloaded PNGs.

### Validator rejects a valid topic

The Validator agent checks topic suitability before ingestion runs. If it incorrectly blocks a topic, check `logs/agents.log` for the validator response and adjust the topic wording.

### Slow ingestion

Tune the speed knobs in `src/config.py` (or override via `.env`):

```
SEARCH_RESULTS_PER_QUERY  # default 20 — lower to 5 for quick tests
CRAWL_MAX_WORKERS         # default 5
CRAWL_MAX_SUB_LINKS       # default 5 — lower to 1 for quick tests
```

### ChromaDB errors on restart

The vector store in `data/chroma_db/` persists between runs. If you see schema errors, delete the folder and re-run ingestion.

---

## 📄 License

This project is licensed under the **MIT License**.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📧 Contact

For questions or support, please open an issue on GitHub.

---