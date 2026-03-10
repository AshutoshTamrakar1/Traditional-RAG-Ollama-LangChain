# PDF RAG Chatbot v2.0

An enterprise-grade, production-ready PDF chatbot with **Retrieval-Augmented Generation (RAG)** capabilities. Built with FastAPI, LangChain, and local LLMs, this system enables intelligent conversations with your PDF documents using multiple AI models, persistent storage, and advanced observability.

## 🎯 Overview

This chatbot allows users to:
- **Upload and query PDF documents** using natural language
- **Multi-document RAG** - Ask questions across multiple PDFs simultaneously
- **User authentication** with JWT tokens (stateless)
- **Persistent conversation history** stored in MongoDB
- **Multiple AI models** (Llama3, Gemma, Phi3) for different use cases
- **Mindmap generation** from PDF content
- **Structured output parsing** with observability and callbacks

---

## 🏗️ Architecture Design

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend Layer                          │
│                   ┌──────────────────────┐                      │
│                   │   Reflex Web App     │                      │
│                   │ (Python-based UI)    │                      │
│                   └──────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
                              ⬇ HTTP/REST API
┌─────────────────────────────────────────────────────────────────┐
│                       API Gateway Layer                         │
│                     ┌─────────────────┐                         │
│                     │  pdfreader.py   │                         │
│                     │ (FastAPI Main)  │                         │
│                     └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
                              ⬇
┌─────────────────────────────────────────────────────────────────┐
│                      Service Layer (REST)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ PDF Service  │  │ Chat Service │  │Mindmap Svc   │         │
│  │ •Upload      │  │ •Query RAG   │  │•Generate     │         │
│  │ •Process     │  │ •Multi-PDF   │  │ from PDF     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                            ⬇                                    │
│  ┌──────────────────────────────────────────────────┐          │
│  │          Auth Service (auth.py)                  │          │
│  │  •User Registration  •Login  •JWT Tokens        │          │
│  └──────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ⬇
┌─────────────────────────────────────────────────────────────────┐
│                       Business Logic Layer                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    ai_engine.py                           │  │
│  │  •Chat Completion  •RAG Queries  •Mindmap Generation     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  chains.py   │  │ prompts.py   │  │ callbacks.py │        │
│  │ LangChain    │  │ LLM Prompts  │  │ Observability│        │
│  │ LCEL Chains  │  │ Templates    │  │ & Logging    │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐                           │
│  │output_       │  │ memory_      │                           │
│  │parsers.py    │  │ manager.py   │                           │
│  │ Structured   │  │ Chat History │                           │
│  │ Responses    │  │ Management   │                           │
│  └──────────────┘  └──────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                              ⬇
┌─────────────────────────────────────────────────────────────────┐
│                    Data Access Layer                            │
│  ┌────────────────────┐        ┌────────────────────┐          │
│  │   db_manager.py    │        │ vectorstore_       │          │
│  │                    │        │ manager.py         │          │
│  │ •Users             │        │                    │          │
│  │ •Chat Sessions     │        │ •Document Storage  │          │
│  │ •MongoDB Ops       │        │ •Similarity Search │          │
│  └────────────────────┘        └────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ⬇
┌─────────────────────────────────────────────────────────────────┐
│                      External Systems                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  MongoDB    │  │  ChromaDB   │  │ Ollama LLMs │            │
│  │             │  │             │  │             │            │
│  │ •Users      │  │ •Embeddings │  │ •llama3     │            │
│  │ •Chat Hist. │  │ •Vectors    │  │ •gemma      │            │
│  │ •Documents  │  │ •Documents  │  │ •phi3       │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### Layer-by-Layer Breakdown

#### 1. **Frontend Layer**
- **Reflex App**: Modern Python-based reactive UI ([reflex_app/app/app.py](reflex_app/app/app.py))

#### 2. **API Gateway Layer**
- **[pdfreader.py](pdfreader.py)**: Main FastAPI application
  - Registers all service routers
  - Handles CORS, middleware, startup/shutdown events
  - Runs on port 8000

