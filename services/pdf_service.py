from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from pathlib import Path
import shutil
from datetime import datetime

from config import Settings, get_settings
from .exceptions import ThreadNotFoundError
from .utils import ensure_upload_dir
from db_manager import (
    add_source_to_chat_session,
    add_filename_to_uploaded_list,
    update_chat_session_field,
    get_chat_session_by_id,
    create_chat_session_in_db,
    get_user_chat_session_list,
    mark_chat_session_as_deleted
)
from auth import get_current_user
import uuid
from logging_config import get_logger, log_exceptions

logger = get_logger(__name__)
router = APIRouter(tags=["PDF Operations"])

@router.post("/session")
@log_exceptions
async def create_chat_session(
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings)
):
    """Create a new chat session"""
    logger.info(f"Creating new chat session for user: {current_user}")
    
    try:
        user_id = current_user
        chat_session_id = str(uuid.uuid4())
        
        new_chat_session = {
            "chat_session_id": chat_session_id,
            "user_id": user_id,
            "title": "New Chat",
            "created_at": datetime.utcnow().isoformat(),
            "messages": [],
            "sources": []
        }
        
        # Database write — use async db_manager (Motor)
        await create_chat_session_in_db(new_chat_session)
        
        return JSONResponse(
            status_code=200,
            content={
                "chat_session_id": chat_session_id,
                "title": "New Chat"
            }
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create chat session")

@router.get("/session/{chat_session_id}")
@log_exceptions
async def get_chat_session(
    chat_session_id: str,
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings)
):
    """Get chat session details including updated title"""
    logger.info(f"Fetching chat session: {chat_session_id}")
    
    try:
        user_id = current_user
        chat_session_data = await get_chat_session_by_id(chat_session_id, user_id)
        
        if not chat_session_data:
            raise ThreadNotFoundError()
        
        return JSONResponse(
            status_code=200,
            content={
                "chat_session_id": chat_session_id,
                "title": chat_session_data.get("title", "New Chat"),
                "created_at": chat_session_data.get("created_at"),
                "message_count": len(chat_session_data.get("messages", [])),
                "source_count": len(chat_session_data.get("sources", []))
            }
        )
    except ThreadNotFoundError:
        raise HTTPException(status_code=404, detail="Chat session not found")
    except Exception as e:
        logger.error(f"Error fetching chat session: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch chat session")

@router.get("/sessions")
@log_exceptions
async def list_chat_sessions(
    current_user: str = Depends(get_current_user)
):
    """List the current user's chat sessions (most recent first)"""
    sessions = await get_user_chat_session_list(current_user)
    return JSONResponse(
        status_code=200,
        content={
            "sessions": [
                {
                    "chat_session_id": s.get("chat_session_id"),
                    "title": s.get("title", "New Chat"),
                    "created_at": s.get("created_at"),
                    "updated_at": s.get("updated_at"),
                }
                for s in sessions
            ]
        }
    )

@router.delete("/session/{chat_session_id}")
@log_exceptions
async def delete_chat_session(
    chat_session_id: str,
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings)
):
    """Delete a chat session together with its uploaded files and vector collections"""
    chat_session_data = await get_chat_session_by_id(chat_session_id, current_user)
    if not chat_session_data:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Remove vectors for every source in this session
    try:
        from ai_engine import _get_collection_name
        from vectorstore_manager import get_vectorstore_manager
        vs = get_vectorstore_manager()
        for src in chat_session_data.get("sources", []):
            filepath = src.get("filepath")
            if not filepath:
                continue
            name = _get_collection_name(filepath)
            if await run_in_threadpool(vs.collection_exists, name):
                await run_in_threadpool(vs.delete_collection, name)
    except Exception as e:
        logger.warning(f"Could not remove vectors for session {chat_session_id}: {e}")

    # Remove uploaded files
    session_dir = Path(settings.UPLOAD_DIR) / current_user / chat_session_id
    shutil.rmtree(session_dir, ignore_errors=True)

    await mark_chat_session_as_deleted(chat_session_id)
    logger.info(f"Chat session deleted: {chat_session_id}")
    return JSONResponse(
        status_code=200,
        content={"status": "success", "chat_session_id": chat_session_id}
    )

@router.post("/upload")
@log_exceptions
async def upload_pdf(
    file: UploadFile = File(...),
    chat_session_id: str = Form(...),
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings)
):
    """Handle PDF upload with improved error handling and logging"""
    logger.info(f"Processing PDF upload: {file.filename} for chat session {chat_session_id}")
    
    try:
        user_id = current_user
        logger.debug(f"Authenticated user_id: {user_id}")
        
        logger.debug(f"Fetching chat session: {chat_session_id}")
        chat_session_data = await get_chat_session_by_id(chat_session_id, user_id)
        
        if not chat_session_data:
            logger.error(f"Chat session not found: {chat_session_id}")
            raise ThreadNotFoundError()

        # Validate the upload is really a PDF (extension + magic bytes)
        original_name = Path(file.filename or "").name  # strips any path components
        if not original_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        header = await file.read(5)
        await file.seek(0)
        if header != b"%PDF-":
            raise HTTPException(status_code=400, detail="File is not a valid PDF")

        source_id = str(uuid.uuid4())
        logger.debug(f"Creating upload directory for source: {source_id}")
        upload_dir = ensure_upload_dir(
            user_id, chat_session_id, source_id, settings.UPLOAD_DIR
        )
        
        file_path = upload_dir / original_name
        logger.debug(f"Saving file to: {file_path}")
        
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        new_source = {
            "source_id": source_id,
            "filename": original_name,
            "filepath": str(file_path),
            "related_questions": [],
            "mindmap": {"path": None, "chat_messages": []},
        }

        # DB writes — use async db_manager functions
        await add_source_to_chat_session(chat_session_id, new_source)
        await add_filename_to_uploaded_list(chat_session_id, original_name)

        # Update chat session title if needed
        new_title = None
        if not chat_session_data.get('sources') and chat_session_data.get('title') == "New Chat":
            new_title = original_name
            await update_chat_session_field(chat_session_id, {'title': new_title})
            logger.info(f"Updated chat session title to: {new_title}")

        logger.info(f"PDF upload successful: {file.filename}")
        return JSONResponse(
            status_code=200,
            content={
                "message": "File uploaded successfully",
                "new_source": new_source,
                "chat_session_id": chat_session_id,
                "new_title": new_title
            }
        )

    except HTTPException:
        # Re-raise HTTP exceptions (like ThreadNotFoundError)
        raise
    except Exception as e:
        logger.error(f"PDF upload error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
