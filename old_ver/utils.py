import zipfile
import os
import shutil
from pathlib import Path
from typing import List
from ..src.config import STORAGE_DIR


def extract_book_zip(zip_path: Path, extract_to: Path) -> Path:
    """
    Extracts the zip file to a specific directory.
    Standardizes behavior: Cleans up old extraction before unzipping.
    """
    # Create a clean folder name based on the zip file
    folder_name = zip_path.stem
    target_dir = extract_to / folder_name
    
    # 1. Clean up previous extraction if exists (Idempotency)
    if target_dir.exists():
        print(f"[INFO] Cleaning up old data in {target_dir.name}...")
        try:
            shutil.rmtree(target_dir)
        except OSError as e:
            print(f"[WARNING] Could not delete old folder: {e}")
            # If we can't delete, we try to proceed anyway

    # 2. Create fresh directory
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Extract
    print(f"[INFO] Extracting {zip_path.name} to {target_dir}...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
            
        print(f"[SUCCESS] Extracted to: {target_dir}")
      
        return target_dir
        
    except zipfile.BadZipFile:
        print(f"[ERROR] The file {zip_path.name} is not a valid zip file.")
        
        return target_dir
    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        return target_dir

def find_content_files(root_dir: Path) -> List[Path]:
    """
    Recursively find all .xhtml, . html, or . cnxml files in the given directory.
    Skips trash file (table of contents nav.xhtml, cover.html...).
    """
    content_files = []
    
    #ePub system files don't need to be processed
    ignore_files = ["nav.xhtml", "cover.html", "toc.html", "titlepage.html"]
    try: 
        for path in root_dir.rglob('*'):
            if path.is_file() and path.suffix in ['.xhtml', '.html', '.cnxml']:
                if path.name not in ignore_files:
                    content_files.append(path)
        print(f"Found {len(content_files)} content files.")
    except Exception as e:
        print(f"Error while searching for content files: {e}")
    return content_files


    