#### 3. **Service Layer**
Organized in [services/](services/) directory:
- **[pdf_service.py](services/pdf_service.py)**: PDF upload, processing, session creation
- **[chat_service.py](services/chat_service.py)**: Chat completions, RAG queries, title generation
- **[mindmap_service.py](services/mindmap_service.py)**: Generate mindmaps from PDF content
- **[models.py](services/models.py)**: Pydantic request/response models
- **[exceptions.py](services/exceptions.py)**: Custom exception classes
- **[utils.py](services/utils.py)**: Validation utilities

#### 4. **Business Logic Layer**

**Core Modules:**
- **[ai_engine.py](ai_engine.py)**: AI operations orchestration
  - Chat completions (streaming)
  - Single & multi-PDF RAG
  - Mindmap generation
  - Model management (llama3, gemma, phi3)

- **[chains.py](chains.py)**: LangChain LCEL chains
  - `create_chat_chain_with_history()` - Conversational chains
  - `create_rag_chain_with_history()` - Single-doc RAG
  - `create_multi_pdf_rag_chain_with_history()` - Multi-doc RAG

- **[prompts.py](prompts.py)**: Centralized prompt templates
  - System prompts
  - RAG prompts
  - Mindmap generation prompts
  - LangChain prompt templates

- **[callbacks.py](callbacks.py)**: Observability & monitoring
  - Streaming handlers
  - Performance monitoring
  - Logging callbacks
  - Callback manager

- **[output_parsers.py](output_parsers.py)**: Structured output parsing
  - Title extraction
  - Mindmap parsing
  - JSON validation

- **[memory_manager.py](memory_manager.py)**: Conversation history
  - MongoDB-backed chat history
  - Message windowing
  - History caching

- **[auth.py](auth.py)**: Authentication & authorization
  - User registration/login
  - JWT token generation & validation
  - Access token & refresh token support
  - Password hashing (bcrypt)
  - Stateless authentication

#### 5. **Data Access Layer**

- **[db_manager.py](db_manager.py)**: MongoDB operations
  - User CRUD
  - Chat session tracking
  - Async Motor client

- **[vectorstore_manager.py](vectorstore_manager.py)**: ChromaDB operations
  - Document embedding & storage
  - Similarity search
  - Collection management
  - HuggingFace embeddings

#### 6. **Configuration & Logging**

- **[config.py](config.py)**: Centralized configuration
  - Environment variables
  - Database settings
  - Vector store config
  - Pydantic Settings

- **[logging_config.py](logging_config.py)**: Structured logging
  - File & console handlers
  - Log rotation
  - Exception decorators

---

## 🚀 Features

### Core Features
- ✅ **Multi-user authentication** with JWT tokens (stateless)
- ✅ **PDF upload & processing** with PyMuPDF
- ✅ **Semantic search** using ChromaDB + HuggingFace embeddings
- ✅ **RAG (Retrieval-Augmented Generation)** with context-aware responses
- ✅ **Multi-document RAG** - Query across multiple PDFs
- ✅ **Conversation history** persisted in MongoDB
- ✅ **Multiple LLM models** (llama3, gemma, phi3)
- ✅ **Mindmap generation** from PDF content
- ✅ **Streaming responses** with async generators
- ✅ **Structured output parsing** with Pydantic models

### Advanced Features
- 🔍 **LangChain LCEL** (Expression Language) chains
- 📊 **Observability** with callbacks and performance monitoring
- 🔐 **Secure JWT authentication** with access & refresh tokens
- 📝 **Automatic chat title generation**
- 🎯 **Windowed memory** for conversation context
- ⚡ **Async/await** throughout for high performance
- 🛠️ **Modular service architecture**
- 📦 **Clean separation of concerns**

---

## 🛠️ Tech Stack

### Backend
- **FastAPI** - Modern async web framework
- **LangChain** - LLM orchestration framework
- **LangChain Ollama** - Local LLM integration
- **Pydantic v2** - Data validation

### AI & ML
- **Ollama** - Local LLM runtime (llama3, gemma, phi3)
- **HuggingFace Transformers** - Embeddings (all-MiniLM-L6-v2)
- **ChromaDB** - Vector database
- **sentence-transformers** - Semantic embeddings

