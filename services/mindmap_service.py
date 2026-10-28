from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path

from config import Settings, get_settings
from .models import MindmapRequest, MindmapResponse
from .exceptions import ThreadNotFoundError, SourceNotFoundError
from db_manager import (
    update_source_field,
    get_chat_session_by_id
)
from ai_engine import (
    generate_mindmap_from_pdf,
    estimate_mindmap_generation_time
)
from output_parsers import MindmapOutputParser
from auth import get_current_user
from logging_config import get_logger, log_exceptions

logger = get_logger(__name__)
router = APIRouter(tags=["Mindmap Operations"])

@router.post("/generate", response_model=MindmapResponse)
@log_exceptions
async def generate_mindmap(
    request: MindmapRequest,
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings)
) -> MindmapResponse:
    """Generate mindmap from PDF with improved error handling"""
    logger.info(f"Generating mindmap for chat session: {request.chat_session_id}, source: {request.source_id}")
    
    try:
        user_id = current_user
        chat_session_data = await get_chat_session_by_id(request.chat_session_id, user_id)
        
        if not chat_session_data:
            raise ThreadNotFoundError()

        source_data = next(
            (s for s in chat_session_data.get("sources", []) 
             if s.get("source_id") == request.source_id),
            None
        )
        
        if not source_data or not source_data.get("filepath"):
            raise SourceNotFoundError()

        pdf_path = source_data["filepath"]
        estimated_time = estimate_mindmap_generation_time(pdf_path)
        logger.info(f"Estimated generation time: {estimated_time} seconds")

        # Generate mindmap with callback support for monitoring
        markdown, error = await generate_mindmap_from_pdf(pdf_path)
        if error:
            logger.error(f"Error generating mindmap: {error}")
            raise HTTPException(status_code=500, detail=error)

        # Validate mindmap with parser
        try:
            mindmap_parser = MindmapOutputParser()
            validated_mindmap = mindmap_parser.parse(markdown)
            logger.info(f"Mindmap validated: {validated_mindmap.node_count} nodes, valid={validated_mindmap.is_valid}")
            # Use validated markdown
            markdown = validated_mindmap.markdown
        except Exception as parse_error:
            logger.warning(f"Mindmap validation warning: {parse_error}. Using raw output.")
            # Continue with raw markdown if validation fails

        # Save mindmap
        mindmap_path = Path(pdf_path).parent / "mindmap.md"
        mindmap_path.write_text(markdown, encoding="utf-8")
        
        # Update database
        await update_source_field(request.chat_session_id, request.source_id, {"mindmap.path": str(mindmap_path)})

        logger.info(f"Mindmap generated and saved to: {mindmap_path}")
        return MindmapResponse(
            status="success",
            markdown=markdown,
            estimated_time=estimated_time,
            chat_session_id=request.chat_session_id,
            source_id=request.source_id
        )

    except Exception as e:
        logger.error(f"Error in mindmap generation: {str(e)}", exc_info=True)
        raise
