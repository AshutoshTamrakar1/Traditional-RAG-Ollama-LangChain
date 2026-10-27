# PDF RAG Chatbot v2.0

An enterprise-grade, production-ready PDF chatbot with **Retrieval-Augmented Generation (RAG)** capabilities. Built with FastAPI, LangChain 0.3+, and local LLMs via Ollama, this system enables intelligent conversations with your PDF documents using multiple AI models, persistent storage in MongoDB & ChromaDB, and a modern reactive Reflex UI.

---

## 🎯 Overview

This chatbot allows users to:
- **Upload and query PDF documents** using natural language
- **Multi-document RAG** - Ask questions across multiple PDFs simultaneously with source attribution
- **User authentication** with secure JWT tokens (access + refresh token rotation and token revocation)
- **Persistent conversation history** stored in MongoDB with windowed memory
- **Multiple AI models** (Llama3, Gemma, Phi3) running locally via Ollama
- **Mindmap generation** from PDF content with robust syntax normalization
- **Structured output parsing** with observability, callbacks, and performance logging
- **Modern Reflex Frontend** featuring dynamic dark/light aesthetics, centered upload modal with drag & drop, and reactive state management

---

## 🏗️ Architecture Design

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend Layer                          │
│                   ┌──────────────────────┐                      │
│                   │   Reflex Web App     │                      │
│                   │ (Python / Next.js)   │                      │
│                   └──────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
                              ⬇ HTTP & WebSocket API
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
│  │ •Sessions    │  │ •Multi-PDF   │  │ from PDF     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                            ⬇                                    │
│  ┌──────────────────────────────────────────────────┐          │
│  │          Auth Service (auth.py)                  │          │
│  │  •User Registration  •Login  •Token Revocation   │          │
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
│  │ •Revoked Tokens    │        │ •Similarity Search │          │
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

---

## 🚀 Features & Recent Improvements

### Core Capabilities
- ✅ **Secure Multi-User Auth**: JWT-based access & refresh tokens with JTI tracking and MongoDB TTL token blacklisting upon logout.
- ✅ **PDF Ingestion & Validation**: Strict validation verifying `.pdf` extension, `%PDF-` magic bytes, and path traversal security.
- ✅ **Semantic Search**: Fast, local embeddings using `all-MiniLM-L6-v2` with offline-first caching (`local_files_only: True`) to eliminate remote HF latency.
- ✅ **Isolated Collections**: Vectorstore collections keyed by unique `source_id` to prevent document collisions across users and sessions.
- ✅ **Conversational RAG Memory**: Follow-up queries retain conversational context via sliding window memory within LCEL chains.
- ✅ **Multi-Document RAG**: Query across multiple PDFs simultaneously with model selection support (`llama3`, `gemma`).
- ✅ **Mindmap Extraction**: Automated mindmap generation from PDF content with regex post-processing and indentation normalization.
- ✅ **Session Lifecycle Management**: Endpoints to list sessions (`GET /pdf/sessions`) and delete sessions with associated vector collections (`DELETE /pdf/session/{id}`).
- ✅ **Reflex 0.8+ Frontend**:
  - Full-screen centered modal dialog with drag-and-drop zone and selected file badges.
  - In-modal validation and loading spinners.
  - Reactive immutable state updates ensuring instant sidebar list and chat message rendering.
  - Token refresh handling and seamless session routing.

---

## 🛠️ Tech Stack

### Backend
- **FastAPI**: Modern async web framework with automatic OpenAPI docs.
- **LangChain 0.3+**: Modern LCEL chains for RAG and chat pipelines.
- **LangChain-Ollama 0.3+**: Local LLM orchestration.
- **Pydantic v2**: High-performance request and response validation.

### AI & Embeddings
- **Ollama**: Local model execution (`llama3`, `gemma`, `phi3`).
- **HuggingFace Sentence-Transformers**: `all-MiniLM-L6-v2` for dense embeddings.
- **ChromaDB**: Embedded vector database.

### Storage
- **MongoDB (Motor)**: Async document storage for users, chat sessions, turns, and revoked tokens.
- **Local Filesystem**: Structured multi-tenant PDF file storage (`uploads/{user_id}/{session_id}/{source_id}/`).

### Frontend
- **Reflex 0.8+**: Python full-stack reactive framework with Next.js frontend engine.

---

## 📦 Installation & Setup

### Prerequisites
- **Python 3.10+** (tested on Python 3.12)
- **MongoDB**: Running locally on `localhost:27017` or configured via `MONGODB_URI`
- **Ollama**: Installed and running locally
- **Bun** or **Node.js**: Required by Reflex frontend builder

