import chromadb
from src.config import CHROMA_DB_DIR
from src.ingestion.search_engine import search_web
import os
import sys
# Fix đường dẫn import để chạy được từ thư mục gốc
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls

def test_retrieval():
    print(f"Connecting to DB at: {CHROMA_DB_DIR}")
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    
    try:
        collection = client.get_collection("openstax_textbooks")
        count = collection.count()
        print(f"--> Total chunks in DB: {count}")
        
        # Thử tìm kiếm
        query = "Blood vessels"
        print(f"\n--> Querying: '{query}'")
        
        results = collection.query(
            query_texts=[query],
            n_results=10
        )
        
        # --- FIX LỖI PYLANCE Ở ĐÂY ---
        # Kiểm tra xem kết quả có tồn tại không trước khi truy cập [0]
        documents = results.get('documents')
        metadatas = results.get('metadatas')

        if documents and metadatas: # Nếu cả 2 đều không phải None và không rỗng
            # ChromaDB trả về list lồng nhau (list of lists) nên cần lấy [0]
            first_query_docs = documents[0]
            first_query_meta = metadatas[0]

            for i, doc in enumerate(first_query_docs):
                meta = first_query_meta[i]
                # Dùng .get() để an toàn hơn nếu metadata thiếu trường section_title
                source_title = meta.get('section_title', 'Unknown Section')
                
                print(f"\n[Result {i+1}] (Source: {source_title})")
                print("-" * 50)
                print(doc[:200] + "...") 
        else:
            print("[WARNING] No results found or data is corrupted.")
            
    except Exception as e:
        print(f"Error: {e}")

def test_search_and_filter():
    # 1. SEARCH (Tìm kiếm dư thừa - Lấy 20 kết quả để lọc dần)
    topic = "Làm nails cơ bản"
    print(f"\n--- BƯỚC 1: SEARCHING '{topic}' (Max 20) ---")
    
    # Lưu ý: search_web trả về List[Dict]
    raw_results = search_web(topic, max_results=200)
    
    # Trích xuất chỉ lấy danh sách URL (String) để đưa vào bộ lọc
    raw_urls = [item['href'] for item in raw_results]
    
    print(f"--> Tìm thấy: {len(raw_urls)} links thô.")
    # In thử 3 link đầu để kiểm tra
    # for u in raw_urls[:3]: print(f"    - {u}")

    # 2. FILTERING (Áp dụng Phễu lọc 3 lớp)
    print(f"\n--- BƯỚC 2: FILTERING (Static + Head Check) ---")
    
    # Hàm này sẽ chạy:
    # - Lớp 1: Loại bỏ facebook, youtube, shopee...
    # - Lớp 2: Ping thử (HEAD request) xem có phải HTML/PDF không
    clean_links = filter_and_classify_urls(raw_urls)
    
    # 3. KẾT QUẢ
    print(f"\n--- BƯỚC 3: KẾT QUẢ CUỐI CÙNG ---")
    print(f"Tỷ lệ lọc: {len(raw_urls)} -> {len(clean_links)} links chất lượng.\n")
    
    if clean_links:
        print(f"{'STT':<4} {'TYPE':<6} {'URL'}")
        print("-" * 80)
        for i, item in enumerate(clean_links, 1):
            # item là dict {'url': '...', 'type': 'html'/'pdf'}
            print(f"{i:<4} {item['type'].upper():<6} {item['url']}")
            
            # (Optional) Nếu muốn map ngược lại Title từ kết quả search ban đầu
            # original_title = next((r['title'] for r in raw_results if r['href'] == item['url']), "Unknown Title")
            # print(f"     Title: {original_title[:60]}...")
            
    else:
        print("❌ Không còn link nào sau khi lọc (Quá chặt hoặc Search kém).")

if __name__ == "__main__":
    test_search_and_filter()