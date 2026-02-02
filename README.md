# 📚 AI Textbook Generator (AI Curriculum Agent)

> An automated, multi-agent system powered by **LangGraph** and **OpenAI** that researches, plans, writes, reviews, and publishes comprehensive academic textbooks in Vietnamese based on a single user topic.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![LangChain](https://img.shields.io/badge/LangChain-v0.1-green)
![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-red)
![Status](https://img.shields.io/badge/Status-Stable-success)

## 📖 Overview

This project automates the entire lifecycle of educational content creation. Instead of manually writing a textbook, you simply input a topic (e.g., "Machine Learning Basics" or "Start a Bubble Tea Shop"). The system employs a team of AI Agents to browse the web, structure a curriculum, draft content with academic rigor, review for errors, and compile a final PDF.

## ✨ Key Features

* **Multi-Agent Architecture:** Uses **LangGraph** to orchestrate specialized agents (Planner, Researcher, Writer, Reviewer, Publisher).
* **RAG (Retrieval-Augmented Generation):** Crawls real-time data from the web (Google Search) and stores it in **ChromaDB** for accurate, grounded content generation.
* **Academic Quality:**
    * Automatic **Table of Contents** generation using Topic Modeling (NMF).
    * **LaTeX Support:** Handles complex math formulas (`$$E=mc^2$$`) and scientific notation.
    * **Vietnamese Support:** Fully optimized for Vietnamese language output using XeLaTeX.
    * **Review System:** A dedicated Editor Agent fixes formatting, structure, and tone.
* **Modern Frontend:** A user-friendly **Streamlit** interface with real-time progress tracking, logs, and file downloads.
* **Professional Output:** Generates both Markdown (`.md`) and formatted PDF (`.pdf`) with automated TOC, page breaks, and chapter styling.

## 🏗️ System Architecture

The workflow follows a sequential and iterative graph:
graph TD
    A[Start] --> B(Ingestion Node);
    B --> C(Planner Node);
    C --> D{Iterate Chapters};
    D --> E(Researcher Node);
    E --> F(Writer Node);
    F --> G(Reviewer Node);
    G --> H{More Sections?};
    H -- Yes --> E;
    H -- No --> I(Publisher Node);
    I --> J[End / PDF Output];
Agents Description:
Ingestion: Searches Google, crawls websites, chunks text, and embeds into Vector DB.

Planner: Analyzes the knowledge base to create a structured logical curriculum (Chapters & Subsections).

Researcher: Retrieves relevant context from ChromaDB for the specific section being written.

Writer: Drafts the section content using the retrieved context, strictly following LaTeX and Markdown rules.

Reviewer: Acts as a Senior Editor. Checks for logical flow, formatting errors, "hanging headers," and enforces academic tone.

Publisher: Compiles all sections, adds metadata (YAML), and converts the final document to PDF using Pandoc/XeLaTeX.

🛠️ Tech Stack
Core: Python 3.10+

Orchestration: LangChain, LangGraph

LLM: OpenAI (GPT-4o, GPT-4o-mini)

Database: ChromaDB (Vector Store)

Search: DuckDuckGo / SerpApi (Configurable)

Frontend: Streamlit

Document Conversion: Pandoc, PyPandoc, MiKTeX/TeX Live (XeLaTeX engine).

🚀 Installation
1. Prerequisites
Python 3.10 or higher.

Pandoc: Required for PDF generation.

Windows: winget install pandoc

LaTeX Engine: Required for PDF generation (specifically xelatex for Vietnamese).

Windows: Install MiKTeX or TeX Live.

2. Clone the Repository
Bash
git clone [https://github.com/your-username/ai-textbook-generator.git](https://github.com/your-username/ai-textbook-generator.git)
cd ai-textbook-generator
3. Setup Virtual Environment
Bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
4. Install Dependencies
Bash
pip install -r requirements.txt
5. Environment Configuration
Create a .env file in the root directory:

Đoạn mã
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxx
# Optional: If using SerpApi for images/search
SERPAPI_API_KEY=xxxxxxxxxxxxxxxx
🖥️ Usage
Run the Streamlit application:

Bash
streamlit run src/app.py
Open your browser (usually http://localhost:8501).

Enter a Topic (e.g., "Giáo trình Marketing Căn bản").

Adjust Recursion Limit in the sidebar (Default: 150).

Click "🚀 Bắt đầu tạo sách".

Wait for the process to finish and click "⬇️ Download PDF".

📂 Project Structure
Plaintext
.
├── outputs/               # Generated .md and .pdf files
├── src/
│   ├── agents/            # Agent logic
│   │   ├── ingestion.py
│   │   ├── planner.py
│   │   ├── researcher.py
│   │   ├── writer.py      # Includes LaTeX/Header formatting logic
│   │   ├── reviewer.py    # Includes defensive checks & formatting fixes
│   │   └── publisher.py   # PDF conversion logic
│   ├── graph/
│   │   ├── state.py       # Defines AgentState
│   │   └── workflow.py    # LangGraph construction
│   ├── tools/             # Helper tools (Search, Crawler)
│   ├── app.py             # Streamlit Frontend
│   └── config.py          # Configuration settings
├── .env                   # API Keys
├── requirements.txt
└── README.md
🐛 Troubleshooting
PDF Generation Failed:

Ensure pandoc is in your system PATH.

Ensure xelatex (MiKTeX) is installed and packages are updated.

Check logs/agents.log for details.

"Missing Variable" Error:

This has been patched in the latest version by removing f-strings in LangChain prompts. Ensure you pulled the latest code.

Download Button Not Showing:

Fixed via session_state persistence in app.py. Try clearing cache in the sidebar.