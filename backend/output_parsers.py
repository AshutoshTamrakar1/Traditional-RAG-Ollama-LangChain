"""
Output parsers and structured output models for LangChain.

This module provides:
- Pydantic models for structured outputs
- Output parsers for different response types
- Validation and formatting utilities
"""

import logging
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Final
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from langchain_core.output_parsers import StrOutputParser, JsonOutputParser, PydanticOutputParser

logger = logging.getLogger(__name__)

# Constants
JSON_CODE_BLOCK_START: Final[str] = "```json"
CODE_BLOCK_DELIMITER: Final[str] = "```"
DEFAULT_CHAT_TITLE: Final[str] = "New Chat"

TITLE_PREFIXES: Final[tuple[str, ...]] = (
    "title:",
    "suggested title:",
    "chat title:",
    "conversation title:",
)

PREAMBLE_PREFIXES: Final[tuple[str, ...]] = (
    "here is",
    "here's",
    "here are",
    "sure",
    "certainly",
    "okay",
    "ok",
    "based on the conversation",
    "based on our conversation",
)

QUOTE_AND_MARKDOWN_CHARS: Final[str] = "\"'`“«”»*# \t\r\n"


# ============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUTS
# ============================================================================

class ChatTitle(BaseModel):
    """Model for chat conversation title."""
    title: str = Field(
        description="A concise, descriptive title for the conversation (max 100 chars)"
    )
    confidence: Optional[float] = Field(
        default=None,
        description="Confidence score for the generated title (0-1)"
    )
    keywords: Optional[List[str]] = Field(
        default=None,
        description="Key topics or keywords from the conversation"
    )
    
    @field_validator("title")
    @classmethod
    def title_length(cls, v):
        """Validate title length."""
        if len(v) > 100:
            return v[:97] + "..."
        return v
    
    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v):
        """Validate confidence is between 0 and 1."""
        if v is not None and (v < 0 or v > 1):
            raise ValueError("Confidence must be between 0 and 1")
        return v


class ChatMetadata(BaseModel):
    """Metadata for chat completion."""
    model: str = Field(description="Model used for generation")
    duration: Optional[float] = Field(default=None, description="Generation duration in seconds")
    tokens: Optional[int] = Field(default=None, description="Approximate token count")
    timestamp: datetime = Field(default_factory=datetime.now, description="Completion timestamp")
    session_id: Optional[str] = Field(default=None, description="Session identifier")
    has_context: bool = Field(default=False, description="Whether RAG context was used")
    context_source: Optional[str] = Field(default=None, description="Source of context (PDF, etc.)")


class StructuredChatResponse(BaseModel):
    """Structured chat response with metadata."""
    response: str = Field(description="The actual chat response text")
    metadata: ChatMetadata = Field(description="Response metadata")
    error: Optional[str] = Field(default=None, description="Error message if any")
    
    @field_validator("response")
    @classmethod
    def response_not_empty(cls, v):
        """Validate response is not empty."""
        if not v or not v.strip():
            raise ValueError("Response cannot be empty")
        return v


class DocumentSummary(BaseModel):
    """Summary of a document for RAG operations."""
    title: str = Field(description="Document title or filename")
    summary: str = Field(description="Brief summary of document content")
    key_topics: List[str] = Field(description="Main topics covered")
    page_count: Optional[int] = Field(default=None, description="Number of pages")
    word_count: Optional[int] = Field(default=None, description="Approximate word count")


class RAGResponse(BaseModel):
    """Structured RAG response with sources."""
    answer: str = Field(description="The answer to the question")
    sources: List[str] = Field(default_factory=list, description="Source documents used")
    confidence: Optional[float] = Field(default=None, description="Confidence in answer (0-1)")
    relevant_chunks: Optional[int] = Field(default=None, description="Number of relevant chunks retrieved")
    metadata: Optional[ChatMetadata] = Field(default=None, description="Response metadata")


# ============================================================================
# EXTRACTION UTILITIES
# ============================================================================

def _clean_json_string(s: str) -> str:
    """Clean common LLM JSON syntax issues like trailing commas before closing brackets."""
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s.strip()


