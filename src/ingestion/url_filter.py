import logging
from urllib.parse import urlparse
import requests

logger = logging.getLogger(__name__)

# Danh sách miền rác (Cần loại bỏ)
BLACKLIST_DOMAINS = [
    "facebook.com", "twitter.com", "instagram.com", "youtube.com", "tiktok.com", "linkedin.com",
    "shopee.vn", "tiki.vn", "lazada.vn", "sendo.vn", # E-commerce
    "udemy.com", "coursera.org", # Course selling (thường chặn bot hoặc bắt login)
    "login.", "signup.", "account.", "signin." # Trang đăng nhập
]

# Danh sách đuôi file không đọc được
BLACKLIST_EXTENSIONS = [
    ".zip", ".rar", ".exe", ".iso", ".mp4", ".mp3", ".avi", ".jpg", ".png", ".ppt", ".pptx", ".xls", ".xlsx"
]

BLACKLIST_EXTENSIONS = [
    ".zip", ".rar", ".exe", ".iso", ".mp4", ".mp3", ".avi", ".jpg", ".png", ".ppt", ".pptx", ".xls", ".xlsx"
]

# Giả lập User-Agent xịn
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def is_valid_url_static(url: str) -> bool:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        for bad_domain in BLACKLIST_DOMAINS:
            if bad_domain in domain: return False
                
        for ext in BLACKLIST_EXTENSIONS:
            if path.endswith(ext): return False
        
        return True
    except:
        return False

def check_url_content_type(url: str) -> str:
    """
    Dùng GET stream=True thay vì HEAD để tránh bị chặn
    """
    try:
        # stream=True: Chỉ tải headers, chưa tải nội dung -> Nhanh như HEAD nhưng ít lỗi hơn
        response = requests.get(url, headers=HEADERS, timeout=5, stream=True)
        
        if response.status_code != 200:
            return None # type: ignore
            
        content_type = response.headers.get('Content-Type', '').lower()
        
        # Đóng kết nối ngay lập tức
        response.close()
        
        if 'application/pdf' in content_type:
            return 'pdf'
        elif 'text/html' in content_type:
            return 'html'
        else:
            return None # type: ignore
    except Exception:
        return None # Coi như lỗi mạng # type: ignore

def filter_and_classify_urls(urls: list[str]):
    clean_urls = []
    unique_urls = list(set(urls))
    
    logger.info(f"🔍 Filtering {len(unique_urls)} URLs...")
    
    for url in unique_urls:
        if not is_valid_url_static(url): continue
            
        doc_type = check_url_content_type(url)
        if doc_type:
            clean_urls.append({"url": url, "type": doc_type})
            
    logger.info(f"✅ Filtered: {len(unique_urls)} -> {len(clean_urls)} valid links.")
    return clean_urls