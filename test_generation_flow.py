import sys
import os
import shutil
import logging

# Config path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.planner import HybridPlanner
from src.agents.researcher import ResearcherAgent
from src.agents.writer import WriterAgent
# from src.agents.reviewer import ReviewerAgent  <-- Tạm thời chưa dùng
from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR
from src.agents.query_expansion import QueryExpansionAgent
from src.ingestion.search_engine import search_web
from src.ingestion.url_filter import filter_and_classify_urls
from src.ingestion.crawler import ingest_dynamic_data

# Setup global logger
logger = setup_logger(name="FullFlow", logfile="logs/generation.log")

def reset_chroma_db():
    print("\n🧹 Đang dọn dẹp bộ nhớ (ChromaDB)...")
    db_path = str(CHROMA_DB_DIR)
    
    if os.path.exists(db_path):
        try:
            shutil.rmtree(db_path)
            print("   ✅ Đã xóa sạch dữ liệu cũ.")
        except Exception as e:
            print(f"   ⚠️ Không thể xóa: {e}")
    else:
        print("   ℹ️ Database sạch.")

def run_generation_test():
    # 1. CHỌN CHỦ ĐỀ KHÓ (NHIỀU TOÁN) ĐỂ TEST WRITER
    topic = "Nấu ăn phong cách châu Á" 
    
    print(f"\n🚀 BẮT ĐẦU TEST TOÁN/LÝ (WRITER ONLY) VỚI: '{topic}'\n")

    # === RESET DB & CRAWL ===
    reset_chroma_db()
    
    print("\n--- BƯỚC 1: LẬP KẾ HOẠCH & THU THẬP ---")
    qe_agent = QueryExpansionAgent()
    search_queries = qe_agent.expand_query(topic)
    main_topic = search_queries[0] if search_queries else topic
    
    print(f"--> Query tối ưu: '{main_topic}'")
    
    # Search & Crawl
    raw_results = search_web(main_topic, max_results=25) 
    raw_urls = [r['href'] for r in raw_results]
    clean_links = filter_and_classify_urls(raw_urls)
    
    if not ingest_dynamic_data(topic, clean_links):
        print("❌ Crawl thất bại.")
        return

    # --- PLANNER ---
    print("\n3️⃣  [PLAN] Đang lập dàn ý...")
    planner = HybridPlanner()
    plan = planner.create_curriculum(topic)
    
    if not plan:
        print("❌ Plan thất bại.")
        return

    print(f"📘 Tiêu đề: {plan.get('title')}")
    chapters = plan.get('chapters', [])
    print(f"📊 Tổng số chương: {len(chapters)}")

    # 2. KHỞI TẠO AGENTS (Chỉ Researcher & Writer)
    researcher = ResearcherAgent()
    writer = WriterAgent()
    
    full_book_content = f"# {plan.get('title')}\n\n"

    # 3. VÒNG LẶP SẢN XUẤT (Test 2 chương đầu)
    print("\n--- BƯỚC 2: VIẾT NỘI DUNG (WRITER ONLY) ---")
    
    for i, chapter in enumerate(chapters[:2]): 
        chap_title = chapter['chapter_title']
        display_chap_num = i + 1
        
        print(f"\n📂 Chương {display_chap_num}: {chap_title}")
        full_book_content += f"## Chương {display_chap_num}. {chap_title}\n\n"
        
        sections = chapter['sections']
        
        for j, sec_title in enumerate(sections):
            display_sec_num = f"{display_chap_num}.{j + 1}"
            print(f"   --> Mục {display_sec_num}: {sec_title}")
            
            # A. RESEARCH
            search_query = f"{chap_title} - {sec_title}"
            context = researcher.retrieve_context(search_query, k=4) 
            
            # B. WRITER (Viết nháp)
            # Tự tạo description giả lập
            fake_desc = f"Giải thích chi tiết định luật, công thức toán học và ví dụ về {sec_title}."
            
            content = writer.write_section(
                course_topic=topic,
                chapter_num=display_chap_num,
                chapter_title=chap_title,
                section_num=display_sec_num,
                section_title=sec_title,
                section_description=fake_desc,
                context=context
            )
            
            # Lưu thẳng content của Writer (Chưa qua Reviewer)
            full_book_content += content + "\n\n"
            
            print("      ✅ Xong.")

    # 4. XUẤT FILE
    output_file = f"{topic}.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(full_book_content)
        
    print(f"\n🎉 HOÀN THÀNH! Mở file '{output_file}' để kiểm tra công thức.")

if __name__ == "__main__":
    run_generation_test()