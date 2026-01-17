import os
import re
import shutil
import uuid
from pathlib import Path
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import chromadb
from tqdm import tqdm
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- IMPORTS ---
from .config import (
    CHROMA_DB_DIR, 
    EMBEDDING_MODEL_NAME, 
    CHUNK_SIZE, 
    CHUNK_OVERLAP, 
    EXTRACTED_DIR,
    STORAGE_DIR
)
from .utils import extract_book_zip
from .log_config import setup_logger

# Initialize Logger
logger = setup_logger(name="CurriculumProcessor", logfile="logs/processor.log")

class CurriculumProcessor:
    def __init__(self):
        """
        Initialize the Processor with ChromaDB client and Text Splitter.
        """
        logger.info("Initializing ChromaDB Client and Processor...")
        try:
            # Initialize Persistent Client
            self.chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
            
            # Create or get collection with cosine similarity
            self.collection = self.chroma_client.get_or_create_collection(
                name="openstax_textbooks",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            logger.critical(f"Failed to initialize ChromaDB: {e}")
            raise e
        
        # Initialize Level 2.5 Splitter (Recursive + Context aware)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ".", " ", ""],
            length_function=len,
        )
        logger.info(f"Ready to use Embedding Model: {EMBEDDING_MODEL_NAME}")

    def parse_cnxml_file(self, file_path: Path) -> Optional[Dict]:
        """
        Parses CNXML/HTML file to extract clean text and section title.
        Includes Regex fixing for broken math equations and spacing.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Use 'lxml' parser for speed and robustness
            soup = BeautifulSoup(content, 'lxml')
            
            # 1. Remove garbage tags (metadata, styles, scripts)
            for tag in soup(["script", "style", "nav", "footer", "meta", "object", "param"]):
                tag.decompose()
            
            # 2. Extract Clean Text
            # Use space separator to avoid 'Vertical Math' issues
            raw_text = soup.get_text(separator=' ', strip=True)
            
            # 3. Regex Cleaning (Crucial Step for Math/Physics content)
            # Fix A: Collapse multiple spaces into one
            clean_text = re.sub(r'\s+', ' ', raw_text)
            
            # Fix B: Add space after period if missing (e.g., "end.The" -> "end. The")
            clean_text = re.sub(r'\.([A-Z])', r'. \1', clean_text)

            # 4. Extract Title (Context)
            title = "Unknown Section"
            
            # Strategy 1: Look for <title> tag (Standard CNXML)
            title_tag = soup.find("title") 
            
            # Strategy 2: Look for class="title"
            if not title_tag:
                title_tag = soup.find(class_="title")
                
            # Strategy 3: Look for <h1>
            if not title_tag:
                title_tag = soup.find("h1")

            if title_tag:
                title = title_tag.get_text(strip=True)
            else:
                # Strategy 4 (Fallback): Use the first sentence as title
                if len(clean_text) > 0:
                    title = clean_text.split('.')[0][:100]

            return {"text": clean_text, "section_title": title}
            
        except Exception as e:
            logger.warning(f"Issue parsing file {file_path.name}: {e}")
            return None

    def process_book_zip(self, zip_path: Path):
        """
        Main pipeline: Unzip -> Parse -> Chunk -> Embed -> Store.
        Uses recursive glob to find files in nested folders.
        """
        logger.info(f"Starting pipeline for: {zip_path.name}")
        
        # Step 1: Extract Zip
        try:
            book_dir = extract_book_zip(zip_path, EXTRACTED_DIR)
        except Exception as e:
            logger.error(f"Extraction failed for {zip_path.name}: {e}")
            return

        # Step 2: Find content files (Aggressive Search)
        patterns = ["index.cnxml", "index.html", "*.xhtml", "*.cnxml"]
        all_files = []
        for pattern in patterns:
            found = list(book_dir.rglob(pattern))
            all_files.extend(found)
        
        # Deduplicate and Filter
        all_files = list(set(all_files))
        ignore_list = ["nav.xhtml", "toc.xhtml", "cover.xhtml", "collection.xml"]
        all_files = [f for f in all_files if f.name not in ignore_list]
        
        logger.info(f"Found {len(all_files)} content modules in {book_dir.name}")
        
        if len(all_files) == 0:
            logger.warning(f"No content files found in {book_dir}. Please check structure.")
            return

        batch_documents = []
        batch_metadatas = []
        batch_ids = []
        
        # Step 3: Process files
        # Tqdm writes to stderr, so it won't conflict much with logger unless we log inside loop heavily
        for file_path in tqdm(all_files, desc=f"Processing {zip_path.name}"):
            parsed_data = self.parse_cnxml_file(file_path)
            if not parsed_data: continue
            
            text_content = parsed_data["text"]
            section_title = parsed_data["section_title"]
            
            # Skip empty content
            if len(text_content) < 100:
                continue

            # Construct Metadata
            module_id = file_path.parent.name
            base_metadata = {
                "source": zip_path.stem, 
                "module": module_id,
                "section_title": section_title 
            }
            
            # Chunking
            docs = self.text_splitter.create_documents([text_content], metadatas=[base_metadata])
            
            for doc in docs:
                batch_documents.append(doc.page_content)
                batch_metadatas.append(doc.metadata)
                # FIX: Added parentheses to uuid4()
                batch_ids.append(str(uuid.uuid4()))
                
        # Step 4: Batch Insert to ChromaDB
        if batch_documents:
            batch_limit = 5000 
            total_chunks = len(batch_documents)
            logger.info(f"Generated {total_chunks} chunks. Saving to Database...")
            
            try:
                for i in range(0, total_chunks, batch_limit):
                    end = i + batch_limit
                    self.collection.add(
                        documents=batch_documents[i:end],
                        metadatas=batch_metadatas[i:end],
                        ids=batch_ids[i:end]
                    )
                logger.info(f"SUCCESS: Finished processing {zip_path.name}")
        #Step 5 Cleanup
        #Move base Zip file to storage
                target_zip = STORAGE_DIR / zip_path.name
                if target_zip.exists():
                    os.remove(target_zip)
                shutil.move(str(zip_path), str(STORAGE_DIR))
                logger.info(f"Moved source zip to storage: {STORAGE_DIR}")
        #Remove extracted folder, cause have zip inside storage     
                if book_dir.exists():
                    shutil.rmtree(book_dir)
                    logger.info(f"Cleaned up temp extracted folder: {book_dir.name}")
                    
                
            except Exception as e:
                logger.error(f"Failed to save batch to ChromaDB: {e}")
        else:
            logger.warning(f"No valid chunks generated for {zip_path.name}")