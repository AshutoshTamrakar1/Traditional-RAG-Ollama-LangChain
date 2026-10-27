"""
Output parsers and structured output models for LangChain.

This module provides:
- Pydantic models for structured outputs
- Output parsers for different response types
- Validation and formatting utilities
"""

import logging
import re
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from langchain_core.output_parsers import StrOutputParser, JsonOutputParser, PydanticOutputParser
from langchain_core.exceptions import OutputParserException

logger = logging.getLogger(__name__)


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


class MindmapNode(BaseModel):
    """Model for a single mindmap node."""
    id: str = Field(description="Unique identifier for the node")
    label: str = Field(description="Display label for the node")
    level: int = Field(description="Hierarchy level (0=root, 1=main branch, etc.)")
    parent_id: Optional[str] = Field(default=None, description="ID of parent node")


class MindmapOutput(BaseModel):
    """Model for mindmap generation output."""
    markdown: str = Field(description="Mermaid mindmap markdown syntax")
    nodes: Optional[List[MindmapNode]] = Field(
        default=None,
        description="Structured node representation"
    )
    root_topic: Optional[str] = Field(
        default=None,
        description="Main topic/root of the mindmap"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata (source, timestamp, etc.)"
    )
    
    @field_validator("markdown")
    @classmethod
    def validate_mindmap_syntax(cls, v):
        """Validate that markdown starts with 'mindmap'."""
        if not v.strip().lower().startswith("mindmap"):
            # Try to fix it
            if "mindmap" in v.lower():
                lines = v.split('\n')
                mindmap_idx = next(
                    (i for i, line in enumerate(lines) if line.strip().lower() == "mindmap"),
                    None
                )
                if mindmap_idx is not None:
                    return '\n'.join(lines[mindmap_idx:])
            # If can't fix, prepend mindmap
            return "mindmap\n" + v
        return v

    @property
    def node_count(self) -> int:
        """Number of nodes (non-empty lines after the leading 'mindmap' keyword)."""
        lines = [l for l in self.markdown.splitlines() if l.strip()]
        return max(len(lines) - 1, 0)

    @property
    def is_valid(self) -> bool:
        """A mindmap is valid if it starts with 'mindmap' and has at least one node."""
        return self.markdown.strip().lower().startswith("mindmap") and self.node_count > 0


def _clean_mindmap_label(label: str) -> str:
    """Remove characters that break Mermaid mindmap node text."""
    return re.sub(r'[(){}\[\]"`]', '', label).strip().strip("'").strip()


def normalize_mindmap(text: str) -> str:
    """Turn raw LLM output into valid, indentation-based Mermaid mindmap syntax.

    Handles markdown code fences, trailing prose, and the brace-style pseudo syntax
    (``branch "Title" { ... }``) that small models often produce.
    """
    t = (text or "").strip()
    fenced = re.search(r"```(?:mermaid)?\s*\n(.*?)```", t, re.S)
    if fenced:
        t = fenced.group(1)
    else:
        t = t.replace("```mermaid", "").replace("```", "")

    lines = [l.rstrip() for l in t.splitlines() if l.strip()]
    # Discard anything before the 'mindmap' keyword line
    start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith("mindmap")), None)
    if start is not None:
        lines = lines[start:]
        rest = lines[0].strip()[len("mindmap"):].strip()
        lines = ([rest] if rest else []) + lines[1:]

    if any("{" in l or l.strip() in ("}", "},") for l in lines):
        items = []
        depth = 0
        for l in lines:
            s = l.strip()
            if s in ("}", "},"):
                depth = max(0, depth - 1)
                continue
            opens = s.endswith("{")
            if opens:
                s = s[:-1].strip()
            quoted = re.findall(r'"([^"]+)"', s)
            label = _clean_mindmap_label(quoted[-1] if quoted else s)
            if label:
                items.append((depth, label))
            if opens:
                depth += 1
        if not items:
            return "mindmap\n  root((Document))"
        if sum(1 for d, _ in items if d == 0) > 1:
            items = [(d + 1, lab) for d, lab in items]
            items.insert(0, (0, "Document"))
        out = ["mindmap"]
        for i, (d, lab) in enumerate(items):
            out.append("  " * (d + 1) + (f"root(({lab}))" if i == 0 else lab))
        return "\n".join(out)

    body = [l for l in lines]
    if not body:
        return "mindmap\n  root((Document))"
    return "mindmap\n" + "\n".join(body)


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
    sources: List[str] = Field(description="Source documents used")
    confidence: Optional[float] = Field(default=None, description="Confidence in answer (0-1)")
    relevant_chunks: Optional[int] = Field(default=None, description="Number of relevant chunks retrieved")
    metadata: Optional[ChatMetadata] = Field(default=None, description="Response metadata")


# ============================================================================
# CUSTOM OUTPUT PARSERS
# ============================================================================