### Databases
- **MongoDB** (Motor) - User data, chat history, metadata
- **ChromaDB** - Vector embeddings and documents

### PDF Processing
- **PyMuPDF (fitz)** - PDF parsing and text extraction
- **pdfplumber** - Advanced PDF analysis
- **pypdf** - PDF utilities

### Frontend
- **Reflex** - Python-based reactive UI framework

### DevOps & Utilities
- **python-dotenv** - Environment management
- **bcrypt** - Password hashing
- **PyJWT** - JWT token generation & validation
- **python-jose[cryptography]** - Enhanced JWT support
- **rich** - Enhanced terminal output

---

## 📦 Installation

### Prerequisites
- **Python 3.10+**
- **MongoDB** - Running locally or connection URI
- **Ollama** - Installed with models: `llama3`, `gemma`, `phi3`

### 1. Clone Repository
```bash
git clone <repository-url>
cd pdf-rag-chatbot-v1
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Ollama Models
```bash
ollama pull llama3
ollama pull gemma
ollama pull phi3
```

### 4. Configure Environment
Create a `.env` file in the project root:

```env
# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017/chatbot
MONGODB_DB_NAME=pdf_rag_chatbot

# ChromaDB Configuration
CHROMA_PERSIST_DIR=./chroma_db
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2

# Server Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=True
ENVIRONMENT=development

# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=True
LOG_DIR=./logs
```

### 5. Start MongoDB
```bash
# Make sure MongoDB is running
mongod --dbpath /path/to/data
```

### 6. Run Backend Server
```bash
python pdfreader.py
```
Server starts at: **http://localhost:8000**

### 7. Run Frontend (Reflex)
```bash
cd reflex_app
reflex run
```
Frontend starts at: **http://localhost:3000**

---

## 📂 Project Structure

```
pdf-rag-chatbot-v1/
├── pdfreader.py              # Main FastAPI application entry point
├── ai_engine.py              # Core AI operations (chat, RAG, mindmap)
├── chains.py                 # LangChain LCEL chains
├── prompts.py                # LLM prompt templates
├── callbacks.py              # Observability callbacks
├── output_parsers.py         # Structured output parsing
├── memory_manager.py         # Conversation history management
├── vectorstore_manager.py    # ChromaDB vector store operations
├── db_manager.py             # MongoDB database operations
├── auth.py                   # Authentication & JWT token management
├── config.py                 # Configuration management
├── logging_config.py         # Logging configuration
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (create this)
│
├── services/                 # Service layer modules
│   ├── pdf_service.py        # PDF upload & processing
│   ├── chat_service.py       # Chat & RAG operations
│   ├── mindmap_service.py    # Mindmap generation
│   ├── models.py             # Pydantic models
│   ├── exceptions.py         # Custom exceptions
│   └── utils.py              # Utility functions
│
├── reflex_app/               # Reflex frontend application
│   ├── app/
│   │   └── app.py            # Main Reflex UI
│   └── rxconfig.py           # Reflex configuration
│
├── chroma_db/                # ChromaDB persistent storage (auto-created)
├── logs/                     # Application logs (auto-created)
├── uploaded_pdfs/            # Uploaded PDF files (auto-created)
└── uploads/                  # User-specific uploads (auto-created)
```

---

## 🔄 Data Flow

### PDF Upload & Processing Flow
```
User → PDF Service → ai_engine.load_and_store_pdf()
                   → PyMuPDF (extract text)
                   → Text Splitter (chunking)
                   → HuggingFace Embeddings
                   → ChromaDB (store vectors)
                   → MongoDB (store metadata)
```

### Chat Query Flow (RAG)
```
User → Chat Service → ai_engine.chat_with_pdf()
                    → vectorstore_manager.search()
                    → Retrieve relevant chunks
                    → chains.create_rag_chain()
                    → LangChain LCEL chain
                    → Ollama LLM (llama3/gemma)
                    → Streaming response
                    → memory_manager.save_history()
