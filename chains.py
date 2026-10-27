"""
Chains module for LangChain Expression Language (LCEL) implementations.

This module provides LCEL-based chains for chat and RAG operations,
replacing the old async generator approach with composable chains.

Phase 4 additions: Callback integration for observability and monitoring.
"""

import logging
from typing import Dict, List, Optional, Any
from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel, RunnableLambda
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_ollama import OllamaLLM

from prompts import (
    CHAT_PROMPT_TEMPLATE,
    RAG_PROMPT_TEMPLATE,
    MULTI_PDF_RAG_PROMPT_TEMPLATE,
    HISTORY_LENGTH
)
from vectorstore_manager import get_vectorstore_manager
from memory_manager import get_windowed_messages
from callbacks import create_callback_manager, LoggingCallbackHandler, PerformanceCallbackHandler
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ============================================================================
# LLM INSTANCES
# ============================================================================

# Initialize Ollama models (same as ai_engine.py)
llama3_llm = OllamaLLM(model="llama3", temperature=0.1)
gemma_llm = OllamaLLM(model="gemma", temperature=0.1)
phi3_llm = OllamaLLM(model="phi3", temperature=0.1)

# Model mapping
AVAILABLE_MODELS = {
    "llama3": llama3_llm,
    "gemma": gemma_llm,
    "phi3": phi3_llm
}

CHAT_MODELS = {
    "llama3": llama3_llm,
    "gemma": gemma_llm
}


def get_llm(model_name: str = "llama3") -> OllamaLLM:
    """Get LLM instance by name."""
    return CHAT_MODELS.get(model_name, llama3_llm)


# ============================================================================
# HELPER FUNCTIONS FOR CHAINS
# ============================================================================

def format_chat_history(messages: List) -> List:
    """
    Convert message list to LangChain message format.
    
    Args:
        messages: List of messages (ChatMessage objects or dicts)
        
    Returns:
        List of HumanMessage/AIMessage objects
    """
    formatted = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'user':
                formatted.append(HumanMessage(content=content))
            elif role == 'assistant':
                formatted.append(AIMessage(content=content))
        else:
            # Already a ChatMessage object
            formatted.append(msg)
    return formatted


def format_docs(docs: List) -> str:
    """
    Format retrieved documents into context string.
    
    Args:
        docs: List of Document objects
        
    Returns:
        Formatted context string
    """
    return "\n\n--\n\n".join([doc.page_content for doc in docs])


def get_session_history(session_id: str, k: int = HISTORY_LENGTH) -> List:
    """
    Retrieve windowed chat history for a session.
    
    Args:
        session_id: Chat session ID
        k: Number of message pairs to retrieve
        
    Returns:
        List of ChatMessage objects
    """
    messages = get_windowed_messages(session_id, k=k)
    return messages


# ============================================================================
# BASIC CHAT CHAIN (No RAG)
# ============================================================================

def create_chat_chain(
    model_name: str = "llama3",
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False
):
    """
    Create a basic chat chain using LCEL.
    
    Chain structure: prompt | llm | output_parser
    
    Args:
        model_name: Name of the model to use (llama3, gemma)
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Runnable chain
    """
    llm = get_llm(model_name)
    output_parser = StrOutputParser()
    
    # Create default callbacks if observability enabled
    if enable_observability and callbacks is None:
        callbacks = create_callback_manager(
            enable_logging=True,
            enable_performance=True,
            enable_debug=False
        )
    
    # LCEL chain: prompt template | llm | output parser
    chain = CHAT_PROMPT_TEMPLATE | llm | output_parser
    
    # Attach callbacks if provided
    if callbacks:
        chain = chain.with_config(callbacks=callbacks)
    
    logger.info(f"Created chat chain with model: {model_name}, callbacks: {len(callbacks) if callbacks else 0}")
    return chain


def create_chat_chain_with_history(
    model_name: str = "llama3",
    session_id: Optional[str] = None,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False
):
    """
    Create a chat chain with conversation history.
    
    Args:
        model_name: Name of the model to use
        session_id: Session ID for history retrieval
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Runnable chain with history integration
    """
    llm = get_llm(model_name)
    output_parser = StrOutputParser()
    
    # Create default callbacks if observability enabled
    if enable_observability and callbacks is None:
        callbacks = create_callback_manager(
            enable_logging=True,
            enable_performance=True,
            enable_debug=False
        )
    
    # Create chain with history loading
    def load_history(inputs: Dict) -> Dict:
        """Load chat history for the session."""
        sid = inputs.get('session_id', session_id)
        if sid:
            history = get_session_history(sid)
            inputs['chat_history'] = history
        else:
            inputs['chat_history'] = []
        return inputs
    
    # LCEL chain with history
    chain = (
        RunnableLambda(load_history)
        | CHAT_PROMPT_TEMPLATE
        | llm
        | output_parser
    )
    
    # Attach callbacks if provided
    if callbacks:
        chain = chain.with_config(callbacks=callbacks)
    
    logger.info(f"Created chat chain with history for session: {session_id}, callbacks: {len(callbacks) if callbacks else 0}")
    return chain


