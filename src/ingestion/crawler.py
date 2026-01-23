import re
import sys
import os
import io
import shutil
from venv import logger
from urllib.parse import urljoin, urlparse
import requests
import concurrent.futures
from bs4 import BeautifulSoup
from pypdf import PdfReader

# Import các thư viện AI
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR, EMBEDDING_MODEL_NAME



logger = setup_logger(name="Crawler", logfile="logs/Crawler.log")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; 64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4427.124 Safari/537.36'
}


def get_internal_links(soup, base_url, limit=5):
    """Tìm link con cùng domain (Logic Deep Crawl)"""
    internal_links = set()
    domain = urlparse(base_url).netloc
    
    # Chỉ tìm link trong vùng nội dung chính
    content_area = soup.find('article') or soup.find('main') or soup.find('body')
    if not content_area: return []

    for a_tag in content_area.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        if parsed.netloc == domain:
            if any(x in full_url for x in ['#', 'login', 'register', 'tag', 'search', 'cart']):
                continue
            # Chỉ lấy link html
            path = parsed.path.lower()
            if path.endswith('.pdf') or '.' not in path or path.endswith('.html'):
                internal_links.add(full_url)
                if len(internal_links) >= limit: break
                
    return list(internal_links)

def fetch_text_from_url(url):
    """Tải và parse HTML"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200: return "", None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Xóa rác
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            tag.decompose()
            
        # Lấy text
        text_parts = []
        tags = soup.find_all(['h1', 'h2', 'h3', 'p', 'li', 'pre', 'code'])
        for tag in tags:
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 30: text_parts.append(text)
                
        return "\n\n".join(text_parts), soup
    except:
        return "", None

def process_deep_crawl(link_info):
    """Xử lý 1 Root Link -> Ra nhiều Docs"""
    url = link_info['url']
    doc_type = link_info['type']
    results = []
    
    try:
        # CASE 1: PDF
        if doc_type == 'pdf':
            response = requests.get(url, headers=HEADERS, timeout=15)
            pdf_file = io.BytesIO(response.content)
            reader = PdfReader(pdf_file)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted: text += extracted + "\n"
            
            if len(text) > 300:
                logger.info(f"   📄 [PDF] {url} ({len(text)} chars)")
                results.append(Document(page_content=text, metadata={"source": url, "type": "pdf"}))
            return results

        # CASE 2: HTML (Deep Crawl)
        main_text, soup = fetch_text_from_url(url)
        if len(main_text) > 300:
            logger.info(f"   🌐 [ROOT] {url} ({len(main_text)} chars)")
            results.append(Document(page_content=main_text, metadata={"source": url, "type": "html", "depth": 0}))
            
            # Đào sâu (Depth = 1)
            if soup:
                sub_links = get_internal_links(soup, url, limit=5)
                if sub_links:
                    logger.info(f"      ↳ Crawling {len(sub_links)} sub-links...")
                    for sub in sub_links:
                        sub_text, _ = fetch_text_from_url(sub)
                        if len(sub_text) > 500:
                            results.append(Document(
                                page_content=sub_text, 
                                metadata={"source": sub, "type": "html", "depth": 1, "parent": url}
                            ))
    except Exception as e:
        logger.warning(f"Error {url}: {e}")
        
    return results

def ingest_dynamic_data(topic: str, clean_links: list[dict]):
    if not clean_links: return False
    
    logger.info(f"🕷️ Starting DEEP Crawler (Max depth=1, 5 sub-links/page)...")
    all_docs = []
    
    # Chạy song song các Root Link
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_deep_crawl, link) for link in clean_links]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                for doc in res:
                    doc.metadata['topic'] = topic
                    all_docs.append(doc)

    if not all_docs:
        logger.error("❌ No content crawled.")
        return False
        
    logger.info(f"📊 Total Documents: {len(all_docs)} (Roots + Subs).")

    # Chunking
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(all_docs)
    logger.info(f"🧩 Total Chunks: {len(chunks)}")

    # Save ChromaDB
    logger.info("💾 Saving to ChromaDB...")
    embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
    
    if os.path.exists(CHROMA_DB_DIR):
        try: shutil.rmtree(CHROMA_DB_DIR)
        except: pass

    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embedding_model,
        persist_directory=str(CHROMA_DB_DIR),
        collection_name="dynamic_context"
    )
    
    logger.info("✅ Ingestion Complete!")
    return True