```

### Multi-PDF Query Flow
```
User → Chat Service → ai_engine.chat_with_multiple_pdfs()
                    → vectorstore_manager.search_multiple()
                    → Merge results from multiple collections
                    → chains.create_multi_pdf_rag_chain()
                    → LLM with aggregated context
                    → Response with source attribution
```

---

## 🌐 API Endpoints

**Authentication Required**: All endpoints (except `/auth/register` and `/auth/login`) require an `Authorization` header with a Bearer token:
```
Authorization: Bearer <access_token>
```

### Authentication
- `POST /auth/register` - Register new user
- `POST /auth/login` - User login (returns access & refresh tokens)
- `POST /auth/refresh` - Refresh access token using refresh token
- `POST /auth/logout` - User logout
- `GET /auth/profile` - Get user profile
- `POST /auth/change-password` - Change user password
- `POST /auth/verify-token` - Verify JWT token validity

### PDF Operations
- `POST /pdf/session` - Create chat session
- `POST /pdf/upload` - Upload PDF file
- `GET /pdf/sessions` - List user's chat sessions
- `DELETE /pdf/session/{id}` - Delete chat session

### Chat Operations
- `POST /chat/send` - Send chat message (RAG query)
- `POST /chat/generate-title` - Generate chat title
- `GET /chat/models` - List available models

### Mindmap Operations
- `POST /mindmap/generate` - Generate mindmap from PDF

---

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URI` | `mongodb://localhost:27017/chatbot` | MongoDB connection string |
| `MONGODB_DB_NAME` | `pdf_rag_chatbot` | MongoDB database name |
| `JWT_SECRET_KEY` | Auto-generated | Secret key for JWT token signing (256-bit) |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token expiry time (minutes) |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token expiry time (days) |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | ChromaDB storage directory |
| `EMBEDDING_MODEL_NAME` | `all-MiniLM-L6-v2` | HuggingFace embedding model |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DEBUG` | `True` | Debug mode |

### Model Configuration

Models are defined in [ai_engine.py](ai_engine.py):
- **llama3**: Primary chat model
- **gemma**: Alternative chat model
- **phi3**: Reserved for specialized tasks (podcast generation)

### RAG Parameters

Configured in [ai_engine.py](ai_engine.py):
- **Chunk Size**: 1000 characters
- **Chunk Overlap**: 200 characters
- **Top K**: 3 documents retrieved per query
- **Temperature**: 0.1 (deterministic responses)

---

## 🧪 Testing

Test files for different phases:
- `test_phase1_vectorstore.py` - Vector store operations
- `test_phase2_memory.py` - Memory management
- `test_phase3_chains.py` - LangChain chains
- `test_phase4_observability.py` - Callbacks & parsers
- `test_phase5_integration.py` - End-to-end integration
- `test_integration_quick.py` - Quick smoke tests

Run tests:
```bash
pytest test_phase*.py
```

---

## 📝 Development Notes

### Design Patterns
- **Repository Pattern**: Database operations abstracted in `db_manager.py`
- **Factory Pattern**: Model creation in `ai_engine.py`
- **Singleton Pattern**: Configuration via `get_settings()`
- **Dependency Injection**: FastAPI `Depends()` for services
- **Service Layer Pattern**: Business logic separated from API routes

### Code Organization
- **Separation of Concerns**: Clear boundaries between layers
- **DRY Principle**: Reusable components and utilities
- **Type Hints**: Full type annotations with Pydantic
- **Async First**: Async/await throughout for performance
- **Error Handling**: Centralized exception handling with decorators

---

## 🚧 Future Enhancements

- [ ] WebSocket support for real-time streaming
- [ ] Podcast generation from PDF content
- [ ] Speech-to-text (STT) integration
- [ ] Text-to-speech (TTS) for responses
- [ ] Redis for session caching
- [ ] Docker containerization
- [ ] API rate limiting
- [ ] Comprehensive test coverage
- [ ] OpenAPI documentation
- [ ] CI/CD pipeline

---

## 📄 License

This project is for educational and development purposes.

---

## 🤝 Contributing

Contributions welcome! Please follow the existing code structure and patterns.

---

## 📧 Support

For issues or questions, please open a GitHub issue.
