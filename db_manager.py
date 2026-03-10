import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from logging_config import get_logger, log_exceptions
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = get_logger(__name__)

# ============================================================================
# MONGODB CONNECTION & CONFIGURATION
# ============================================================================

class MongoDBManager:
    """Async MongoDB connection manager using Motor

    Usage:
        _db_manager = MongoDBManager()
        await _db_manager.connect(mongo_uri, database_name)
    """
    _instance = None
    _client: Optional[AsyncIOMotorClient] = None
    _db = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MongoDBManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    async def connect(self, mongo_uri: Optional[str] = None, database_name: Optional[str] = None):
        if self._initialized:
            return

        # allow explicit params or fallback to env
        mongo_uri = mongo_uri or os.getenv("MONGODB_URI")
        database_name = database_name or os.getenv("MONGODB_DB_NAME")

        if not mongo_uri:
            raise ValueError("MONGODB_URI environment variable is not set")
        if not database_name:
            raise ValueError("MONGODB_DB_NAME environment variable is not set")

        logger.info(f"Connecting to MongoDB at {mongo_uri} (async)")
        try:
            self._client = AsyncIOMotorClient(mongo_uri)
            # Motor does not require explicit ping to construct client, but test the connection
            await self._client.admin.command("ping")
            logger.info("MongoDB async connection successful")
            self._db = self._client[database_name]
            await self._initialize_collections()
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB (async): {e}")
            raise

    async def _initialize_collections(self):
        """Create collections and set up indexes (async)"""
        try:
            # Create collections if they don't exist
            existing = await self._db.list_collection_names()
            if "users" not in existing:
                await self._db.create_collection("users")
                logger.info("Created 'users' collection")
            
            if "chat_sessions" not in existing:
                await self._db.create_collection("chat_sessions")
                logger.info("Created 'chat_sessions' collection")

            # If there's an old unique index on the legacy 'id' field that indexes NULLs
            # (causing duplicate-key errors on insert), attempt to drop it so we can
            # re-create safer indexes. Not all deployments will have this index.
            try:
                existing_indexes = await self._db.chat_sessions.index_information()
                if "id_1" in existing_indexes and existing_indexes["id_1"].get("unique"):
                    logger.info("Dropping legacy unique index 'id_1' on chat_sessions to avoid duplicate-null conflicts")
                    await self._db.chat_sessions.drop_index("id_1")
            except Exception as e:
                # Non-fatal — log and continue
                logger.debug(f"No legacy id_1 index to drop or error checking indexes: {e}")

            if "sessions" not in existing:
                await self._db.create_collection("sessions")
                logger.info("Created 'sessions' collection")

            if "pdf_metadata" not in existing:
                await self._db.create_collection("pdf_metadata")
                logger.info("Created 'pdf_metadata' collection")
            
            # Create indexes for users collection
            await self._db.users.create_index("user_id", unique=True)
            await self._db.users.create_index("email", unique=True, sparse=True)
            # Ensure username uniqueness at DB level as well
            await self._db.users.create_index("username", unique=True, sparse=True)
            await self._db.users.create_index("created_at", background=True)
            
            # Create indexes for chat_sessions collection (use chat_session_id field)
            # Use a partial index so documents missing chat_session_id (or with null)
            # do not cause a duplicate-key build failure (common during migration/testing).
            # Only index chat_session_id when it's a non-null string value so null
            # / non-string legacy records are skipped by the index build.
            await self._db.chat_sessions.create_index(
                "chat_session_id",
                unique=True,
                partialFilterExpression={"chat_session_id": {"$type": "string"}}
            )
            await self._db.chat_sessions.create_index("user_id", background=True)
            await self._db.chat_sessions.create_index("created_at", background=True)
            await self._db.chat_sessions.create_index([("user_id", DESCENDING), ("created_at", DESCENDING)], background=True)

            # Create indexes for sessions collection
            # Use partial index to skip documents missing session_id (pre-existing NULLs)
            await self._db.sessions.create_index(
                "session_id",
                unique=True,
                partialFilterExpression={"session_id": {"$type": "string"}}
            )
            await self._db.sessions.create_index("user_id", background=True)
            await self._db.sessions.create_index("created_at", background=True)

            # Create indexes for pdf metadata
            await self._db.pdf_metadata.create_index("pdf_id", unique=True)
            await self._db.pdf_metadata.create_index("uploaded_at", background=True)
            
            logger.info("Database indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error initializing collections: {e}")
            raise

    @property
    def db(self):
        """Get database instance"""
        if self._db is None:
            raise RuntimeError("Database not initialized. Call __init__ first.")
        return self._db

    async def close(self):
        """Close MongoDB connection (async)"""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")


