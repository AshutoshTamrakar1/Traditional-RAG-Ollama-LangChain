"""
Memory Manager for MongoDB-backed conversation history.

This module provides LangChain memory management integrated with MongoDB,
allowing conversation history to persist across sessions.
"""

import logging
from typing import Optional, Dict
from langchain_mongodb.chat_message_histories import MongoDBChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory

from config import get_settings
from db_manager import _db_manager

logger = logging.getLogger(__name__)

# Cache for history instances (per session)
_history_cache: Dict[str, MongoDBChatMessageHistory] = {}


def get_mongodb_chat_history(
    session_id: str
) -> MongoDBChatMessageHistory:
    """
    Get MongoDB-backed chat message history for a session.
    
    Args:
        session_id: Chat session ID
        
    Returns:
        MongoDBChatMessageHistory instance
    """
    # Return cached instance if exists
    if session_id in _history_cache:
        return _history_cache[session_id]
    
    settings = get_settings()
    
    # Use session_id as collection name (MongoDB will create if doesn't exist)
    # Note: MongoDBChatMessageHistory expects connection_string, not client
    history = MongoDBChatMessageHistory(
        connection_string=settings.MONGODB_URI,
        database_name=settings.MONGODB_DB_NAME,
        collection_name=f"chat_history_{session_id}",
        session_id=session_id
    )
    
    # Cache for reuse
    _history_cache[session_id] = history
    
    logger.debug(f"Created MongoDB chat history for session: {session_id}")
    return history


def get_windowed_messages(
    session_id: str,
    k: int = 10
) -> list:
    """
    Get the last k message pairs from history (windowed memory).
    
    This provides memory window functionality without ConversationBufferWindowMemory.
    
    Args:
        session_id: Chat session ID
        k: Number of message exchanges to return (default: 10, from HISTORY_LENGTH)
        
    Returns:
        List of recent messages (max 2*k messages for k exchanges)
    """
    history = get_mongodb_chat_history(session_id)
    messages = history.messages
    
    # Return last k exchanges (2 messages per exchange)
    max_messages = k * 2
    windowed = messages[-max_messages:] if len(messages) > max_messages else messages
    
    logger.debug(f"Retrieved {len(windowed)} windowed messages for session {session_id}")
    return windowed


def clear_history_cache(session_id: Optional[str] = None):
    """
    Clear history cache for a specific session or all sessions.
    
    Args:
        session_id: If provided, clear only this session. If None, clear all.
    """
    global _history_cache
    
    if session_id:
        # Clear specific session
        if session_id in _history_cache:
            del _history_cache[session_id]
        logger.info(f"Cleared history cache for session: {session_id}")
    else:
        # Clear all
        _history_cache.clear()
        logger.info("Cleared all history cache")


def get_recent_messages(
    session_id: str,
    limit: int = 10
) -> list:
    """
    Get recent messages from MongoDB chat history.
    
    Args:
        session_id: Chat session ID
        limit: Number of recent messages to retrieve
        
    Returns:
        List of message dictionaries with 'role' and 'content'
    """
    try:
        history = get_mongodb_chat_history(session_id)
        messages = history.messages
        
        # Convert to simple dict format
        recent = []
        for msg in messages[-limit:] if len(messages) > limit else messages:
            if hasattr(msg, 'type'):
                role = 'user' if msg.type == 'human' else 'assistant'
            else:
                role = 'assistant'
            
            recent.append({
                'role': role,
                'content': msg.content
            })
        
        logger.debug(f"Retrieved {len(recent)} recent messages for session: {session_id}")
        return recent
        
    except Exception as e:
        logger.exception(f"Failed to get recent messages for session {session_id}: {e}")
        return []


def add_message_to_history(
    session_id: str,
    role: str,
    content: str
):
    """
    Add a message to MongoDB chat history.
    
    Args:
        session_id: Chat session ID
        role: 'user' or 'assistant'
        content: Message content
    """
    try:
        history = get_mongodb_chat_history(session_id)
        
        if role == 'user':
            history.add_user_message(content)
        else:
            history.add_ai_message(content)
        
        logger.debug(f"Added {role} message to session {session_id}")
        
    except Exception as e:
        logger.exception(f"Failed to add message to session {session_id}: {e}")
        raise


async def sync_memory_with_mongodb(session_id: str):
    """
    Synchronize LangChain memory with existing MongoDB chat messages.
    
    This is useful when migrating from the old system where messages
    were stored directly in MongoDB chat_sessions collection.
    
    Args:
        session_id: Chat session ID to sync
    """
    try:
        # Get messages from old MongoDB structure
        chat_session = await _db_manager.chat_sessions.find_one(
            {"chat_session_id": session_id}
        )
        
        if not chat_session:
            logger.warning(f"No chat session found for {session_id}")
            return
        
        messages = chat_session.get('messages', [])
        if not messages:
            logger.info(f"No messages to sync for session {session_id}")
            return
        
        # Get MongoDB chat history (LangChain)
        history = get_mongodb_chat_history(session_id)
        
        # Check if already synced (avoid duplicates)
        if len(history.messages) >= len(messages):
            logger.info(f"Session {session_id} already synced")
            return
        
        # Add messages to LangChain history
        for msg in messages:
            role = msg.get('role')
            content = msg.get('content')
            
            if role == 'user':
                history.add_user_message(content)
            elif role == 'assistant':
                history.add_ai_message(content)
        
        logger.info(f"Synced {len(messages)} messages for session {session_id}")
        
    except Exception as e:
        logger.exception(f"Failed to sync memory for session {session_id}: {e}")
        raise


# Global singleton for memory management
_memory_manager_initialized = False


def initialize_memory_manager():
    """Initialize memory manager (called on app startup)."""
    global _memory_manager_initialized
    
    if not _memory_manager_initialized:
        logger.info("Memory manager initialized with MongoDB backend")
        _memory_manager_initialized = True


# Initialize on module import
initialize_memory_manager()
