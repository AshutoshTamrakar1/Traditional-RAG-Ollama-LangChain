from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


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


# centralized logger available here for any model-related validation logging
from logging_config import get_logger
logger = get_logger(__name__)