def _extract_from_code_block(text: str) -> Optional[Any]:
    """Attempt extracting JSON from markdown code blocks (```json ... ``` or ``` ... ```)."""
    # 1. Explicit ```json block
    if JSON_CODE_BLOCK_START in text:
        start_idx = text.find(JSON_CODE_BLOCK_START) + len(JSON_CODE_BLOCK_START)
        end_idx = text.find(CODE_BLOCK_DELIMITER, start_idx)
        if end_idx > start_idx:
            content = _clean_json_string(text[start_idx:end_idx])
            try:
                return json.loads(content)
            except Exception:
                pass

    # 2. Generic ``` block
    if CODE_BLOCK_DELIMITER in text:
        start_idx = text.find(CODE_BLOCK_DELIMITER) + len(CODE_BLOCK_DELIMITER)
        # Skip optional language identifier on the first line
        first_newline = text.find("\n", start_idx)
        if first_newline != -1 and first_newline - start_idx < 15:
            start_idx = first_newline + 1
        end_idx = text.find(CODE_BLOCK_DELIMITER, start_idx)
        if end_idx > start_idx:
            content = _clean_json_string(text[start_idx:end_idx])
            try:
                return json.loads(content)
            except Exception:
                pass

    return None


def _extract_from_brackets(text: str) -> Optional[Any]:
    """Attempt extracting JSON object { ... } or array [ ... ]."""
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = _clean_json_string(text[first_brace:last_brace + 1])
        try:
            return json.loads(candidate)
        except Exception:
            pass

    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = _clean_json_string(text[first_bracket:last_bracket + 1])
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


def extract_json_from_text(text: str) -> Optional[Any]:
    """
    Extract JSON from text that may contain markdown or conversational formatting.
    
    Args:
        text: Input text that may contain JSON
    
    Returns:
        Parsed JSON dict/list or None if extraction fails
    """
    if not text or not text.strip():
        return None

    # Try direct parse first
    try:
        return json.loads(_clean_json_string(text))
    except Exception:
        pass

    # Try markdown code blocks
    block_parsed = _extract_from_code_block(text)
    if block_parsed is not None:
        return block_parsed

    # Try finding outermost bracket structures
    return _extract_from_brackets(text)


def _extract_title_from_json(text: str) -> Optional[str]:
    """Extract title field from JSON if the model responded with JSON."""
    if "{" in text and "}" in text:
        try:
            parsed = extract_json_from_text(text)
            if isinstance(parsed, dict) and "title" in parsed:
                return str(parsed["title"]).strip()
        except Exception:
            pass
    return None


def _extract_candidate_from_line(line: str) -> Optional[str]:
    """Examine a single line to extract a title candidate, if valid."""
    cleaned_line = line.lstrip(QUOTE_AND_MARKDOWN_CHARS)
    lower_line = cleaned_line.lower()

    # Check for explicit label prefix like "Title: XYZ"
    for prefix in TITLE_PREFIXES:
        if lower_line.startswith(prefix):
            remainder = cleaned_line[len(prefix):].strip()
            if remainder:
                return remainder

    # Check for conversational preamble like "Here is a title: XYZ"
    if lower_line.startswith(PREAMBLE_PREFIXES):
        if ":" in cleaned_line:
            _, after_colon = cleaned_line.split(":", 1)
            after_colon = after_colon.strip()
            if after_colon and len(after_colon.split()) <= 10:
                return after_colon
        return None

    return cleaned_line


