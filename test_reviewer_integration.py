import sys
import os

# Config path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.reviewer import ReviewerAgent

def run_reviewer_test():
    print("\n--- 🕵️ TEST RIÊNG REVIEWER (LATEX FIXING) ---")
    
    # 1. Giả lập một bản nháp "lỗi"
    bad_draft = """
    ## 1.1 Định luật 2 Newton
    
    Theo định luật này, gia tốc của vật tỉ lệ thuận với lực.
    Công thức là:
    \[ F = m \cdot a \]
    
    Trong đó F là lực, m là khối lượng, a là gia tốc.
    Ví dụ nếu m = 2kg và a = 5m/s^2 thì F = 10N.
    """
    
    print("\n🔴 BẢN NHÁP LỖI (INPUT):")
    print(bad_draft)
    
    # 2. Gọi Reviewer sửa (VỚI ĐỦ THAM SỐ GIẢ LẬP)
    reviewer = ReviewerAgent()
    polished = reviewer.review_content(
        course_topic="Vật lý Đại cương",
        chapter_num="1",
        chapter_title="Động lực học", 
        section_num="1.1",
        section_title="Định luật Newton", 
        section_description="Giải thích định luật 2 Newton và công thức F=ma",
        draft_content=bad_draft
    )
    
    # 3. Kiểm tra kết quả
    print("\n🟢 BẢN ĐÃ SỬA (OUTPUT):")
    print(polished)
    
    # 4. Tự động kiểm tra
    if "$$ F =" in polished or "$$F =" in polished:
        print("\n✅ PASSED: Đã chuyển \[...\] thành $$...$$")
    else:
        print("\n❌ FAILED: Chưa sửa lỗi Block Math.")
        
    if "$F$" in polished or "$m$" in polished:
        print("✅ PASSED: Đã thêm $ vào biến số.")
    else:
        print("❌ FAILED: Biến số vẫn trơ trọi.")

if __name__ == "__main__":
    run_reviewer_test()