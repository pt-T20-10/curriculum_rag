import sys
import os
from dotenv import load_dotenv

# Load env trước
load_dotenv()

# Add path để import được src
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.agents.illustrator import IllustratorAgent

def run_test():
    print("--- 🎨 TEST ILLUSTRATOR AGENT ---")
    
    # 1. Giả lập nội dung có thẻ tag
    mock_content = """
    ## Giới thiệu về Hoa Hồng
    Hoa hồng là loài hoa biểu tượng cho tình yêu.
    
    > [IMAGE SUGGESTION: A bouquet of red roses in a flower shop, high quality, realistic]
    
    Hoa hồng có nhiều màu sắc khác nhau.
    """
    
    print("\n1. Nội dung gốc:")
    print(mock_content)
    
    # 2. Gọi Agent
    agent = IllustratorAgent()
    
    if not agent.api_key:
        print("\n❌ LỖI: Chưa có API Key!")
        return

    print("\n2. Đang gọi SerpApi (Google Images)...")
    new_content = agent.illustrate_content(mock_content)
    
    # 3. Kết quả
    print("\n3. Nội dung sau khi xử lý:")
    print(new_content)
    
    if "![" in new_content and "http" in new_content:
        print("\n✅ THÀNH CÔNG: Đã chèn link ảnh vào bài!")
    else:
        print("\n❌ THẤT BẠI: Không thấy link ảnh.")

if __name__ == "__main__":
    run_test()