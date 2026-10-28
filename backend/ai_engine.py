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
from services.utils import resolve_pdf_path
from output_parsers import (
    TitleOutputParser,
    ChatTitle,
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

# Chat models
CHAT_MODELS = {
    "llama3": llama3_llm,
    "gemma": gemma_llm
}

AVAILABLE_MODELS = CHAT_MODELS

def get_available_models() -> List[str]:
    """Return list of available chat model names"""
    return list(CHAT_MODELS.keys())

def get_model_llm(model_name: str):
    """Get LLM instance by model name, defaults to llama3"""
    return CHAT_MODELS.get(model_name, llama3_llm)

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
async def chat_completion_llama_model_ws(
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
            
            # Yield complete response
            yield full_response, None
            
        except Exception as e:
            if isinstance(e, (httpx.ConnectError, ConnectionRefusedError, OSError)):
                logger.exception(f"LLM service connection error for Chat: {e}")
                yield None, (
                    "LLM service unreachable. Ensure the local LLM service (e.g. Ollama) is running "
                    "and listening (default: localhost:11434)."
                )
                return
            logger.exception(f"Chat generation failed: {e}")
            yield None, f"Error during chat completion: {e}"
            return
            
    except Exception as e:
        logger.exception(f"Llama3 Chat: {e}")
        yield None, f"Error during Llama3 chat completion: {e}"


# Backward compatibility alias
chat_completion_LlamaModel_ws = chat_completion_llama_model_ws


async def chat_completion_gemma_ws(
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
        logger.exception(f"Gemma Chat: {e}")
        yield None, f"Error during Gemma chat completion: {e}"


# Backward compatibility alias
chat_completion_Gemma_ws = chat_completion_gemma_ws

async def _ensure_pdf_indexed(pdf_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Ensure a PDF is in ChromaDB. Returns (collection_name, error_message)."""
    if not pdf_path:
        return None, "Document path not provided."

    collection_name = _get_collection_name(pdf_path)
    if vectorstore_mgr.collection_exists(collection_name) and vectorstore_mgr.get_collection_count(collection_name) > 0:
        return collection_name, None

    resolved_path = resolve_pdf_path(pdf_path)
    if not resolved_path or not os.path.exists(resolved_path):
        logger.error(f"PDF not found at path: {pdf_path}")
        return None, "The associated document could not be found."

    try:
        col_name = await asyncio.to_thread(_load_and_store_pdf, resolved_path)
        return col_name, None
    except Exception as e:
        logger.exception(f"Failed to process PDF for ChromaDB: {e}")
        return None, "The associated document could not be processed for context (empty content)."


async def _collect_pdf_collections(pdf_paths: List[str]) -> List[str]:
    """Collect ChromaDB collection names for all valid pdf_paths."""
    collections = []
    for path in pdf_paths:
        col_name, _ = await _ensure_pdf_indexed(path)
        if col_name:
            collections.append(col_name)
    return collections


def _build_single_pdf_rag_chain(
    collection_name: str,
    text: str,
    model: str,
    history: List[Dict[str, str]],
    session_id: Optional[str]
):
    """Build single PDF RAG chain and its input."""
    if session_id:
        chain = create_rag_chain_with_history(
            collection_name=collection_name,
            session_id=session_id,
            model_name=model,
            k=3
        )
        return chain, {"input": text}

    from chains import create_rag_chain
    chain = create_rag_chain(
        collection_name=collection_name,
        model_name=model,
        k=3,
        history=history[-(HISTORY_LENGTH * 2):]
    )
    return chain, text


def _build_multi_pdf_rag_chain(
    collection_names: List[str],
    text: str,
    model: str,
    history: List[Dict[str, str]],
    session_id: Optional[str]
):
    """Build multi-PDF RAG chain and its input."""
    if session_id:
        chain = create_multi_pdf_rag_chain_with_history(
            collection_names=collection_names,
            session_id=session_id,
            model_name=model,
            k=2
        )
        return chain, {"input": text}

    from chains import create_multi_pdf_rag_chain
    chain = create_multi_pdf_rag_chain(
        collection_names=collection_names,
        model_name=model,
        k=2,
        history=history[-(HISTORY_LENGTH * 2):]
    )
    return chain, text


async def _stream_chain_response(chain, chain_input) -> Tuple[Optional[str], Optional[str]]:
    """Execute LCEL chain streaming and handle connection errors."""
    try:
        full_response = ""
        async for chunk in chain.astream(chain_input):
            if chunk:
                full_response += chunk
        return full_response, None
    except Exception as e:
        if isinstance(e, (httpx.ConnectError, ConnectionRefusedError, OSError)):
            logger.exception(f"LLM service connection error: {e}")
            return None, (
                "LLM service unreachable. Ensure the local LLM service (e.g. Ollama) is running "
                "and listening (default: localhost:11434)."
            )
        logger.exception(f"RAG generation failed: {e}")
        return None, f"Error during RAG completion: {e}"


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
        collection_name, error = await _ensure_pdf_indexed(pdf_path)
        if error:
            yield None, error
            return

        chain, chain_input = _build_single_pdf_rag_chain(collection_name, text, model, history, session_id)
        response, stream_error = await _stream_chain_response(chain, chain_input)
        yield response, stream_error

    except Exception as e:
        logger.exception(f"Main Chat RAG: {e}")
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
        collection_names = await _collect_pdf_collections(pdf_paths)
        if not collection_names:
            yield None, "No valid documents could be processed for context."
            return

        chain, chain_input = _build_multi_pdf_rag_chain(collection_names, text, model, history, session_id)
        response, stream_error = await _stream_chain_response(chain, chain_input)
        yield response, stream_error

    except Exception as e:
        logger.exception(f"Multi-PDF RAG: {e}")
        yield None, f"Error during Multi-PDF RAG completion: {e}"

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
        logger.exception(f"Failed to generate chat title: {e}")
        return None

logger.info("ai_engine.py loaded with local Ollama models: llama3, gemma.")
