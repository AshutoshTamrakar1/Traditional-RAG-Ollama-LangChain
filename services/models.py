from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class MessageType(str, Enum):
    CHAT = "chat_message"
    CREATE_THREAD = "create_new_thread"
    LOAD_THREAD = "load_thread"
    DELETE_THREAD = "delete_thread"
    RENAME_THREAD = "rename_thread"
    GENERATE_MINDMAP = "generate_mindmap"
    GENERATE_PODCAST = "generate_podcast"
    FEEDBACK = "message_feedback"

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
    model: Optional[str] = "llama3"  # Model to use: llama3, gemma, phi3
    # Optionally keep thread_id for backward compatibility
    thread_id: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    turn_id: str
    sources: List[str]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class MindmapRequest(BaseRequest):
    """Mindmap generation request - inherits session_id, thread_id, chat_session_id, source_id from BaseRequest"""
    pass

class MindmapResponse(BaseModel):
    status: str
    markdown: str
    estimated_time: int
    thread_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    source_id: Optional[str] = None
    file_path: Optional[str] = None

class PodcastRequest(BaseRequest):
    """Podcast generation request - inherits session_id, thread_id, chat_session_id, source_id from BaseRequest"""
    mindmap_id: Optional[str] = None

class PodcastResponse(BaseModel):
    status: str
    data: Dict[str, Any]
    estimated_time: int
    thread_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    source_id: Optional[str] = None
    audio_path: Optional[str] = None

class WebSocketMessage(BaseModel):
    type: MessageType
    data: Dict[str, Any] = Field(default_factory=dict)
    client_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @validator('data')
    def validate_data(cls, v, values):
        msg_type = values.get('type')
        if msg_type == MessageType.CHAT:
            if not v.get('user_input'):
                raise ValueError("Chat messages must include user_input")
        elif msg_type == MessageType.GENERATE_MINDMAP:
            if not v.get('source_id'):
                raise ValueError("Mindmap generation requires source_id")
        return v

class WebSocketResponse(BaseModel):
    type: str
    data: Dict[str, Any]
    error: Optional[str] = None
    client_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# centralized logger available here for any model-related validation logging
from logging_config import get_logger
logger = get_logger(__name__)