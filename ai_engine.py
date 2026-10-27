import logging
import httpx
import asyncio
import os
from typing import List, Dict, AsyncGenerator, Optional, Tuple
from langchain_core.documents import Document
from langchain_community.document_loaders import PyMuPDFLoader

from langchain_ollama import OllamaLLM
from langchain_text_splitters import RecursiveCharacterTextSplitter
from prompts import (
    SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT,
    MINDMAP_PROMPT_TEMPLATE,
    TITLE_GENERATION_PROMPT,
    HISTORY_LENGTH,
)
from vectorstore_manager import get_vectorstore_manager
from memory_manager import add_message_to_history
from chains import (
    create_chat_chain_with_history,
    create_rag_chain_with_history,
    create_multi_pdf_rag_chain_with_history,
)
from config import get_settings
from output_parsers import (
    TitleOutputParser,
    MindmapOutputParser,
    ChatTitle,
    MindmapOutput,
)

logger = logging.getLogger(__name__)

# Get settings instance
settings = get_settings()

# --- RAG and Model Setup ---
# Vectorstore manager for ChromaDB operations (replaces manual embeddings)
vectorstore_mgr = get_vectorstore_manager()

# Text splitter for chunking documents
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " ", ""]
)

# --- Ollama Local Models ---
llama3_llm = OllamaLLM(model="llama3", temperature=0.1)
gemma_llm = OllamaLLM(model="gemma", temperature=0.1)
phi3_llm = OllamaLLM(model="phi3", temperature=0.1)

# Available models mapping
AVAILABLE_MODELS = {
    "llama3": llama3_llm,
    "gemma": gemma_llm,
    "phi3": phi3_llm
}

# Chat models only (phi3 reserved for podcast generation)
CHAT_MODELS = {
    "llama3": llama3_llm,
    "gemma": gemma_llm
}

def get_available_models() -> List[str]:
    """Return list of available chat model names (excludes phi3 which is for podcasts)"""
    return list(CHAT_MODELS.keys())

def get_model_llm(model_name: str):
    """Get LLM instance by model name, defaults to llama3"""
    return CHAT_MODELS.get(model_name, llama3_llm)

def get_podcast_model():
    """Get the dedicated podcast generation model (phi3)"""
    return phi3_llm

# --- Podcast prompt (moved) ---
# The PODCAST_SCRIPT_PROMPT_TEMPLATE used to live here but was moved to `prompts.py`
# (see `prompts.PODCAST_SCRIPT_PROMPT_TEMPLATE`). Keep the code here minimal and import
# the template from prompts.py when enabling podcast generation features.

# --- Mindmap Generation Prompt ---
# Imported from prompts.py (MINDMAP_PROMPT_TEMPLATE)

# --- Estimation functions ---
def estimate_mindmap_generation_time(pdf_path: str) -> int:
    try:
        # Use PyMuPDFLoader to get document content
        loader = PyMuPDFLoader(pdf_path)
        documents = loader.load()
        
        if not documents:
            logger.warning(f"No content in PDF for time estimation: {pdf_path}")
            return 45
        
        # Combine all page content
        pdf_text = "\n".join([doc.page_content for doc in documents])
        char_count = len(pdf_text)
        base_time_seconds = 15
        chars_per_second_of_processing = 1000
        estimated_time = base_time_seconds + (char_count / chars_per_second_of_processing)
        max_time_seconds = 300
        final_time = min(int(estimated_time), max_time_seconds)
        logger.info(f"Estimated mindmap generation time for PDF with {char_count} chars: {final_time}s")
        return final_time
    except Exception as e:
        logger.error(f"Could not estimate mindmap time for {pdf_path}: {e}")
        return 45

def estimate_podcast_generation_time(mindmap_md: str) -> int:
    if not mindmap_md:
        return 45
    char_count = len(mindmap_md)
    line_count = mindmap_md.count('\n') + 1
    base_time_seconds = 30
    time_per_char = 1/12
    time_per_line = 0.5
    estimated_time = base_time_seconds + (char_count * time_per_char) + (line_count * time_per_line)
    max_time_seconds = 480
    final_time = min(int(estimated_time), max_time_seconds)
    logger.info(
        f"Estimated podcast generation time for mindmap with {char_count} chars and "
        f"{line_count} lines: {final_time}s"
    )
    return final_time

