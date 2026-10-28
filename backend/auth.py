import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any
from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from logging_config import get_logger, log_exceptions
from db_manager import (
    create_user,
    get_user_by_id,
    update_user_last_login,
    revoke_token,
    is_token_revoked,
    COLLECTION_USERS
)
from config import get_settings

logger = get_logger(__name__)
settings = get_settings()

# ============================================================================
# CONFIGURATION
# ============================================================================

# JWT Configuration from settings
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS

# Security scheme
security = HTTPBearer()

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class UserRegisterRequest(BaseModel):
    """User registration request model"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    def validate_username(cls, v):
        """Validate username format"""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username can only contain alphanumeric characters, underscores, and hyphens")
        return v

    @model_validator(mode="after")
    def validate_passwords_match(cls, model):
        """Ensure passwords match"""
        if getattr(model, "password", None) != getattr(model, "confirm_password", None):
            raise ValueError("Passwords do not match")
        return model


class UserLoginRequest(BaseModel):
    """User login request model"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response model"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserLoginResponse(BaseModel):
    """User login response model"""
    status: str
    message: str
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRegisterResponse(BaseModel):
    """User registration response model"""
    status: str
    message: str
    user_id: str
    email: str
    username: str


class TokenRefreshRequest(BaseModel):
    """Token refresh request model"""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Optional logout body; pass the refresh token to revoke it too"""
    refresh_token: Optional[str] = None


class UserProfileResponse(BaseModel):
    """User profile response model"""
    user_id: str
    email: str
    username: str
    created_at: str
    last_login: Optional[str] = None
    active: bool


class ChangePasswordRequest(BaseModel):
    """Change password request model"""
    old_password: str
    new_password: str
    confirm_password: str


# ============================================================================
# PASSWORD HASHING
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


# ============================================================================
# JWT TOKEN MANAGEMENT
# ============================================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
        "type": "refresh"
    })
    
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except ExpiredSignatureError:
        logger.warning("Token has expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"}
        )


def verify_access_token(token: str) -> str:
    """Verify access token and return user_id"""
    payload = decode_token(token)
    
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return user_id


def verify_refresh_token(token: str) -> str:
    """Verify refresh token and return user_id"""
    payload = decode_token(token)
    
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return user_id


# ============================================================================
# DEPENDENCY FUNCTIONS
# ============================================================================

def _revoked_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token has been revoked",
        headers={"WWW-Authenticate": "Bearer"}
    )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Dependency to get current user from JWT token (rejects revoked tokens)"""
    token = credentials.credentials
    user_id = verify_access_token(token)
    if await is_token_revoked(decode_token(token).get("jti")):
        raise _revoked_error()
    return user_id


