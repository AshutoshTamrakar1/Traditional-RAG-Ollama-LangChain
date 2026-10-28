import reflex as rx
import httpx

BACKEND_URL = "http://localhost:8000"
DEFAULT_CHAT_TITLE = "New Chat"
MSG_SESSION_EXPIRED = "Session expired. Please log in again."
PADDING_HALF_EM = "0.5em"
COLOR_BLUE_100 = "blue.100"
BORDER_SUBTLE = "1px solid #e2e8f0"


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
                    return rx.redirect(f"/chat?access_token={self.access_token}&refresh_token={self.refresh_token}&user_id={self.user_id}")
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
                        return rx.redirect(f"/chat?access_token={self.access_token}&refresh_token={self.refresh_token}&user_id={self.user_id}")
                    else:
                        # Fallback to login page if no tokens
                        return rx.call_script("setTimeout(() => window.location.href = '/', 2000)")
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
    current_chat_title: str = DEFAULT_CHAT_TITLE
    
    # Messages
    messages: list[dict] = []
    user_input: str = ""
    
    # PDFs
    uploaded_pdfs: list[dict] = []
    active_source_ids: list[str] = []
    
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

    def _update_session_title_in_list(self, chat_session_id: str, new_title: str):
        """Update a chat session's title in chat_sessions state list"""
        updated = []
        for s in self.chat_sessions:
            if s.get("chat_session_id") == chat_session_id:
                updated.append({**s, "title": new_title})
            else:
                updated.append(s)
        self.chat_sessions = updated
    
    async def refresh_access_token(self) -> bool:
        """Refresh access token using refresh token. Returns True if successful."""
        if not self.refresh_token:
            print("[REFRESH] No refresh token available")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print("[REFRESH] Refreshing access token")
                response = await client.post(
                    f"{BACKEND_URL}/auth/refresh",
                    headers={"Authorization": f"Bearer {self.refresh_token}"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    self.refresh_token = data.get("refresh_token", self.refresh_token)
                    print("[REFRESH SUCCESS] Token refreshed")
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
                print("[MAIN] New login detected, clearing old state")
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
            return rx.redirect("/")
        
        # Load user's existing chat sessions from backend
        await self.load_chat_sessions()
        
        # Select active or most recent chat session, or create one if none exists
        existing_ids = [s.get("chat_session_id") for s in self.chat_sessions]
        if self.current_chat_id and self.current_chat_id in existing_ids:
            await self.select_chat(self.current_chat_id)
        elif self.chat_sessions:
            await self.select_chat(self.chat_sessions[0]["chat_session_id"])
        else:
            print("[MAIN] Creating initial chat session")
            await self.create_new_chat()

    async def load_chat_sessions(self):
        """Fetch the user's chat session history list from backend"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{BACKEND_URL}/pdf/sessions",
                    headers=self.get_auth_headers()
                )
                if response.status_code == 401 and await self.refresh_access_token():
                    response = await client.get(
                        f"{BACKEND_URL}/pdf/sessions",
                        headers=self.get_auth_headers()
                    )
                if response.status_code == 200:
                    data = response.json()
                    self.chat_sessions = data.get("sessions", [])
                    print(f"[SESSIONS] Loaded {len(self.chat_sessions)} chat sessions")
        except Exception as e:
            print(f"[SESSIONS ERROR] {e}")

    async def select_chat(self, chat_session_id: str):
        """Load a specific chat session's messages and uploaded PDFs"""
        if not chat_session_id:
            return
        print(f"[SELECT_CHAT] Loading chat session: {chat_session_id}")
        self.error = ""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{BACKEND_URL}/pdf/session/{chat_session_id}",
                    headers=self.get_auth_headers()
                )
                if response.status_code == 401 and await self.refresh_access_token():
                    response = await client.get(
                        f"{BACKEND_URL}/pdf/session/{chat_session_id}",
                        headers=self.get_auth_headers()
                    )
                if response.status_code == 200:
                    data = response.json()
                    self.current_chat_id = chat_session_id
                    self.current_chat_title = data.get("title", DEFAULT_CHAT_TITLE)
                    self.messages = data.get("messages", [])
                    self.uploaded_pdfs = data.get("sources", [])
                    self.active_source_ids = [
                        s.get("source_id") or s.get("id")
                        for s in self.uploaded_pdfs
                        if s.get("source_id") or s.get("id")
                    ]
                    print(
                        f"[SELECT_CHAT SUCCESS] Loaded {len(self.messages)} messages "
                        f"and {len(self.uploaded_pdfs)} PDFs"
                    )
                else:
                    self.error = "Failed to load chat session"
        except Exception as e:
            self.error = f"Error loading chat: {str(e)}"
            print(f"[SELECT_CHAT EXCEPTION] {e}")

    def toggle_source(self, source_id: str):
        """Toggle whether an uploaded PDF is active for RAG queries"""
        if source_id in self.active_source_ids:
            self.active_source_ids = [sid for sid in self.active_source_ids if sid != source_id]
        else:
            self.active_source_ids = [*self.active_source_ids, source_id]
    
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
                if response.status_code == 401 and await self.refresh_access_token():
                    response = await client.post(
                        f"{BACKEND_URL}/pdf/session",
                        headers=self.get_auth_headers()
                    )
                
                print(f"[CREATE_CHAT] Response status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    self.current_chat_id = data["chat_session_id"]
                    self.current_chat_title = data.get("title", DEFAULT_CHAT_TITLE)
                    self.messages = []
                    self.uploaded_pdfs = []
                    self.active_source_ids = []
                    
                    # Prepend to sessions list so newest chat is at the top
                    self.chat_sessions = [
                        {
                            "chat_session_id": self.current_chat_id,
                            "title": self.current_chat_title
                        },
                        *self.chat_sessions
                    ]
                    print(f"[CREATE_CHAT SUCCESS] Created chat session: {self.current_chat_id}")
                elif response.status_code == 401:
                    self.error = MSG_SESSION_EXPIRED
                    print("[CREATE_CHAT ERROR] Token refresh failed")
                    return rx.redirect("/")
                else:
                    self.error = "Failed to create chat session"
                    print(f"[CREATE_CHAT ERROR] {self.error}")
        except Exception as e:
            self.error = f"Error creating chat: {str(e)}"
            print(f"[CREATE_CHAT EXCEPTION] {e}")
    
    def _sanitize_upload_filename(self, file) -> str:
        """Extract and sanitize filename from upload file object."""
        raw_filename = getattr(file, "filename", None) or getattr(file, "name", None) or ""
        filename = raw_filename.replace("\\", "/").split("/")[-1]
        if not filename or not filename.lower().endswith(".pdf"):
            return (filename or "document") + ".pdf"
        return filename

    async def _post_pdf_file(self, client: httpx.AsyncClient, filename: str, file_data: bytes):
        """Send a single PDF file upload request to backend with auth retry."""
        files_data = {"file": (filename, file_data, "application/pdf")}
        form_data = {"chat_session_id": self.current_chat_id}
        print(f"[UPLOAD] Sending {filename} to {BACKEND_URL}/pdf/upload")
        
        response = await client.post(
            f"{BACKEND_URL}/pdf/upload",
            headers=self.get_auth_headers(),
            data=form_data,
            files=files_data
        )
        if response.status_code == 401 and await self.refresh_access_token():
            response = await client.post(
                f"{BACKEND_URL}/pdf/upload",
                headers=self.get_auth_headers(),
                data=form_data,
                files=files_data
            )
        return response

    def _process_upload_response(
        self,
        response,
        filename: str,
        uploaded_sources: list,
        active_ids: list,
        errors: list
    ) -> bool:
        """Process response for a single uploaded file. Returns False if upload loop should terminate."""
        print(f"[UPLOAD] Response status for {filename}: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            new_source = data["new_source"]
            uploaded_sources.append(new_source)
            if new_source["source_id"] not in active_ids:
                active_ids.append(new_source["source_id"])
            if data.get("new_title"):
                self.current_chat_title = data["new_title"]
                self._update_session_title_in_list(self.current_chat_id, data["new_title"])
            print(f"[UPLOAD SUCCESS] PDF uploaded: {new_source['filename']}")
            return True
        
        if response.status_code == 401:
            errors.append(MSG_SESSION_EXPIRED)
            return False
            
        detail = ""
        try:
            detail = response.json().get("detail", "")
        except Exception:
            pass
        errors.append(f"{filename}: {detail}" if detail else f"Failed to upload {filename}")
        return True

    async def _ensure_chat_session_for_upload(self) -> bool:
        """Ensure an active chat session exists before file upload."""
        if self.current_chat_id:
            return True
        print("[UPLOAD] No active chat session, creating one first...")
        await self.create_new_chat()
        return bool(self.current_chat_id)

    async def upload_pdf(self, files: list):
        """Upload one or more PDF files"""
        print(f"[UPLOAD] Uploading {len(files) if files else 0} file(s)")
        self.error = ""
        self.is_loading = True
        
        if not files:
            self.error = "No file selected"
            self.is_loading = False
            return
        
        if not await self._ensure_chat_session_for_upload():
            self.error = "Please start a chat session before uploading"
            self.is_loading = False
            return
        
        uploaded_sources = list(self.uploaded_pdfs)
        active_ids = list(self.active_source_ids)
        errors = []
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                for file in files:
                    filename = self._sanitize_upload_filename(file)
                    print(f"[UPLOAD] Processing file: {filename}")
                    file_data = await file.read() if hasattr(file, "read") else file
                    
                    response = await self._post_pdf_file(client, filename, file_data)
                    should_continue = self._process_upload_response(
                        response, filename, uploaded_sources, active_ids, errors
                    )
                    if not should_continue:
                        break
            
            self.uploaded_pdfs = uploaded_sources
            self.active_source_ids = active_ids
            
            if errors:
                self.error = "; ".join(errors)
                print(f"[UPLOAD ERROR] {self.error}")
            else:
                self.show_upload = False
                self.error = ""
        except Exception as e:
            self.error = f"Upload error: {str(e)}"
            print(f"[UPLOAD EXCEPTION] {e}")
        finally:
            self.is_loading = False
    
    async def handle_upload(self, files: list[rx.UploadFile]):
        """Handle file upload from rx.upload component"""
        print(f"[HANDLE_UPLOAD] Files received: {len(files) if files else 0}")
        await self.upload_pdf(files)
        return rx.clear_selected_files("pdf_upload")
    
    async def send_message(self, _form_data: dict = None):
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
                
                if response.status_code == 401 and await self.refresh_access_token():
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
                    
                    # Refresh chat title if this was the first message turn
                    if len(self.messages) == 2:
                        await self.refresh_chat_title()
                elif response.status_code == 401:
                    self.error = MSG_SESSION_EXPIRED
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
                    self.available_models = data.get("models", ["llama3", "gemma"])
                    self.selected_model = data.get("default", "llama3")
                    print(f"[MODELS] Loaded: {self.available_models}")
        except Exception as e:
            print(f"[MODELS ERROR] {e}")
            self.available_models = ["llama3", "gemma"]
    
    def set_model(self, model: str):
        """Set selected chat model"""
        self.selected_model = model
        print(f"[MODEL] Selected: {model}")

    def set_user_input(self, val: str):
        """Update user input text"""
        self.user_input = val
    
    async def logout(self):
        """Logout user and invalidate JWT tokens on backend"""
        print("[LOGOUT] Logging out user")
        
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
                if response.status_code == 401 and await self.refresh_access_token():
                    response = await client.get(
                        f"{BACKEND_URL}/pdf/session/{self.current_chat_id}",
                        headers=self.get_auth_headers()
                    )
                if response.status_code == 200:
                    data = response.json()
                    new_title = data.get("title", DEFAULT_CHAT_TITLE)
                    if new_title != DEFAULT_CHAT_TITLE:
                        self.current_chat_title = new_title
                        self._update_session_title_in_list(self.current_chat_id, new_title)
                        print(f"[TITLE] Updated to: {new_title}")
        except Exception as e:
            print(f"[TITLE ERROR] {e}")


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


def _render_user_message(msg):
    return rx.hstack(
        rx.spacer(),
        rx.box(
            rx.text(
                msg["content"],
                size="3",
                white_space="pre-wrap",
                line_height="1.5",
            ),
            background_color="var(--blue-9)",
            color="white",
            padding="0.75rem 1.15rem",
            border_radius="16px 16px 4px 16px",
            max_width="75%",
            box_shadow="0 2px 6px rgba(0, 0, 0, 0.12)",
        ),
        rx.avatar(
            fallback="U",
            size="2",
            variant="solid",
            color_scheme="blue",
            radius="full",
        ),
        width="100%",
        align="end",
        spacing="3",
    )


def _render_assistant_message(msg):
    return rx.hstack(
        rx.avatar(
            fallback="AI",
            size="2",
            variant="soft",
            color_scheme="violet",
            radius="full",
        ),
        rx.box(
            rx.markdown(
                msg["content"],
            ),
            background_color="var(--gray-a2)",
            border="1px solid var(--gray-a4)",
            padding="1rem 1.25rem",
            border_radius="4px 16px 16px 16px",
            max_width="85%",
            box_shadow="0 1px 4px rgba(0, 0, 0, 0.05)",
            line_height="1.65",
            width="100%",
        ),
        rx.spacer(),
        width="100%",
        align="start",
        spacing="3",
    )


def render_chat_message(msg):
    return rx.cond(
        msg["role"] == "user",
        _render_user_message(msg),
        _render_assistant_message(msg),
    )


def _render_welcome_screen():
    return rx.center(
        rx.vstack(
            rx.avatar(fallback="AI", size="5", variant="soft", color_scheme="violet"),
            rx.heading("PDF RAG Assistant", size="6", weight="bold"),
            rx.text(
                "Upload PDF documents or choose a chat from the sidebar to ask questions with grounded context.",
                size="3",
                color="gray",
                text_align="center",
                max_width="480px",
            ),
            rx.button(
                rx.hstack(
                    rx.icon("paperclip", size=18),
                    rx.text("Upload PDFs to Begin"),
                    spacing="2",
                    align="center",
                ),
                on_click=MainState.toggle_upload,
                size="3",
                variant="solid",
                color_scheme="blue",
            ),
            align="center",
            spacing="4",
            padding="2em",
        ),
        height="100%",
        width="100%",
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
                rx.box(
                    rx.vstack(
                        rx.foreach(
                            MainState.chat_sessions,
                            lambda session: rx.box(
                                rx.text(
                                    session["title"],
                                    size="2",
                                    weight=rx.cond(
                                        MainState.current_chat_id == session["chat_session_id"],
                                        "bold",
                                        "regular"
                                    ),
                                ),
                                padding=PADDING_HALF_EM,
                                width="100%",
                                border_radius="0.375em",
                                bg=rx.cond(
                                    MainState.current_chat_id == session["chat_session_id"],
                                    COLOR_BLUE_100,
                                    "transparent"
                                ),
                                _hover={"bg": "gray.200", "cursor": "pointer"},
                                on_click=getattr(MainState, "select_chat")(session["chat_session_id"]),  # NOSONAR
                            )
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    flex="1",
                    width="100%",
                    overflow_y="auto",
                ),
                rx.divider(),
                rx.text("Uploaded PDFs (click to toggle):", font_weight="bold", size="2"),
                rx.box(
                    rx.vstack(
                        rx.foreach(
                            MainState.uploaded_pdfs,
                            lambda pdf: rx.box(
                                rx.hstack(
                                    rx.text(
                                        rx.cond(
                                            MainState.active_source_ids.contains(pdf["source_id"]),
                                            "✓",
                                            "○"
                                        ),
                                        size="1",
                                        weight="bold",
                                    ),
                                    rx.text(pdf["filename"], size="1", flex="1"),
                                    spacing="2",
                                    width="100%",
                                    align="center",
                                ),
                                padding="0.35em 0.5em",
                                bg=rx.cond(
                                    MainState.active_source_ids.contains(pdf["source_id"]),
                                    COLOR_BLUE_100,
                                    "gray.100"
                                ),
                                border_radius="0.25em",
                                width="100%",
                                _hover={"cursor": "pointer", "opacity": "0.85"},
                                on_click=getattr(MainState, "toggle_source")(pdf["source_id"]),  # NOSONAR
                            )
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    max_height="200px",
                    overflow_y="auto",
                    width="100%",
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
                    rx.heading(MainState.current_chat_title, size="5", weight="bold"),
                    rx.spacer(),
                    rx.hstack(
                        rx.text("Model:", size="2", color="gray", weight="medium"),
                        rx.select(
                            MainState.available_models,
                            value=MainState.selected_model,
                            on_change=MainState.set_model,
                            size="2",
                        ),
                        rx.button(
                            rx.hstack(
                                rx.icon("paperclip", size=16),
                                rx.text("Upload PDFs", size="2"),
                                spacing="1",
                                align="center",
                            ),
                            on_click=MainState.toggle_upload,
                            size="2",
                            variant="surface",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    width="100%",
                    padding="0.85em 1.5em",
                    border_bottom=BORDER_SUBTLE,
                    align="center",
                ),
                # Messages
                rx.box(
                    rx.cond(
                        MainState.messages.length() == 0,
                        _render_welcome_screen(),
                        rx.box(
                            rx.vstack(
                                rx.foreach(MainState.messages, render_chat_message),
                                spacing="4",
                                width="100%",
                            ),
                            max_width="880px",
                            width="100%",
                            margin_x="auto",
                            padding_x="1em",
                        ),
                    ),
                    flex="1",
                    overflow_y="auto",
                    padding_y="1.5em",
                    width="100%",
                ),
                # Input area
                rx.box(
                    rx.box(
                        rx.cond(
                            MainState.error != "",
                            rx.box(
                                rx.hstack(
                                    rx.icon("circle-alert", size=16, color="red"),
                                    rx.text(MainState.error, color="red", size="2"),
                                    spacing="2",
                                    align="center",
                                ),
                                padding_bottom="0.5em",
                            ),
                        ),
                        rx.form(
                            rx.hstack(
                                rx.input(
                                    placeholder="Ask a question about your documents...",
                                    value=MainState.user_input,
                                    on_change=MainState.set_user_input,
                                    flex="1",
                                    size="3",
                                    variant="surface",
                                    radius="large",
                                ),
                                rx.button(
                                    rx.cond(
                                        MainState.is_loading,
                                        rx.spinner(size="2"),
                                        rx.icon("send", size=18),
                                    ),
                                    type="submit",
                                    size="3",
                                    radius="large",
                                    color_scheme="blue",
                                    variant="solid",
                                    disabled=MainState.is_loading,
                                ),
                                width="100%",
                                spacing="3",
                                align="center",
                            ),
                            on_submit=MainState.send_message,
                            width="100%",
                        ),
                        max_width="880px",
                        width="100%",
                        margin_x="auto",
                        padding_x="1em",
                    ),
                    width="100%",
                    padding_y="1em",
                    border_top=BORDER_SUBTLE,
                ),
                height="100vh",
                width="100%",
                spacing="0",
            ),
            margin_left="250px",
            min_height="100vh",
            height="100vh",
            width="calc(100% - 250px)",
        ),
        # Upload modal
        rx.cond(
            MainState.show_upload,
            rx.box(
                rx.box(
                    rx.vstack(
                        rx.hstack(
                            rx.heading("Upload PDF Documents", size="5"),
                            rx.spacer(),
                            rx.button("✕", on_click=MainState.toggle_upload, variant="ghost", size="2"),
                            width="100%",
                            align="center",
                        ),
                        rx.upload(
                            rx.vstack(
                                rx.button("Choose PDF Files", color_scheme="blue", size="2"),
                                rx.text("or drag & drop one or more PDFs here", size="2", color="gray"),
                                align="center",
                                spacing="2",
                            ),
                            id="pdf_upload",
                            accept={"application/pdf": [".pdf"]},
                            multiple=True,
                            max_files=20,
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
                                on_click=getattr(MainState, "handle_upload")(rx.upload_files(upload_id="pdf_upload")),  # NOSONAR
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
        on_mount=MainState.on_load,
    )


app = rx.App()
app.add_page(login_page, route="/")
app.add_page(register_page, route="/register")
app.add_page(chat_page, route="/chat")
