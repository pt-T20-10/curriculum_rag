from importlib import metadata
import logging
from pydoc import doc
from typing import List, Dict
from unittest import result
import chromadb
from langchain_core.tools import tool
from sympy import re

from src.config import CHROMA_DB_DIR

logger = logging.getLogger("SearchTool")

#Singleton for ChromaDB
try:
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    collection = chroma_client.get_collection("openstax_textbooks")
    logger.info(f"Connected to Knowledge Base at: {CHROMA_DB_DIR}") 
except Exception as e:
    logger.error(f"Failed to connect to ChromaDB: {e}")
    collection = None
    
@tool
def search_knowlege_base(query: str) -> str:
    """
    Useful for retrieving academic content from physics/IT textbooks.
    Input should be a specific query string (e.g., 'Newton's second law definition', 'Python lists vs tuples').
    Returns the most relevant text chunks from the database.
    """
    if not collection:
        return "Error: Database connection is not active"
    
    try:
        logger.info(f"Searching for: '{query}'")
        
        #Query, get best 5 results
        results = collection.query(
            query_texts=[query],
            n_results=5
        )
        
        #Process result, covert to string for Agent can read
        documents = results.get('documents', [[]])[0] # type: ignore
        metadatas = results.get('metadatas', [[]])[0] # type: ignore
    
        if not documents:
            return "No relevant information found in the knowledge base."
        
        formmated_results = []
        
        for i, (doc,meta) in enumerate(zip(documents,metadatas)):
            source = meta.get('section_title', 'Unknown Source')
            
            formmated_results.append(f"Source {i+1} ({source}):\n {doc}")
            
        return "\n\n---\n\n".join(formmated_results)
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Error executing search: {e}"
    
    