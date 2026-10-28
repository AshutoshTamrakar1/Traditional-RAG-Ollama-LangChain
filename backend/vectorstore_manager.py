"""
Vector Store Manager for ChromaDB integration.

This module provides a clean abstraction layer for ChromaDB operations,
including document storage, retrieval, and collection management.
"""

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from typing import List, Optional, Tuple
import logging

from config import get_settings

logger = logging.getLogger(__name__)

# Get settings instance
settings = get_settings()


class VectorStoreManager:
    """Manages ChromaDB vector store operations for PDF document retrieval."""
    
    def __init__(self):
        """Initialize ChromaDB client and embeddings model."""
        self._client = None
        self._embeddings = None
        self._vectorstore_cache = {}  # Cache Chroma instances by collection name
        
    @property
    def client(self) -> chromadb.PersistentClient:
        """Lazy initialization of ChromaDB client."""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=settings.CHROMA_PERSIST_DIR,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"ChromaDB client initialized at {settings.CHROMA_PERSIST_DIR}")
        return self._client
    
    @property
    def embeddings(self) -> HuggingFaceEmbeddings:
        """Lazy initialization of embeddings model."""
        if self._embeddings is None:
            try:
                self._embeddings = HuggingFaceEmbeddings(
                    model_name=settings.EMBEDDING_MODEL_NAME,
                    model_kwargs={'device': 'cpu', 'local_files_only': True},
                    encode_kwargs={'normalize_embeddings': True}
                )
            except Exception:
                self._embeddings = HuggingFaceEmbeddings(
                    model_name=settings.EMBEDDING_MODEL_NAME,
                    model_kwargs={'device': 'cpu'},
                    encode_kwargs={'normalize_embeddings': True}
                )
            logger.info(f"Embeddings model initialized: {settings.EMBEDDING_MODEL_NAME}")
        return self._embeddings
    
    def get_vectorstore(self, collection_name: str) -> Chroma:
        """
        Get or create a Chroma vectorstore for a specific collection.
        
        Args:
            collection_name: Name of the collection (typically PDF ID or unified collection)
            
        Returns:
            Chroma vectorstore instance
        """
        if collection_name not in self._vectorstore_cache:
            self._vectorstore_cache[collection_name] = Chroma(
                client=self.client,
                collection_name=collection_name,
                embedding_function=self.embeddings
            )
            logger.info(f"Vectorstore created/loaded for collection: {collection_name}")
        
        return self._vectorstore_cache[collection_name]
    
    def add_documents(
        self,
        documents: List[Document],
        collection_name: str,
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """
        Add documents to a ChromaDB collection.
        
        Args:
            documents: List of LangChain Document objects with page_content and metadata
            collection_name: Name of the collection to add documents to
            ids: Optional list of document IDs (will auto-generate if not provided)
            
        Returns:
            List of document IDs that were added
        """
        vectorstore = self.get_vectorstore(collection_name)
        
        try:
            doc_ids = vectorstore.add_documents(documents=documents, ids=ids)
            logger.info(f"Added {len(documents)} documents to collection '{collection_name}'")
            return doc_ids
        except Exception as e:
            logger.exception(f"Failed to add documents to collection '{collection_name}': {e}")
            raise
    
    def similarity_search(
        self,
        query: str,
        collection_name: str,
        k: Optional[int] = None,
        filter: Optional[dict] = None
    ) -> List[Document]:
        """
        Perform similarity search in a ChromaDB collection.
        
        Args:
            query: Query text to search for
            collection_name: Name of the collection to search in
            k: Number of results to return (defaults to settings.VECTOR_STORE_K)
            filter: Optional metadata filter
            
        Returns:
            List of Document objects ordered by similarity
        """
        vectorstore = self.get_vectorstore(collection_name)
        k = k or settings.VECTOR_STORE_K
        
        try:
            results = vectorstore.similarity_search(query=query, k=k, filter=filter)
            logger.info(f"Found {len(results)} results for query in collection '{collection_name}'")
            return results
        except Exception as e:
            logger.exception(f"Similarity search failed in collection '{collection_name}': {e}")
            raise
    
    def similarity_search_with_score(
        self,
        query: str,
        collection_name: str,
        k: Optional[int] = None,
        filter: Optional[dict] = None
    ) -> List[Tuple[Document, float]]:
        """
        Perform similarity search with relevance scores.
        
        Args:
            query: Query text to search for
            collection_name: Name of the collection to search in
            k: Number of results to return (defaults to settings.VECTOR_STORE_K)
            filter: Optional metadata filter
            
        Returns:
            List of (Document, score) tuples ordered by similarity
        """
        vectorstore = self.get_vectorstore(collection_name)
        k = k or settings.VECTOR_STORE_K
        
        try:
            results = vectorstore.similarity_search_with_score(query=query, k=k, filter=filter)
            logger.info(f"Found {len(results)} results with scores for query in collection '{collection_name}'")
            return results
        except Exception as e:
            logger.exception(f"Similarity search with score failed in collection '{collection_name}': {e}")
            raise
    
    def delete_collection(self, collection_name: str) -> None:
        """
        Delete a ChromaDB collection.
        
        Args:
            collection_name: Name of the collection to delete
        """
        try:
            # Remove from cache if exists
            if collection_name in self._vectorstore_cache:
                del self._vectorstore_cache[collection_name]
            
            # Delete from ChromaDB
            self.client.delete_collection(name=collection_name)
            logger.info(f"Deleted collection: {collection_name}")
        except Exception as e:
            logger.exception(f"Failed to delete collection '{collection_name}': {e}")
            raise
    
    def collection_exists(self, collection_name: str) -> bool:
        """
        Check if a collection exists in ChromaDB.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            True if collection exists, False otherwise
        """
        try:
            collections = self.client.list_collections()
            return any(col.name == collection_name for col in collections)
        except Exception as e:
            logger.exception(f"Failed to check collection existence '{collection_name}': {e}")
            return False
    
    def get_collection_count(self, collection_name: str) -> int:
        """
        Get the number of documents in a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Number of documents in the collection
        """
        try:
            vectorstore = self.get_vectorstore(collection_name)
            collection = vectorstore._collection
            return collection.count()
        except Exception as e:
            logger.exception(f"Failed to get count for collection '{collection_name}': {e}")
            return 0
    
    def list_collections(self) -> List[str]:
        """
        List all collections in ChromaDB.
        
        Returns:
            List of collection names
        """
        try:
            collections = self.client.list_collections()
            return [col.name for col in collections]
        except Exception as e:
            logger.exception(f"Failed to list collections: {e}")
            return []
    
    def as_retriever(self, collection_name: str, **kwargs):
        """
        Get a LangChain retriever interface for a collection.
        
        Args:
            collection_name: Name of the collection
            **kwargs: Additional arguments for retriever configuration
                     (search_type, search_kwargs, etc.)
            
        Returns:
            VectorStoreRetriever instance
        """
        vectorstore = self.get_vectorstore(collection_name)
        
        # Set defaults from settings if not provided
        search_type = kwargs.get('search_type', settings.VECTOR_STORE_SEARCH_TYPE)
        search_kwargs = kwargs.get('search_kwargs', {'k': settings.VECTOR_STORE_K})
        
        return vectorstore.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )


# Global singleton instance
_vectorstore_manager = None


def get_vectorstore_manager() -> VectorStoreManager:
    """Get the global VectorStoreManager singleton instance."""
    global _vectorstore_manager
    if _vectorstore_manager is None:
        _vectorstore_manager = VectorStoreManager()
    return _vectorstore_manager