# Initialize MongoDB manager
_db_manager = MongoDBManager()


# Export collection names as constants
COLLECTION_USERS = "users"
COLLECTION_CHAT_SESSIONS = "chat_sessions"
COLLECTION_PDF_METADATA = "pdf_metadata"

# Note: Session management has been migrated to JWT tokens (stateless authentication)
# The COLLECTION_SESSIONS and related functions have been removed

# PDF METADATA FUNCTIONS
@log_exceptions
async def add_pdf_metadata(metadata: Dict[str, Any]) -> None:
    """Add PDF metadata to collection"""
    metadata.setdefault("created_at", datetime.utcnow().isoformat())
    await _db_manager.db[COLLECTION_PDF_METADATA].insert_one(metadata)
    logger.info(f"PDF metadata added: {metadata.get('pdf_id')}")

@log_exceptions
async def get_pdf_metadata(pdf_id: str) -> Optional[Dict[str, Any]]:
    """Get PDF metadata by pdf_id"""
    return await _db_manager.db[COLLECTION_PDF_METADATA].find_one({"pdf_id": pdf_id})


# ============================================================================
# USER MANAGEMENT FUNCTIONS
# ============================================================================

@log_exceptions
async def create_user(user_id: str, email: str = None, username: str = None) -> Dict[str, Any]:
    """Create a new user"""
    user_doc = {
        "user_id": user_id,
        "email": email,
        "username": username,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "last_login": None,
        "active": True
    }
    
    result = await _db_manager.db[COLLECTION_USERS].insert_one(user_doc)
    logger.info(f"User created: {user_id}")
    return user_doc


@log_exceptions
async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user by user_id"""
    user = await _db_manager.db[COLLECTION_USERS].find_one({"user_id": user_id})
    return user


@log_exceptions
async def update_user_last_login(user_id: str) -> None:
    """Update user's last login timestamp"""
    await _db_manager.db[COLLECTION_USERS].update_one(
        {"user_id": user_id},
        {"$set": {"last_login": datetime.utcnow().isoformat()}}
    )
    logger.info(f"Updated last login for user: {user_id}")


@log_exceptions
async def delete_user(user_id: str) -> None:
    """Soft delete user (mark as inactive)"""
    await _db_manager.db[COLLECTION_USERS].update_one(
        {"user_id": user_id},
        {"$set": {"active": False, "updated_at": datetime.utcnow().isoformat()}}
    )
    logger.info(f"User marked as inactive: {user_id}")


# ============================================================================
# CHAT SESSION MANAGEMENT FUNCTIONS
# ============================================================================

@log_exceptions
async def create_chat_session_in_db(chat_session: Dict[str, Any]) -> None:
    """Create a new chat session in database"""
    # Ensure required fields
    if "chat_session_id" not in chat_session:
        raise ValueError("chat_session must have 'chat_session_id' field")
    if "user_id" not in chat_session:
        raise ValueError("chat_session must have 'user_id' field")
    
    # Set default values
    chat_session.setdefault("title", "New Chat")
    chat_session.setdefault("created_at", datetime.utcnow().isoformat())
    chat_session.setdefault("updated_at", datetime.utcnow().isoformat())
    chat_session.setdefault("messages", [])
    chat_session.setdefault("sources", [])
    chat_session.setdefault("deleted", False)
    
    await _db_manager.db[COLLECTION_CHAT_SESSIONS].insert_one(chat_session)
    logger.info(f"Chat session created: {chat_session['chat_session_id']} for user: {chat_session['user_id']}")


@log_exceptions
async def get_chat_session_by_id(chat_session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get chat session by ID (ensure user ownership)"""
    # First try the new field name, fallback to legacy 'id' for backward compatibility
    session = await _db_manager.db[COLLECTION_CHAT_SESSIONS].find_one({
        "chat_session_id": chat_session_id,
        "user_id": user_id,
        "deleted": False
    })

    if not session:
        session = await _db_manager.db[COLLECTION_CHAT_SESSIONS].find_one({
            "id": chat_session_id,
            "user_id": user_id,
            "deleted": False
        })
    return session


@log_exceptions
async def get_user_chat_session_list(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get all chat sessions for a user, sorted by most recent"""
    cursor = _db_manager.db[COLLECTION_CHAT_SESSIONS].find(
        {"user_id": user_id, "deleted": False},
        {"sources": 0, "messages": 0}  # Exclude large fields for list view
    ).sort("created_at", DESCENDING).limit(limit)
    raw_sessions = await cursor.to_list(length=limit)
    # Normalize field names (support legacy 'id' -> 'chat_session_id')
    sessions = []
    for s in raw_sessions:
        if 'chat_session_id' not in s and 'id' in s:
            s['chat_session_id'] = s.pop('id')
        sessions.append(s)
    return sessions


@log_exceptions
async def update_chat_session_field(chat_session_id: str, update_dict: Dict[str, Any]) -> None:
    """Update specific fields in a chat session"""
    update_dict["updated_at"] = datetime.utcnow().isoformat()
    
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {"$set": update_dict}
    )
    
    if result.matched_count == 0:
        logger.warning(f"Chat session not found: {chat_session_id}")
    else:
        logger.info(f"Chat session updated: {chat_session_id}")


