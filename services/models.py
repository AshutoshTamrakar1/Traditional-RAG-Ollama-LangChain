from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime


class BaseRequest(BaseModel):
    thread_id: Optional[str] = Field(None, description="Thread ID")
    chat_session_id: Optional[str] = Field(None, description="Chat session ID (alias for thread_id)")
    source_id: Optional[str] = Field(None, description="Source document ID")
    
    @validator("thread_id", always=True, pre=True)
    def populate_thread_id(cls, v, values):
        """Use chat_session_id as thread_id if thread_id not provided"""
        if v:
            return v
        return values.get("chat_session_id")


class ChatRequest(BaseModel):
    chat_session_id: str  # Make it required
    user_input: str
    active_source_ids: List[str] = []
    model: Optional[str] = "llama3"  # Model to use: llama3, gemma
    # Optionally keep thread_id for backward compatibility
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    turn_id: str
    sources: List[str]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MindmapRequest(BaseRequest):
    """Mindmap generation request - inherits thread_id, chat_session_id, source_id from BaseRequest"""
    pass


class MindmapResponse(BaseModel):
    status: str
    markdown: str
    estimated_time: int
    thread_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    source_id: Optional[str] = None
    file_path: Optional[str] = None


# centralized logger available here for any model-related validation logging
from logging_config import get_logger
logger = get_logger(__name__)
