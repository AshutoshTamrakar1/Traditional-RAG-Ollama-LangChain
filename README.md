# PDF RAG Chatbot v2.1

An enterprise-grade, production-ready PDF chatbot with **Retrieval-Augmented Generation (RAG)** capabilities. Built with FastAPI, LangChain 0.3+, and local LLMs via Ollama, this system enables intelligent conversations with your PDF documents using multiple AI models, persistent storage in MongoDB & ChromaDB, and a modern reactive Reflex UI.

---

## 🎯 Overview

This chatbot allows users to:
- **Upload and query PDF documents** using natural language with high accuracy and local privacy
- **Multi-document RAG** - Ingest and query across multiple PDFs simultaneously with source attribution
- **Batch PDF Upload** - Centered modal dialog supporting up to 20 files with drag-and-drop and progress tracking
- **Modern Reflex Chat UI** - Rich Markdown rendering, dedicated user & AI message bubbles, custom avatars, centered reading column, and header model selector
- **Session Context Continuity** - Seamlessly switch between past conversations while automatically restoring active document IDs and memory
- **User authentication** - Secure JWT tokens with access & refresh token rotation and token revocation in MongoDB
- **Persistent conversation history** - Stored in MongoDB with sliding window memory for follow-up questions
- **Multiple AI models** - Run local LLMs (`llama3`, `gemma`, `phi3`) via Ollama with zero external API costs
- **Clean Code Architecture** - SonarLint / SonarQube compliant with cognitive complexity <= 15 and modern type annotations

---

## 🏗️ Architecture Design

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend Layer (reflex_app/)                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Reflex Web App                         │  │
│  │  • Rich Markdown Rendering (`rx.markdown`)                │  │
│  │  • Dedicated User (var(--blue-9)) & AI Bubble Cards       │  │
│  │  • User ('U') & AI ('AI') Avatars                         │  │
│  │  • Centered Reading Container (max_width=880px)           │  │
│  │  • Header Model Selector & Batch Upload Modal             │  │
│  │  • Enter-to-Submit Form with Loading Spinners             │  │
│  │  • Active Document & Session Context Restoration          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               ⬇ REST & WebSocket API
┌─────────────────────────────────────────────────────────────────┐
│               API Gateway Layer (backend/pdfreader.py)          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   FastAPI Application                     │  │
│  │  • CORS Middleware  • Global Exception Handler            │  │
│  │  • Lifespan & Logging Setup                               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               ⬇
┌─────────────────────────────────────────────────────────────────┐
│               Service Layer (backend/services/)                 │
│  ┌──────────────────────────────┐  ┌──────────────────────────┐ │
│  │          pdf_service         │  │       chat_service       │ │
│  │  • Batch Upload              │  │  • Multi-PDF RAG         │ │
│  │  • Session Lifecycle         │  │  • Conversation Routing  │ │
│  └──────────────────────────────┘  └──────────────────────────┘ │
│                            ⬇                                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │               Auth Service (backend/auth.py)               │ │
│  │  • JWT Rotation  • Bcrypt Hashing  • JTI Blacklist         │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                               ⬇
┌─────────────────────────────────────────────────────────────────┐
│               Business Logic Layer (backend/)                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    ai_engine.py                           │  │
│  │  • Chat Completion  • Multi-PDF RAG Orchestration        │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  chains.py   │  │ prompts.py   │  │ callbacks.py │         │
│  │ LangChain    │  │ LLM Prompts  │  │ Latency &    │         │
│  │ LCEL Chains  │  │ Templates    │  │ Token Metrics│         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│  ┌──────────────┐  ┌──────────────┐                           │
│  │output_parsers│  │memory_manager│                           │
│  │ Structured   │  │ MongoDB Chat │                           │
│  │ Responses    │  │ History      │                           │
│  └──────────────┘  └──────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                               ⬇
┌─────────────────────────────────────────────────────────────────┐
│                 Data Access Layer (backend/)                    │
│  ┌────────────────────┐        ┌────────────────────┐          │
│  │   db_manager.py    │        │vectorstore_manager │          │
│  │ •Users & Sessions  │        │ •ChromaDB Isolation│          │
│  │ •Revoked Tokens    │        │ •Offline Embeddings│          │
│  └────────────────────┘        └────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                               ⬇
┌─────────────────────────────────────────────────────────────────┐
│                      External Services                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  MongoDB    │  │  ChromaDB   │  │ Ollama LLMs │            │
│  │ •Sessions   │  │ •Vectors    │  │ •llama3     │            │
│  │ •Chat Turns │  │ •Embeddings │  │ •gemma      │            │
│  │ •Blacklist  │  │ •Collections│  │ •phi3       │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Features & Recent Improvements

### Modern Chat UI
- **Rich Markdown AI Responses**: AI output is compiled with `rx.markdown`, cleanly displaying headers (`## Topic`), bulleted lists, numbered lists, tables, bold text, and code blocks.
- **Visual Separation with Avatars**:
  - User messages appear on the right in solid accent bubbles with an avatar badge (`U`).
  - AI responses appear on the left in structured surface cards with an AI avatar badge (`AI`).
- **Optimal Reading Layout**: A centered `max_width="880px"` chat container ensures readable text line lengths regardless of screen size.
- **Clean Header Controls**: Model selector dropdown and PDF upload trigger are consolidated into the top header, freeing vertical chat space.
- **Keyboard Submission**: Full <kbd>Enter</kbd> key support via `rx.form` with real-time loading feedback and Lucide send icon.