@log_exceptions
async def rename_chat_session_title(chat_session_id: str, new_title: str) -> None:
    """Rename a chat session"""
    await update_chat_session_field(chat_session_id, {"title": new_title})
    logger.info(f"Chat session renamed: {chat_session_id} to '{new_title}'")


@log_exceptions
async def mark_chat_session_as_deleted(chat_session_id: str) -> None:
    """Soft delete a chat session (mark as deleted)"""
    await update_chat_session_field(chat_session_id, {"deleted": True})
    logger.info(f"Chat session marked as deleted: {chat_session_id}")


# ============================================================================
# SOURCE/PDF MANAGEMENT FUNCTIONS
# ============================================================================

@log_exceptions
async def add_source_to_chat_session(chat_session_id: str, source: Dict[str, Any]) -> None:
    """Add a PDF source to a chat session"""
    if "source_id" not in source:
        raise ValueError("source must have 'source_id' field")
    
    source.setdefault("uploaded_at", datetime.utcnow().isoformat())
    source.setdefault("related_questions", [])
    source.setdefault("mindmap", {"path": None, "chat_messages": []})
    source.setdefault("podcast", {"data": None})
    
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {
            "$push": {"sources": source},
            "$set": {"updated_at": datetime.utcnow().isoformat()}
        }
    )
    if result.matched_count == 0:
        logger.warning(f"Chat session not found while adding source: {chat_session_id}")
    logger.info(f"Source added to chat session: {chat_session_id}, source: {source['source_id']}")


@log_exceptions
async def update_source_field(chat_session_id: str, source_id: str, update_dict: Dict[str, Any]) -> None:
    """Update fields of a specific source within a chat session"""
    # Use positional operator ($) to update array element
    query_dict = {}
    for key, value in update_dict.items():
        query_dict[f"sources.$.{key}"] = value
    
    query_dict["updated_at"] = datetime.utcnow().isoformat()
    
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "sources.source_id": source_id, "deleted": False},
        {"$set": query_dict}
    )
    
    if result.matched_count == 0:
        logger.warning(f"Source not found: {source_id} in chat session: {chat_session_id}")
    else:
        logger.info(f"Source updated: {source_id}")


