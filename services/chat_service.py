from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from typing import Dict, Any, Optional, List, AsyncGenerator, Tuple
from pydantic import BaseModel
from datetime import datetime

from config import Settings, get_settings
from .models import ChatRequest, ChatResponse
from .exceptions import InvalidSessionError, ThreadNotFoundError
from .utils import get_user_from_token, handle_service_error
from db_manager import (
    add_turn_to_general_chat,
    add_turn_to_multi_source_chat,
    add_question_to_source,
    get_chat_session_by_id,
    rename_chat_session_title
)
from ai_engine import (
    chat_completion_LlamaModel_ws,
    chat_completion_Gemma_ws,
    chat_completion_with_pdf_ws,
    chat_completion_with_multiple_pdfs_ws,
    get_available_models,
    generate_chat_title,
    HISTORY_LENGTH
)
from callbacks import (
    create_callback_manager,
    PerformanceCallbackHandler,
    LoggingCallbackHandler
)
from output_parsers import TitleOutputParser, ChatTitle
from auth import get_current_user
import uuid
from logging_config import get_logger, log_exceptions

logger = get_logger(__name__)
router = APIRouter(tags=["Chat Operations"])

def process_chat_completion(
    user_input: str,
    chat_session_data: Dict,
    active_source_ids: List[str],
    settings: Settings,
    model: Optional[str] = None
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """Select correct ai_engine async-generator based on context and requested model.

    - If one or more PDFs selected -> use RAG functions (llama3 RAG).
    - If no PDFs selected -> use Gemma if model == "gemma", otherwise llama3.
    Returns an async generator yielding (chunk, error).
    """
    logger.debug(f"Processing chat with {len(active_source_ids)} active sources; model={model}")

    # Get chat turns and convert to history format expected by AI engine
    raw_messages = chat_session_data.get("messages", []) or []
    logger.debug(f"Retrieved {len(raw_messages)} raw messages from chat session")
    history: List[Dict[str, str]] = []
    
    # Convert from {user_query, assistant_response} to [{role, content}] format
    for msg in raw_messages:
        if isinstance(msg, dict):
            # If already in correct format
            if "role" in msg and "content" in msg:
                history.append(msg)
            # If in database format (turns)
            elif "user_query" in msg or "assistant_response" in msg:
                if "user_query" in msg and msg["user_query"]:
                    history.append({"role": "user", "content": msg["user_query"]})
                if "assistant_response" in msg and msg["assistant_response"]:
                    history.append({"role": "assistant", "content": msg["assistant_response"]})
    
    logger.debug(f"Converted to {len(history)} history messages in [{{'role', 'content'}}] format")

    if len(active_source_ids) == 1:
        source_data = next(
            (s for s in chat_session_data.get("sources", [])
             if s.get("source_id") == active_source_ids[0]),
            None
        )
        if not source_data or not source_data.get("filepath"):
            async def _err():
                yield None, "Source document not found"
            return _err()

        # single-PDF RAG with selected model
        return chat_completion_with_pdf_ws(
            user_input,
            history,
            source_data["filepath"],
            model=model or "llama3"
        )
    elif len(active_source_ids) > 1:
        pdf_paths = [
            s.get("filepath") for s in chat_session_data.get("sources", [])
            if s.get("source_id") in active_source_ids and s.get("filepath")
        ]
        return chat_completion_with_multiple_pdfs_ws(
            user_input,
            history,
            pdf_paths,
            model=model or "llama3"
        )
    else:
        # general chat: use selected model (llama3 or gemma only)
        if model and model.lower() == "gemma":
            return chat_completion_Gemma_ws(user_input, history)
        # Default to llama3 for any other model
        return chat_completion_LlamaModel_ws(user_input, history)

@router.post("/send", response_model=ChatResponse)
@log_exceptions
async def send_chat(
    request: ChatRequest,
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings)
) -> ChatResponse:
    """Handle chat messages with model selection support (llama3, gemma). phi3 is reserved for podcast generation."""
    logger.info(f"Chat request received:")
    logger.info(f"  - user_id: {current_user[:20] if current_user else 'None'}...")
    logger.info(f"  - chat_session_id: {request.chat_session_id}")
    logger.info(f"  - user_input: {request.user_input[:50] if request.user_input else 'None'}...")
    logger.info(f"  - active_source_ids: {request.active_source_ids}")
    logger.info(f"  - model: {request.model}")
    logger.info(f"Processing chat request for chat session: {request.chat_session_id}; model={request.model}")

    try:
        user_id = current_user
        chat_session_data = await get_chat_session_by_id(request.chat_session_id, user_id)

        if not chat_session_data:
            raise ThreadNotFoundError()

        # get async generator (do NOT await)
        completion_generator = process_chat_completion(
            request.user_input,
            chat_session_data,
            request.active_source_ids,
            settings,
            model=request.model
        )

        # Stream / collect response
        full_response = ""
        async for chunk, error in completion_generator:
            if error:
                logger.error(f"Error in chat completion: {error}")
                raise HTTPException(status_code=500, detail=error)
            if chunk:
                full_response += chunk

        # Save chat turn
        turn_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        new_turn = {
            "id": turn_id,
            "user_query": request.user_input,
            "assistant_response": full_response,
            "timestamp": timestamp,
            "feedback": None
        }

        # Save based on chat type
        if len(request.active_source_ids) > 1:
            await add_turn_to_multi_source_chat(request.chat_session_id, request.active_source_ids, new_turn)
        elif len(request.active_source_ids) == 1:
            await add_question_to_source(request.chat_session_id, request.active_source_ids[0], new_turn)
        else:
            await add_turn_to_general_chat(request.chat_session_id, new_turn)

        logger.info(f"Chat turn saved with ID: {turn_id}")
        
        # Generate a title automatically on the first message (the upload step may already
        # have set a placeholder title such as the PDF filename, so don't require "New Chat")
        if len(chat_session_data.get("messages", [])) == 0:
            logger.info("First message detected, generating chat title...")
            try:
                # Create messages for title generation
                messages_for_title = [
                    {"role": "user", "content": request.user_input},
                    {"role": "assistant", "content": full_response}
                ]
                
                # Generate title asynchronously
                new_title = await generate_chat_title(messages_for_title)
                
                if new_title:
                    await rename_chat_session_title(request.chat_session_id, new_title)
                    logger.info(f"Chat title updated to: {new_title}")
            except Exception as e:
                logger.error(f"Failed to generate chat title: {e}")
                # Don't fail the request if title generation fails
        
        return ChatResponse(
            answer=full_response,
            turn_id=turn_id,
            sources=request.active_source_ids
        )

    except Exception:
        # decorator already logs exception; re-raise to let FastAPI handle response
        raise