class SafeJsonOutputParser(JsonOutputParser):
    """
    JSON output parser with error handling.
    Falls back to extracting JSON from text if direct parsing fails.
    """
    
    def parse(self, text: str) -> Dict[str, Any]:
        """Parse JSON with fallback logic."""
        try:
            # Try direct JSON parsing
            return super().parse(text)
        except Exception as e:
            logger.warning(f"Direct JSON parsing failed: {e}. Attempting extraction...")
            
            # Try to extract JSON from markdown code blocks
            if "```json" in text:
                json_start = text.find("```json") + 7
                json_end = text.find("```", json_start)
                if json_end > json_start:
                    json_text = text[json_start:json_end].strip()
                    try:
                        return json.loads(json_text)
                    except Exception:
                        pass
            
            # Try to find any JSON-like structure
            if "{" in text and "}" in text:
                json_start = text.find("{")
                json_end = text.rfind("}") + 1
                json_text = text[json_start:json_end]
                try:
                    return json.loads(json_text)
                except Exception:
                    pass
            
            # If all else fails, return error dict
            logger.error(f"Failed to parse JSON from: {text[:200]}...")
            return {"error": "Failed to parse JSON", "raw_text": text}


class TitleOutputParser(PydanticOutputParser):
    """Parser specifically for chat title generation."""
    
    def __init__(self):
        super().__init__(pydantic_object=ChatTitle)
    
    def parse(self, text: str) -> ChatTitle:
        """Parse title with fallback to simple string."""
        try:
            return super().parse(text)
        except Exception as e:
            logger.warning(f"Structured title parsing failed: {e}. Using simple extraction.")
            
            # Extract title from various formats
            title = text.strip()
            
            # Remove quotes if present
            if title.startswith('"') and title.endswith('"'):
                title = title[1:-1]
            if title.startswith("'") and title.endswith("'"):
                title = title[1:-1]
            
            # Remove "Title:" prefix if present
            if title.lower().startswith("title:"):
                title = title[6:].strip()
            
            # Limit length
            if len(title) > 100:
                title = title[:97] + "..."
            
            return ChatTitle(title=title)


class MindmapOutputParser(PydanticOutputParser):
    """Parser specifically for mindmap generation."""
    
    def __init__(self):
        super().__init__(pydantic_object=MindmapOutput)
    
    def parse(self, text: str) -> MindmapOutput:
        """Parse mindmap output. JSON is only attempted when the text looks like JSON;
        otherwise the text is normalized into valid Mermaid mindmap syntax."""
        if text.lstrip().startswith("{") and '"markdown"' in text:
            try:
                return super().parse(text)
            except Exception as e:
                logger.warning(f"Structured mindmap parsing failed: {e}. Using markdown normalization.")
        return MindmapOutput(markdown=normalize_mindmap(text))


class RAGResponseParser(PydanticOutputParser):
    """Parser for RAG responses with source tracking."""
    
    def __init__(self):
        super().__init__(pydantic_object=RAGResponse)
    
    def parse(self, text: str) -> RAGResponse:
        """Parse RAG response with fallback to answer-only."""
        try:
            return super().parse(text)
        except Exception as e:
            logger.warning(f"Structured RAG parsing failed: {e}. Using answer extraction.")
            
            # Simple fallback: treat entire text as answer
            return RAGResponse(
                answer=text.strip(),
                sources=["unknown"],
                confidence=None,
                relevant_chunks=None
            )


# ============================================================================
# PARSER FACTORY
# ============================================================================

def get_output_parser(parser_type: str) -> Any:
    """
    Factory function to get the appropriate output parser.
    
    Args:
        parser_type: Type of parser ('str', 'json', 'title', 'mindmap', 'rag')
    
    Returns:
        Output parser instance
    """
    parsers = {
        "str": StrOutputParser(),
        "json": SafeJsonOutputParser(),
        "title": TitleOutputParser(),
        "mindmap": MindmapOutputParser(),
        "rag": RAGResponseParser(),
    }
    
    parser = parsers.get(parser_type.lower())
    if parser is None:
        logger.warning(f"Unknown parser type: {parser_type}. Defaulting to StrOutputParser.")
        return StrOutputParser()
    
    return parser


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from text that may contain markdown or other formatting.
    
    Args:
        text: Input text that may contain JSON
    
    Returns:
        Parsed JSON dict or None if extraction fails
    """
    # Try markdown code block
    if "```json" in text:
        json_start = text.find("```json") + 7
        json_end = text.find("```", json_start)
        if json_end > json_start:
            json_text = text[json_start:json_end].strip()
            try:
                return json.loads(json_text)
            except Exception:
                pass
    
    # Try finding JSON structure
    if "{" in text and "}" in text:
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        json_text = text[json_start:json_end]
        try:
            return json.loads(json_text)
        except Exception:
            pass
    
    return None


def validate_mindmap_markdown(markdown: str) -> tuple[bool, Optional[str]]:
    """
    Validate mindmap markdown syntax.
    
    Args:
        markdown: Mermaid mindmap markdown
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not markdown or not markdown.strip():
        return False, "Empty mindmap"
    
    if not markdown.strip().lower().startswith("mindmap"):
        return False, "Mindmap must start with 'mindmap' keyword"
    
    # Check for at least one root node
    lines = [line.strip() for line in markdown.split('\n') if line.strip()]
    if len(lines) < 2:
        return False, "Mindmap must have at least one node besides 'mindmap' keyword"
    
    return True, None


def format_rag_sources(sources: List[str], max_length: int = 50) -> List[str]:
    """
    Format RAG source references for display.
    
    Args:
        sources: List of source identifiers
        max_length: Maximum length for each source string
    
    Returns:
        Formatted source list
    """
    formatted = []
    for source in sources:
        if len(source) > max_length:
            formatted.append(source[:max_length-3] + "...")
        else:
            formatted.append(source)
    return formatted


logger.info("output_parsers.py loaded with structured output models and parsers")