# --- RAG Helper Functions ---
def _get_collection_name(pdf_path: str) -> str:
    """Generate a unique ChromaDB collection name for a PDF.

    Uploaded files live in ``uploads/<user>/<chat_session>/<source_id>/<file>.pdf`` so the
    parent directory (source_id) is unique per upload. Using the bare filename caused two
    different users/sessions uploading ``report.pdf`` to share (and mix) one collection.
    """
    source_dir = os.path.basename(os.path.dirname(os.path.abspath(pdf_path)))
    base = source_dir or os.path.splitext(os.path.basename(pdf_path))[0]
    # Sanitize: replace non-alphanumeric with underscore
    sanitized = ''.join(c if c.isalnum() else '_' for c in base)
    # ChromaDB collection names must be 3-63 chars, start/end with alphanumeric
    collection_name = f"src_{sanitized}"[:63].strip('_')
    return collection_name

def _load_and_store_pdf(pdf_path: str) -> str:
    """
    Load PDF using PyMuPDFLoader, chunk it, and store in ChromaDB.
    Returns collection name.
    """
    collection_name = _get_collection_name(pdf_path)
    
    # Check if already processed
    if vectorstore_mgr.collection_exists(collection_name):
        doc_count = vectorstore_mgr.get_collection_count(collection_name)
        if doc_count > 0:
            logger.info(f"PDF already in ChromaDB: {collection_name} ({doc_count} chunks)")
            return collection_name
    
    # Load PDF with PyMuPDFLoader
    loader = PyMuPDFLoader(pdf_path)
    documents = loader.load()
    
    if not documents:
        logger.error(f"PyMuPDFLoader returned no documents for: {pdf_path}")
        raise ValueError(f"No content extracted from PDF: {pdf_path}")
    
    # Split documents into chunks
    chunks = text_splitter.split_documents(documents)
    
    if not chunks:
        logger.error(f"No chunks created from PDF: {pdf_path}")
        raise ValueError(f"No text chunks extracted from PDF: {pdf_path}")
    
    # Store in ChromaDB
    vectorstore_mgr.add_documents(chunks, collection_name)
    logger.info(f"Stored {len(chunks)} chunks in ChromaDB collection: {collection_name}")
    
    return collection_name

def _retrieve_context(query: str, collection_name: str, k: int = 3) -> str:
    """
    Retrieve relevant context from ChromaDB for a query.
    Returns formatted context string.
    """
    results = vectorstore_mgr.similarity_search_with_score(
        query=query,
        collection_name=collection_name,
        k=k
    )
    
    if not results:
        return "No relevant context found."
    
    # Format context with scores
    context_parts = []
    for doc, score in results:
        context_parts.append(doc.page_content)
    
    return "\n\n--\n\n".join(context_parts)