async def get_current_user_from_header(authorization: Optional[str] = Header(None)) -> str:
    """Alternative: Get current user from Authorization header"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Bearer"}
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user_id = verify_access_token(token)
    if await is_token_revoked(decode_token(token).get("jti")):
        raise _revoked_error()
    return user_id


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

router = APIRouter(tags=["Authentication"])


@router.post("/register", response_model=UserRegisterResponse, status_code=status.HTTP_201_CREATED)
@log_exceptions
async def register(request: UserRegisterRequest):
    """Register a new user"""
    logger.info(f"Registration attempt for email: {request.email}")
    
    try:
        from db_manager import _db_manager
        
        email_clean = request.email.strip().lower()
        username_clean = request.username.strip()
        
        # Check if user already exists
        existing_user = await _db_manager.db[COLLECTION_USERS].find_one({
            "$or": [
                {"email": email_clean},
                {"username": username_clean}
            ]
        })
        
        if existing_user:
            if existing_user.get("email") == email_clean:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already registered"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already taken"
                )
        
        # Create new user
        user_id = str(uuid.uuid4())
        hashed_password = hash_password(request.password.strip())
        
        user_doc = {
            "user_id": user_id,
            "email": email_clean,
            "username": username_clean,
            "password_hash": hashed_password,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_login": None,
            "active": True
        }
        
        await _db_manager.db[COLLECTION_USERS].insert_one(user_doc)
        logger.info(f"User registered successfully: {user_id}")
        
        return UserRegisterResponse(
            status="success",
            message="User registered successfully",
            user_id=user_id,
            email=request.email,
            username=request.username
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )


@router.post("/login", response_model=UserLoginResponse)
@log_exceptions
async def login(request: UserLoginRequest):
    """Login user and return JWT tokens"""
    logger.info(f"Login attempt for email: {request.email}")
    
    try:
        from db_manager import _db_manager
        
        email_clean = request.email.strip().lower()
        password_clean = request.password.strip()
        
        # Find user by email
        user = await _db_manager.db[COLLECTION_USERS].find_one({"email": email_clean})
        
        if not user:
            logger.warning(f"Login failed: user not found for email {email_clean}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        if not user.get("active"):
            logger.warning(f"Login failed: user account inactive {user.get('user_id')}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        # Verify password
        if not verify_password(password_clean, user.get("password_hash", "")):
            logger.warning(f"Login failed: invalid password for email {email_clean}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Create JWT tokens
        user_id = user.get("user_id")
        token_data = {"sub": user_id, "email": email_clean}
        
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        
        # Update last login
        await update_user_last_login(user_id)
        
        logger.info(f"User logged in successfully: {user_id}")
        
        return UserLoginResponse(
            status="success",
            message="Login successful",
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )


@router.post("/refresh", response_model=TokenResponse)
@log_exceptions
async def refresh_token(
    request: Optional[TokenRefreshRequest] = None,
    authorization: Optional[str] = Header(None)
):
    """Refresh access token using refresh token (JSON body or `Authorization: Bearer <refresh>`)"""
    logger.info("Token refresh attempt")

    raw_refresh = request.refresh_token if request else None
    if not raw_refresh and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_refresh = parts[1]
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        # Verify refresh token (and that it has not been revoked / already used)
        user_id = verify_refresh_token(raw_refresh)
        old_payload = decode_token(raw_refresh)
        if await is_token_revoked(old_payload.get("jti")):
            raise _revoked_error()
        
        # Get user to ensure still active
        user = await get_user_by_id(user_id)
        if not user or not user.get("active"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )
        
        # Create new tokens
        token_data = {"sub": user_id, "email": user.get("email")}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Rotate: the used refresh token can no longer be replayed
        if old_payload.get("jti") and old_payload.get("exp"):
            await revoke_token(
                old_payload["jti"],
                datetime.fromtimestamp(old_payload["exp"], tz=timezone.utc)
            )
        
        logger.info(f"Tokens refreshed for user: {user_id}")
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.post("/logout")
@log_exceptions
async def logout(
    body: Optional[LogoutRequest] = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: str = Depends(get_current_user)
):
    """Logout user: revokes the access token (and the refresh token if supplied)"""
    logger.info(f"Logout for user: {current_user}")

    tokens = [credentials.credentials]
    if body and body.refresh_token:
        tokens.append(body.refresh_token)

    for tok in tokens:
        try:
            payload = decode_token(tok)
        except HTTPException:
            continue  # expired/invalid tokens need no revocation
        if payload.get("sub") == current_user and payload.get("jti") and payload.get("exp"):
            await revoke_token(payload["jti"], datetime.fromtimestamp(payload["exp"], tz=timezone.utc))

    return {
        "status": "success",
        "message": "Logged out successfully. Tokens revoked."
    }


@router.get("/profile", response_model=UserProfileResponse)
@log_exceptions
async def get_profile(current_user: str = Depends(get_current_user)):
    """Get user profile information"""
    logger.info(f"Profile request for user: {current_user}")
    
    try:
        user = await get_user_by_id(current_user)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserProfileResponse(
            user_id=user.get("user_id"),
            email=user.get("email"),
            username=user.get("username"),
            created_at=user.get("created_at"),
            last_login=user.get("last_login"),
            active=user.get("active")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile retrieval error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve profile"
        )


@router.post("/change-password")
@log_exceptions
async def change_password(
    request: ChangePasswordRequest,
    current_user: str = Depends(get_current_user)
):
    """Change user password"""
    logger.info(f"Password change attempt for user: {current_user}")
    
    try:
        # Validate new passwords match
        if request.new_password != request.confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New passwords do not match"
            )
        
        # Validate password length
        if len(request.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters"
            )
        
        # Get user and verify old password
        user = await get_user_by_id(current_user)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if not verify_password(request.old_password, user.get("password_hash", "")):
            logger.warning(f"Password change failed: invalid old password for {current_user}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid old password"
            )
        
        # Update password
        from db_manager import _db_manager
        hashed_new_password = hash_password(request.new_password)

        await _db_manager.db[COLLECTION_USERS].update_one(
            {"user_id": current_user},
            {
                "$set": {
                    "password_hash": hashed_new_password,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
            }
        )
        
        logger.info(f"Password changed for user: {current_user}")
        
        return {
            "status": "success",
            "message": "Password changed successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password change error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed"
        )


@router.post("/verify-token")
@log_exceptions
async def verify_token_endpoint(current_user: str = Depends(get_current_user)):
    """Verify if token is valid"""
    return {
        "status": "success",
        "message": "Token is valid",
        "user_id": current_user
    }


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def auth_health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "auth_type": "JWT",
        "token_expire_minutes": ACCESS_TOKEN_EXPIRE_MINUTES
    }


logger.info("auth.py loaded successfully (JWT-based authentication)")
