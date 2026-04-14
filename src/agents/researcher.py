"""
Researcher Agent for AI Textbook Generator.

This agent retrieves relevant document chunks from ChromaDB using semantic
similarity search based on the current subsection's search_query field.

It is called once per subsection iteration in the workflow loop:
    Researcher -> Writer -> Reviewer -> Illustrator -> [next subsection]

Performance note:
    ResearcherAgent is instantiated via a module-level lazy singleton
    (_get_researcher()) so that the ChromaDB client connection is created
    once and reused across all N×M subsection calls, rather than
    reconnecting on every iteration.

RAG Context Logging:
    Every retrieve_context() call writes a structured entry to
    logs/rag_context.log containing:
        - The search query used
        - Total chars retrieved
        - Full content of every chunk with source URL and similarity rank
    This log is the primary audit trail for RAG quality evaluation.
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma

from src.config import CHROMA_DB_DIR, RAG_TOP_K, get_embedding_model
from src.graph.state import AgentState, Chapter, SubSection, get_chapter_and_subsection
from src.log_config import setup_logger

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")


# ============================================================================
# RAG Context Logger
#
# Writes the full retrieved context (query + all chunks) to a dedicated log
# file separate from the main agents.log. This keeps RAG audit data readable
# without being buried in general workflow logs.
#
# Log format per retrieval call:
#   ════════════════════════════════════════════════════════════════════════
#   [RAG #N] YYYY-MM-DD HH:MM:SS | Chapter X.Y | total_chars chars
#   QUERY: <search_query string>
#   ────────────────────────────────────────────────────────────────────────
#   [Chunk 1/k] Source: <url>
#   <full chunk text — no truncation>
#   ────────────────────────────────────────────────────────────────────────
#   [Chunk 2/k] Source: <url>
#   <full chunk text>
#   ...
#   ════════════════════════════════════════════════════════════════════════
# ============================================================================

_rag_log_counter: int = 0
_rag_log_lock = threading.Lock()


class RAGContextLogger:
    """
    Writes full RAG retrieval records to logs/rag_context.log.

    Each record captures the search query and the complete untruncated
    content of every retrieved chunk, making it possible to audit:
        - Whether the search query matched useful chunks
        - What information the Writer actually had access to
        - Which source URLs contributed to each section
    """

    def __init__(self, log_dir: str = "logs") -> None:
        self.log_path = Path(log_dir) / "rag_context.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        query:         str,
        chunks:        list[dict],   # list of {"source": str, "content": str}
        context_label: str = "",     # e.g. "Chapter 1.2 Ten muc"
    ) -> int:
        """
        Write one retrieval record to rag_context.log.

        Args:
            query:         The search query sent to ChromaDB.
            chunks:        Retrieved chunks as list of {source, content} dicts.
            context_label: Human-readable label for the retrieval (chapter.section).

        Returns:
            1-indexed sequence number of the entry written.
        """
        global _rag_log_counter

        with _rag_log_lock:
            _rag_log_counter += 1
            n = _rag_log_counter

        timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_chars = sum(len(c["content"]) for c in chunks)
        label_part  = f" | {context_label}" if context_label else ""

        divider_thick = "=" * 72
        divider_thin  = "-" * 72

        lines = [
            divider_thick,
            f"[RAG #{n}] {timestamp}{label_part} | {total_chars} chars retrieved",
            f"QUERY: {query}",
            divider_thin,
        ]

        for i, chunk in enumerate(chunks, 1):
            lines += [
                f"[Chunk {i}/{len(chunks)}] Source: {chunk['source']}",
                chunk["content"],
                divider_thin,
            ]

        lines += ["", ""]   # trailing blank lines for readability

        entry = "\n".join(lines) + "\n"

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        return n


# Module-level singleton logger — one file handle shared across all calls.
_rag_logger: Optional[RAGContextLogger] = None


def _get_rag_logger() -> RAGContextLogger:
    """Return the module-level RAGContextLogger singleton."""
    global _rag_logger
    if _rag_logger is None:
        _rag_logger = RAGContextLogger()
    return _rag_logger


# ============================================================================
# ResearcherAgent
# ============================================================================

class ResearcherAgent:
    """
    Researcher Agent: semantic similarity search over the ingested ChromaDB corpus.

    Responsibilities:
        - Maintain a single ChromaDB client connection (shared via singleton)
        - Perform top-k similarity search for a given subsection query
        - Format retrieved chunks with source metadata for the Writer's RAG context
        - Write full retrieval records to logs/rag_context.log for audit

    Instantiate via _get_researcher() rather than directly — this ensures the
    ChromaDB connection is reused across all subsection calls in the workflow.
    """

    def __init__(self) -> None:
        """
        Open a ChromaDB connection using the singleton embedding model.

        Uses get_embedding_model() which is itself lru_cache-cached, so the
        embedding model is loaded once per process regardless of how many
        ResearcherAgent instances are created.
        """
        self.vector_db = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=get_embedding_model(),
            collection_name="dynamic_context",
        )

    def retrieve_context(
        self,
        query:         str,
        k:             int  = 5,
        context_label: str  = "",
    ) -> str:
        """
        Retrieve the top-k most relevant document chunks for a given query.

        Performs cosine similarity search via ChromaDB, writes the full
        retrieval record to logs/rag_context.log, then returns a formatted
        string suitable for injection into the Writer's system prompt.

        Args:
            query:         Search query string (typically subsection.search_query).
            k:             Maximum number of chunks to retrieve.
            context_label: Human-readable label written to the RAG log
                           (e.g. "Chapter 1.2 Ten muc"). Auto-populated by
                           perform_research() from the curriculum position.

        Returns:
            Formatted string of retrieved chunks with source metadata.
            Empty string if no results found or on retrieval error.
        """
        logger.info(f"Searching ChromaDB — query: '{query}' | k={k}")

        try:
            results = self.vector_db.similarity_search(query, k=k)

            if not results:
                logger.warning(f"No content found for query: '{query}'")
                return ""

            # ----------------------------------------------------------------
            # Build chunk list for both the RAG log and the formatted string.
            # Content is kept in its original form (newlines preserved) for
            # the log; newlines are collapsed to spaces for the Writer prompt
            # to avoid breaking the XML-structured system prompt template.
            # ----------------------------------------------------------------
            chunks: list[dict] = []
            for doc in results:
                chunks.append({
                    "source":  doc.metadata.get("source", "Unknown"),
                    "content": doc.page_content,   # full content, no truncation
                })

            # ----------------------------------------------------------------
            # Write full RAG record to logs/rag_context.log
            # ----------------------------------------------------------------
            entry_num = _get_rag_logger().log(
                query         = query,
                chunks        = chunks,
                context_label = context_label,
            )
            logger.info(
                f"Retrieved {len(chunks)} chunks ({sum(len(c['content']) for c in chunks)} chars) "
                f"— logged as RAG #{entry_num} in logs/rag_context.log"
            )

            # ----------------------------------------------------------------
            # Build the formatted context string for Writer injection.
            # Newlines in chunk content are collapsed to spaces so the multi-
            # line XML system prompt template is not accidentally broken.
            # ----------------------------------------------------------------
            formatted_content = ""
            for i, chunk in enumerate(chunks, 1):
                inline_content = chunk["content"].replace("\n", " ")
                formatted_content += (
                    f"Document {i} (Source: {chunk['source']}):\n"
                    f"{inline_content}\n\n"
                )

            return formatted_content

        except Exception as e:
            logger.error(f"Error during retrieval: {e}", exc_info=True)
            return ""


# ---------------------------------------------------------------------------
#
# ResearcherAgent.__init__ opens a ChromaDB connection. Without a singleton,
# a new connection would be created for every subsection call (N chapters ×
# M subsections = N×M reconnections). The singleton ensures the connection
# is opened once and reused for the entire workflow run.
# ---------------------------------------------------------------------------

_researcher_instance: Optional[ResearcherAgent] = None


def _get_researcher() -> ResearcherAgent:
    """
    Return the module-level ResearcherAgent singleton.

    Instantiates on first call; returns the cached instance on subsequent
    calls. Thread-safety is not guaranteed — this is safe for the single-
    threaded LangGraph workflow but should not be used from multiple threads
    without a lock.

    Returns:
        The shared ResearcherAgent instance.
    """
    global _researcher_instance
    if _researcher_instance is None:
        _researcher_instance = ResearcherAgent()
    return _researcher_instance


def perform_research(state: AgentState) -> dict:
    """
    Researcher node: retrieve RAG context for the current subsection.

    Reads curriculum position from state indexes, extracts the subsection's
    search_query, and performs a similarity search against ChromaDB.
    Passes a context_label to retrieve_context() so every RAG log entry
    is tagged with the chapter.subsection position for easy cross-reference.

    Workflow integration:
        Input:  state["curriculum"], state["current_chapter_index"],
                state["current_subsection_index"]
        Output (success):
                state["rag_context"]  — formatted chunk string for Writer
                state["messages"]     — milestone log entry
        Output (no results):
                state["messages"]     — warning; rag_context NOT written,
                                        Writer falls back to internal knowledge
        Output (error):
                state["messages"]     — error description

    Args:
        state: Current LangGraph workflow state (AgentState TypedDict).

    Returns:
        Partial state update dict.
    """
    logger.info("=" * 60)
    logger.info("NODE: Researcher - Retrieving context")
    logger.info("=" * 60)

    curriculum = state["curriculum"]
    chap_idx   = state["current_chapter_index"]
    sub_idx    = state["current_subsection_index"]

    try:
        # Unified accessor — handles both Pydantic CurriculumOutline and dict
        chapter, subsection = get_chapter_and_subsection(curriculum, chap_idx, sub_idx)

        chap_title = (
            chapter.title if isinstance(chapter, Chapter)
            else chapter.get("title", "Unknown")
        )
        sec_title = (
            subsection.title if isinstance(subsection, SubSection)
            else subsection.get("title", "Unknown")
        )
        query = (
            subsection.search_query if isinstance(subsection, SubSection)
            else subsection.get("search_query", f"{chap_title} - {sec_title}")
        )

        logger.info(f"Target: Chapter {chap_idx + 1}.{sub_idx + 1} - {sec_title}")
        logger.info(f"Query:  {query}")

        # Human-readable label written into the RAG log entry header.
        # Format: "Chapter 1.2 Ten muc" for cross-reference with other logs.
        context_label = f"Chapter {chap_idx + 1}.{sub_idx + 1} {sec_title}"

        context = _get_researcher().retrieve_context(
            query         = query,
            k             = RAG_TOP_K,
            context_label = context_label,
        )

        if not context:
            logger.warning("No context retrieved — Writer will use general knowledge")
            return {
                "messages": ["No specific context found. Using general knowledge."]
            }

        return {
            "rag_context": context,
            "messages": [
                f"✓ Retrieved context for: '{sec_title}' "
                f"(query: '{query[:40]}...') — see logs/rag_context.log"
            ],
        }

    except IndexError as e:
        logger.error(f"Invalid chapter/subsection index: {e}")
        return {"messages": ["Error: Invalid curriculum index"]}

    except (KeyError, AttributeError) as e:
        logger.error(f"Missing required field in curriculum: {e}")
        return {"messages": ["Error: Malformed curriculum structure"]}

    except Exception as e:
        logger.error(f"Unexpected error in Researcher: {e}", exc_info=True)
        return {"messages": ["Error retrieving context"]}