# --- Chat Functions (LCEL-based) ---
async def chat_completion_LlamaModel_ws(
    text: str,
    history: List[Dict[str, str]],
    session_id: Optional[str] = None
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """Chat completion using LCEL chain with optional memory."""
    logger.info(f"Initiating Standard Llama3 WS completion (LCEL) for text: '{text[:50]}...'")
    try:
        # Create chain with or without history based on session_id
        if session_id:
            chain = create_chat_chain_with_history(model_name="llama3", session_id=session_id)
            chain_input = {"input": text, "session_id": session_id}
        else:
            # For backward compatibility, use chain without session
            from chains import create_chat_chain
            chain = create_chat_chain(model_name="llama3")
            chain_input = {"input": text, "chat_history": history[-(HISTORY_LENGTH * 2):]}
        
        # Stream response using LCEL
        full_response = ""
        try:
            async for chunk in chain.astream(chain_input):
                if chunk:
                    full_response += chunk
                    # Yield incremental chunks (for real-time streaming)
                    # WebSocket handler expects (answer, error) tuple
            
            # Yield complete response
            yield full_response, None
            
        except Exception as e:
            if isinstance(e, (httpx.ConnectError, ConnectionRefusedError, OSError)):
                logger.error(f"LLM service connection error for Chat: {e}")
                yield None, (
                    "LLM service unreachable. Ensure the local LLM service (e.g. Ollama) is running "
                    "and listening (default: localhost:11434)."
                )
                return
            logger.error(f"Chat generation failed: {e}", exc_info=True)
            yield None, f"Error during chat completion: {e}"
            return
            
    except Exception as e:
        logger.error(f"Llama3 Chat: {e}", exc_info=True)
        yield None, f"Error during Llama3 chat completion: {e}"

async def chat_completion_Gemma_ws(
    text: str,
    history: List[Dict[str, str]],
    session_id: Optional[str] = None
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """Chat completion using LCEL chain with Gemma model."""
    logger.info(f"Initiating Gemma WS completion (LCEL) for text: '{text[:50]}...'")
    try:
        if session_id:
            chain = create_chat_chain_with_history(model_name="gemma", session_id=session_id)
            chain_input = {"input": text, "session_id": session_id}
        else:
            from chains import create_chat_chain
            chain = create_chat_chain(model_name="gemma")
            chain_input = {"input": text, "chat_history": history[-(HISTORY_LENGTH * 2):]}
        
        full_response = ""
        async for chunk in chain.astream(chain_input):
            if chunk:
                full_response += chunk
        
        yield full_response, None
    except Exception as e:
        logger.error(f"Gemma Chat: {e}", exc_info=True)
        yield None, f"Error during Gemma chat completion: {e}"

# --- Phi3 Completion (RESERVED FOR PODCAST GENERATION ONLY) ---
async def chat_completion_phi3_ws(text: str, history: List[Dict[str, str]]) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    logger.info(f"Initiating Phi3 WS completion for text: '{text[:50]}...'")
    try:
        messages_to_send = history[-(HISTORY_LENGTH * 2):]
        if messages_to_send and messages_to_send[0]['role'] == 'assistant':
            messages_to_send.pop(0)
        prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages_to_send]) + f"\nuser: {text}"
        response = await asyncio.to_thread(phi3_llm.generate, [prompt])
        answer = response.generations[0][0].text.strip()
        yield answer, None
    except Exception as e:
        logger.error(f"Phi3 Chat: {e}", exc_info=True)
        yield None, f"Error during Phi3 chat completion: {e}"

