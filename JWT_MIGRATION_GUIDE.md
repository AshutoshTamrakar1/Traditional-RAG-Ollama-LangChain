# JWT Authentication Migration Guide

## Overview

This guide documents the migration from session-based authentication to JWT (JSON Web Token) stateless authentication. This is a **breaking change** that requires updates to all API clients.

**Migration Date**: February 2026  
**Version**: 2.0.0 → 2.1.0  
**Impact**: All authenticated API endpoints

---

## What Changed?

### Before (Session-based Authentication)
- Server maintained in-memory `active_sessions` dictionary
- MongoDB `sessions` collection stored persistent session data
- Clients sent `session_id` in request body/form data
- Session validation on every request queried server state
- Horizontal scaling required shared session storage (Redis)

### After (JWT Token Authentication)
- Stateless authentication using signed JWT tokens
- No server-side session storage
- Clients send `Authorization: Bearer <token>` header
- JWT validation is cryptographic (no database lookup)
- Horizontal scaling with no shared state required

---

## API Changes

### 1. Login Response Format

#### Before:
```json
POST /auth/login
Request:
{
  "email": "user@example.com",
  "password": "password123"
}

Response:
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "65abc123...",
  "email": "user@example.com"
}
```

#### After:
```json
POST /auth/login
Request:
{
  "email": "user@example.com",
  "password": "password123"
}

Response:
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": "65abc123...",
  "email": "user@example.com"
}
```

**Action Required**: Update frontend to store `access_token` and `refresh_token` instead of `session_id`.

---

### 2. Authentication Headers

#### Before:
All endpoints accepted `session_id` in request body:

```http
POST /pdf/upload
Content-Type: multipart/form-data

session_id=550e8400-e29b-41d4-a716-446655440000
file=@document.pdf
```

```json
POST /chat/send
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "chat_session_id": "thread-123",
  "user_input": "What is this document about?"
}
```

#### After:
All endpoints require `Authorization` header with Bearer token:

```http
POST /pdf/upload
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Content-Type: multipart/form-data

file=@document.pdf
```

```json
POST /chat/send
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Content-Type: application/json

{
  "chat_session_id": "thread-123",
  "user_input": "What is this document about?",
  "active_source_ids": []
}
```

**Action Required**: 
1. Remove `session_id` from all request bodies
2. Add `Authorization: Bearer <access_token>` header to all authenticated requests

---

### 3. New Endpoints

#### Token Refresh
```json
POST /auth/refresh
Authorization: Bearer <refresh_token>

Response:
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

#### Token Verification
```json
POST /auth/verify-token
Authorization: Bearer <access_token>

Response:
{
  "valid": true,
  "user_id": "65abc123...",
  "exp": 1709467200,
  "token_type": "access"
}
```

---

### 4. Removed Endpoints

- ❌ `GET /auth/validate` - No longer needed (JWT validation is built into endpoints)

---

### 5. Updated Request Models

#### ChatRequest
```python
# Before:
class ChatRequest(BaseModel):
    session_id: str
    chat_session_id: str
    user_input: str
    active_source_ids: List[str] = []

# After:
class ChatRequest(BaseModel):
    chat_session_id: str
    user_input: str
    active_source_ids: List[str] = []
    # session_id removed - authentication via JWT header
```

#### MindmapRequest
```python
# Before:
class MindmapRequest(BaseRequest):
    session_id: str
    chat_session_id: str
    source_id: str

# After:
class MindmapRequest(BaseRequest):
    chat_session_id: str
    source_id: str
    # session_id removed - authentication via JWT header
```

---

## Frontend Migration

### Step 1: Update Login Logic

```javascript
// Before:
async function login(email, password) {
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  
  const data = await response.json();
  localStorage.setItem('session_id', data.session_id);
  return data;
}

// After:
async function login(email, password) {
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  
  const data = await response.json();
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  return data;
}
```

### Step 2: Update API Request Helper

```javascript
// Before:
async function apiRequest(url, options = {}) {
  const session_id = localStorage.getItem('session_id');
  
  if (options.body && typeof options.body === 'object') {
    options.body.session_id = session_id;
  }
  
  const response = await fetch(url, options);
  return response.json();
}

// After:
async function apiRequest(url, options = {}) {
  const access_token = localStorage.getItem('access_token');
  
  options.headers = {
    ...options.headers,
    'Authorization': `Bearer ${access_token}`
  };
  
  const response = await fetch(url, options);
  
  // Handle token expiry
  if (response.status === 401) {
    await refreshToken();
    return apiRequest(url, options); // Retry with new token
  }
  
  return response.json();
}

