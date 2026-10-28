from typing import Any, Dict, Optional
from pathlib import Path
from fastapi import HTTPException, status, Header
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

# centralized logging + decorator import
from logging_config import get_logger
from config import get_settings

logger = get_logger(__name__)
settings = get_settings()

# JWT Configuration
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM


def verify_jwt_token(token: str) -> str:
    """Verify JWT token and return user_id"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Check token type
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
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )


def get_user_from_token(authorization: Optional[str] = Header(None)) -> str:
    """Extract and validate user from Authorization header with JWT token"""
    if not authorization:
        logger.warning("Authorization header missing")
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
                detail="Invalid authentication scheme. Use Bearer token",
                headers={"WWW-Authenticate": "Bearer"}
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user_id = verify_jwt_token(token)
    logger.debug(f"User authenticated from JWT: {user_id[:20]}...")
    return user_id


def ensure_upload_dir(user_id: str, thread_id: str, source_id: str, base_dir: Path) -> Path:
    """Ensure upload directory exists and return path"""
    # Convert to Path if it's a string
    if isinstance(base_dir, str):
        base_dir = Path(base_dir)
    upload_dir = base_dir / user_id / thread_id / source_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir.resolve()


UPLOADS_PREFIX = "uploads/"


def _find_by_uploads_subpath(norm_path: str, project_root: Path, upload_dir: Path) -> Optional[str]:
    """Check candidate file paths based on 'uploads/' substring."""
    if UPLOADS_PREFIX not in norm_path:
        return None
    sub = norm_path[norm_path.index(UPLOADS_PREFIX):]
    candidate = project_root / sub
    if candidate.is_file():
        return str(candidate.resolve())
    candidate = upload_dir / sub[len(UPLOADS_PREFIX):]
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _find_by_filename(upload_dir: Path, filename: str) -> Optional[str]:
    """Search for file by basename inside upload directory."""
    if not filename or not upload_dir.exists():
        return None
    for match in upload_dir.rglob(filename):
        if match.is_file():
            return str(match.resolve())
    return None


def resolve_pdf_path(pdf_path: Optional[str]) -> Optional[str]:
    """Resolve a PDF filepath across possible root, backend, or uploads directories."""
    if not pdf_path:
        return None

    path_obj = Path(pdf_path)
    if path_obj.is_file():
        return str(path_obj.resolve())

    # Project root is 2 levels up from backend/services/utils.py
    project_root = Path(__file__).resolve().parent.parent.parent
    upload_dir = Path(get_settings().UPLOAD_DIR)

    for base in (project_root, upload_dir):
        candidate = base / pdf_path
        if candidate.is_file():
            return str(candidate.resolve())

    norm = pdf_path.replace("\\", "/")
    found = _find_by_uploads_subpath(norm, project_root, upload_dir)
    if found:
        return found

    return _find_by_filename(upload_dir, path_obj.name)


async def handle_service_error(func: callable, *args, **kwargs) -> Dict[str, Any]:
    """Generic error handler for service functions"""
    try:
        return await func(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Service error in {func.__name__}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service error: {str(e)}"
        )
