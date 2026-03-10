# Architecture Design Document

## PDF RAG Chatbot v2.0 - Technical Architecture

**Version**: 2.0.0  
**Last Updated**: February 2026  
**Status**: Production Ready

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Layers](#architecture-layers)
3. [Component Details](#component-details)
4. [Data Models](#data-models)
5. [API Design](#api-design)
6. [Security Architecture](#security-architecture)
7. [Scalability Considerations](#scalability-considerations)
8. [Monitoring & Observability](#monitoring--observability)

---

## System Overview

### Purpose
A scalable, production-ready PDF chatbot system that enables users to upload PDF documents and have intelligent conversations using Retrieval-Augmented Generation (RAG) with local LLMs.

### Key Characteristics
- **Architecture Style**: Layered Architecture with Service-Oriented Design
- **Communication**: RESTful APIs with async/await patterns
- **Data Persistence**: MongoDB (user/chat data) + ChromaDB (vector embeddings)
- **AI Models**: Local Ollama LLMs (llama3, gemma, phi3)
- **Authentication**: Stateless JWT tokens with access & refresh tokens

---

## Architecture Layers

### 1. Presentation Layer (Frontend)

#### Components:
- **Reflex Application** (`reflex_app/app/app.py`)
  - Python-based reactive UI framework
  - Real-time state management
  - WebSocket ready for streaming
  - Async state management with httpx

#### Responsibilities:
- User input collection
- Response rendering
- JWT token storage (localStorage/cookies)
- File upload handling

---

### 2. API Gateway Layer

#### Main Component: `pdfreader.py`

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
/mindmap/*     → Mindmap generation
```

**Middleware Stack:**
1. CORS Middleware (allow all origins in dev)
2. Exception handlers (custom error responses)
3. Request logging (via logging_config)

---

### 3. Service Layer

Located in `services/` directory. Each service module handles a specific domain.

#### 3.1 PDF Service (`pdf_service.py`)

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
- `auth.active_sessions`: Session validation

---

#### 3.2 Chat Service (`chat_service.py`)

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

#### 3.3 Mindmap Service (`mindmap_service.py`)

**Endpoints:**
- `POST /mindmap/generate` - Generate mindmap from PDF

**Key Operations:**
```python
generate_mindmap()
  → get_current_user() [JWT dependency]
  → estimate_generation_time()
  → ai_engine.generate_mindmap_from_pdf()
  → MindmapOutputParser.parse()
  → db_manager.update_source_field()
```

---

#### 3.4 Supporting Modules

**`models.py`** - Pydantic Models
```python
ChatRequest
ChatResponse
MindmapRequest
MindmapResponse
BaseRequest (with validation)
```

**`exceptions.py`** - Custom Exceptions
```python
PDFBotException (base)
  ↳ InvalidSessionError (403)
  ↳ ThreadNotFoundError (404)
  ↳ SourceNotFoundError (404)
```

**`utils.py`** - Utility Functions
```python
verify_jwt_token()        # Validates JWT and extracts user_id
get_user_from_token()     # Gets user from Authorization header
ensure_upload_dir()
RequestSimulator (for testing)
# Deprecated:
validate_session()        # Raises error directing to JWT
```

---

### 4. Business Logic Layer

Core intelligence and orchestration modules.

#### 4.1 AI Engine (`ai_engine.py`)

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

generate_mindmap_from_pdf()
  → Load PDF with PyMuPDF
  → Apply MINDMAP_PROMPT_TEMPLATE
  → Parse structured output

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

#### 4.2 Chains Module (`chains.py`)

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

#### 4.3 Memory Manager (`memory_manager.py`)

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

#### 4.4 Vector Store Manager (`vectorstore_manager.py`)

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
- Good semantic understanding

---

#### 4.5 Database Manager (`db_manager.py`)

**MongoDB Operations with Motor (async)**

**User Management:**
```python
create_user(email, username, hashed_password)
get_user_by_id(user_id)
get_user_by_email(email)
update_user_last_login(user_id)
```

**Session Management:**
```python
create_session(session_id, user_id)
get_session(session_id)
delete_session(session_id)
cleanup_expired_sessions()  # Background task
```

**Chat Session Management:**
```python
create_chat_session_in_db(user_id, session_id, chat_session_id)
add_source_to_chat_session(chat_session_id, source_id, filename, filepath)
add_turn_to_general_chat(chat_session_id, question, answer)
add_turn_to_multi_source_chat(chat_session_id, question, answer, source_ids)
get_chat_session_by_id(chat_session_id)
get_user_chat_session_list(user_id, session_id)
```

**Collections:**
- `users` - User accounts
- `sessions` - Active sessions
- `chat_sessions` - Thread metadata
- `chat_history_{session_id}` - Per-session messages

---

#### 4.6 Authentication (`auth.py`)

**Session-Based Authentication (No JWT)**

**Registration Flow:**
```python
register()
  → validate_email()
  → hash_password(bcrypt)
  → db_manager.create_user()
  → create_session()
  → return session_id
```

**Login Flow:**
```python
login()
  → db_manager.get_user_by_email()
  → bcrypt.checkpw()
  → db_manager.create_session()
  → active_sessions[session_id] = {user_id, timestamp}
  → return session_id
```

**Session Validation:**
```python
validate_session()
  → Check active_sessions (in-memory)
  → Fallback: db_manager.get_session()
  → Verify expiry
  → return user_id
```

**Security Measures:**
- Bcrypt password hashing (cost factor: 12)
- Session expiry (24 hours default)
- Email validation with Pydantic
- Password complexity requirements

---

#### 4.7 Prompts (`prompts.py`)

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

MINDMAP_PROMPT_TEMPLATE = PromptTemplate(...)
TITLE_GENERATION_PROMPT = PromptTemplate(...)
```

---

#### 4.8 Callbacks (`callbacks.py`)

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

create_callback_manager(handlers_list)
  → Returns CallbackManager for LangChain
```

---

#### 4.9 Output Parsers (`output_parsers.py`)

**Structured Output Parsing**

```python
class TitleOutputParser(BaseOutputParser[ChatTitle]):
    parse() → Extract title from LLM response
    
class MindmapOutputParser(BaseOutputParser[MindmapOutput]):
    parse() → Extract JSON mindmap structure
    
class SafeJsonOutputParser(BaseOutputParser[Any]):
    parse() → Fault-tolerant JSON extraction
    
extract_json_from_text() → Regex-based JSON extraction
```

---

#### 4.10 Configuration (`config.py`)

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
    
    # Logging
    LOG_LEVEL: str
    LOG_TO_FILE: bool
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True
    )

@lru_cache()
def get_settings() → Settings (singleton)
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

### Session Model
```python
{
    "_id": ObjectId,
    "session_id": str (UUID),
    "user_id": str,
    "created_at": datetime,
    "expires_at": datetime
}
```

### Chat Session Model
```python
{
    "_id": ObjectId,
    "chat_session_id": str (UUID),
    "user_id": str,
    "session_id": str,
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
            "uploaded_at": datetime,
            "mindmap": dict (optional)
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
- Proper status codes

### Authentication Flow
```
1. POST /auth/register → {session_id, user_id}
2. POST /auth/login → {session_id, user_id}
3. Include session_id in all subsequent requests
4. POST /auth/logout → Clear session
```

### PDF RAG Flow
```
1. POST /pdf/session → {chat_session_id}
2. POST /pdf/upload → {source_id, filename}
3. POST /chat/send → {answer, streaming}
4. POST /mindmap/generate → {mindmap_data}
```

### Error Responses
```json
{
    "detail": "Error message",
    "status_code": 400/403/404/500
}
```

---

## Security Architecture

### Authentication
- **JWT-based**: Stateless token authentication
- **Token Types**:
  - **Access Token**: Short-lived (60 minutes default), used for API authentication
  - **Refresh Token**: Long-lived (7 days default), used to obtain new access tokens
- **Password Hashing**: Bcrypt with salt (unchanged)
- **Token Algorithm**: HS256 (HMAC with SHA-256)
- **Secret Key**: 256-bit randomly generated (configurable via env var)

### Authorization
- User-scoped resources (chat sessions, uploads)
- JWT validation on every protected endpoint
- Dependency injection pattern using `Depends(get_current_user)`
- No server-side session storage (stateless)

### Token Flow
```
1. Login/Register → Returns access_token + refresh_token
2. Client stores tokens (localStorage or httpOnly cookies)
3. API requests include: Authorization: Bearer <access_token>
4. Server validates JWT signature and expiry
5. On access_token expiry → Use refresh_token to get new access_token
6. Logout → Client discards tokens (server-side logout optional)
```

### Data Security
- Passwords never stored in plaintext
- JWT tokens signed with secret key (prevents tampering)
- File uploads validated (PDF only)
- MongoDB connections over authenticated channels
- Environment variables for secrets
- No session data stored server-side (horizontal scaling friendly)

---

## Scalability Considerations

### Current Limitations
- Single-server deployment
- Local Ollama models (not load-balanced)
- File storage on disk (not object storage)
- No distributed caching layer

### Scaling Strategies
1. **Horizontal Scaling**:
   - Deploy multiple FastAPI instances (stateless JWT enables this)
   - Load balancer (Nginx/HAProxy)
   - No shared session state required (JWT FTW!)

2. **Database Scaling**:
   - MongoDB replica sets
   - Read replicas for queries
   - Sharding by user_id

3. **Vector Store Scaling**:
   - Distributed ChromaDB clusters
   - Or migrate to Pinecone/Weaviate

4. **LLM Scaling**:
   - Ollama cluster with load balancing
   - Or migrate to cloud LLM APIs

---

## Monitoring & Observability

### Logging
- **Structured logging** with `logging_config.py`
- **Log levels**: DEBUG, INFO, WARNING, ERROR
- **File rotation**: Daily rotation with 7-day retention
- **Console output**: Rich formatting

### Callbacks
- **Performance tracking**: Token speed, latency
- **Error tracking**: LLM failures, chain errors
- **Debug mode**: Detailed chain execution logs

### Metrics (Future)
- Request rate (requests/sec)
- Response time (p50, p95, p99)
- Error rate
- Active sessions
- Vector store size

---

## Deployment Architecture

### Development
```
Local Machine
├── Python FastAPI Server (port 8000)
├── Reflex Frontend (port 3000)
├── MongoDB (port 27017)
├── Ollama (port 11434)
└── ChromaDB (embedded)
```

### Production (Recommended)
```
Load Balancer
├── FastAPI Instance 1
├── FastAPI Instance 2
└── FastAPI Instance N
     ↓
Redis (Session Cache)
MongoDB Replica Set
ChromaDB Cluster
Ollama Cluster / Cloud LLM API
```

---

## Technology Decisions

### Why FastAPI?
- Async/await native support
- Auto-generated OpenAPI docs
- Pydantic integration
- High performance

### Why MongoDB?
- Flexible document schema
- Good for chat history
- Async driver (Motor)
- Easy horizontal scaling

### Why ChromaDB?
- Open-source vector database
- Persistent storage
- Good performance for medium-scale
- Python-native API

### Why Local LLMs (Ollama)?
- Data privacy
- No API costs
- Low latency (local inference)
- Model flexibility

### Why LangChain?
- Standardized LLM interfaces
- LCEL composability
- Rich ecosystem
- Memory management

---

## Conclusion

This architecture provides:
- ✅ **Modularity**: Clear separation of concerns
- ✅ **Scalability**: Ready for horizontal scaling
- ✅ **Maintainability**: Well-organized codebase
- ✅ **Observability**: Comprehensive logging and callbacks
- ✅ **Security**: Session-based auth with bcrypt
- ✅ **Performance**: Async/await throughout
- ✅ **Extensibility**: Easy to add new features

The layered architecture ensures that each component has a single responsibility and can be modified or replaced independently.
