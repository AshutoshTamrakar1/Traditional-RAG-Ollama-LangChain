import reflex as rx
import httpx
from typing import List, Dict
import asyncio

BACKEND_URL = "http://localhost:8000"

# Shared authentication data (simple approach for state sharing)
class SharedAuth(rx.Base):
    access_token: str = ""
    refresh_token: str = ""
    user_id: str = ""

class AuthState(rx.State):
    username: str = ""
    password: str = ""
    email: str = ""
    confirm_password: str = ""
    access_token: str = ""
    refresh_token: str = ""
    user_id: str = ""
    error: str = ""
    success: str = ""
    
    async def login(self):
        """Login user via backend API"""
        print(f"[LOGIN] Attempting login for email: {self.email}")
        self.error = ""
        self.success = ""
        
        email = self.email.strip()
        password = self.password.strip()
        if not email or not password:
            self.error = "Email and password are required"
            print(f"[LOGIN ERROR] {self.error}")
            return
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print(f"[LOGIN] Sending request to {BACKEND_URL}/auth/login")
                response = await client.post(
                    f"{BACKEND_URL}/auth/login",
                    json={"email": email.lower(), "password": password}
                )
                
                print(f"[LOGIN] Response status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    # JWT auth: backend returns access_token, refresh_token, and user_id
                    self.access_token = data["access_token"]
                    self.refresh_token = data["refresh_token"]
                    self.user_id = data["user_id"]
                    self.success = "Login successful!"
                    print(f"[LOGIN SUCCESS] User {self.user_id} logged in, token: {self.access_token[:20]}...")
                    
                    # Redirect with auth info in URL (will be picked up by MainState)
                    yield rx.redirect(f"/chat?access_token={self.access_token}&refresh_token={self.refresh_token}&user_id={self.user_id}")
                else:
                    error_data = response.json()
                    self.error = error_data.get("detail", "Login failed")
                    print(f"[LOGIN ERROR] {self.error}")
        except Exception as e:
            self.error = f"Connection error: {str(e)}"
            print(f"[LOGIN EXCEPTION] {e}")
    
    async def register(self):
        """Register new user via backend API"""
        print(f"[REGISTER] Attempting registration for email: {self.email}")
        self.error = ""
        self.success = ""
        
        email = self.email.strip().lower()
        username = self.username.strip()
        password = self.password.strip()
        confirm_password = self.confirm_password.strip()
        if not email or not username or not password or not confirm_password:
            self.error = "All fields are required"
            print(f"[REGISTER ERROR] {self.error}")
            return
        
        if password != confirm_password:
            self.error = "Passwords do not match"
            print(f"[REGISTER ERROR] {self.error}")
            return
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print(f"[REGISTER] Sending request to {BACKEND_URL}/auth/register")
                response = await client.post(
                    f"{BACKEND_URL}/auth/register",
                    json={
                        "email": email,
                        "username": username,
                        "password": password,
                        "confirm_password": confirm_password
                    }
                )
                
                print(f"[REGISTER] Response status: {response.status_code}")
                if response.status_code == 201:
                    data = response.json()
                    # JWT auth: registration also returns tokens
                    self.access_token = data.get("access_token", "")
                    self.refresh_token = data.get("refresh_token", "")
                    self.user_id = data.get("user_id", "")
                    self.success = f"Registration successful! Welcome {data['username']}"
                    print(f"[REGISTER SUCCESS] User {data['user_id']} registered")
                    # Clear form
                    self.email = ""
                    self.username = ""
                    self.password = ""
                    self.confirm_password = ""
                    # Redirect to chat with auth tokens
                    if self.access_token:
                        yield rx.redirect(f"/chat?access_token={self.access_token}&refresh_token={self.refresh_token}&user_id={self.user_id}")
                    else:
                        # Fallback to login page if no tokens
                        yield rx.call_script("setTimeout(() => window.location.href = '/', 2000)")
                else:
                    error_data = response.json()
                    self.error = error_data.get("detail", "Registration failed")
                    print(f"[REGISTER ERROR] {self.error}")
        except Exception as e:
            self.error = f"Connection error: {str(e)}"
            print(f"[REGISTER EXCEPTION] {e}")


class MainState(rx.State):
    # Authentication - JWT tokens
    access_token: str = ""
    refresh_token: str = ""
    user_id: str = ""
    
    # Chat sessions
    chat_sessions: list[dict] = []
    current_chat_id: str = ""
    current_chat_title: str = "New Chat"
    
    # Messages
    messages: list[dict] = []
    user_input: str = ""
    
    # PDFs
    uploaded_pdfs: list[dict] = []
    active_source_ids: list[str] = []
    
    # Mindmap
    show_mindmap: bool = False
    mindmap_markdown: str = ""
    mindmap_loading: bool = False
    selected_pdf_for_mindmap: str = ""
    mindmap_items: list[dict[str, str]] = []
    expanded_nodes: list[str] = []
    
    # UI state
    error: str = ""
    is_loading: bool = False
    show_upload: bool = False
    
    # Model selection
    available_models: list[str] = []
    selected_model: str = "llama3"
    
    def get_auth_headers(self) -> dict:
        """Get Authorization header with Bearer token for API requests"""
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}
    
    async def refresh_access_token(self) -> bool:
        """Refresh access token using refresh token. Returns True if successful."""
        if not self.refresh_token:
            print("[REFRESH] No refresh token available")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print(f"[REFRESH] Refreshing access token")
                response = await client.post(
                    f"{BACKEND_URL}/auth/refresh",
                    headers={"Authorization": f"Bearer {self.refresh_token}"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    self.refresh_token = data.get("refresh_token", self.refresh_token)
                    print(f"[REFRESH SUCCESS] Token refreshed")
                    return True
                else:
                    print(f"[REFRESH ERROR] Failed with status {response.status_code}")
                    # Refresh token expired or invalid, redirect to login
                    self.access_token = ""
                    self.refresh_token = ""
                    self.user_id = ""
                    return False
        except Exception as e:
            print(f"[REFRESH EXCEPTION] {e}")
            return False
    
    def set_auth_from_login(self, access_token: str, refresh_token: str, user_id: str):
        """Called to set auth data from login page (JWT auth)"""
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_id = user_id
        print(f"[MAIN] Auth set - access_token: {self.access_token[:20]}...")
    
    async def on_load(self):
        """Load user data when chat page loads"""
        print("[MAIN] Loading chat page...")
        
        # Get auth from URL query params (passed from login)
        if self.router.page.params:
            new_access_token = self.router.page.params.get("access_token", "")
            if new_access_token and new_access_token != self.access_token:
                # New login detected - clear old state
                print(f"[MAIN] New login detected, clearing old state")
                self.access_token = new_access_token
                self.refresh_token = self.router.page.params.get("refresh_token", "")
                self.user_id = self.router.page.params.get("user_id", "")
                self.current_chat_id = ""  # Clear old chat
                self.messages = []
                self.chat_sessions = []
                self.uploaded_pdfs = []
                self.active_source_ids = []
                print(f"[MAIN] Auth loaded from URL params - access_token: {self.access_token[:20]}...")
        
        # Load available models
        await self.load_available_models()
        
        print(f"[MAIN] Current auth - access_token: {self.access_token[:20] if self.access_token else 'None'}...")
        
        # If no access token, user needs to login
        if not self.access_token:
            print("[MAIN] No access token, redirecting to login")
            yield rx.redirect("/")
            return
        
        # Create initial chat session if none exists
        if not self.current_chat_id:
            print("[MAIN] Creating initial chat session")
            # Use async for to handle generator
            async for _ in self.create_new_chat():
                pass
    
    async def create_new_chat(self):
        """Create a new chat session"""
        print("[CREATE_CHAT] Creating new chat session")
        self.error = ""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print(f"[CREATE_CHAT] Sending request to {BACKEND_URL}/pdf/session")
                response = await client.post(
                    f"{BACKEND_URL}/pdf/session",
                    headers=self.get_auth_headers()
                )
                
                print(f"[CREATE_CHAT] Response status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    self.current_chat_id = data["chat_session_id"]
                    self.current_chat_title = data.get("title", "New Chat")
                    self.messages = []
                    self.uploaded_pdfs = []
                    self.active_source_ids = []
                    
                    # Add to sessions list (use chat_session_id key)
                    self.chat_sessions.append({
                        "chat_session_id": self.current_chat_id,
                        "title": self.current_chat_title
                    })
                    print(f"[CREATE_CHAT SUCCESS] Created chat session: {self.current_chat_id}")
                elif response.status_code == 401:
                    # Token expired, try to refresh
                    print("[CREATE_CHAT] Token expired, attempting refresh...")
                    if await self.refresh_access_token():
                        # Retry with new token
                        await self.create_new_chat()
                    else:
                        # Refresh failed, redirect to login
                        self.error = "Session expired. Please log in again."
                        print("[CREATE_CHAT ERROR] Token refresh failed")
                        yield rx.redirect("/")
                else:
                    self.error = "Failed to create chat session"
                    print(f"[CREATE_CHAT ERROR] {self.error}")
        except Exception as e:
            self.error = f"Error creating chat: {str(e)}"
            print(f"[CREATE_CHAT EXCEPTION] {e}")
    
    async def upload_pdf(self, files: list):
        """Upload PDF file"""
        print(f"[UPLOAD] Uploading {len(files)} file(s)")
        self.error = ""
        self.is_loading = True
        
        if not files:
            self.error = "No file selected"
            self.is_loading = False
            return
        
        # Ensure an active chat session exists before uploading
        if not self.current_chat_id:
            print("[UPLOAD] No active chat session, creating one first...")
            await self.create_new_chat()
            if not self.current_chat_id:
                self.error = "Please start a chat session before uploading"
                self.is_loading = False
                return
        
        try:
            file = files[0]
            raw_filename = getattr(file, "filename", None) or getattr(file, "name", None) or ""
            # Strip directory prefixes for cross-platform safety
            filename = raw_filename.replace("\\", "/").split("/")[-1]
            if not filename or not filename.lower().endswith(".pdf"):
                filename = (filename or "document") + ".pdf"
            print(f"[UPLOAD] Processing file: {filename}")
            
            # Read file content
            file_data = await file.read() if hasattr(file, 'read') else file
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                files_data = {
                    "file": (filename, file_data, "application/pdf")
                }
                form_data = {
                    "chat_session_id": self.current_chat_id
                }
                
                print(f"[UPLOAD] Sending to {BACKEND_URL}/pdf/upload")
                response = await client.post(
                    f"{BACKEND_URL}/pdf/upload",
                    headers=self.get_auth_headers(),
                    data=form_data,
                    files=files_data
                )
                
                print(f"[UPLOAD] Response status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    new_source = data["new_source"]
                    self.uploaded_pdfs = [*self.uploaded_pdfs, new_source]
                    self.active_source_ids = [*self.active_source_ids, new_source["source_id"]]
                    
                    # Update title if changed
                    if data.get("new_title"):
                        self.current_chat_title = data["new_title"]
                    
                    self.show_upload = False
                    self.error = ""
                    print(f"[UPLOAD SUCCESS] PDF uploaded: {new_source['filename']}")
                elif response.status_code == 401:
                    # Token expired, try to refresh
                    print("[UPLOAD] Token expired, attempting refresh...")
                    if await self.refresh_access_token():
                        # Retry upload
                        await self.upload_pdf(files)
                    else:
                        self.error = "Session expired. Please log in again."
                        print("[UPLOAD ERROR] Token refresh failed")
                else:
                    detail = ""
                    try:
                        detail = response.json().get("detail", "")
                    except Exception:
                        pass
                    self.error = f"Upload failed: {detail}" if detail else "Upload failed"
                    print(f"[UPLOAD ERROR] {self.error}")
        except Exception as e:
            self.error = f"Upload error: {str(e)}"
            print(f"[UPLOAD EXCEPTION] {e}")
        finally:
            self.is_loading = False
    
    async def generate_mindmap(self, source_id: str):
        """Generate mindmap from PDF"""
        print(f"[MINDMAP] Generating mindmap for source: {source_id}")
        self.mindmap_loading = True
        self.error = ""
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                payload = {
                    "chat_session_id": self.current_chat_id,
                    "source_id": source_id
                }
                
                print(f"[MINDMAP] Sending request to {BACKEND_URL}/mindmap/generate")
                response = await client.post(
                    f"{BACKEND_URL}/mindmap/generate",
                    headers=self.get_auth_headers(),
                    json=payload
                )
                
                print(f"[MINDMAP] Response status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    self.mindmap_markdown = data["markdown"]
                    self.parse_mindmap_text(self.mindmap_markdown)
                    self.show_mindmap = True
                    self.selected_pdf_for_mindmap = source_id
                    print(f"[MINDMAP SUCCESS] Generated {len(self.mindmap_markdown)} chars")
                elif response.status_code == 401:
                    # Token expired, try to refresh
                    print("[MINDMAP] Token expired, attempting refresh...")
                    if await self.refresh_access_token():
                        # Retry mindmap generation
                        await self.generate_mindmap(source_id)
                    else:
                        self.error = "Session expired. Please log in again."
                        print("[MINDMAP ERROR] Token refresh failed")
                else:
                    self.error = f"Mindmap generation failed: {response.text}"
                    print(f"[MINDMAP ERROR] {self.error}")
        except Exception as e:
            self.error = f"Mindmap error: {str(e)}"
            print(f"[MINDMAP EXCEPTION] {e}")
        finally:
            self.mindmap_loading = False
    
    async def generate_mindmap_from_active_pdfs(self):
        """Generate mindmap from the first uploaded PDF in current chat"""
        print(f"[MINDMAP] Generating mindmap from active PDFs")
        
        if not self.uploaded_pdfs:
            self.error = "Please upload a PDF first"
            return
        
        # Use the first uploaded PDF
        first_pdf = self.uploaded_pdfs[0]
        source_id = first_pdf.get("source_id")
        
        if not source_id:
            self.error = "No valid PDF source found"
            return
        
        # Call the existing generate_mindmap function
        await self.generate_mindmap(source_id)
    
    def parse_mindmap_text(self, text: str):
        """Parse mindmap text into hierarchical list with parent-child relationships"""
        lines = text.strip().split('\n')
        items = []
        current_id = 0
        stack = []  # Stack to track parent IDs at each level
        
        for line in lines:
            if not line.strip() or line.strip().startswith('mindmap'):
                continue
            
            # Detect indent level
            stripped = line.lstrip()
            indent = (len(line) - len(stripped)) // 2  # Normalize to 0, 1, 2, 3...
            text_content = stripped.strip()
            
            # Skip if empty
            if not text_content:
                continue
            
            # Extract root title
            if 'root((' in text_content:
                title = text_content.split('((')[1].split('))')[0] if '((' in text_content else text_content
                items.append({
                    "id": "root",
                    "title": title,
                    "level": "0",
                    "parent_id": "",
                    "has_children": "false"
                })
                stack = [(0, "root")]  # (indent_level, node_id)
                continue
            
            # Create item
            current_id += 1
            item_id = f"node_{current_id}"
            
            # Find parent based on indentation
            while stack and stack[-1][0] >= indent:
                stack.pop()
            
            parent_id = stack[-1][1] if stack else ""
            
            items.append({
                "id": item_id,
                "title": text_content.replace(':', ' -'),
                "level": str(indent),
                "parent_id": parent_id,
                "has_children": "false"  # Will be updated
            })
            
            # Mark parent as having children
            if parent_id:
                for item in items:
                    if item["id"] == parent_id:
                        item["has_children"] = "true"
                        break
            
            stack.append((indent, item_id))
        
        self.mindmap_items = items
        self.expanded_nodes = ["root"]  # Start with root expanded
    
    def toggle_node(self, node_id: str):
        """Toggle expand/collapse state of a node"""
        if node_id in self.expanded_nodes:
            self.expanded_nodes.remove(node_id)
        else:
            self.expanded_nodes.append(node_id)
    
    def toggle_mindmap(self):
        """Toggle mindmap modal"""
        self.show_mindmap = not self.show_mindmap
        if not self.show_mindmap:
            self.mindmap_markdown = ""
            self.selected_pdf_for_mindmap = ""
            self.mindmap_items = []
            self.expanded_nodes = []
    
    async def handle_upload(self, files: list[rx.UploadFile]):
        """Handle file upload from rx.upload component"""
        print(f"[HANDLE_UPLOAD] Files received: {files}")
        await self.upload_pdf(files)
        return rx.clear_selected_files("pdf_upload")
    
    async def send_message(self):
        """Send chat message"""
        print(f"[SEND_MSG] Sending message: {self.user_input[:50]}...")
        
        if not self.user_input.strip():
            print("[SEND_MSG] Empty message, skipping")
            return
        
        self.error = ""
        user_msg = self.user_input
        self.user_input = ""
        
        # Add user message to UI immediately
        self.messages = [*self.messages, {"role": "user", "content": user_msg}]
        self.is_loading = True
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Convert active_source_ids to plain list to avoid serialization issues
                source_ids = list(self.active_source_ids) if self.active_source_ids else []
                
                payload = {
                    "chat_session_id": self.current_chat_id,
                    "user_input": user_msg,
                    "active_source_ids": source_ids,
                    "model": self.selected_model
                }
                
                print(f"[SEND_MSG] Payload: {payload}")
                print(f"[SEND_MSG] Sending to {BACKEND_URL}/chat/send")
                
                response = await client.post(
                    f"{BACKEND_URL}/chat/send",
                    headers=self.get_auth_headers(),
                    json=payload
                )
                
                print(f"[SEND_MSG] Response status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    assistant_msg = data["answer"]
                    self.messages = [*self.messages, {"role": "assistant", "content": assistant_msg}]
                    print(f"[SEND_MSG SUCCESS] Got response: {assistant_msg[:50]}...")
                    
                    # Refresh chat title if this was the first message
                    if self.current_chat_title == "New Chat" and len(self.messages) == 2:
                        await self.refresh_chat_title()
                elif response.status_code == 401:
                    # Token expired, try to refresh
                    print("[SEND_MSG] Token expired, attempting refresh...")
                    if await self.refresh_access_token():
                        # Retry send message
                        self.user_input = user_msg  # Restore message
                        await self.send_message()
                    else:
                        self.error = "Session expired. Please log in again."
                        print("[SEND_MSG ERROR] Token refresh failed")
                else:
                    error_data = response.json()
                    self.error = error_data.get("detail", "Failed to send message")
                    print(f"[SEND_MSG ERROR] {self.error}")
        except Exception as e:
            self.error = f"Error: {str(e)}"
            print(f"[SEND_MSG EXCEPTION] {e}")
        finally:
            self.is_loading = False
    
    def toggle_upload(self):
        """Toggle upload modal"""
        self.show_upload = not self.show_upload
        print(f"[UI] Upload modal: {self.show_upload}")
    
    async def load_available_models(self):
        """Load available chat models from backend"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{BACKEND_URL}/chat/models")
                if response.status_code == 200:
                    data = response.json()
                    self.available_models = data.get("models", ["llama3", "gemma", "phi3"])
                    self.selected_model = data.get("default", "llama3")
                    print(f"[MODELS] Loaded: {self.available_models}")
        except Exception as e:
            print(f"[MODELS ERROR] {e}")
            self.available_models = ["llama3", "gemma", "phi3"]
    
    def set_model(self, model: str):
        """Set selected chat model"""
        self.selected_model = model
        print(f"[MODEL] Selected: {model}")
    
    async def logout(self):
        """Logout user and invalidate JWT tokens on backend"""
        print(f"[LOGOUT] Logging out user")
        
        # Call backend to invalidate tokens (optional - JWT is stateless)
        if self.access_token:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        f"{BACKEND_URL}/auth/logout",
                        headers=self.get_auth_headers(),
                        json={"refresh_token": self.refresh_token or None}
                    )
                    print(f"[LOGOUT] Backend response: {response.status_code}")
            except Exception as e:
                print(f"[LOGOUT ERROR] {e}")
        
        # Clear frontend state
        self.access_token = ""
        self.refresh_token = ""
        self.user_id = ""
        self.current_chat_id = ""
        self.messages = []
        self.chat_sessions = []
        self.uploaded_pdfs = []
        self.active_source_ids = []
        return rx.redirect("/")
    
    async def refresh_chat_title(self):
        """Fetch updated chat title from backend"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{BACKEND_URL}/pdf/session/{self.current_chat_id}",
                    headers=self.get_auth_headers()
                )
                if response.status_code == 200:
                    data = response.json()
                    new_title = data.get("title", "New Chat")
                    if new_title != "New Chat":
                        self.current_chat_title = new_title
                        # Update in sessions list
                        for session in self.chat_sessions:
                            if session.get("chat_session_id") == self.current_chat_id:
                                session["title"] = new_title
                        print(f"[TITLE] Updated to: {new_title}")
                elif response.status_code == 401:
                    # Token expired, try to refresh
                    print("[TITLE] Token expired, attempting refresh...")
                    if await self.refresh_access_token():
                        # Retry
                        await self.refresh_chat_title()
        except Exception as e:
            print(f"[TITLE ERROR] {e}")


def render_mindmap_item(item: dict) -> rx.Component:
    """Render a single mindmap item as a tree node with expand/collapse"""
    # Determine indentation based on level
    indent_px = rx.cond(
        item["level"] == "0", "0px",
        rx.cond(item["level"] == "1", "20px",
        rx.cond(item["level"] == "2", "40px",
        rx.cond(item["level"] == "3", "60px", "80px")))
    )
    
    # Color coding based on level
    return rx.cond(
        item["level"] == "0",
        # Level 0 (root) - Blue
        rx.vstack(
            rx.hstack(
                rx.cond(
                    item["has_children"] == "true",
                    rx.button(
                        rx.cond(
                            MainState.expanded_nodes.contains(item["id"]),
                            "▼",
                            "▶"
                        ),
                        on_click=lambda id=item["id"]: MainState.toggle_node(id),
                        size="1",
                        variant="ghost",
                        color="blue.700",
                    ),
                    rx.box(width="20px"),
                ),
                rx.box(
                    rx.text(item["title"], font_weight="700", font_size="1.3em", color="black"),
                    padding="0.6em 1.2em",
                    bg="blue.200",
                    border_radius="0.5em",
                    border="2px solid var(--blue-700)",
                    flex="1",
                ),
                width="100%",
                align="center",
                margin_left=indent_px,
            ),
            width="100%",
            spacing="1",
        ),
        rx.cond(
            item["level"] == "1",
            # Level 1 - Green
            rx.cond(
                (MainState.expanded_nodes.contains(item["parent_id"])) | (item["parent_id"] == ""),
                rx.vstack(
                    rx.hstack(
                        rx.cond(
                            item["has_children"] == "true",
                            rx.button(
                                rx.cond(
                                    MainState.expanded_nodes.contains(item["id"]),
                                    "▼",
                                    "▶"
                                ),
                                on_click=lambda id=item["id"]: MainState.toggle_node(id),
                                size="1",
                                variant="ghost",
                                color="green.700",
                            ),
                            rx.box(width="20px"),
                        ),
                        rx.box(
                            rx.text(item["title"], font_weight="600", font_size="1.1em", color="black"),
                            padding="0.5em 1em",
                            bg="green.100",
                            border_radius="0.5em",
                            border_left="4px solid var(--green-600)",
                            flex="1",
                        ),
                        width="100%",
                        align="center",
                        margin_left=indent_px,
                    ),
                    width="100%",
                    spacing="1",
                ),
                rx.box(),  # Hidden if parent not expanded
            ),
            rx.cond(
                item["level"] == "2",
                # Level 2 - Purple
                rx.cond(
                    MainState.expanded_nodes.contains(item["parent_id"]),
                    rx.vstack(
                        rx.hstack(
                            rx.cond(
                                item["has_children"] == "true",
                                rx.button(
                                    rx.cond(
                                        MainState.expanded_nodes.contains(item["id"]),
                                        "▼",
                                        "▶"
                                    ),
                                    on_click=lambda id=item["id"]: MainState.toggle_node(id),
                                    size="1",
                                    variant="ghost",
                                    color="purple.700",
                                ),
                                rx.box(width="20px"),
                            ),
                            rx.box(
                                rx.text(item["title"], font_weight="500", font_size="1.0em", color="black"),
                                padding="0.4em 0.9em",
                                bg="purple.50",
                                border_radius="0.5em",
                                border_left="4px solid var(--purple-500)",
                                flex="1",
                            ),
                            width="100%",
                            align="center",
                            margin_left=indent_px,
                        ),
                        width="100%",
                        spacing="1",
                    ),
                    rx.box(),  # Hidden if parent not expanded
                ),
                # Level 3+ - Orange
                rx.cond(
                    MainState.expanded_nodes.contains(item["parent_id"]),
                    rx.vstack(
                        rx.hstack(
                            rx.cond(
                                item["has_children"] == "true",
                                rx.button(
                                    rx.cond(
                                        MainState.expanded_nodes.contains(item["id"]),
                                        "▼",
                                        "▶"
                                    ),
                                    on_click=lambda id=item["id"]: MainState.toggle_node(id),
                                    size="1",
                                    variant="ghost",
                                    color="orange.700",
                                ),
                                rx.box(width="20px"),
                            ),
                            rx.box(
                                rx.text(item["title"], font_weight="500", font_size="0.95em", color="black"),
                                padding="0.4em 0.8em",
                                bg="orange.50",
                                border_radius="0.4em",
                                border_left="3px solid var(--orange-500)",
                                flex="1",
                            ),
                            width="100%",
                            align="center",
                            margin_left=indent_px,
                        ),
                        width="100%",
                        spacing="1",
                    ),
                    rx.box(),  # Hidden if parent not expanded
                ),
            ),
        ),
    )


def login_page():
    return rx.container(
        rx.vstack(
            rx.heading("Login", size="9"),
            rx.input(
                placeholder="Email",
                value=AuthState.email,
                on_change=AuthState.set_email,
            ),
            rx.input(
                placeholder="Password",
                type="password",
                value=AuthState.password,
                on_change=AuthState.set_password,
            ),
            rx.button("Login", on_click=AuthState.login),
            rx.text(AuthState.success, color="green"),
            rx.text(AuthState.error, color="red"),
            rx.text("Don't have an account?"),
            rx.button("Register", on_click=lambda: rx.redirect("/register")),
            spacing="4",
            align="center",
        ),
        padding="4em",
    )

def register_page():
    return rx.container(
        rx.vstack(
            rx.heading("Register", size="9"),
            rx.input(
                placeholder="Email",
                value=AuthState.email,
                on_change=AuthState.set_email,
            ),
            rx.input(
                placeholder="Username",
                value=AuthState.username,
                on_change=AuthState.set_username,
            ),
            rx.input(
                placeholder="Password",
                type="password",
                value=AuthState.password,
                on_change=AuthState.set_password,
            ),
            rx.input(
                placeholder="Confirm Password",
                type="password",
                value=AuthState.confirm_password,
                on_change=AuthState.set_confirm_password,
            ),
            rx.button("Register", on_click=AuthState.register),
            rx.text(AuthState.success, color="green"),
            rx.text(AuthState.error, color="red"),
            rx.text("Already have an account?"),
            rx.button("Login", on_click=lambda: rx.redirect("/")),
            spacing="4",
            align="center",
        ),
        padding="4em",
    )

def chat_page():
    """Main chat interface with sidebar"""
    return rx.box(
        # Sidebar
        rx.box(
            rx.vstack(
                rx.heading("Chats", size="6"),
                rx.button(
                    "+ New Chat",
                    on_click=MainState.create_new_chat,
                    width="100%"
                ),
                rx.divider(),
                rx.foreach(
                    MainState.chat_sessions,
                    lambda session: rx.box(
                        rx.text(session["title"]),
                        padding="0.5em",
                        _hover={"bg": "gray.100", "cursor": "pointer"},
                    )
                ),
                rx.spacer(),
                rx.divider(),
                rx.text("Uploaded PDFs:", font_weight="bold", size="2"),
                rx.foreach(
                    MainState.uploaded_pdfs,
                    lambda pdf: rx.box(
                        rx.hstack(
                            rx.text(pdf["filename"], size="1", flex="1"),
                            rx.button(
                                "🗺️",
                                size="1",
                                on_click=lambda: MainState.generate_mindmap(pdf["source_id"]),
                                title="Generate Mindmap",
                            ),
                            spacing="1",
                            width="100%",
                        ),
                        padding="0.25em",
                        bg="blue.50",
                        border_radius="0.25em",
                        margin="0.25em 0",
                    )
                ),
                rx.divider(),
                rx.button(
                    "Logout",
                    on_click=MainState.logout,
                    width="100%",
                    color_scheme="red",
                    variant="outline"
                ),
                spacing="2",
                width="100%",
                height="100%",
            ),
            width="250px",
            height="100vh",
            bg="gray.50",
            padding="1em",
            position="fixed",
            left="0",
            top="0",
            display="flex",
            flex_direction="column",
        ),
        # Main chat area
        rx.box(
            rx.vstack(
                # Header
                rx.hstack(
                    rx.heading(MainState.current_chat_title, size="7"),
                    rx.spacer(),
                    rx.button(
                        "📎 Upload PDF",
                        on_click=MainState.toggle_upload,
                    ),
                    width="100%",
                    padding="1em",
                    border_bottom="1px solid #e2e8f0",
                ),
                # Messages
                rx.box(
                    rx.foreach(
                        MainState.messages,
                        lambda msg: rx.box(
                            rx.text(
                                msg["content"],
                                bg=rx.cond(
                                    msg["role"] == "user",
                                    "blue.100",
                                    "gray.100"
                                ),
                                padding="1em",
                                border_radius="0.5em",
                                max_width="70%",
                                margin_left=rx.cond(
                                    msg["role"] == "user",
                                    "auto",
                                    "0"
                                ),
                            ),
                            width="100%",
                            padding="0.5em",
                        )
                    ),
                    flex="1",
                    overflow_y="auto",
                    padding="1em",
                    width="100%",
                ),
                # Error message
                rx.cond(
                    MainState.error != "",
                    rx.text(MainState.error, color="red", padding="0.5em"),
                ),
                # Model selector and mindmap button
                rx.hstack(
                    rx.text("Model:", font_weight="500"),
                    rx.select(
                        MainState.available_models,
                        value=MainState.selected_model,
                        on_change=MainState.set_model,
                    ),
                    rx.spacer(),
                    rx.button(
                        "Generate Mindmap",
                        on_click=MainState.generate_mindmap_from_active_pdfs,
                        is_loading=MainState.mindmap_loading,
                        is_disabled=MainState.uploaded_pdfs.length() == 0,
                        color_scheme="blue",
                        size="2",
                    ),
                    padding="0.5em 1em",
                    spacing="2",
                    border_top="1px solid #e2e8f0",
                    width="100%",
                    align="center",
                ),
                # Input area
                rx.hstack(
                    rx.input(
                        placeholder="Type your message...",
                        value=MainState.user_input,
                        on_change=MainState.set_user_input,
                        flex="1",
                    ),
                    rx.button(
                        "Send",
                        on_click=MainState.send_message,
                        is_loading=MainState.is_loading,
                    ),
                    width="100%",
                    padding="1em",
                    border_top="1px solid #e2e8f0",
                ),
                height="100vh",
                width="100%",
                spacing="0",
            ),
            margin_left="250px",
        ),
        # Upload modal
        rx.cond(
            MainState.show_upload,
            rx.box(
                rx.box(
                    rx.vstack(
                        rx.hstack(
                            rx.heading("Upload PDF Document", size="5"),
                            rx.spacer(),
                            rx.button("✕", on_click=MainState.toggle_upload, variant="ghost", size="2"),
                            width="100%",
                            align="center",
                        ),
                        rx.upload(
                            rx.vstack(
                                rx.button("Choose PDF File", color_scheme="blue", size="2"),
                                rx.text("or drag & drop PDF here", size="2", color="gray"),
                                align="center",
                                spacing="2",
                            ),
                            id="pdf_upload",
                            accept={"application/pdf": [".pdf"]},
                            border="2px dashed #cbd5e1",
                            padding="1.5em",
                            border_radius="8px",
                            width="100%",
                        ),
                        rx.hstack(
                            rx.foreach(
                                rx.selected_files("pdf_upload"),
                                lambda file: rx.badge(file, color_scheme="blue", size="2"),
                            ),
                            spacing="2",
                            wrap="wrap",
                        ),
                        rx.cond(
                            MainState.error != "",
                            rx.text(MainState.error, color="red", size="2"),
                        ),
                        rx.hstack(
                            rx.button(
                                "Upload & Process",
                                on_click=MainState.handle_upload(rx.upload_files(upload_id="pdf_upload")),
                                is_loading=MainState.is_loading,
                                loading_text="Uploading...",
                                color_scheme="blue",
                                size="2",
                            ),
                            rx.button(
                                "Cancel",
                                on_click=MainState.toggle_upload,
                                variant="soft",
                                size="2",
                            ),
                            spacing="3",
                            justify="end",
                            width="100%",
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    bg="white",
                    color="gray.800",
                    padding="2em",
                    border_radius="12px",
                    box_shadow="0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
                    max_width="480px",
                    width="90%",
                ),
                position="fixed",
                top="0",
                left="0",
                width="100vw",
                height="100vh",
                bg="rgba(0,0,0,0.5)",
                display="flex",
                align_items="center",
                justify_content="center",
                z_index="1000",
            )
        ),
        # Mindmap modal
        rx.cond(
            MainState.show_mindmap,
            rx.box(
                rx.box(
                    rx.vstack(
                        rx.hstack(
                            rx.heading("Mindmap", size="6"),
                            rx.spacer(),
                            rx.button(
                                "✕",
                                on_click=MainState.toggle_mindmap,
                                size="2",
                            ),
                            width="100%",
                        ),
                        rx.cond(
                            MainState.mindmap_loading,
                            rx.spinner(size="3"),
                            rx.vstack(
                                rx.foreach(
                                    MainState.mindmap_items,
                                    render_mindmap_item
                                ),
                                width="100%",
                                max_height="70vh",
                                overflow_y="auto",
                                padding="1em",
                                bg="white",
                                border_radius="0.5em",
                                spacing="2",
                            ),
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    bg="white",
                    padding="2em",
                    border_radius="0.5em",
                    box_shadow="lg",
                    width="90vw",
                    max_width="1200px",
                    max_height="90vh",
                ),
                position="fixed",
                top="50%",
                left="50%",
                transform="translate(-50%, -50%)",
                bg="rgba(0,0,0,0.5)",
                width="100vw",
                height="100vh",
                z_index="1000",
                display="flex",
                align_items="center",
                justify_content="center",
            )
        ),
        on_mount=MainState.on_load,
    )

app = rx.App()
app.add_page(login_page, route="/")
app.add_page(register_page, route="/register")
app.add_page(chat_page, route="/chat")