# ============================================================================
# RAG CHAIN (Single PDF)
# ============================================================================

def create_rag_chain(
    collection_name: str,
    model_name: str = "llama3",
    k: int = 3,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False,
    history: Optional[List] = None
):
    """
    Create a RAG chain using LCEL with ChromaDB retriever.
    
    Chain structure: retriever → format_context → prompt | llm | output_parser
    
    Args:
        collection_name: ChromaDB collection name (PDF identifier)
        model_name: Name of the model to use
        k: Number of documents to retrieve
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Runnable RAG chain
    """
    llm = get_llm(model_name)
    output_parser = StrOutputParser()
    
    # Create default callbacks if observability enabled
    if enable_observability and callbacks is None:
        callbacks = create_callback_manager(
            enable_logging=True,
            enable_performance=True,
            enable_debug=False
        )
    
    # Get retriever from vectorstore manager
    vectorstore_mgr = get_vectorstore_manager()
    retriever = vectorstore_mgr.as_retriever(
        collection_name=collection_name,
        search_kwargs={'k': k}
    )
    
    # LCEL chain: retriever | format | prompt | llm | parse
    chain = (
        {
            "context": retriever | RunnableLambda(format_docs),
            "input": RunnablePassthrough(),
            "chat_history": lambda x: format_chat_history(history or [])
        }
        | RAG_PROMPT_TEMPLATE
        | llm
        | output_parser
    )
    
    # Attach callbacks if provided
    if callbacks:
        chain = chain.with_config(callbacks=callbacks)
    
    logger.info(f"Created RAG chain for collection: {collection_name}, callbacks: {len(callbacks) if callbacks else 0}")
    return chain


def create_rag_chain_with_history(
    collection_name: str,
    session_id: str,
    model_name: str = "llama3",
    k: int = 3,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False
):
    """
    Create a RAG chain with conversation history.
    
    Args:
        collection_name: ChromaDB collection name
        session_id: Session ID for history retrieval
        model_name: Name of the model to use
        k: Number of documents to retrieve
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Runnable RAG chain with history
    """
    llm = get_llm(model_name)
    output_parser = StrOutputParser()
    
    # Create default callbacks if observability enabled
    if enable_observability and callbacks is None:
        callbacks = create_callback_manager(
            enable_logging=True,
            enable_performance=True,
            enable_debug=False
        )
    
    # Get retriever
    vectorstore_mgr = get_vectorstore_manager()
    retriever = vectorstore_mgr.as_retriever(
        collection_name=collection_name,
        search_kwargs={'k': k}
    )
    
    # LCEL chain with history
    chain = (
        {
            "context": itemgetter("input") | retriever | RunnableLambda(format_docs),
            "input": itemgetter("input"),
            "chat_history": lambda x: get_session_history(session_id)
        }
        | RAG_PROMPT_TEMPLATE
        | llm
        | output_parser
    )
    
    # Attach callbacks if provided
    if callbacks:
        chain = chain.with_config(callbacks=callbacks)
    
    logger.info(f"Created RAG chain with history for collection: {collection_name}, session: {session_id}, callbacks: {len(callbacks) if callbacks else 0}")
    return chain


# ============================================================================
# MULTI-PDF RAG CHAIN
# ============================================================================

def create_multi_pdf_rag_chain(
    collection_names: List[str],
    model_name: str = "llama3",
    k: int = 2,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False,
    history: Optional[List] = None
):
    """
    Create a multi-PDF RAG chain using LCEL.
    
    Retrieves context from multiple collections and combines them.
    
    Args:
        collection_names: List of ChromaDB collection names
        model_name: Name of the model to use
        k: Number of documents to retrieve per collection
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Runnable multi-PDF RAG chain
    """
    llm = get_llm(model_name)
    output_parser = StrOutputParser()
    vectorstore_mgr = get_vectorstore_manager()
    
    # Create default callbacks if observability enabled
    if enable_observability and callbacks is None:
        callbacks = create_callback_manager(
            enable_logging=True,
            enable_performance=True,
            enable_debug=False
        )
    
    def retrieve_from_multiple(query: str) -> str:
        """Retrieve and combine context from multiple collections."""
        all_contexts = []
        
        for col_name in collection_names:
            try:
                retriever = vectorstore_mgr.as_retriever(
                    collection_name=col_name,
                    search_kwargs={'k': k}
                )
                docs = retriever.get_relevant_documents(query)
                if docs:
                    context = format_docs(docs)
                    # Add source identifier
                    all_contexts.append(f"Context from {col_name}:\n{context}")
            except Exception as e:
                logger.warning(f"Failed to retrieve from {col_name}: {e}")
                continue
        
        return "\n\n--\n\n".join(all_contexts) if all_contexts else "No context found."
    
    # LCEL chain for multi-PDF
    chain = (
        {
            "context": RunnableLambda(retrieve_from_multiple),
            "input": RunnablePassthrough(),
            "chat_history": lambda x: format_chat_history(history or [])
        }
        | MULTI_PDF_RAG_PROMPT_TEMPLATE
        | llm
        | output_parser
    )
    
    # Attach callbacks if provided
    if callbacks:
        chain = chain.with_config(callbacks=callbacks)
    
    logger.info(f"Created multi-PDF RAG chain for {len(collection_names)} collections, callbacks: {len(callbacks) if callbacks else 0}")
    return chain


