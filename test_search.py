import chromadb
from src.config import CHROMA_DB_DIR

def test_retrieval():
    print(f"Connecting to DB at: {CHROMA_DB_DIR}")
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    
    try:
        collection = client.get_collection("openstax_textbooks")
        count = collection.count()
        print(f"--> Total chunks in DB: {count}")
        
        # Thử tìm kiếm
        query = "Blood vessels"
        print(f"\n--> Querying: '{query}'")
        
        results = collection.query(
            query_texts=[query],
            n_results=10
        )
        
        # --- FIX LỖI PYLANCE Ở ĐÂY ---
        # Kiểm tra xem kết quả có tồn tại không trước khi truy cập [0]
        documents = results.get('documents')
        metadatas = results.get('metadatas')

        if documents and metadatas: # Nếu cả 2 đều không phải None và không rỗng
            # ChromaDB trả về list lồng nhau (list of lists) nên cần lấy [0]
            first_query_docs = documents[0]
            first_query_meta = metadatas[0]

            for i, doc in enumerate(first_query_docs):
                meta = first_query_meta[i]
                # Dùng .get() để an toàn hơn nếu metadata thiếu trường section_title
                source_title = meta.get('section_title', 'Unknown Section')
                
                print(f"\n[Result {i+1}] (Source: {source_title})")
                print("-" * 50)
                print(doc[:200] + "...") 
        else:
            print("[WARNING] No results found or data is corrupted.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_retrieval()