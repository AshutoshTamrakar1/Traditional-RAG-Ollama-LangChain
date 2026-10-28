from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional, List, AsyncGenerator, Tuple, Annotated
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

from .models import ChatRequest, ChatResponse
from .exceptions import ThreadNotFoundError
from db_manager import (
    add_turn_to_general_chat,
    add_turn_to_multi_source_chat,
    add_question_to_source,
    get_chat_session_by_id,
    rename_chat_session_title
)
from ai_engine import (
    chat_completion_llama_model_ws,
    chat_completion_gemma_ws,
    chat_completion_with_pdf_ws,
    chat_completion_with_multiple_pdfs_ws,
    get_available_models,
    generate_chat_title
)
from auth import get_current_user
from logging_config import get_logger, log_exceptions

logger = get_logger(__name__)
router = APIRouter(tags=["Chat Operations"])


def _format_history_messages(raw_messages: list) -> List[Dict[str, str]]:
    """Convert raw database messages into standard [{role, content}] format."""
    history: List[Dict[str, str]] = []
    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        if "role" in msg and "content" in msg:
            history.append(msg)
        elif "user_query" in msg or "assistant_response" in msg:
            if msg.get("user_query"):
                history.append({"role": "user", "content": msg["user_query"]})
            if msg.get("assistant_response"):
                history.append({"role": "assistant", "content": msg["assistant_response"]})
    return history


def _get_source_id(source: dict) -> str:
    """Extract source identifier from source dict (supports source_id or legacy id)."""
    return source.get("source_id") or source.get("id") or ""


def _extract_active_pdf_paths(active_source_ids: List[str], session_sources: list) -> List[str]:
    """Extract filepaths for active sources in a session, auto-activating if unselected."""
    if not active_source_ids and session_sources:
        active_source_ids = [_get_source_id(s) for s in session_sources if _get_source_id(s)]

    target_ids = set(active_source_ids)
    return [
        s["filepath"]
        for s in session_sources
        if _get_source_id(s) in target_ids and s.get("filepath")
    ]


def _dispatch_chat_completion(
    user_input: str,
    history: List[Dict[str, str]],
    chat_session_data: Dict,
    active_source_ids: List[str],
    model: Optional[str] = None
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """Dispatch chat completion to appropriate AI generator."""
    session_sources = chat_session_data.get("sources", []) or []
    pdf_paths = _extract_active_pdf_paths(active_source_ids, session_sources)

    if active_source_ids and not pdf_paths:
        async def _err():
            yield None, "Source document not found"
        return _err()

    if len(pdf_paths) == 1:
        return chat_completion_with_pdf_ws(
            user_input,
            history,
            pdf_paths[0],
            model=model or "llama3"
        )

    if len(pdf_paths) > 1:
        return chat_completion_with_multiple_pdfs_ws(
            user_input,
            history,
            pdf_paths,
            model=model or "llama3"
        )

    if model and model.lower() == "gemma":
        return chat_completion_gemma_ws(user_input, history)
    return chat_completion_llama_model_ws(user_input, history)


def process_chat_completion(
    user_input: str,
    chat_session_data: Dict,
    active_source_ids: List[str],
    model: Optional[str] = None
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """Select correct ai_engine async-generator based on context and requested model.

    - If one or more PDFs selected -> use RAG functions (llama3 RAG).
    - If no PDFs selected -> use Gemma if model == "gemma", otherwise llama3.
    Returns an async generator yielding (chunk, error).
    """
    logger.debug(f"Processing chat with {len(active_source_ids)} active sources; model={model}")
    raw_messages = chat_session_data.get("messages", []) or []
    history = _format_history_messages(raw_messages)
    return _dispatch_chat_completion(user_input, history, chat_session_data, active_source_ids, model)


async def _save_chat_turn(
    chat_session_id: str,
    active_source_ids: List[str],
    new_turn: Dict[str, Any]
) -> None:
    """Save turn to DB according to single, multi, or general chat context."""
    if len(active_source_ids) > 1:
        await add_turn_to_multi_source_chat(chat_session_id, active_source_ids, new_turn)
    elif len(active_source_ids) == 1:
        await add_question_to_source(chat_session_id, active_source_ids[0], new_turn)
    else:
        await add_turn_to_general_chat(chat_session_id, new_turn)


async def _maybe_generate_initial_title(
    chat_session_data: Dict[str, Any],
    chat_session_id: str,
    user_input: str,
    full_response: str
) -> None:
    """Auto-generate chat title on first message in a thread."""
    if len(chat_session_data.get("messages", [])) == 0:
        logger.info("First message detected, generating chat title...")
        try:
            messages_for_title = [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": full_response}
            ]
            new_title = await generate_chat_title(messages_for_title)
            if new_title:
                await rename_chat_session_title(chat_session_id, new_title)
                logger.info(f"Chat title updated to: {new_title}")
        except Exception as e:
            logger.error(f"Failed to generate chat title: {e}")


@router.post(
    "/send",
    responses={
        404: {"description": "Chat session not found"},
        500: {"description": "Error in chat completion"}
    }
)
@log_exceptions
async def send_chat(
    request: ChatRequest,
    current_user: Annotated[str, Depends(get_current_user)]
) -> ChatResponse:
    """Handle chat messages with model selection support (llama3, gemma)."""
    logger.info("Chat request received:")
    logger.info(f"  - user_id: {current_user[:20] if current_user else 'None'}...")
    logger.info(f"  - chat_session_id: {request.chat_session_id}")
    logger.info(f"  - user_input: {request.user_input[:50] if request.user_input else 'None'}...")
    logger.info(f"  - active_source_ids: {request.active_source_ids}")
    logger.info(f"  - model: {request.model}")
    logger.info(f"Processing chat request for chat session: {request.chat_session_id}; model={request.model}")

    user_id = current_user
    chat_session_data = await get_chat_session_by_id(request.chat_session_id, user_id)

    if not chat_session_data:
        raise ThreadNotFoundError()

    # get async generator (do NOT await)
    completion_generator = process_chat_completion(
        request.user_input,
        chat_session_data,
        request.active_source_ids,
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
    timestamp = datetime.now(timezone.utc).isoformat()

    new_turn = {
        "id": turn_id,
        "user_query": request.user_input,
        "assistant_response": full_response,
        "timestamp": timestamp,
        "feedback": None
    }

    await _save_chat_turn(request.chat_session_id, request.active_source_ids, new_turn)
    logger.info(f"Chat turn saved with ID: {turn_id}")

    # Generate a title automatically on the first message
    await _maybe_generate_initial_title(chat_session_data, request.chat_session_id, request.user_input, full_response)

    return ChatResponse(
        answer=full_response,
        turn_id=turn_id,
        sources=request.active_source_ids
    )


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


@router.post(
    "/generate-title",
    responses={
        400: {"description": "Chat has no messages to generate a title from"},
        404: {"description": "Chat session not found"},
        500: {"description": "Failed to generate title"}
    }
)
@log_exceptions
async def generate_title(
    request: GenerateTitleRequest,
    current_user: Annotated[str, Depends(get_current_user)]
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
