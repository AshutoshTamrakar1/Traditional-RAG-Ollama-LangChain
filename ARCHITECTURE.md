# Architecture Design Document

## PDF RAG Chatbot v2.1 - Technical Architecture

**Version**: 2.1.0  
**Last Updated**: October 2026  
**Status**: Production Ready

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Layers](#architecture-layers)
3. [Component Details](#component-details)
4. [Data Models](#data-models)
5. [API Design](#api-design)
6. [Security Architecture](#security-architecture)
7. [Code Quality & SonarQube Standards](#code-quality--sonarqube-standards)
8. [Scalability Considerations](#scalability-considerations)
9. [Monitoring & Observability](#monitoring--observability)
10. [Deployment Architecture](#deployment-architecture)

---

## System Overview

### Purpose
A scalable, production-ready PDF chatbot system that enables users to upload PDF documents and have intelligent conversations using Retrieval-Augmented Generation (RAG) with local LLMs.

### Key Characteristics
- **Architecture Style**: Layered Architecture with clean Backend / Frontend separation
- **Codebase Organization**: Dedicated `backend/` service directory and `reflex_app/` frontend directory
- **Communication**: RESTful APIs with async/await patterns
- **Data Persistence**: MongoDB (user/chat data) + ChromaDB (vector embeddings)
- **AI Models**: Local Ollama LLMs (llama3, gemma, phi3)
- **Authentication**: Stateless JWT tokens with access & refresh tokens and revocation blacklisting
- **Quality**: SonarLint / SonarQube clean code compliant (Cognitive Complexity <= 15)

---

## Architecture Layers

### 1. Presentation Layer (Frontend)

#### Components:
- **Reflex Application** (`reflex_app/app/app.py`)
  - Python-based reactive UI framework (Reflex 0.8+)
  - Real-time client-state synchronization
  - **Rich Markdown Rendering**: `rx.markdown` dynamically compiles AI responses to formatted HTML with support for headings (`##`, `###`), bold formatting, bullet and numbered lists, code blocks, blockquotes, and tables
  - **Visual Message Separation**:
    - **User Messages**: Right-aligned accent chat bubbles (`background_color="var(--blue-9)"`, crisp white typography, `border_radius="16px 16px 4px 16px"`, elevation drop-shadow) with solid user avatar (`U`)
    - **AI Assistant Messages**: Left-aligned structured surface cards (`background_color="var(--gray-a2)"`, subtle border, `border_radius="4px 16px 16px 16px"`) paired with a violet AI avatar badge
  - **Centered Reading Container**: `max_width="880px"` chat area for optimal reading line length on widescreen monitors
  - **Consolidated Chat Header**: Chat title on the left; inline model selector dropdown and PDF upload trigger on the right
  - **Form Submission**: Wrapped in `rx.form` supporting keyboard <kbd>Enter</kbd> to submit, animated loading spinner, and Lucide send icon
  - **Multi-File Upload Modal**: Drag-and-drop file upload supporting up to 20 PDFs simultaneously
  - **Session Context Continuity**: Switching between previous sessions in the sidebar queries MongoDB to re-synchronize active document IDs (`active_source_ids`) and conversation history

#### Responsibilities:
- User input collection and keyboard shortcut handling
- Markdown and structured response rendering
- JWT token storage (URL handover and state persistence)
- Active session switching and PDF source toggling
- Multi-file upload handling and progress tracking

---

### 2. API Gateway Layer

#### Main Component: `backend/pdfreader.py`

**Responsibilities:**
- FastAPI application initialization
- Router registration and mounting
- CORS middleware configuration
- Lifecycle management (startup/shutdown)
- Global exception handling

**Router Structure:**
```python
/auth/*        → Authentication endpoints
/pdf/*         → PDF operations
/chat/*        → Chat and RAG queries
```

**Middleware Stack:**
1. CORS Middleware (allow all origins in dev)
2. Exception handlers (custom error responses)
3. Request logging (via logging_config)

---

### 3. Service Layer

Located in `backend/services/` directory. Each service module handles a specific domain.

#### 3.1 PDF Service (`backend/services/pdf_service.py`)

**Endpoints:**
- `POST /pdf/session` - Create new chat session
- `POST /pdf/upload` - Upload and process PDF
- `GET /pdf/sessions` - List user sessions
- `DELETE /pdf/session/{id}` - Delete session

**Key Operations:**
```python
upload_pdf()
  → get_current_user() [JWT dependency]
  → ensure_upload_dir()
  → save_file_to_disk()
  → ai_engine._load_and_store_pdf()
  → db_manager.add_source_to_chat_session()
```

**Dependencies:**
- `db_manager`: Session persistence
- `ai_engine`: PDF processing and embedding
- `auth`: JWT token validation

---

#### 3.2 Chat Service (`backend/services/chat_service.py`)

**Endpoints:**
- `POST /chat/send` - Send message (RAG query)
- `POST /chat/generate-title` - Generate chat title
- `GET /chat/models` - List available models

**Key Operations:**
```python
send_chat()
  → get_current_user() [JWT dependency]
  → determine_chat_mode() 
     • No PDF: chat_completion_LlamaModel_ws()
     • Single PDF: chat_completion_with_pdf_ws()
     • Multiple PDFs: chat_completion_with_multiple_pdfs_ws()
  → save_to_database()
  → return streaming response
```

**Chat Modes:**
1. **General Chat**: No PDF context, using chat history
2. **Single-PDF RAG**: Query one PDF with context retrieval
3. **Multi-PDF RAG**: Query across multiple PDFs with merged context

---

#### 3.3 Supporting Modules

**`backend/services/models.py`** - Pydantic Models
```python
ChatRequest
ChatResponse
BaseRequest (with validation)
```

**`backend/services/exceptions.py`** - Custom Exceptions
```python
PDFBotException (base)
  ↳ InvalidSessionError (403)
  ↳ ThreadNotFoundError (404)
  ↳ SourceNotFoundError (404)
```

**`backend/services/utils.py`** - Utility Functions
```python
verify_jwt_token()        # Validates JWT and extracts user_id
get_user_from_token()     # Gets user from Authorization header
ensure_upload_dir()
RequestSimulator (for testing)
```

---

### 4. Business Logic Layer

Core intelligence and orchestration modules located in `backend/`.

#### 4.1 AI Engine (`backend/ai_engine.py`)

**Primary Functions:**

```python
chat_completion_LlamaModel_ws()
  → chains.create_chat_chain_with_history()
  → Stream tokens via async generator

chat_completion_with_pdf_ws()
  → vectorstore_manager.search()
  → chains.create_rag_chain_with_history()
  → Stream with context

chat_completion_with_multiple_pdfs_ws()
  → vectorstore_manager.search_multiple_collections()
  → chains.create_multi_pdf_rag_chain_with_history()
  → Merged context streaming

_load_and_store_pdf()
  → PyMuPDFLoader.load()
  → text_splitter.split_documents()
  → vectorstore_manager.add_documents()
```

**Model Management:**
```python
AVAILABLE_MODELS = {
    "llama3": llama3_llm,    # Primary chat
    "gemma": gemma_llm,      # Alternative chat
    "phi3": phi3_llm         # Specialized tasks
}
```

---

#### 4.2 Chains Module (`backend/chains.py`)

**LangChain LCEL Chains** - Composable chain architecture

**Chat Chain:**
```python
create_chat_chain_with_history(model_name, session_id)
  → get_mongodb_chat_history()
  → RunnableWithMessageHistory(
       chat_chain,
       history_factory,
       input_messages_key="input",
       history_messages_key="chat_history"
     )
```

**RAG Chain:**
```python
create_rag_chain_with_history(model_name, session_id, collection_name)
  → vectorstore_manager.get_vectorstore(collection_name)
  → retriever = vectorstore.as_retriever()
  → rag_chain = (
       RunnableParallel({
         "context": itemgetter("input") | retriever | format_docs,
         "input": itemgetter("input"),
         "chat_history": itemgetter("chat_history")
       })
       | RAG_PROMPT_TEMPLATE
       | llm
       | StrOutputParser()
     )
```

**Multi-PDF Chain:**
```python
create_multi_pdf_rag_chain_with_history(model_name, session_id, collections)
  → for each collection: get_vectorstore() → retriever
  → aggregate_retrievers = lambda query: merge_results()
  → similar structure to RAG chain with merged context
```

---

#### 4.3 Memory Manager (`backend/memory_manager.py`)

**MongoDB-backed Conversation History**

```python
get_mongodb_chat_history(session_id, user_id)
  → MongoDBChatMessageHistory(
       connection_string=MONGODB_URI,
       database_name=DB_NAME,
       collection_name=f"chat_history_{session_id}",
       session_id=session_id
     )
  → Cached for performance

add_message_to_history(session_id, role, content, user_id)
  → history.add_user_message() or add_ai_message()

get_windowed_messages(session_id, user_id, max_messages)
  → get_mongodb_chat_history()
  → history.messages[-max_messages:]
  → format_chat_history()
```

**Message Windowing:**
- Default: Last 10 messages (5 exchanges)
- Prevents context overflow
- Maintains conversation continuity

---

#### 4.4 Vector Store Manager (`backend/vectorstore_manager.py`)

**ChromaDB Abstraction Layer**

```python
class VectorStoreManager:
    _client: ChromaDB PersistentClient
    _embeddings: HuggingFaceEmbeddings
    _vectorstore_cache: Dict[str, Chroma]
    
    add_documents(collection_name, documents, metadatas)
      → get_or_create_collection()
      → embeddings.embed_documents()
      → collection.add()
    
    search(collection_name, query, k=3)
      → vectorstore.similarity_search(query, k=k)
      → Returns List[Document]
    
    search_multiple_collections(collections, query, k_per_collection)
      → for each: search()
      → merge and sort by relevance
    
    delete_collection(collection_name)
      → client.delete_collection()
      → Clear cache
```

**Embedding Model:**
- `all-MiniLM-L6-v2` (384 dimensions)
- Fast inference
- Offline caching (`local_files_only: True`)

---

#### 4.5 Database Manager (`backend/db_manager.py`)

**MongoDB Operations with Motor (async)**

**User Management:**
```python
create_user(email, username, hashed_password)
get_user_by_id(user_id)
get_user_by_email(email)
update_user_last_login(user_id)
```

**Chat Session Management:**
```python
create_chat_session_in_db(user_id, session_id, chat_session_id)
add_source_to_chat_session(chat_session_id, source_id, filename, filepath)
add_turn_to_general_chat(chat_session_id, question, answer)
add_turn_to_multi_source_chat(chat_session_id, question, answer, source_ids)
get_chat_session_by_id(chat_session_id)
get_user_chat_session_list(user_id)
delete_chat_session(chat_session_id, user_id)
```

**Token Revocation & Blacklisting:**
```python
revoke_token(jti, token_type, expires_at)
is_token_revoked(jti)
cleanup_expired_tokens()
```

**Collections:**
- `users` - User accounts
- `chat_sessions` - Session metadata, sources, and conversation turns
- `revoked_tokens` - Blacklisted JWT JTIs with MongoDB TTL expiration
- `chat_history_{session_id}` - Per-session raw message documents

---

#### 4.6 Authentication (`backend/auth.py`)

**Stateless JWT Authentication with Token Rotation**

**Registration Flow:**
```python
register()
  → validate_email()
  → hash_password(bcrypt)
  → db_manager.create_user()
  → generate access_token + refresh_token
  → return tokens
```

**Login Flow:**
```python
login()
  → db_manager.get_user_by_email()
  → bcrypt.checkpw()
  → db_manager.update_user_last_login()
  → generate access_token + refresh_token
  → return tokens
```

**Token Refresh Flow:**
```python
refresh()
  → verify refresh_token
  → check db_manager.is_token_revoked(jti)
  → db_manager.revoke_token(jti) [Refresh token rotation]
  → generate new access_token + new refresh_token
  → return tokens
```

**Security Measures:**
- Bcrypt password hashing (salt rounds: 12)
- Short-lived Access Tokens (60 min) + Long-lived Refresh Tokens (7 days)
- Refresh token rotation (single-use refresh tokens)
- Immediate token blacklisting on logout via JTI tracking

---

#### 4.7 Prompts (`backend/prompts.py`)

**Centralized Prompt Templates using LangChain**

```python
CHAT_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    HumanMessagePromptTemplate.from_template("{input}")
])

RAG_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(RAG_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    HumanMessagePromptTemplate.from_template(
        "Context from document:\n{context}\n\nQuestion: {input}"
    )
])

TITLE_GENERATION_PROMPT = PromptTemplate(...)
```

---

#### 4.8 Callbacks (`backend/callbacks.py`)

**Observability & Monitoring Handlers**

```python
class StreamingCallbackHandler(AsyncCallbackHandler):
    on_llm_new_token() → Capture streaming tokens
    on_llm_start() → Initialize
    on_llm_end() → Finalize

class LoggingCallbackHandler(BaseCallbackHandler):
    on_llm_start() → Log prompt
    on_llm_end() → Log completion
    on_llm_error() → Log errors

class PerformanceCallbackHandler(BaseCallbackHandler):
    on_llm_start() → Start timer
    on_llm_end() → Calculate duration, tokens/sec
    on_chain_start/end() → Track chain performance
```

---

#### 4.9 Output Parsers (`backend/output_parsers.py`)

**Structured Output Parsing**

```python
class TitleOutputParser(BaseOutputParser[ChatTitle]):
    parse() → Extract title from LLM response
    
class SafeJsonOutputParser(BaseOutputParser[Any]):
    parse() → Fault-tolerant JSON extraction
```

---

#### 4.10 Configuration (`backend/config.py`)

**Pydantic Settings Management**

```python
class Settings(BaseSettings):
    # App
    APP_NAME: str
    ENVIRONMENT: str
    
    # Server
    HOST: str
    PORT: int
    
    # MongoDB
    MONGODB_URI: str
    MONGODB_DB_NAME: str
    
    # ChromaDB
    CHROMA_PERSIST_DIR: str
    EMBEDDING_MODEL_NAME: str
    
    # Security
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int
    
    # Logging
    LOG_LEVEL: str
    LOG_TO_FILE: bool
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True
    )
```

---

## Data Models

### User Model
```python
{
    "_id": ObjectId,
    "user_id": str (UUID),
    "email": str (unique),
    "username": str,
    "hashed_password": str,
    "created_at": datetime,
    "last_login": datetime
}
```

### Chat Session Model
```python
{
    "_id": ObjectId,
    "chat_session_id": str (UUID),
    "user_id": str,
    "title": str,
    "created_at": datetime,
    "updated_at": datetime,
    "deleted": bool,
    "model": str,
    "sources": [
        {
            "source_id": str,
            "filename": str,
            "filepath": str,
            "uploaded_at": datetime
        }
    ],
    "turns": [
        {
            "question": str,
            "answer": str,
            "timestamp": datetime,
            "source_ids": list (optional)
        }
    ]
}
```

### Revoked Token Model
```python
{
    "_id": ObjectId,
    "jti": str (JWT ID),
    "token_type": str ("access" | "refresh"),
    "revoked_at": datetime,
    "expires_at": datetime (Indexed with TTL for auto-cleanup)
}
```

### Vector Store Document
```python
{
    "id": str (UUID),
    "embedding": List[float],  # 384 dimensions
    "metadata": {
        "source": str (filename),
        "page": int,
        "collection_name": str
    },
    "document": str (chunk text)
}
```

---

## API Design

### RESTful Principles
- Resource-based URLs
- Standard HTTP methods (GET, POST, DELETE)
- JSON request/response bodies
- Proper HTTP status codes with RFC error details

### Authentication Flow
```
1. POST /auth/register → {access_token, refresh_token, user_id}
2. POST /auth/login → {access_token, refresh_token, user_id}
3. Include Authorization: Bearer <access_token> in subsequent requests
4. POST /auth/refresh → {access_token, refresh_token} (Rotates refresh token)
5. POST /auth/logout → Blacklists token JTI in MongoDB
```

### PDF RAG Flow
```
1. POST /pdf/session → {chat_session_id}
2. POST /pdf/upload → {source_id, filename}
3. POST /chat/send → {answer, streaming}
```

---

## Security Architecture

### Authentication
- **JWT-based**: Stateless token authentication
- **Token Types**:
  - **Access Token**: Short-lived (60 minutes default), used for API requests
  - **Refresh Token**: Long-lived (7 days default), rotated on each refresh
- **Password Hashing**: Bcrypt with salt (12 rounds)
- **Token Algorithm**: HS256 (HMAC with SHA-256)
- **Revocation**: Instant token blacklisting with MongoDB TTL index

### Authorization
- User-scoped resources (chat sessions, uploads, vector collections)
- JWT validation on every protected endpoint via `Annotated[str, Depends(get_current_user)]`
- No cross-tenant document or history leakage

---

## Code Quality & SonarQube Standards

### 1. Cognitive Complexity Compliance
- All service methods, AI orchestration routines, and Reflex event handlers maintain **Cognitive Complexity <= 15** (strictly adhering to SonarLint rule `python:S3776`).
- Complex loops and nested conditionals were decomposed into single-responsibility private helper functions.

### 2. Modern Dependency Injection & Type Annotations
- FastAPI dependency injection leverages `typing.Annotated` (`python:S8410`), separating dependency definitions from type annotations.
- Redundant `response_model` annotations matching return signatures have been eliminated (`python:S8409`).

### 3. Timezone-Aware Datetime Operations
- Replaced deprecated naive `datetime.utcnow()` with timezone-aware `datetime.now(timezone.utc)` across auth and database layers (`python:S6903`).

### 4. Literal De-duplication
- Repeated string literals (such as session IDs, status strings, error messages, and file paths) have been extracted into uppercase constants (`python:S1192`).

### 5. Exception Logging
- Generic logging calls in exception blocks were updated to `logger.exception()` / `logging.exception()` to preserve full stack traces for automated log collectors (`python:S8572`).

---

## Scalability Considerations

### Horizontal Scaling
- Stateless JWT authentication allows deploying multiple FastAPI replicas behind a load balancer without sticky sessions.
- MongoDB and ChromaDB operate as decoupled storage backends.

### Database Scaling
- MongoDB replica sets for high availability and read-replica distribution.
- Vector collections are isolated per document source ID (`source_id`), preventing cross-document retrieval interference.

---

## Monitoring & Observability

### Logging
- **Structured logging** via `backend/logging_config.py`.
- **Log levels**: DEBUG, INFO, WARNING, ERROR.
- **File rotation**: Daily rotation with 7-day retention.

### Performance Callbacks
- LangChain callback managers track token streaming latency, generation speed, and LLM invocation metrics.

---

## Deployment Architecture

### Directory Layout
```
pdf-rag-chatbot-v1/
├── backend/                   # FastAPI Backend Services
│   ├── services/              # Domain service routers
│   ├── ai_engine.py           # Core AI & RAG execution
│   ├── auth.py                # JWT auth & bcrypt hashing
│   ├── chains.py              # LCEL chains
│   ├── config.py              # Pydantic configuration
│   ├── db_manager.py          # MongoDB persistence
│   ├── logging_config.py      # Structured logging
│   ├── memory_manager.py      # Chat history memory
│   ├── output_parsers.py      # Output parsing
│   ├── pdfreader.py           # FastAPI entrypoint
│   ├── prompts.py             # Prompt templates
│   ├── requirements.txt       # Backend dependencies
│   └── vectorstore_manager.py # ChromaDB manager
│
├── reflex_app/                # Reflex Frontend Web App
│   ├── app/
│   │   └── app.py             # Reflex reactive UI & state
│   └── rxconfig.py            # Reflex configuration
│
├── tests/                     # Automated tests
├── ARCHITECTURE.md            # Technical Architecture
└── README.md                  # Project Documentation
```

### Local Services
```
Local Environment:
├── FastAPI Server        (http://localhost:8000)
├── Reflex Web Frontend   (http://localhost:3000)
├── Reflex Backend Server (http://localhost:8001)
├── MongoDB               (mongodb://localhost:27017)
├── Ollama LLM Service    (http://localhost:11434)
└── ChromaDB              (Embedded at backend/chroma_db)
```
