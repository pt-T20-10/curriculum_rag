import os
from pathlib import Path
from bs4 import BeautifulSoup

# Lấy đại 1 file trong thư mục đã giải nén để soi
# Bạn hãy sửa đường dẫn này trỏ tới 1 file index.cnxml hoặc index.html bất kỳ trong máy bạn
TEST_FILE = Path(r"D:\Thesis\curriculum_rag\data\extracted\osbooks-university-physics-bundle-main\modules\m58297\index.cnxml")

def inspect_file():
    if not TEST_FILE.exists():
        print("File không tồn tại! Hãy sửa đường dẫn TEST_FILE.")
        return

    with open(TEST_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    soup = BeautifulSoup(content, 'lxml')
    
    print("=== 1. TÌM TIÊU ĐỀ (TITLE DEBUG) ===")
    # In ra tất cả các thẻ có khả năng là tiêu đề
    print("H1 tags:", soup.find_all('h1'))
    print("Class 'title':", soup.find_all(class_='title'))
    print("Attribute 'data-type=document-title':", soup.find_all(attrs={"data-type": "document-title"}))

    print("\n=== 2. TEST TEXT CLEANING ===")
    # Test thử cách lấy text hiện tại
    raw_text = soup.get_text(separator='\n', strip=True)
    print("--- Text gốc (bị lỗi xuống dòng) ---")
    print(raw_text[:500]) # In 500 ký tự đầu

if __name__ == "__main__":
    inspect_file()