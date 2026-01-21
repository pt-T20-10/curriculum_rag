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

def is_valid_url_static(url: str) -> bool:
    """
    Lớp 1: Kiểm tra nhanh dựa trên chuỗi URL
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        # 1. Kiểm tra Domain rác
        for bad_domain in BLACKLIST_DOMAINS:
            if bad_domain in domain:
                logger.info(f"Filtered Domain: {domain}")
                return False
                
        # 2. Kiểm tra đuôi file rác
        for ext in BLACKLIST_EXTENSIONS:
            if path.endswith(ext):
                logger.info(f" Filtered Ext: {path}")
                return False
        
        return True
    except:
        return False

def check_url_content_type(url: str) -> str:
    """
    Lớp 2: Gửi HEAD request để kiểm tra loại nội dung mà không cần tải hết
    Trả về: 'pdf', 'html', hoặc None (nếu rác)
    """
    try:
        # Timeout ngắn (3s) để check nhanh
        response = requests.head(url, timeout=3, allow_redirects=True)
        
        if response.status_code != 200:
            return None # type: ignore
            
        content_type = response.headers.get('Content-Type', '').lower()
        
        if 'application/pdf' in content_type:
            return 'pdf'
        elif 'text/html' in content_type:
            return 'html'
        else:
            return None # Loại bỏ ảnh, video, binary khác # type: ignore
            
    except Exception:
        return None # type: ignore

def filter_and_classify_urls(urls: list[str]):
    """
    Hàm chính: Lọc danh sách URL thô và phân loại
    """
    clean_urls = []
    
    # Bước 1: Lọc trùng lặp
    unique_urls = list(set(urls))
    
    logger.info(f"🔍 Filtering {len(unique_urls)} URLs...")
    
    for url in unique_urls:
        # Lớp 1: Check tĩnh
        if not is_valid_url_static(url):
            continue
            
        # Lớp 2: Check HEAD (Có thể bỏ qua bước này nếu muốn tốc độ cực nhanh, 
        # nhưng nên giữ để biết đâu là PDF)
        doc_type = check_url_content_type(url)
        
        if doc_type:
            clean_urls.append({
                "url": url,
                "type": doc_type
            })
        else:
            pass
            logger.warning(f" ⚠️ Unreachable or Invalid Type: {url}")
            
    logger.info(f"✅ Filtered: {len(unique_urls)} -> {len(clean_urls)} high-quality links.")
    return clean_urls