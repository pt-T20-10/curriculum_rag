import sys
import os

# Config path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.publisher import publish_curriculum

def run_publisher_test():
    print("\n--- 🖨️ TEST PUBLISHER (MARKDOWN -> PDF) ---")
    
    # 1. Giả lập nội dung sách (Đã qua Reviewer làm sạch)
    dummy_content = """
# Chương 1: Động lực học chất điểm

## 1.1. Định luật 2 Newton

Định luật 2 Newton là nền tảng của cơ học cổ điển. Nó phát biểu rằng:

> "Gia tốc của một vật cùng hướng với lực tác dụng lên vật. Độ lớn của gia tốc tỉ lệ thuận với độ lớn của lực và tỉ lệ nghịch với khối lượng của vật."

Công thức tổng quát:

$$ \\vec{F} = m \\cdot \\vec{a} $$

Trong hệ tọa độ Descartes, ta có thể viết:

$$ F_x = m a_x $$

Nếu một vật có khối lượng $m = 10 \\text{ kg}$ chịu tác dụng của lực $F = 50 \\text{ N}$, gia tốc sẽ là:

$$ a = \\frac{F}{m} = \\frac{50}{10} = 5 \\text{ m/s}^2 $$

## 1.2. Ví dụ thực tế

Khi bạn đẩy một chiếc xe hàng trong siêu thị...
"""
    
    # 2. Giả lập State
    mock_state = {
        "request": "Test Vật Lý PDF",
        "final_content": dummy_content,
        "current_content": dummy_content # Fallback
    }
    
    # 3. Chạy Publisher
    result = publish_curriculum(mock_state) # type: ignore
    
    # 4. Kết quả
    print("\nKẾT QUẢ:")
    print(result["messages"])
    
    print("\n👉 Hãy mở folder 'outputs' để kiểm tra file PDF xem có hiển thị đúng Tiếng Việt và Công Thức không.")

if __name__ == "__main__":
    run_publisher_test()