### 1. Clone & Set Up Environment
```bash
git clone <repository-url>
cd pdf-rag-chatbot-v1

# Create and activate virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Pull Required Ollama Models
Ensure the Ollama service is running (`ollama serve`), then pull the models:
```bash
ollama pull llama3
ollama pull gemma
ollama pull phi3
```

### 4. Configure `.env`
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

# Security & JWT
JWT_SECRET_KEY=your-secure-random-secret-key-here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=True
LOG_DIR=./logs
```

---

## 🏃 Running the Application

### 1. Start External Services
Ensure MongoDB and Ollama are active:
```bash
# Start MongoDB (if not running as a service)
mongod --dbpath /path/to/data

# Start Ollama
ollama serve
```

### 2. Start the FastAPI Backend
```bash
python pdfreader.py
```
- API Server: `http://localhost:8000`
- Interactive OpenAPI Docs: `http://localhost:8000/docs`

### 3. Start the Reflex Frontend
In a separate terminal:
```bash
cd reflex_app
reflex run
```
- Frontend Web Interface: `http://localhost:3000`
- Reflex Internal Backend: `http://localhost:8001`

---

## 🌐 API Endpoints

All endpoints (except `/auth/register` and `/auth/login`) require the Bearer token:
```http
Authorization: Bearer <access_token>
```

### 🔑 Authentication (`/auth`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/register` | Register a new user |
| `POST` | `/auth/login` | Authenticate and obtain access + refresh tokens |
| `POST` | `/auth/refresh` | Refresh access token (revokes used refresh token) |
| `POST` | `/auth/logout` | Revoke tokens and invalidate current session |
| `GET`  | `/auth/profile` | Retrieve authenticated user profile |
| `POST` | `/auth/change-password` | Update account password |
| `POST` | `/auth/verify-token` | Validate token status and claims |

### 📄 PDF & Session Management (`/pdf`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pdf/session` | Create a new chat session |
| `GET`  | `/pdf/sessions` | List user's chat sessions (most recent first) |
| `GET`  | `/pdf/session/{id}` | Retrieve chat session details & message count |
| `DELETE`| `/pdf/session/{id}` | Delete session, uploaded files, and vector collections |
| `POST` | `/pdf/upload` | Upload & index PDF file (`multipart/form-data`) |

### 💬 Chat & RAG (`/chat`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/send` | Send query across single/multiple PDFs with RAG |
| `POST` | `/chat/generate-title` | Auto-generate session title based on conversation |
| `GET`  | `/chat/models` | List available Ollama models |

### 🗺️ Mindmap (`/mindmap`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/mindmap/generate` | Generate mindmap outline from uploaded PDF |

---

## 🧪 Testing

### Unit Tests
Run the pytest suite:
```bash
pytest tests
```

### End-to-End Suite
To run the automated 41-check end-to-end backend verification (testing auth, upload validation, single & multi-PDF RAG, memory retention, mindmap parsing, session deletion, and token revocation):
```bash
python scratch/e2e_test.py
```

---

## 📂 Project Structure

```
pdf-rag-chatbot-v1/
├── pdfreader.py              # Main FastAPI application entry point
├── ai_engine.py              # Core AI operations (RAG, completions, mindmap)
├── chains.py                 # LangChain LCEL chains with history
├── prompts.py                # LLM prompt templates
├── callbacks.py              # Observability and performance callbacks
├── output_parsers.py         # Structured output & mindmap parsing
├── memory_manager.py         # MongoDB conversation memory
├── vectorstore_manager.py    # ChromaDB & offline embeddings management
├── db_manager.py             # MongoDB async CRUD & token revocation
├── auth.py                   # JWT security & password hashing
├── config.py                 # Centralized configuration via Pydantic
├── logging_config.py         # Logging configuration & exception decorators
├── requirements.txt          # Python dependencies
│
├── services/                 # Modular API service routers
│   ├── pdf_service.py        # PDF upload, session listing & cleanup
│   ├── chat_service.py       # Chat & RAG query endpoints
│   ├── mindmap_service.py    # Mindmap generation endpoint
│   ├── models.py             # Pydantic request/response schemas
│   ├── exceptions.py         # Domain exceptions
│   └── utils.py              # Shared service utilities
│
├── tests/                    # Test suite
│   └── test_mindmap_normalizer.py # Mindmap parsing unit tests
│
└── reflex_app/               # Reflex frontend web application
    ├── app/
    │   └── app.py            # Reactive frontend components & state
    └── rxconfig.py           # Reflex project configuration
```

---

## 📄 License

This project is for educational and development purposes.
