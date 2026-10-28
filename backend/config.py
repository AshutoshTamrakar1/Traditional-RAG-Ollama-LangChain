import logging
import os
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import validator, Field

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION SETTINGS - Centralized Environment Configuration
# ============================================================================

class Settings(BaseSettings):
    """
    Centralized application configuration using Pydantic BaseSettings.
    
    Note: Some configuration values are stored directly in other files:
    - Auth/token behavior → auth.py / db_manager.py
    - AI model configurations (model names, prompts) → ai_engine.py
    - RAG parameters (chunk size, overlap, top_k) → ai_engine.py
    
    This file focuses on environment, server, database, and deployment settings.
    """
    
    # ========================================================================
    # APPLICATION SETTINGS
    # ========================================================================
    
    APP_NAME: str = Field(default="Traditional RAG with Ollama and LangChain", env="APP_NAME")
    APP_VERSION: str = Field(default="2.0.0", env="APP_VERSION")
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    DEBUG: bool = Field(default=True, env="DEBUG")
    
    # ========================================================================
    # SERVER SETTINGS
    # ========================================================================
    
    HOST: str = Field(default="127.0.0.1", env="HOST")
    PORT: int = Field(default=8000, env="PORT")
    WORKERS: int = Field(default=1, env="WORKERS")
    RELOAD: bool = Field(default=True, env="RELOAD")
    
    # ========================================================================
    # DATABASE SETTINGS (MongoDB)
    # ========================================================================
    
    MONGODB_URI: str = Field(
        default="mongodb://localhost:27017/chatbot",
        env="MONGODB_URI",
        description="MongoDB connection string"
    )
    MONGODB_DB_NAME: str = Field(
        default="pdf_rag_chatbot",
        env="MONGODB_DB_NAME",
        description="MongoDB database name"
    )
    
    # ========================================================================
    # JWT AUTHENTICATION SETTINGS
    # ========================================================================
    
    JWT_SECRET_KEY: str = Field(
        default="your-super-secret-jwt-key-change-this-in-production",
        env="JWT_SECRET_KEY",
        description="Secret key for JWT token encoding/decoding"
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        env="JWT_ALGORITHM",
        description="JWT algorithm (HS256, RS256, etc.)"
    )
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60,
        env="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        description="Access token expiration time in minutes"
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        env="JWT_REFRESH_TOKEN_EXPIRE_DAYS",
        description="Refresh token expiration time in days"
    )
    
    # ========================================================================
    # VECTOR STORE SETTINGS (ChromaDB)
    # ========================================================================
    
    CHROMA_PERSIST_DIR: str = Field(
        default="./chroma_db",
        env="CHROMA_PERSIST_DIR",
        description="ChromaDB persistent storage directory"
    )
    CHROMA_COLLECTION_NAME: str = Field(
        default="pdf_documents",
        env="CHROMA_COLLECTION_NAME",
        description="Default ChromaDB collection name"
    )
    EMBEDDING_MODEL_NAME: str = Field(
        default="all-MiniLM-L6-v2",
        env="EMBEDDING_MODEL_NAME",
        description="HuggingFace embedding model name"
    )
    VECTOR_STORE_SEARCH_TYPE: str = Field(
        default="similarity",
        env="VECTOR_STORE_SEARCH_TYPE",
        description="Vector store search type: similarity, mmr, or similarity_score_threshold"
    )
    VECTOR_STORE_K: int = Field(
        default=3,
        env="VECTOR_STORE_K",
        description="Number of documents to retrieve (k)"
    )
    VECTOR_STORE_FETCH_K: int = Field(
        default=10,
        env="VECTOR_STORE_FETCH_K",
        description="Number of documents to fetch for MMR (fetch_k)"
    )
    
    # ========================================================================
    # LOGGING SETTINGS
    # ========================================================================
    
    LOG_LEVEL: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    LOG_FILE: Optional[str] = Field(
        default=None,
        env="LOG_FILE",
        description="Log file path (if None, uses default)"
    )
    
    # ========================================================================
    # FILE UPLOAD SETTINGS
    # ========================================================================
    
    UPLOAD_DIR: str = Field(
        default="./uploads",
        env="UPLOAD_DIR",
        description="Directory for uploaded PDF files"
    )
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=50,
        env="MAX_UPLOAD_SIZE_MB",
        description="Maximum upload size in MB"
    )
    ALLOWED_FILE_EXTENSIONS: List[str] = Field(
        default=["pdf"],
        description="Allowed file extensions for upload"
    )
    
    # ========================================================================
    # CORS SETTINGS
    # ========================================================================
    
    CORS_ORIGINS: List[str] = Field(
        default=["*"],
        env="CORS_ORIGINS",
        description="CORS allowed origins"
    )
    CORS_CREDENTIALS: bool = Field(
        default=True,
        env="CORS_CREDENTIALS"
    )
    CORS_METHODS: List[str] = Field(
        default=["*"],
        env="CORS_METHODS"
    )
    CORS_HEADERS: List[str] = Field(
        default=["*"],
        env="CORS_HEADERS"
    )
    
    # ========================================================================
    # PERFORMANCE SETTINGS
    # ========================================================================
    
    MAX_CONCURRENT_UPLOADS: int = Field(
        default=10,
        env="MAX_CONCURRENT_UPLOADS"
    )
    PDF_PROCESSING_TIMEOUT_SECONDS: int = Field(
        default=300,
        env="PDF_PROCESSING_TIMEOUT_SECONDS"
    )
    
    # ========================================================================
    # VALIDATORS
    # ========================================================================
    
    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        """Validate environment value"""
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v
    
    @validator("LOG_LEVEL")
    def validate_log_level(cls, v):
        """Validate log level"""
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()
    
    @validator("MAX_UPLOAD_SIZE_MB")
    def validate_upload_size(cls, v):
        """Validate upload size"""
        if v <= 0:
            raise ValueError("MAX_UPLOAD_SIZE_MB must be greater than 0")
        return v

    @validator("UPLOAD_DIR", pre=True)
    def validate_upload_dir(cls, v):
        """Ensure UPLOAD_DIR is anchored to project root when relative"""
        if not v:
            v = "./uploads"
        p = Path(v)
        if not p.is_absolute():
            repo_path = (Path(__file__).resolve().parent.parent / p).resolve()
            return str(repo_path)
        return str(p.resolve())

    @validator("CHROMA_PERSIST_DIR", pre=True)
    def validate_chroma_dir(cls, v):
        """Ensure CHROMA_PERSIST_DIR is anchored to project root when relative"""
        if not v:
            v = "./chroma_db"
        p = Path(v)
        if not p.is_absolute():
            repo_path = (Path(__file__).resolve().parent.parent / p).resolve()
            return str(repo_path)
        return str(p.resolve())
    
    @validator("CORS_ORIGINS", pre=True)
    def validate_cors_origins(cls, v):
        """Parse CORS origins from string if needed"""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    @validator("CORS_METHODS", pre=True)
    def validate_cors_methods(cls, v):
        """Parse CORS methods from string if needed"""
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [method.strip() for method in v.split(",")]
        return v
    
    @validator("CORS_HEADERS", pre=True)
    def validate_cors_headers(cls, v):
        """Parse CORS headers from string if needed"""
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [header.strip() for header in v.split(",")]
        return v
    
    model_config = SettingsConfigDict(
        env_file=(os.path.join(os.path.dirname(__file__), ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Ignore extra fields from .env
    )


# ============================================================================
# SETTINGS INSTANCE & UTILITY FUNCTIONS
# ============================================================================

_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings instance (dependency injection for FastAPI)"""
    global _settings
    
    if _settings is None:
        _settings = Settings()
        logger.info(f"Settings initialized: Environment={_settings.ENVIRONMENT}")
        logger.debug(f"Database: {_settings.MONGODB_URI}")
        logger.debug(f"Upload directory: {_settings.UPLOAD_DIR}")
    
    return _settings


def reload_settings() -> Settings:
    """Reload settings (useful for testing)"""
    global _settings
    _settings = Settings()
    logger.info("Settings reloaded")
    return _settings


# ============================================================================
# DIRECTORY INITIALIZATION
# ============================================================================

def create_upload_directories():
    """Create necessary upload and output directories"""
    settings = get_settings()
    
    directories = [
        settings.UPLOAD_DIR,
        settings.CHROMA_PERSIST_DIR,
        "./logs"
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"Directory ready: {directory}")


# ============================================================================
# ENVIRONMENT HELPERS
# ============================================================================

def is_production() -> bool:
    """Check if running in production"""
    settings = get_settings()
    return settings.ENVIRONMENT == "production"


def is_development() -> bool:
    """Check if running in development"""
    settings = get_settings()
    return settings.ENVIRONMENT == "development"


def get_max_upload_size_bytes() -> int:
    """Get max upload size in bytes"""
    settings = get_settings()
    return settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_configuration():
    """Validate critical configuration values"""
    settings = get_settings()
    errors = []
    
    # Check MongoDB URI
    if not settings.MONGODB_URI or settings.MONGODB_URI == "":
        errors.append("MONGODB_URI is not configured")
    
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        raise ValueError("Configuration validation failed. See logs for details.")
    
    logger.info("Configuration validation passed")


# ============================================================================
# INITIALIZATION
# ============================================================================

def initialize_config():
    """Initialize configuration on app startup"""
    logger.info("Initializing configuration...")
    
    try:
        # Load settings
        settings = get_settings()
        
        # Create directories
        create_upload_directories()
        
        # Validate configuration
        validate_configuration()
        
        # Log configuration summary
        logger.info(f"Application: {settings.APP_NAME} v{settings.APP_VERSION}")
        logger.info(f"Environment: {settings.ENVIRONMENT}")
        logger.info(f"Server: {settings.HOST}:{settings.PORT}")
        logger.info(f"Database: {settings.MONGODB_DB_NAME}")
        logger.info(f"Logging level: {settings.LOG_LEVEL}")
        
        return settings
    
    except Exception as e:
        logger.exception(f"Configuration initialization failed: {e}")
        raise


logger.info("config.py loaded successfully")