def create_multi_pdf_rag_chain_with_history(
    collection_names: List[str],
    session_id: str,
    model_name: str = "llama3",
    k: int = 2,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False
):
    """
    Create a multi-PDF RAG chain with conversation history.
    
    Args:
        collection_names: List of ChromaDB collection names
        session_id: Session ID for history retrieval
        model_name: Name of the model to use
        k: Number of documents to retrieve per collection
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Runnable multi-PDF RAG chain with history
    """
    llm = get_llm(model_name)
    output_parser = StrOutputParser()
    vectorstore_mgr = get_vectorstore_manager()
    
    # Create default callbacks if observability enabled
    if enable_observability and callbacks is None:
        callbacks = create_callback_manager(
            enable_logging=True,
            enable_performance=True,
            enable_debug=False
        )
    
    def retrieve_from_multiple(inputs: Dict) -> str:
        """Retrieve and combine context from multiple collections."""
        query = inputs.get("input", "")
        all_contexts = []
        
        for col_name in collection_names:
            try:
                retriever = vectorstore_mgr.as_retriever(
                    collection_name=col_name,
                    search_kwargs={'k': k}
                )
                docs = retriever.get_relevant_documents(query)
                if docs:
                    context = format_docs(docs)
                    all_contexts.append(f"Context from {col_name}:\n{context}")
            except Exception as e:
                logger.warning(f"Failed to retrieve from {col_name}: {e}")
                continue
        
        return "\n\n--\n\n".join(all_contexts) if all_contexts else "No context found."
    
    # LCEL chain with history
    chain = (
        {
            "context": RunnableLambda(retrieve_from_multiple),
            "input": itemgetter("input"),
            "chat_history": lambda x: get_session_history(session_id)
        }
        | MULTI_PDF_RAG_PROMPT_TEMPLATE
        | llm
        | output_parser
    )
    
    # Attach callbacks if provided
    if callbacks:
        chain = chain.with_config(callbacks=callbacks)
    
    logger.info(f"Created multi-PDF RAG chain with history for {len(collection_names)} collections, session: {session_id}, callbacks: {len(callbacks) if callbacks else 0}")
    return chain


# ============================================================================
# CHAIN FACTORY
# ============================================================================

def get_chain(
    chain_type: str,
    model_name: str = "llama3",
    collection_name: Optional[str] = None,
    collection_names: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    k: int = 3,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
    enable_observability: bool = False
):
    """
    Factory function to get the appropriate chain based on parameters.
    
    Args:
        chain_type: Type of chain ('chat', 'rag', 'multi_rag')
        model_name: Name of the model to use
        collection_name: Single collection name (for RAG)
        collection_names: Multiple collection names (for multi-RAG)
        session_id: Session ID for history (optional)
        k: Number of documents to retrieve
        callbacks: Optional list of callback handlers
        enable_observability: Auto-create logging/performance callbacks
        
    Returns:
        Appropriate chain instance
    """
    if chain_type == "chat":
        if session_id:
            return create_chat_chain_with_history(model_name, session_id, callbacks, enable_observability)
        else:
            return create_chat_chain(model_name, callbacks, enable_observability)
    
    elif chain_type == "rag":
        if not collection_name:
            raise ValueError("collection_name required for RAG chain")
        if session_id:
            return create_rag_chain_with_history(collection_name, session_id, model_name, k, callbacks, enable_observability)
        else:
            return create_rag_chain(collection_name, model_name, k, callbacks, enable_observability)
    
    elif chain_type == "multi_rag":
        if not collection_names:
            raise ValueError("collection_names required for multi-RAG chain")
        if session_id:
            return create_multi_pdf_rag_chain_with_history(collection_names, session_id, model_name, k, callbacks, enable_observability)
        else:
            return create_multi_pdf_rag_chain(collection_names, model_name, k, callbacks, enable_observability)
    
    else:
        raise ValueError(f"Unknown chain type: {chain_type}")


logger.info("Chains module loaded with LCEL implementations")
