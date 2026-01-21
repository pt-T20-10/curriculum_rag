import sys
import os
import io
import shutil
import requests
import concurrent.futures
from bs4 import BeautifulSoup
from pypdf import PdfReader

# Import các thư viện AI
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.log_config import setup_logger
from src.config import CHROMA_DB_DIR, EMBEDDING_MODEL_NAME