@log_exceptions
async def get_source_by_id(chat_session_id: str, source_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific source from a chat session"""
    session = await _db_manager.db[COLLECTION_CHAT_SESSIONS].find_one(
        {"chat_session_id": chat_session_id, "sources.source_id": source_id, "deleted": False},
        {"sources.$": 1}
    )
    
    if session and session.get("sources"):
        return session["sources"][0]
    return None


@log_exceptions
async def add_filename_to_uploaded_list(chat_session_id: str, filename: str) -> None:
    """Add filename to the uploaded files list"""
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {
            "$addToSet": {"uploaded_files": filename},
            "$set": {"updated_at": datetime.utcnow().isoformat()}
        }
    )
    if result.matched_count == 0:
        logger.warning(f"Chat session not found while adding filename: {chat_session_id}")
    else:
        logger.info(f"File added to uploaded list: {filename}")


# ============================================================================
# MESSAGE/TURN MANAGEMENT FUNCTIONS
# ============================================================================

@log_exceptions
async def add_turn_to_general_chat(chat_session_id: str, turn: Dict[str, Any]) -> None:
    """Add a chat turn to general chat (no specific PDF source)"""
    if "id" not in turn:
        raise ValueError("turn must have 'id' field")
    
    turn.setdefault("timestamp", datetime.utcnow().isoformat())
    
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {
            "$push": {"messages": turn},
            "$set": {"updated_at": datetime.utcnow().isoformat()}
        }
    )
    if result.matched_count == 0:
        logger.warning(f"Chat session not found while adding turn: {chat_session_id}")
    else:
        logger.info(f"Turn added to general chat: {chat_session_id}")


@log_exceptions
async def add_turn_to_multi_source_chat(
    chat_session_id: str,
    source_ids: List[str],
    turn: Dict[str, Any]
) -> None:
    """Add a chat turn that references multiple PDF sources"""
    if "id" not in turn:
        raise ValueError("turn must have 'id' field")
    
    turn.setdefault("timestamp", datetime.utcnow().isoformat())
    turn["source_ids"] = source_ids
    
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {
            "$push": {"messages": turn},
            "$set": {"updated_at": datetime.utcnow().isoformat()}
        }
    )
    if result.matched_count == 0:
        logger.warning(f"Chat session not found while adding multi-source turn: {chat_session_id}")
    else:
        logger.info(f"Multi-source turn added: {chat_session_id}, sources: {source_ids}")


@log_exceptions
async def add_question_to_source(
    chat_session_id: str,
    source_id: str,
    question_turn: Dict[str, Any]
) -> None:
    """Add a Q&A turn to a specific source"""
    if "id" not in question_turn:
        raise ValueError("question_turn must have 'id' field")
    
    question_turn.setdefault("timestamp", datetime.utcnow().isoformat())
    
    # Add to general messages
    result1 = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {
            "$push": {"messages": question_turn},
            "$set": {"updated_at": datetime.utcnow().isoformat()}
        }
    )
    
    # Also add to source's related questions
    result2 = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "sources.source_id": source_id, "deleted": False},
        {
            "$push": {"sources.$.related_questions": question_turn},
            "$set": {"updated_at": datetime.utcnow().isoformat()}
        }
    )
    if (result1.matched_count == 0) and (result2.matched_count == 0):
        logger.warning(f"Chat session or source not found while adding question: {source_id}")
    else:
        logger.info(f"Question added to source: {source_id}")


@log_exceptions
async def get_chat_messages(chat_session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get chat messages from a session"""
    session = await _db_manager.db[COLLECTION_CHAT_SESSIONS].find_one(
        {"chat_session_id": chat_session_id, "deleted": False},
        {"messages": {"$slice": -limit}}
    )
    
    if session:
        return session.get("messages", [])
    return []


@log_exceptions
async def add_feedback_to_turn(
    chat_session_id: str,
    turn_id: str,
    feedback: Dict[str, Any]
) -> None:
    """Add user feedback to a chat turn"""
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_one(
        {"chat_session_id": chat_session_id, "messages.id": turn_id, "deleted": False},
        {"$set": {"messages.$.feedback": feedback, "updated_at": datetime.utcnow().isoformat()}}
    )
    if result.matched_count == 0:
        logger.warning(f"Turn not found while adding feedback: {turn_id}")
    else:
        logger.info(f"Feedback added to turn: {turn_id}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

@log_exceptions
async def get_user_chat_session_count(user_id: str) -> int:
    """Get total number of chat sessions for a user"""
    count = await _db_manager.db[COLLECTION_CHAT_SESSIONS].count_documents({
        "user_id": user_id,
        "deleted": False
    })
    return count


@log_exceptions
async def search_chat_sessions_by_title(user_id: str, search_term: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search chat sessions by title"""
    cursor = _db_manager.db[COLLECTION_CHAT_SESSIONS].find(
        {
            "user_id": user_id,
            "deleted": False,
            "title": {"$regex": search_term, "$options": "i"}
        },
        {"sources": 0, "messages": 0}
    ).sort("created_at", DESCENDING)
    results = await cursor.to_list(length=limit)
    return results


@log_exceptions
async def cleanup_old_sessions(days: int = 30) -> int:
    """Delete sessions older than specified days (soft delete)"""
    from datetime import timedelta
    
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
    
    result = await _db_manager.db[COLLECTION_CHAT_SESSIONS].update_many(
        {"created_at": {"$lt": cutoff_date}, "deleted": False},
        {"$set": {"deleted": True, "updated_at": datetime.utcnow().isoformat()}}
    )
    
    logger.info(f"Cleaned up {result.modified_count} old sessions (older than {days} days)")
    return result.modified_count


@log_exceptions
async def export_chat_session(chat_session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Export full chat session data (for backup/analysis)"""
    # Try new field first, then fall back to legacy 'id'
    session = await _db_manager.db[COLLECTION_CHAT_SESSIONS].find_one({
        "chat_session_id": chat_session_id,
        "user_id": user_id,
        "deleted": False
    })

    if not session:
        session = await _db_manager.db[COLLECTION_CHAT_SESSIONS].find_one({
            "id": chat_session_id,
            "user_id": user_id,
            "deleted": False
        })
    return session


# ============================================================================
# HEALTH CHECK
# ============================================================================

async def check_database_connection() -> bool:
    """Check if database connection is active"""
    try:
        await _db_manager.db.command('ping')
        logger.info("Database health check: OK")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


logger.info("db_manager.py loaded successfully")
