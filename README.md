# 📚 Agentic RAG Curriculum Generator (MVP)

> **Project:** Automated Curriculum Generation System using Multi-Agent AI and RAG.
> **Current Status:** Phase 1 - Data Ingestion & Knowledge Base Construction.

## 📖 Introduction
This project is an **Agentic RAG (Retrieval-Augmented Generation)** system designed to automatically draft academic IT textbooks and curricula based on high-quality open educational resources (**OpenStax**). The system utilizes the **LangGraph** framework to orchestrate a team of AI Agents (Planner, Researcher, Writer) to produce structured, pedagogically sound content.

Currently, the project is in **Phase 1**, focusing on building a robust local Knowledge Base from raw OpenStax source code (XML/HTML).

## 🚀 Tech Stack
* **Language:** Python 3.10+
* **Orchestration:** LangChain & LangGraph
* **Vector Database:** ChromaDB (Local Persistent)
* **Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (Local - Offline capable)
* **Data Processing:** BeautifulSoup4, RecursiveCharacterTextSplitter (LangChain)

---

## 📂 Project Structure
```text
curriculum_rag/
├── data/
│   ├── raw_manual/      # [INPUT] Manually downloaded OpenStax GitHub source code (.zip)
│   ├── extracted/       # [TEMP] Temporary extraction folder for processing
│   └── chroma_db/       # [OUTPUT] Vector Database (Stores Embeddings)
├── src/
│   ├── config.py        # System configuration (Paths, Model parameters)
│   ├── processor.py     # Core Logic: Parse XML -> Chunking -> Embedding
│   └── utils.py         # Utilities (Unzipping, File finding)
├── main_ingest.py       # Entry point for the Data Ingestion Pipeline
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables
└── README.md            # Project documentation#