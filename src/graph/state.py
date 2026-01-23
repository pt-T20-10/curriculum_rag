from email import message
import operator
from re import search
from typing import Any, List, TypedDict, Annotated, Optional
from pydantic import BaseModel, Field

#--- 1. Data Models -----
# Use pydantic make sure Planner will always return right JSON format


class SubSection(BaseModel):
    title: str = Field(description="Title of the subsection (e.g., 'Variable in Python)")
    description: str = Field(description="Brief description of what to cover")
    search_query: str = Field(description="Specific search query for RAG to find this info")
    
class Chapter(BaseModel):
    title: str = Field(description="Titlle of the chapter")
    subsections: List[SubSection] = Field(description="List of subsections in this chapter")

class CurriculumOutline(BaseModel):
    """ 
        The Master Plan: A complete list of chapters and subsections
    """ 
    topic: str = Field(description="The main topic of the curriculum")
    chapters: List[Chapter] = Field(description="List of all chapter")
    
class AgentState(TypedDict):
    #Input (Ex: "Give me Python curriculum")
    request: str

    #Detailed planed from planner
    curriculum: Any
    
    #Current state
    current_chapter_index: int
    current_subsection_index: int 
    
    current_content: str
    final_content: str

    #Avoid infinity loop
    revision_number: int
    
    #List of all messages/logs from Agent
    #Annotated[List[str], operator.add]: Agent can only add.
    messages: Annotated[List[str], operator.add]