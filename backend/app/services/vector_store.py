"""Vector store service using ChromaDB"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer
import uuid
from datetime import datetime

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class VectorStore:
    """Service for managing embeddings and vector search with ChromaDB"""
    
    def __init__(self):
        """Initialize ChromaDB and embedding model"""
        self.client = None
        self.collection = None
        self.image_collection = None
        self.embedding_model = None
        logger.info("VectorStore initialized (lazy loading)")
    
    def initialize(self):
        """Initialize ChromaDB client and collections"""
        if self.client is not None:
            return
        
        logger.info("Initializing ChromaDB client...")
        
        # Initialize ChromaDB with persistent storage
        self.client = chromadb.PersistentClient(
            path=settings.chroma_db_path,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Get or create text collection
        self.collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Get or create image collection
        self.image_collection = self.client.get_or_create_collection(
            name="images",
            metadata={"hnsw:space": "cosine"}
        )
        
        logger.info(f"ChromaDB initialized at {settings.chroma_db_path}")
        logger.info(f"Text collection size: {self.collection.count()}")
        logger.info(f"Image collection size: {self.image_collection.count()}")
    
    def load_embedding_model(self):
        """Load sentence transformer model for embeddings"""
        if self.embedding_model is not None:
            return
        
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        self.embedding_model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded successfully")
    
    def add_document(
        self,
        document_id: str,
        document_name: str,
        chunks: List[str],
        user_id: int,
        metadata: Optional[Dict] = None
    ) -> int:
        """
        Add document chunks to vector store
        
        Args:
            document_id: Unique document identifier
            document_name: Name of the document
            chunks: List of text chunks
            user_id: ID of the user who owns the document
            metadata: Optional additional metadata
        
        Returns:
            Number of chunks added
        """
        self.initialize()
        self.load_embedding_model()
        
        if not chunks:
            logger.warning(f"No chunks to add for document {document_id}")
            return 0
        
        logger.info(f"Adding {len(chunks)} chunks for document {document_id}")
        
        # Generate embeddings
        embeddings = self.embedding_model.encode(chunks).tolist()
        
        # Prepare metadata for each chunk
        chunk_ids = []
        chunk_metadata = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{document_id}_chunk_{i}"
            chunk_ids.append(chunk_id)
            
            meta = {
                "document_id": document_id,
                "document_name": document_name,
                "user_id": str(user_id),
                "chunk_index": i,
                "created_at": datetime.utcnow().isoformat(),
            }
            
            if metadata:
                meta.update(metadata)
            
            chunk_metadata.append(meta)
        
        # Add to collection
        self.collection.add(
            ids=chunk_ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=chunk_metadata
        )
        
        logger.info(f"Added {len(chunks)} chunks to vector store")
        return len(chunks)
    
    def search(
        self,
        query: str,
        user_id: int,
        top_k: int = 5,
        document_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Search for relevant chunks
        
        Args:
            query: Search query
            user_id: ID of the user (for data isolation)
            top_k: Number of results to return
            document_ids: Optional list of document IDs to search within
        
        Returns:
            List of search results with metadata
        """
        self.initialize()
        self.load_embedding_model()
        
        logger.info(f"Searching for: '{query}' (user: {user_id}, top_k: {top_k})")
        
        # Generate query embedding
        query_embedding = self.embedding_model.encode([query])[0].tolist()
        
        # Build where filter for user isolation
        where_filter = {"user_id": str(user_id)}
        
        # Add document filter if specified
        if document_ids:
            where_filter = {
                "$and": [
                    {"user_id": str(user_id)},
                    {"document_id": {"$in": document_ids}}
                ]
            }
        
        # Search
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        formatted_results = []
        
        if results and results['ids'] and results['ids'][0]:
            for i in range(len(results['ids'][0])):
                result = {
                    "id": results['ids'][0][i],
                    "document_id": results['metadatas'][0][i]['document_id'],
                    "document_name": results['metadatas'][0][i]['document_name'],
                    "chunk_text": results['documents'][0][i],
                    "relevance_score": 1 - results['distances'][0][i],  # Convert distance to similarity
                    "metadata": results['metadatas'][0][i]
                }
                formatted_results.append(result)
        
        logger.info(f"Found {len(formatted_results)} results")
        return formatted_results
    
    def delete_document(self, document_id: str, user_id: int) -> int:
        """
        Delete all chunks for a document
        
        Args:
            document_id: Document identifier
            user_id: User ID for validation
        
        Returns:
            Number of chunks deleted
        """
        self.initialize()
        
        logger.info(f"Deleting document {document_id} for user {user_id}")
        
        # Get all chunk IDs for this document
        results = self.collection.get(
            where={
                "$and": [
                    {"document_id": document_id},
                    {"user_id": str(user_id)}
                ]
            },
            include=["metadatas"]
        )
        
        if not results['ids']:
            logger.warning(f"No chunks found for document {document_id}")
            return 0
        
        # Delete chunks
        self.collection.delete(ids=results['ids'])
        
        # Delete associated images
        try:
            image_results = self.image_collection.get(
                where={
                    "$and": [
                        {"document_id": document_id},
                        {"user_id": str(user_id)}
                    ]
                }
            )
            
            if image_results['ids']:
                self.image_collection.delete(ids=image_results['ids'])
                logger.info(f"Deleted {len(image_results['ids'])} images for document {document_id}")
        
        except Exception as e:
            logger.error(f"Error deleting images: {str(e)}")
        
        logger.info(f"Deleted {len(results['ids'])} chunks")
        return len(results['ids'])
    
    def list_user_documents(self, user_id: int) -> List[Dict]:
        """
        List all documents for a user with full metadata
        
        Args:
            user_id: User identifier
        
        Returns:
            List of document metadata including summaries
        """
        self.initialize()
        
        logger.info(f"Listing documents for user {user_id}")
        
        # Get all chunks for user
        results = self.collection.get(
            where={"user_id": str(user_id)},
            include=["metadatas"]
        )
        
        if not results['ids']:
            return []
        
        # Group by document and collect metadata
        documents = {}
        for metadata in results['metadatas']:
            doc_id = metadata['document_id']
            if doc_id not in documents:
                documents[doc_id] = {
                    "id": doc_id,
                    "document_name": metadata['document_name'],
                    "chunk_count": 0,
                    "created_at": metadata.get('created_at', ''),
                    "summary": metadata.get('summary', None),
                    "file_type": metadata.get('file_type', ''),
                    "file_size": metadata.get('file_size', 0),
                    "full_text_length": metadata.get('full_text_length', 0)
                }
            documents[doc_id]['chunk_count'] += 1
        
        return list(documents.values())
    
    def add_image(
        self,
        image_id: str,
        document_id: str,
        caption: str,
        user_id: int,
        metadata: Dict
    ) -> None:
        """
        Add image embedding to vector store
        
        Args:
            image_id: Unique image identifier
            document_id: Associated document ID
            caption: Image caption/description
            user_id: User ID
            metadata: Image metadata
        """
        self.initialize()
        self.load_embedding_model()
        
        logger.info(f"Adding image {image_id} for document {document_id}")
        
        # Generate embedding from caption
        embedding = self.embedding_model.encode([caption])[0].tolist()
        
        # Prepare metadata
        meta = {
            "document_id": document_id,
            "user_id": str(user_id),
            "image_id": image_id,
            "created_at": datetime.utcnow().isoformat(),
            **metadata
        }
        
        # Add to image collection
        self.image_collection.add(
            ids=[image_id],
            embeddings=[embedding],
            documents=[caption],
            metadatas=[meta]
        )
        
        logger.info(f"Added image {image_id} to vector store")
    
    def search_images(
        self,
        query: str,
        user_id: int,
        top_k: int = 5
    ) -> List[Dict]:
        """
        Search for relevant images
        
        Args:
            query: Search query
            user_id: User ID
            top_k: Number of results
        
        Returns:
            List of image results
        """
        self.initialize()
        self.load_embedding_model()
        
        logger.info(f"Searching images for: '{query}' (user: {user_id})")
        
        # Generate query embedding
        query_embedding = self.embedding_model.encode([query])[0].tolist()
        
        # Search
        results = self.image_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": str(user_id)},
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        formatted_results = []
        
        if results and results['ids'] and results['ids'][0]:
            for i in range(len(results['ids'][0])):
                result = {
                    "id": results['ids'][0][i],
                    "caption": results['documents'][0][i],
                    "relevance_score": 1 - results['distances'][0][i],
                    "metadata": results['metadatas'][0][i]
                }
                formatted_results.append(result)
        
        logger.info(f"Found {len(formatted_results)} image results")
        return formatted_results


# Global vector store instance
vector_store = VectorStore()
