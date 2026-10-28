"""Centralized prompt and template definitions for the PDF RAG chatbot.

Move prompts here so they can be reused, tested, and edited in one place.
Uses LangChain prompt templates for better structure and composability.
"""
from typing import Final
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    PromptTemplate
)

# ============================================================================
# LEGACY STRING PROMPTS (Kept for backward compatibility during migration)
# ============================================================================

# System-level prompt for general chat completions
SYSTEM_PROMPT: Final[str] = (
    "You are a helpful AI assistant. Provide clear, accurate, and well-structured "
    "answers based on the conversation history. When asked to summarize, organize "
    "information logically with bullet points or sections."
)

# Main RAG system prompt used when answering with document context
RAG_SYSTEM_PROMPT: Final[str] = (
    "You are an expert document assistant. Analyze the provided context carefully "
    "and answer the user's question accurately.\n\n"
    "RULES:\n"
    "1. Use ONLY information from the provided context\n"
    "2. When summarizing, organize information with clear sections and bullet points\n"
    "3. Be comprehensive but concise - highlight key points\n"
    "4. If asked to summarize, structure your response with headings\n"
    "5. If the answer is not in the context, say \"I cannot answer this based on the provided document.\"\n"
    "6. Do not copy-paste text directly - synthesize and organize the information\n"
    "7. Provide well-formatted, easy-to-read responses"
)

# ============================================================================
# LANGCHAIN PROMPT TEMPLATES
# ============================================================================

INPUT_VARIABLE_TEMPLATE: Final[str] = "{input}"

# General chat prompt template with system message and history
CHAT_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    HumanMessagePromptTemplate.from_template(INPUT_VARIABLE_TEMPLATE)
])

# RAG prompt template with system message, context, and history
RAG_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(RAG_SYSTEM_PROMPT),
    SystemMessagePromptTemplate.from_template(
        "Context from the document:\n{context}\n\n"
        "Use the above context to answer the following question."
    ),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    HumanMessagePromptTemplate.from_template(INPUT_VARIABLE_TEMPLATE)
])

# Multi-PDF RAG prompt template
MULTI_PDF_RAG_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(RAG_SYSTEM_PROMPT),
    SystemMessagePromptTemplate.from_template(
        "Context from multiple documents:\n{context}\n\n"
        "Use the above context to answer the following question."
    ),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    HumanMessagePromptTemplate.from_template(INPUT_VARIABLE_TEMPLATE)
])

# ============================================================================
# SPECIALIZED PROMPT TEMPLATES (Non-chat use cases)
# ============================================================================

# Title generation prompt template
TITLE_GENERATION_PROMPT_TEMPLATE = PromptTemplate.from_template(
    "Based on the following conversation, generate a short, concise title (4-5 words max).\n"
    "Do not use any quotation marks or labels in your response. Just provide the title text.\n\n"
    "CONVERSATION:\n{conversation_text}\n"
)

# Legacy string version for backward compatibility
TITLE_GENERATION_PROMPT: Final[str] = (
    "Based on the following conversation, generate a short, concise title (4-5 words max).\n"
    "Do not use any quotation marks or labels in your response. Just provide the title text.\n\n"
    "CONVERSATION:\n{conversation_text}\n"
)

# Constants (history length used by the chat engine)
HISTORY_LENGTH: Final[int] = 10

"""End of prompts module."""
