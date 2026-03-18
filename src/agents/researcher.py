"""
Researcher Agent for AI Textbook Generator.

This agent retrieves relevant document chunks from ChromaDB using semantic
similarity search based on the current subsection's search_query field.

It is called once per subsection iteration in the workflow loop:
    Researcher → Writer → Reviewer → Illustrator → [next subsection]

Performance note:
    ResearcherAgent is instantiated via a module-level lazy singleton
    (_get_researcher()) so that the ChromaDB client connection is created
    once and reused across all N×M subsection calls, rather than
    reconnecting on every iteration.
"""

from typing import Optional

from langchain_chroma import Chroma

from src.graph.state import AgentState, Chapter, SubSection, get_chapter_and_subsection
from src.config import CHROMA_DB_DIR, get_embedding_model
from src.log_config import setup_logger

logger = setup_logger(name="ResearcherAgent", logfile="logs/agents.log")


class ResearcherAgent:
    """
    Researcher Agent: semantic similarity search over the ingested ChromaDB corpus.

    Responsibilities:
        - Maintain a single ChromaDB client connection (shared via singleton)
        - Perform top-k similarity search for a given subsection query
        - Format retrieved chunks with source metadata for the Writer's RAG context

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

    def retrieve_context(self, query: str, k: int = 5) -> str:
        """
        Retrieve the top-k most relevant document chunks for a given query.

        Performs cosine similarity search via ChromaDB and formats the results
        as a numbered list with source metadata, suitable for injection into
        the Writer's system prompt as RAG context.

        Args:
            query: Search query string (typically subsection.search_query).
            k:     Maximum number of chunks to retrieve.

        Returns:
            Formatted string of retrieved chunks with source metadata.
            Empty string if no results found or on retrieval error.
        """
        logger.info(f"Searching for: '{query}'")

        try:
            results = self.vector_db.similarity_search(query, k=k)

            if not results:
                logger.warning(f"No content found for query: '{query}'")
                return ""

            # Format chunks with source metadata for Writer citation context
            formatted_content = ""
            for i, doc in enumerate(results, 1):
                source  = doc.metadata.get('source', 'Unknown')
                content = doc.page_content.replace('\n', ' ')
                formatted_content += f"Document {i} (Source: {source}):\n{content}\n\n"

            logger.info(f"Retrieved {len(results)} relevant documents")
            return formatted_content

        except Exception as e:
            logger.error(f"Error during retrieval: {e}", exc_info=True)
            return ""


# ---------------------------------------------------------------------------
# Module-level lazy singleton (BUG-06 fix)
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
    search_query, and performs a top-5 similarity search against ChromaDB.

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
            else chapter.get('title', 'Unknown')
        )
        sec_title = (
            subsection.title if isinstance(subsection, SubSection)
            else subsection.get('title', 'Unknown')
        )
        query = (
            subsection.search_query if isinstance(subsection, SubSection)
            else subsection.get('search_query', f"{chap_title} - {sec_title}")
        )

        logger.info(f"Target: Chapter {chap_idx + 1}.{sub_idx + 1} - {sec_title}")
        logger.info(f"Query:  {query}")

        # Reuse singleton connection (BUG-06 fix)
        context = _get_researcher().retrieve_context(query, k=5)

        if not context:
            logger.warning("No context retrieved — Writer will use general knowledge")
            return {
                "messages": ["No specific context found. Using general knowledge."]
            }

        return {
            "rag_context": context,
            "messages": [
                f"✓ Retrieved context for: '{sec_title}' (query: '{query[:40]}...')"
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