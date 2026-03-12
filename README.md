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

* **Multi-Agent Architecture:** Uses **LangGraph** to orchestrate specialized agents (Planner, Researcher, Writer, Reviewer, Publisher).
* **RAG (Retrieval-Augmented Generation):** Crawls real-time data from the web (Google Search) and stores it in **ChromaDB** for accurate, grounded content generation.
* **Academic Quality:**
    * Automatic **Table of Contents** generation using Topic Modeling (NMF).
    * **LaTeX Support:** Handles complex math formulas (`$$E=mc^2$$`) and scientific notation.
    * **Vietnamese Support:** Fully optimized for Vietnamese language output using Typst.
    * **Review System:** A dedicated Editor Agent fixes formatting, structure, and tone.
* **Modern Frontend:** A user-friendly **Streamlit** interface with real-time progress tracking, logs, and file downloads.
* **Professional Output:** Generates both Markdown (`.md`) and formatted PDF (`.pdf`) with automated TOC, page breaks, and chapter styling.

---

## 🏗️ System Architecture

### **Workflow Components**

**Ingestion**: Searches Google, crawls websites, chunks text, and embeds into Vector DB.

**Planner**: Analyzes the knowledge base to create a structured logical curriculum (Chapters & Subsections).

**Researcher**: Retrieves relevant context from ChromaDB for the specific section being written.

**Writer**: Drafts the section content using the retrieved context, following standard Markdown rules.

**Reviewer**: Acts as a Senior Editor. Checks for logical flow, formatting errors, "hanging headers," and enforces academic tone.

**Illustrator**: Scans content for image suggestions, downloads images from Google (via SerpApi), converts them to PNG, and embeds them into the document.

**Publisher**: Compiles all sections, adds metadata (YAML), generates Table of Contents, and converts the final document to PDF using Pandoc/Typst.

---

## 🛠️ Tech Stack

### **Core Technologies**

* **Core:** Python 3.10+
* **Orchestration:** LangChain, LangGraph
* **LLM:** OpenAI (GPT-4o, GPT-4o-mini)
* **Database:** ChromaDB (Vector Store)
* **Search & Media:** SerpApi (Google Search & Images), Requests, Pillow (Image Processing)
* **Frontend:** Streamlit
* **Document Conversion:** Pandoc, PyPandoc, Typst

---

## ⚙️ Installation & Prerequisites

This project requires both System Tools (for PDF generation) and Python Libraries. Please follow the steps below in order.

### **Step 1: System Requirements (Mandatory)**

You must install these tools on your computer before running the code.

#### **1.1 Pandoc (Universal Document Converter)**

* **Windows:** Download installer from [pandoc.org](https://pandoc.org) or run `winget install pandoc`
* **Mac/Linux:** `brew install pandoc` or `sudo apt-get install pandoc`
* **Verify:** Open terminal and type `pandoc --version`

#### **1.2 Typst (PDF Compiler)**

Required for compiling PDF. Typst is lightweight, fast, and supports UTF-8/Vietnamese natively — no extra font packages needed.

* **Windows:** `winget install typst.typst`
* **Mac:** `brew install typst`
* **Linux:** `snap install typst` or download from [typst.app](https://typst.app)
* **Verify:** Open terminal and type `typst --version`

### **Step 2: Python Setup**

#### **2.1 Clone the Repository**

```bash
git clone <repository-url>
cd ai-textbook-generator
```

#### **2.2 Setup Virtual Environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

#### **2.3 Install Python Dependencies**

```bash
pip install -r requirements.txt
```

### **Step 3: Environment Configuration**

Create a `.env` file in the root directory and add your API keys:

```env
OPENAI_API_KEY=your_openai_api_key_here
SERPAPI_API_KEY=your_serpapi_api_key_here
```

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
ai-textbook-generator/
├── app.py                  # Streamlit frontend
├── agents/                 # Agent definitions
│   ├── planner.py
|   ├── ingester.py
│   ├── researcher.py
│   ├── writer.py
│   ├── reviewer.py
│   ├── illustrator.py
│   └── publisher.py
├── graph/                  # LangGraph workflow
├── utils/                  # Helper functions
├── data/                   # Vector database storage
├── outputs/                # Generated books
├── logs/                   # Application logs
├── requirements.txt        # Python dependencies
├── .env                    # API keys (not in repo)
└── README.md              # This file
```

---

## 🐛 Troubleshooting

### **PDF Generation Failed**

* Ensure `pandoc` is in your system PATH (`pandoc --version`)
* Ensure `typst` is in your system PATH (`typst --version`)
* If Pandoc reports "cannot find typst", reinstall Typst and restart your terminal

### **Images Not Showing**

* Check if `SERPAPI_API_KEY` is valid
* Check `logs/agents.log` for "Connection Error"

### **"Missing Variable" Error**

* Ensure you have updated the code to remove f-strings in LangChain prompts (patched in latest version)

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