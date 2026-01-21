import sys
import os

# Fix import
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls
from src.ingestion.crawler import ingest_dynamic_data

def run_test():
    topic = "Giáo trình Lập trình Python cơ bản"
    print(f"🚀 BẮT ĐẦU QUY TRÌNH DYNAMIC RAG: '{topic}'\n")

    # BƯỚC 1: SEARCH
    print("1️⃣  Searching...")
    raw_results = search_web(topic, max_results=100)
    raw_urls = [r['href'] for r in raw_results]
    print(f"   -> Found {len(raw_urls)} raw links.")

    # BƯỚC 2: FILTER & CLASSIFY
    print("\n2️⃣  Filtering & Classifying...")
    clean_links = filter_and_classify_urls(raw_urls)
    print(f"   -> Retained {len(clean_links)} high-quality links.")
    
    # In ra xem nó nhận diện đúng loại file không
    # for l in clean_links: print(f"      - [{l['type'].upper()}] {l['url']}")

    # BƯỚC 3: CRAWL & INGEST
    print("\n3️⃣  Crawling & Ingesting to ChromaDB...")
    success = ingest_dynamic_data(topic, clean_links)
    
    if success:
        print("\n✅ THÀNH CÔNG! Dữ liệu đã nằm trong ChromaDB.")
    else:
        print("\n❌ THẤT BẠI.")

if __name__ == "__main__":
    run_test()