async function refreshToken() {
  const refresh_token = localStorage.getItem('refresh_token');
  
  const response = await fetch('/auth/refresh', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${refresh_token}`
    }
  });
  
  if (!response.ok) {
    // Refresh token expired, redirect to login
    window.location.href = '/login';
    throw new Error('Session expired');
  }
  
  const data = await response.json();
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
}
```

### Step 3: Update File Upload

```javascript
// Before:
async function uploadPDF(file) {
  const session_id = localStorage.getItem('session_id');
  const formData = new FormData();
  formData.append('session_id', session_id);
  formData.append('file', file);
  
  return fetch('/pdf/upload', {
    method: 'POST',
    body: formData
  });
}

// After:
async function uploadPDF(file) {
  const access_token = localStorage.getItem('access_token');
  const formData = new FormData();
  formData.append('file', file);
  
  return fetch('/pdf/upload', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${access_token}`
    },
    body: formData
  });
}
```

### Step 4: Update Logout

```javascript
// Before:
async function logout() {
  const session_id = localStorage.getItem('session_id');
  await fetch('/auth/logout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id })
  });
  localStorage.removeItem('session_id');
}

// After:
async function logout() {
  const access_token = localStorage.getItem('access_token');
  await fetch('/auth/logout', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${access_token}`
    }
  });
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
}
```

---

## Reflex Frontend Migration

### Update State Management

```python
# Before:
class AppState(rx.State):
    session_id: str = ""
    
    async def login(self, email: str, password: str):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/auth/login",
                json={"email": email, "password": password}
            )
            data = response.json()
            self.session_id = data["session_id"]
    
    async def upload_pdf(self, files: list[rx.UploadFile]):
        async with httpx.AsyncClient() as client:
            data = {"session_id": self.session_id}
            files_data = {"file": file.read()}
            await client.post(
                f"{API_BASE}/pdf/upload",
                data=data,
                files=files_data
            )

# After:
class AppState(rx.State):
    access_token: str = ""
    refresh_token: str = ""
    
    async def login(self, email: str, password: str):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/auth/login",
                json={"email": email, "password": password}
            )
            data = response.json()
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
    
    def get_auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}
    
    async def upload_pdf(self, files: list[rx.UploadFile]):
        async with httpx.AsyncClient() as client:
            files_data = {"file": file.read()}
            await client.post(
                f"{API_BASE}/pdf/upload",
                headers=self.get_auth_headers(),
                files=files_data
            )
    
    async def refresh_access_token(self):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/auth/refresh",
                headers={"Authorization": f"Bearer {self.refresh_token}"}
            )
            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access_token"]
                self.refresh_token = data["refresh_token"]
            else:
                # Redirect to login
                return rx.redirect("/login")
```

---

## Token Lifetime

| Token Type | Default Expiry | Configurable? |
|------------|---------------|---------------|
| Access Token | 60 minutes | Yes (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`) |
| Refresh Token | 7 days | Yes (`JWT_REFRESH_TOKEN_EXPIRE_DAYS`) |

**Best Practices**:
- Store access token in memory or short-lived storage
- Store refresh token in httpOnly cookies (recommended) or localStorage
- Implement automatic token refresh before expiry
- Clear tokens on logout

---

## Error Handling

### New Error Responses

#### 401 Unauthorized - Invalid/Expired Token
```json
{
  "detail": "Could not validate credentials"
}
```

**Action**: Attempt token refresh, then redirect to login if refresh fails.

#### 403 Forbidden - Invalid Token Signature
```json
{
  "detail": "Invalid token"
}
```

**Action**: Token has been tampered with. Clear tokens and redirect to login.

---

## Configuration

### New Environment Variables

Add to `.env` file:

```bash
# JWT Configuration
JWT_SECRET_KEY=<auto-generated-or-specify-your-own>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
```

**Security Note**: 
- `JWT_SECRET_KEY` is auto-generated on first run if not specified
- Use a strong, random 256-bit key in production
- Never commit `.env` to version control

---

## Testing the Migration

### 1. Test Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'
```

Expected response includes `access_token` and `refresh_token`.

### 2. Test Authenticated Endpoint
```bash
curl -X POST http://localhost:8000/pdf/session \
  -H "Authorization: Bearer <access_token>"
```

### 3. Test Token Refresh
```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Authorization: Bearer <refresh_token>"
```

---

## Rollback Plan

If issues arise, rollback is possible:

1. Restore from `auth_session_old.py` backup
2. Revert changes to `config.py`, `services/*.py`, `db_manager.py`
3. Re-enable `create_session()`, `get_session()`, `validate_session()` functions
4. Update frontend to use `session_id` again

---

## FAQ

**Q: Can I use both session_id and JWT during migration?**  
A: No. The migration is a hard cutover. All endpoints now require JWT authentication.

**Q: What happens to old session_id values?**  
A: They are ignored. Clients must obtain new JWT tokens via `/auth/login`.

**Q: Is the sessions collection deleted from MongoDB?**  
A: No, but it's no longer used. You can manually drop it: `db.sessions.drop()`

**Q: Can I increase token expiry times?**  
A: Yes, via environment variables. However, shorter access tokens are more secure.

**Q: How do I test JWT locally?**  
A: Use jwt.io to decode tokens (never paste production tokens there!). Verify the payload contains `sub` (user_id) and `exp` (expiry).

---

## Support

If you encounter issues during migration:
1. Check that `requirements.txt` includes `PyJWT>=2.8.0` and `python-jose[cryptography]>=3.3.0`
2. Verify `.env` has JWT configuration variables
3. Ensure frontend sends `Authorization: Bearer <token>` header, not `session_id` in body
4. Check server logs for JWT validation errors

For questions, open an issue on GitHub.
