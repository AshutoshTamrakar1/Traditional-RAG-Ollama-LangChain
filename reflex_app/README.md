# Reflex UI - Traditional RAG with Ollama and LangChain

## Features
- User authentication (JWT login & register)
- Multi-PDF batch upload (up to 20 files) and selection
- Traditional dense RAG chat interface with local Ollama models (`llama3`, `gemma`, `phi3`)
- Rich Markdown rendering for AI responses
- Active session switching with context and document restoration

## How to Run
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the Reflex app:
   ```bash
   reflex init
   reflex run
   ```
3. Make sure your FastAPI backend is running at `http://localhost:8000`.

## Notes
- Update `BACKEND_URL` in `app.py` if your backend runs on a different address.
- The web app will be available at `http://localhost:3000` by default.