def _find_title_line(text: str) -> str:
    """Find the best candidate title line from raw multi-line LLM output."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return DEFAULT_CHAT_TITLE

    for line in lines:
        candidate = _extract_candidate_from_line(line)
        if candidate:
            return candidate

    return lines[0]


def _sanitize_title(candidate: str) -> str:
    """Strip quotes, markdown, numbering, and enforce length limits."""
    s = candidate.strip(QUOTE_AND_MARKDOWN_CHARS)

    # Strip list numbering e.g. "1. " or "1) "
    s = re.sub(r"^\d+[\.\)]\s+", "", s)
    s = s.strip(QUOTE_AND_MARKDOWN_CHARS)

    # Re-check for leftover prefix
    lower_s = s.lower()
    for prefix in TITLE_PREFIXES:
        if lower_s.startswith(prefix):
            s = s[len(prefix):].strip(QUOTE_AND_MARKDOWN_CHARS)
            break

    # Normalize whitespace
    words = s.split()
    if not words:
        return DEFAULT_CHAT_TITLE

    if len(words) > 8:
        s = " ".join(words[:6])
    else:
        s = " ".join(words)

    if len(s) > 80:
        s = s[:77].rstrip() + "..."

    return s or DEFAULT_CHAT_TITLE


def clean_title(text: str) -> str:
    """
    Extract and clean a high-quality conversation title from LLM output.
    Removes chat preambles, quotes, markdown formatting, and keeps title concise.
    """
    if not text or not text.strip():
        return DEFAULT_CHAT_TITLE

    cleaned = text.strip()
    json_title = _extract_title_from_json(cleaned)
    raw_candidate = json_title if json_title else cleaned

    line_candidate = _find_title_line(raw_candidate)
    return _sanitize_title(line_candidate)


# ============================================================================
# CUSTOM OUTPUT PARSERS
# ============================================================================

class SafeJsonOutputParser(JsonOutputParser):
    """
    JSON output parser with error handling and fallback extraction.
    Falls back to extracting JSON from text/markdown if direct parsing fails.
    """
    
    def parse(self, text: str) -> Dict[str, Any]:
        """Parse JSON with fallback logic and reduced cognitive complexity."""
        try:
            parsed = super().parse(text)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"data": parsed}
            return {"result": parsed}
        except Exception as e:
            logger.debug(f"Direct JSON parsing failed: {e}. Attempting extraction...")
            extracted = extract_json_from_text(text)
            if extracted is not None:
                if isinstance(extracted, dict):
                    return extracted
                if isinstance(extracted, list):
                    return {"data": extracted}
                return {"result": extracted}
            
            logger.error(f"Failed to parse JSON from: {text[:200]}...")
            return {"error": "Failed to parse JSON", "raw_text": text}


class TitleOutputParser(PydanticOutputParser):
    """Parser specifically for chat title generation with clean title post-processing."""
    
    def __init__(self):
        super().__init__(pydantic_object=ChatTitle)
    
    def parse(self, text: str) -> ChatTitle:
        """Parse title with fallback to robust clean title extraction."""
        try:
            result = super().parse(text)
            result.title = clean_title(result.title)
            return result
        except Exception as e:
            logger.debug(f"Structured title parsing failed: {e}. Using clean extraction.")
            return ChatTitle(title=clean_title(text))


class RAGResponseParser(PydanticOutputParser):
    """Parser for RAG responses with source tracking."""
    
    def __init__(self):
        super().__init__(pydantic_object=RAGResponse)
    
    def parse(self, text: str) -> RAGResponse:
        """Parse RAG response with fallback to answer-only."""
        try:
            return super().parse(text)
        except Exception as e:
            logger.debug(f"Structured RAG parsing failed: {e}. Using answer extraction.")
            return RAGResponse(
                answer=text.strip(),
                sources=[],
                confidence=None,
                relevant_chunks=None
            )


# ============================================================================
# PARSER FACTORY & UTILITIES
# ============================================================================

def get_output_parser(parser_type: str) -> Any:
    """
    Factory function to get the appropriate output parser.
    
    Args:
        parser_type: Type of parser ('str', 'json', 'title', 'rag')
    
    Returns:
        Output parser instance
    """
    parsers = {
        "str": StrOutputParser(),
        "json": SafeJsonOutputParser(),
        "title": TitleOutputParser(),
        "rag": RAGResponseParser(),
    }
    
    parser = parsers.get(parser_type.lower())
    if parser is None:
        logger.warning(f"Unknown parser type: {parser_type}. Defaulting to StrOutputParser.")
        return StrOutputParser()
    
    return parser


def format_rag_sources(sources: List[str], max_length: int = 50) -> List[str]:
    """
    Format RAG source references for display.
    Extracts filename from file paths if applicable so the source is meaningful to users.
    
    Args:
        sources: List of source identifiers or file paths
        max_length: Maximum length for each source string
    
    Returns:
        Formatted source list
    """
    formatted = []
    for source in sources:
        if not source:
            continue
        display_name = Path(source).name if ("/" in source or "\\" in source) else str(source).strip()
        if len(display_name) > max_length:
            display_name = display_name[:max_length - 3] + "..."
        formatted.append(display_name)
    return formatted


logger.info("output_parsers.py loaded with structured output models and parsers")
