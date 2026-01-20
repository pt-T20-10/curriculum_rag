import os
import sys
from venv import logger
from src.config import RAW_MANUAL_DIR
from old_ver.processor import CurriculumProcessor
from src.config.log_config import setup_logger

logger = setup_logger(name="MainApplication", logfile="logs/main.log")

def main():
    # 1. Check for existing zip files in the input directory
    zip_files = list(RAW_MANUAL_DIR.glob("*.zip"))
    
    if not zip_files:
        print(f"[ERROR] No .zip files found in directory: {RAW_MANUAL_DIR}")
        print("Please download the Source Code ZIP from OpenStax GitHub and place it there.")
        return

    print(f"[INFO] Found {len(zip_files)} book(s). Starting ingestion pipeline...")
    
    # 2. Initialize the Processor Core
    try:
        processor = CurriculumProcessor()
    except Exception as e:
        print(f"[CRITICAL] Failed to initialize Processor. Check your libraries or API keys. Error: {e}")
        return
    
    # 3. Iterate and process each book
    for zip_file in zip_files:
        print(f"\n=== Processing Book: {zip_file.name} ===")
        try:
            # The processor handles extraction, parsing, and database storage internally
            processor.process_book_zip(zip_file)
        except Exception as e:
            print(f"[ERROR] An error occurred while processing {zip_file.name}: {e}")

if __name__ == "__main__":
    main()