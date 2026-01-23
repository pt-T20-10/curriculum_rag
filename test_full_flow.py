import sys
import os
import logging

# --- Cấu hình đường dẫn để import được src ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

# Import các module chúng ta đã xây dựng
from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls
from src.ingestion.crawler import ingest_dynamic_data
from src.agents.planner import HybridPlanner

# Cấu hình log gọn gàng
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

def run_full_process_test():
    # 0. CẤU HÌNH INPUT
    topic = "Giáo trình Lập trình Python cơ bản"
    print(f"\n🚀 BẮT ĐẦU TEST TOÀN TRÌNH CHO CHỦ ĐỀ: '{topic}'\n")

    # --- GIAI ĐOẠN 1: THU THẬP DỮ LIỆU (INGESTION) ---
    
    print("1️⃣  [SEARCH] Đang tìm kiếm tài liệu trên DuckDuckGo...")
    # Tìm 20 kết quả để lọc dần
    raw_results = search_web(topic, max_results=50)
    raw_urls = [r['href'] for r in raw_results]
    print(f"   -> Tìm thấy {len(raw_urls)} links thô.")

    print("\n2️⃣  [FILTER] Đang lọc rác và phân loại link...")
    # Lọc bỏ facebook, youtube, link chết...
    clean_links = filter_and_classify_urls(raw_urls)
    print(f"   -> Giữ lại {len(clean_links)} links chất lượng (HTML/PDF).")

    print("\n3️⃣  [CRAWL] Đang cào dữ liệu (Deep Crawl) & Lưu vào ChromaDB...")
    # Cào sâu, tách chunks, embed và lưu DB
    is_success = ingest_dynamic_data(topic, clean_links)
    
    if not is_success:
        print("❌ LỖI: Không cào được dữ liệu nào. Dừng chương trình.")
        return

    # --- GIAI ĐOẠN 2: LẬP KẾ HOẠCH (PLANNING) ---

    print("\n4️⃣  [PLAN] Đang khởi chạy Hybrid Planner (Algo + LLM)...")
    try:
        planner = HybridPlanner()
        # Bước này sẽ dùng NMF để gom nhóm keyword + LLM để đặt tên chương
        final_plan = planner.create_curriculum(topic)
        
        # --- KẾT QUẢ ---
        if final_plan:
            print("\n" + "✅" * 30)
            print(f"📘  KẾT QUẢ CUỐI CÙNG: {final_plan.get('title', 'GIÁO TRÌNH')}")
            print("✅" * 30)
            
            chapters = final_plan.get('chapters', [])
            for i, chap in enumerate(chapters, 1):
                print(f"\nCHƯƠNG {i}: {chap['chapter_title']}")
                for sec in chap['sections']:
                    print(f"   • {sec}")
                    
            print(f"\n--> Tổng cộng: {len(chapters)} chương.")
        else:
            print("\n❌ Planner trả về None (Có lỗi trong quá trình phân tích).")
            
    except Exception as e:
        print(f"\n❌ LỖI RUNTIME: {e}")

if __name__ == "__main__":
    run_full_process_test()