@router.get("/models")
@log_exceptions
async def list_available_models():
    """Get list of available chat models"""
    models = get_available_models()
    return {
        "models": models,
        "default": "llama3"
    }


class GenerateTitleRequest(BaseModel):
    chat_session_id: str


@router.post("/generate-title")
@log_exceptions
async def generate_title(
    request: GenerateTitleRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate (and save) a title for a chat session from its first turns"""
    chat_session_data = await get_chat_session_by_id(request.chat_session_id, current_user)
    if not chat_session_data:
        raise HTTPException(status_code=404, detail="Thread not found")

    messages_for_title: List[Dict[str, str]] = []
    for turn in (chat_session_data.get("messages") or [])[:3]:
        if isinstance(turn, dict):
            if turn.get("user_query"):
                messages_for_title.append({"role": "user", "content": turn["user_query"]})
            if turn.get("assistant_response"):
                messages_for_title.append({"role": "assistant", "content": turn["assistant_response"]})
    if not messages_for_title:
        raise HTTPException(status_code=400, detail="Chat has no messages to generate a title from")

    title = await generate_chat_title(messages_for_title)
    if not title:
        raise HTTPException(status_code=500, detail="Failed to generate title")

    await rename_chat_session_title(request.chat_session_id, title)
    return {"chat_session_id": request.chat_session_id, "title": title}