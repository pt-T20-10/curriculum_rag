"""
Web Crawler for AI Textbook Generator.

Deep crawls educational websites to extract text content:
- Handles both HTML pages and PDF documents
- Follows internal links (depth=1) for comprehensive coverage
- Chunks and stores in ChromaDB vector database
"""

import os
import io
import shutil
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Set, Optional

import requests
import concurrent.futures
from bs4 import BeautifulSoup
from pypdf import PdfReader

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.config import get_embedding_model

from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR
from src import stop_signal

logger = setup_logger(name="Crawler", logfile="logs/crawler.log")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def get_internal_links(soup: BeautifulSoup, base_url: str, limit: int = 5) -> List[str]:
    """
    Find internal links (same domain) for deep crawling.
    
    Args:
        soup: BeautifulSoup object of the page
        base_url: Base URL of the current page
        limit: Maximum number of internal links to extract
        
    Returns:
        List of absolute URLs (same domain as base_url).
    """
    internal_links: Set[str] = set()
    domain = urlparse(base_url).netloc
    
    # Focus on main content area
    content_area = soup.find('article') or soup.find('main') or soup.find('body')
    if not content_area:
        return []

    for a_tag in content_area.find_all('a', href=True):
        # FIX: Explicitly convert to string to satisfy type checker
        href_attr = a_tag.get('href')
        
        # Type guard: ensure href is a string
        if not isinstance(href_attr, str):
            continue
        
        href: str = href_attr  # Now type checker knows this is str
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        # Only same domain
        if parsed.netloc != domain:
            continue
        
        # Skip anchors, login, search pages
        if any(x in full_url for x in ['#', 'login', 'register', 'tag', 'search', 'cart']):
            continue
        
        # Only HTML or extensionless paths
        path = parsed.path.lower()
        if path.endswith('.pdf') or '.' not in path or path.endswith('.html'):
            internal_links.add(full_url)
            if len(internal_links) >= limit:
                break
                
    return list(internal_links)


def fetch_text_from_url(url: str) -> tuple[str, Optional[BeautifulSoup]]:
    """
    Fetch and parse HTML page.
    
    Args:
        url: URL to fetch
        
    Returns:
        Tuple of (extracted_text, BeautifulSoup_object).
        Returns ("", None) on error.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return "", None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove noise (scripts, styles, navigation, etc.)
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            tag.decompose()
        
        # Extract text from semantic tags
        text_parts = []
        for tag in soup.find_all(['h1', 'h2', 'h3', 'p', 'li', 'pre', 'code']):
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 30:  # Filter out very short snippets
                text_parts.append(text)
        
        return "\n\n".join(text_parts), soup
        
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return "", None


def process_deep_crawl(link_info: Dict[str, str]) -> List[Document]:
    """
    Process a single root URL with deep crawling (depth=1).
    
    For HTML: Crawls root page + up to 5 internal links
    For PDF: Extracts text from PDF file
    
    Args:
        link_info: Dict with 'url' and 'type' (pdf/html)
        
    Returns:
        List of LangChain Document objects.
    """
    url = link_info['url']
    doc_type = link_info['type']
    results: List[Document] = []
    
    try:
        # CASE 1: PDF Document
        if doc_type == 'pdf':
            response = requests.get(url, headers=HEADERS, timeout=15)
            pdf_file = io.BytesIO(response.content)
            reader = PdfReader(pdf_file)
            
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            
            if len(text) > 300:
                logger.info(f"[PDF] {url} ({len(text)} chars)")
                results.append(Document(
                    page_content=text,
                    metadata={"source": url, "type": "pdf"}
                ))
            return results

        # CASE 2: HTML Page (with deep crawl)
        main_text, soup = fetch_text_from_url(url)
        
        if len(main_text) > 300:
            logger.info(f"[ROOT] {url} ({len(main_text)} chars)")
            results.append(Document(
                page_content=main_text,
                metadata={"source": url, "type": "html", "depth": 0}
            ))
            
            # Deep crawl: Follow internal links (depth=1)
            if stop_signal.is_stopped():
                return results
            if soup:
                sub_links = get_internal_links(soup, url, limit=5)
                if sub_links:
                    logger.info(f"  ↳ Crawling {len(sub_links)} sub-links...")
                    for sub in sub_links:
                        if stop_signal.is_stopped():
                            return results
                        sub_text, _ = fetch_text_from_url(sub)
                        if len(sub_text) > 500:
                            results.append(Document(
                                page_content=sub_text,
                                metadata={
                                    "source": sub,
                                    "type": "html",
                                    "depth": 1,
                                    "parent": url
                                }
                            ))
                            
    except Exception as e:
        logger.warning(f"Error processing {url}: {e}")
        
    return results


def ingest_dynamic_data(topic: str, clean_links: List[Dict[str, str]]) -> bool:
    """
    Ingest data from filtered URLs into ChromaDB.
    
    Pipeline:
    1. Deep crawl all URLs (parallel processing)
    2. Chunk documents into smaller pieces
    3. Generate embeddings and store in ChromaDB
    
    Args:
        topic: User's topic (stored as metadata)
        clean_links: List of filtered URLs with types
        
    Returns:
        True if ingestion successful, False otherwise.
    """
    if not clean_links:
        return False
    
    logger.info(f"Starting deep crawler (max depth=1, 5 sub-links per page)...")
    all_docs: List[Document] = []
    
    # Parallel crawling of root URLs
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(process_deep_crawl, link)
            for link in clean_links
            if not stop_signal.is_stopped()
        ]

        for future in concurrent.futures.as_completed(futures):
            if stop_signal.is_stopped():
                break
            docs = future.result()
            if docs:
                for doc in docs:
                    doc.metadata['topic'] = topic
                    all_docs.append(doc)

    if not all_docs:
        logger.error("No content crawled")
        return False
    
    logger.info(f"Total documents: {len(all_docs)} (roots + sub-pages)")

    # Chunking
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_documents(all_docs)
    logger.info(f"Total chunks: {len(chunks)}")

    # Save to ChromaDB
    logger.info("Saving to ChromaDB...")
    
    Chroma.from_documents(
        documents=chunks,
        embedding= get_embedding_model(),
        persist_directory=str(CHROMA_DB_DIR),
        collection_name="dynamic_context"
    )
    
    logger.info("✓ Ingestion complete")
    return True