### Core Capabilities
- ✅ **Secure Multi-User Auth**: JWT-based access & refresh tokens with JTI tracking and MongoDB TTL token blacklisting upon logout.
- ✅ **PDF Ingestion & Validation**: Strict validation verifying `.pdf` extension, `%PDF-` magic bytes, and path traversal security.
- ✅ **Batch Uploading**: Drag and drop up to 20 PDF documents at once in a modal dialog.
- ✅ **Semantic Search**: Fast, local embeddings using `all-MiniLM-L6-v2` with offline-first caching (`local_files_only: True`) to eliminate remote HF latency.
- ✅ **Isolated Collections**: Vectorstore collections keyed by unique `source_id` to prevent document collisions across users and sessions.
- ✅ **Conversational RAG Memory**: Follow-up queries retain conversational context via sliding window memory within LCEL chains.
- ✅ **Multi-Document RAG**: Query across multiple PDFs simultaneously with model selection support (`llama3`, `gemma`, `phi3`).
- ✅ **Session Context Restoration**: Restores active document IDs and conversation history seamlessly when switching chats from the sidebar.
- ✅ **SonarQube / SonarLint Compliant**: Clean code architecture with cognitive complexity <= 15 across all functions, `typing.Annotated` dependencies, and timezone-aware UTC dates.

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
- **Local Filesystem**: Structured multi-tenant PDF file storage (`backend/uploads/{user_id}/{session_id}/{source_id}/`).

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
pip install -r backend/requirements.txt
```

### 3. Pull Required Ollama Models
Ensure the Ollama service is running (`ollama serve`), then pull the models:
```bash
ollama pull llama3
ollama pull gemma
ollama pull phi3
```

### 4. Configure `.env`
Create a `.env` file in the `backend/` directory (or project root):
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
cd backend
python pdfreader.py
```
*(Alternatively: `python -m uvicorn backend.pdfreader:app --reload --port 8000` from the root directory)*
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
| `POST` | `/auth/refresh` | Refresh access token (rotates refresh token) |
| `POST` | `/auth/logout` | Revoke tokens and blacklist JTI in MongoDB |
| `GET`  | `/auth/profile` | Retrieve authenticated user profile |
| `POST` | `/auth/change-password` | Update account password |
| `POST` | `/auth/verify-token` | Validate token status and claims |

### 📄 PDF & Session Management (`/pdf`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pdf/session` | Create a new chat session |
| `GET`  | `/pdf/sessions` | List user's chat sessions (most recent first) |
| `GET`  | `/pdf/session/{id}` | Retrieve chat session details, sources & turns |
| `DELETE`| `/pdf/session/{id}` | Delete session, uploaded files, and vector collections |
| `POST` | `/pdf/upload` | Upload & index PDF file (`multipart/form-data`) |

### 💬 Chat & RAG (`/chat`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/send` | Send query across single/multiple PDFs with RAG |
| `POST` | `/chat/generate-title` | Auto-generate session title based on conversation |
| `GET`  | `/chat/models` | List available Ollama models |

---

## 🧪 Testing

### Unit Tests
Run the pytest suite:
```bash
pytest tests
```

### End-to-End Suite
To run the automated end-to-end backend verification (testing auth, upload validation, single & multi-PDF RAG, memory retention, session deletion, and token revocation):
```bash
python scratch/e2e_test.py
```

---

## 📂 Project Structure

```
pdf-rag-chatbot-v1/
├── backend/                       # Dedicated backend application directory
│   ├── pdfreader.py               # Main FastAPI application entry point
│   ├── ai_engine.py               # Core AI operations (RAG, completions)
│   ├── chains.py                  # LangChain LCEL chains with history
│   ├── prompts.py                 # LLM prompt templates
│   ├── callbacks.py               # Observability and performance callbacks
│   ├── output_parsers.py          # Structured output parsing
│   ├── memory_manager.py          # MongoDB conversation memory
│   ├── vectorstore_manager.py     # ChromaDB & offline embeddings management
│   ├── db_manager.py              # MongoDB async CRUD & token revocation
│   ├── auth.py                    # JWT security & password hashing
│   ├── config.py                  # Centralized configuration via Pydantic
│   ├── logging_config.py          # Logging configuration & exception decorators
│   ├── requirements.txt           # Backend dependencies
│   │
│   ├── services/                  # Modular API service routers
│   │   ├── pdf_service.py         # PDF upload, session listing & cleanup
│   │   ├── chat_service.py        # Chat & RAG query endpoints
│   │   ├── models.py              # Pydantic request/response schemas
│   │   ├── exceptions.py          # Domain exceptions
│   │   └── utils.py               # Shared service utilities
│   │
│   ├── uploads/                   # User-uploaded PDF documents (multi-tenant)
│   ├── chroma_db/                 # Persistent ChromaDB vector collections
│   └── logs/                      # Log files
│
├── reflex_app/                    # Reflex frontend web application
│   ├── app/
│   │   └── app.py                 # Reactive UI components, markdown & state
│   └── rxconfig.py                # Reflex project configuration
│
├── tests/                         # Automated test suite
│
├── ARCHITECTURE.md                # System Architecture & Technical Specifications
└── README.md                      # Project documentation and setup guide
```

---

## 📄 License

This project is for educational and development purposes.