async def chat_completion_with_pdf_ws(
    text: str,
    history: List[Dict[str, str]],
    pdf_path: str,
    model: str = "llama3",
    session_id: Optional[str] = None
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """RAG completion using LCEL chain with single PDF."""
    logger.info(f"Initiating Main Chat RAG (LCEL) for text: {text[:50]} using PDF: {pdf_path} with model: {model}")
    try:
        # Check PDF exists
        if not os.path.exists(pdf_path):
            logger.error(f"PDF not found at path for Main Chat RAG: {pdf_path}")
            yield None, f"The associated document could not be found."
            return
        
        # Load and store PDF in ChromaDB (idempotent)
        try:
            collection_name = await asyncio.to_thread(_load_and_store_pdf, pdf_path)
        except Exception as e:
            logger.error(f"Failed to process PDF for ChromaDB: {e}")
            yield None, "The associated document could not be processed for context (empty content)."
            return
        
        # Create RAG chain with or without history
        try:
            if session_id:
                chain = create_rag_chain_with_history(
                    collection_name=collection_name,
                    session_id=session_id,
                    model_name=model,
                    k=3
                )
                chain_input = {"input": text}
            else:
                # Backward compatibility - no session
                from chains import create_rag_chain
                chain = create_rag_chain(
                    collection_name=collection_name,
                    model_name=model,
                    k=3,
                    history=history[-(HISTORY_LENGTH * 2):]
                )
                chain_input = text
            
            # Stream response
            full_response = ""
            async for chunk in chain.astream(chain_input):
                if chunk:
                    full_response += chunk
            
            yield full_response, None
            
        except Exception as e:
            if isinstance(e, (httpx.ConnectError, ConnectionRefusedError, OSError)):
                logger.error(f"LLM service connection error for RAG: {e}")
                yield None, (
                    "LLM service unreachable. Ensure the local LLM service (e.g. Ollama) is running "
                    "and listening (default: localhost:11434)."
                )
                return
            logger.error(f"RAG generation failed: {e}", exc_info=True)
            yield None, f"Error during RAG completion: {e}"
            return
            
    except Exception as e:
        logger.error(f"Main Chat RAG: {e}", exc_info=True)
        yield None, f"Error during Main Chat RAG completion: {e}"

async def chat_completion_with_multiple_pdfs_ws(
    text: str,
    history: List[Dict[str, str]],
    pdf_paths: List[str],
    session_id: Optional[str] = None,
    model: str = "llama3"
) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
    """Multi-PDF RAG completion using LCEL chain."""
    logger.info(f"Initiating Multi-PDF RAG (LCEL) for text: {text[:50]}... on {len(pdf_paths)} documents.")
    try:
        # Load and store all PDFs, collect collection names
        collection_names = []
        for pdf_path in pdf_paths:
            if not pdf_path or not os.path.exists(pdf_path):
                logger.warning(f"skipping non-existent PDF for multi-RAG: {pdf_path}")
                continue
            
            try:
                collection_name = await asyncio.to_thread(_load_and_store_pdf, pdf_path)
                collection_names.append(collection_name)
            except Exception as e:
                logger.error(f"Failed to process PDF {pdf_path}: {e}", exc_info=True)
                continue
        
        if not collection_names:
            yield None, "No valid documents could be processed for context."
            return
        
        # Create multi-PDF RAG chain
        try:
            if session_id:
                chain = create_multi_pdf_rag_chain_with_history(
                    collection_names=collection_names,
                    session_id=session_id,
                    model_name=model,
                    k=2
                )
                chain_input = {"input": text}
            else:
                from chains import create_multi_pdf_rag_chain
                chain = create_multi_pdf_rag_chain(
                    collection_names=collection_names,
                    model_name=model,
                    k=2,
                    history=history[-(HISTORY_LENGTH * 2):]
                )
                chain_input = text
            
            # Stream response
            full_response = ""
            async for chunk in chain.astream(chain_input):
                if chunk:
                    full_response += chunk
            
            yield full_response, None
            
        except Exception as e:
            logger.error(f"Multi-PDF RAG generation failed: {e}", exc_info=True)
            yield None, f"Error during Multi-PDF RAG completion: {e}"
            return
            
    except Exception as e:
        logger.error(f"Multi-PDF RAG: {e}", exc_info=True)
        yield None, f"Error during Multi-PDF RAG completion: {e}"

# --- Mindmap Generation using phi3 ---
async def generate_mindmap_from_pdf(pdf_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Generate a Mermaid mindmap from PDF using phi3 model with MindmapOutputParser for validation.
    Returns: (mindmap_markdown, error_message)
    """
    logger.info(f"Generating mindmap from PDF: {pdf_path}")
    try:
        # Load PDF using PyMuPDFLoader
        loader = PyMuPDFLoader(pdf_path)
        documents = await asyncio.to_thread(loader.load)
        
        if not documents:
            error_msg = "No content extracted from PDF"
            logger.error(error_msg)
            return None, error_msg
        
        # Combine all pages into single text
        pdf_text = "\n".join([doc.page_content for doc in documents])
        
        if not pdf_text or len(pdf_text.strip()) < 50:
            error_msg = "PDF text is too short or empty to generate mindmap"
            logger.error(error_msg)
            return None, error_msg
        
        # Truncate text if too long (keep first 4000 chars for better performance)
        if len(pdf_text) > 4000:
            pdf_text = pdf_text[:4000] + "..."
            logger.info(f"Truncated PDF text to 4000 characters for mindmap generation")
        
        # Generate mindmap using phi3
        prompt = MINDMAP_PROMPT_TEMPLATE.format(pdf_text=pdf_text)
        logger.info("Sending prompt to phi3 for mindmap generation...")
        
        response = await asyncio.to_thread(phi3_llm.generate, [prompt])
        raw_mindmap = response.generations[0][0].text.strip()
        
        # Use MindmapOutputParser for validation and correction
        mindmap_parser = MindmapOutputParser()
        
        try:
            parsed_mindmap: MindmapOutput = mindmap_parser.parse(raw_mindmap)
            logger.info(f"Mindmap validated successfully: {parsed_mindmap.node_count} nodes")
            return parsed_mindmap.markdown, None
        except Exception as parse_error:
            # Fallback to legacy validation if structured parsing fails
            logger.warning(f"Failed to parse mindmap with MindmapOutputParser: {parse_error}. Using fallback validation.")
            mindmap_markdown = raw_mindmap
            
            # Legacy validation: Validate that we got Mermaid syntax
            if not mindmap_markdown.startswith("mindmap"):
                logger.warning("Generated mindmap doesn't start with 'mindmap', attempting to fix...")
                if "mindmap" in mindmap_markdown.lower():
                    # Try to extract the mindmap part
                    lines = mindmap_markdown.split('\n')
                    mindmap_start = next((i for i, line in enumerate(lines) if line.strip().lower() == "mindmap"), None)
                    if mindmap_start is not None:
                        mindmap_markdown = '\n'.join(lines[mindmap_start:])
                    else:
                        mindmap_markdown = "mindmap\n" + mindmap_markdown
                else:
                    mindmap_markdown = "mindmap\n" + mindmap_markdown
            
            logger.info(f"Mindmap generated successfully with fallback ({len(mindmap_markdown)} chars)")
            return mindmap_markdown, None
        
    except Exception as e:
        error_msg = f"Error generating mindmap: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg

""" Disabled podcast generation functions as per user request
# --- Mindmap Generation using phi3 ---
# async def generate_mindmap_from_pdf(pdf_path: str) -> Tuple[Optional[str], Optional[str]]:
#     ...
# --- Podcast Generation using phi3 + local TTS ---
# import base64
# import tempfile
# from services.local_audio import generate_tts_audio
# async def generate_podcast_from_mindmap(mindmap_md: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
#     ...
"""

# --- Title Generation using llama3 ---
async def generate_chat_title(messages_for_title_generation: List[Dict[str, str]]) -> Optional[str]:
    """
    Generate a title for the chat conversation using TitleOutputParser for structured output.
    Returns: Title string or None if generation fails
    """
    if not messages_for_title_generation:
        return None
    logger.info(f"Generating chat title for a conversation with {len(messages_for_title_generation)} messages.")
    conversation_summary = "\n".join(f"{msg['role']}: {msg['content']}" for msg in messages_for_title_generation)
    prompt = TITLE_GENERATION_PROMPT.format(conversation_text=conversation_summary)
    
    # Use TitleOutputParser for structured output
    title_parser = TitleOutputParser()
    
    try:
        response = await asyncio.to_thread(llama3_llm.generate, [prompt])
        raw_output = response.generations[0][0].text.strip()
        
        # Parse with TitleOutputParser
        try:
            parsed_title: ChatTitle = title_parser.parse(raw_output)
            logger.info(f"Successfully generated and parsed chat title: '{parsed_title.title}'")
            return parsed_title.title
        except Exception as parse_error:
            # Fallback to simple parsing if structured parsing fails
            logger.warning(f"Failed to parse title with TitleOutputParser: {parse_error}. Using fallback.")
            title = raw_output.strip('\'"')
            if title:
                logger.info(f"Successfully generated chat title (fallback): '{title}'")
                return title
            else:
                logger.warning("Title generation resulted in an empty string.")
                return None
    except Exception as e:
        logger.error(f"Failed to generate chat title: {e}", exc_info=True)
        return None

# Prompt constants are imported from prompts.py at the top of this file

logger.info("ai_engine.py loaded with local Ollama models: llama3, gemma, phi3.")