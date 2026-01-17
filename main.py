# main.py
import sys
from pathlib import Path
import logging

# Add project root to Python path
sys.path.append(str(Path(__file__).parent))

from src.config import setup_directories
from src.log_config import setup_logger
from src.graph.workflow import create_workflow

# Setup Logger cho Main
logger = setup_logger("MainApp", "logs/app.log")

def main():
    # 1. Setup môi trường
    setup_directories()
    
    # 2. Nhập đề bài
    topic = input("Enter the topic you want to learn (e.g., 'Python for Beginners'): ")
    if not topic:
        topic = "Basic Python Programming"
    
    print(f"\n🚀 STARTING AGENT WORKFLOW FOR: '{topic}'")
    print("This may take a few minutes. Please wait...\n")

    # 3. Khởi tạo Graph
    app = create_workflow()
    
    # 4. Chạy Graph
    # initial_state chỉ cần chứa 'request', các trường khác để trống
    initial_state = {
        "request": topic,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "messages": [],
        "revision_number": 0
    }
    
    # app.invoke sẽ chạy đến khi gặp trạng thái END
    try:
        final_state = app.invoke(initial_state) # type: ignore
        
        # 5. Xuất kết quả
        curriculum = final_state.get("curriculum")
        print("\n" + "="*50)
        print("✅ WORKFLOW FINISHED!")
        print("="*50)
        
        if curriculum:
            print(f"Topic: {curriculum.topic}")
            print(f"Total Chapters: {len(curriculum.chapters)}")
            print("-" * 30)
            
            # Ở giai đoạn này, ta mới chỉ in ra nội dung cuối cùng (Last Section)
            # để kiểm tra xem Writer có viết được không.
            # Sau này có Publisher ta sẽ gom lại thành file PDF.
            last_content = final_state.get("current_content", "")
            print("\nSAMPLE CONTENT (Last Section Written):")
            print(last_content[:500] + "...\n(Content truncated)")
            
        else:
            print("❌ Error: No curriculum generated.")
            
    except Exception as e:
        logger.error(f"Workflow crashed: {e}")
        print(f"\n❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    main()