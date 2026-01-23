import sys
import os

# Config path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.graph.workflow import create_workflow
from src.log_config import setup_logger

logger = setup_logger(name="MainApp", logfile="logs/app.log")

def main():
    # 1. Nhập chủ đề muốn viết sách
    topic = "Giáo trình Nhập môn Trí tuệ Nhân tạo" 
    
    print(f"\n🚀 KHỞI ĐỘNG HỆ THỐNG LANGGRAPH: '{topic}'")
    print("⏳ Hệ thống sẽ tự động: Search -> Crawl -> Plan -> Write -> Publish.")
    
    # 2. Khởi tạo Graph
    app = create_workflow()
    
    # 3. Khởi tạo State ban đầu
    initial_state = {
        "request": topic,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "revision_number": 0,
        "messages": [],
        "final_content": "",
        "current_content": ""
    }
    
    # 4. Chạy Workflow
    # recursion_limit=150: Cho phép lặp khoảng 150 bước (đủ cho sách khoảng 10-15 chương nhỏ)
    try:
        for event in app.stream(initial_state, {"recursion_limit": 150}): # type: ignore
            for key, value in event.items():
                print(f"👉 [NODE DONE]: {key}")
    except Exception as e:
        logger.error(f"Critical Error in Workflow: {e}")
            
    print("\n🎉 CHƯƠNG TRÌNH HOÀN TẤT! Kiểm tra folder 'outputs'.")

if __name__ == "__main__":
    main()