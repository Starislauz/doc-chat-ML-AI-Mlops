"""Vector store service using ChromaDB"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer
import hashlib
import math
import re
import uuid
from collections import Counter, OrderedDict
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
        # In-process embedding cache: the same text is never encoded twice.
        # Keyed by normalisation flag + text hash; bounded, FIFO-evicted.
        self._embedding_cache: "OrderedDict[str, List[float]]" = OrderedDict()
        self._embedding_cache_max = 2048
        self.embedding_cache_hits = 0
        self.embedding_cache_misses = 0
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
        """Load the sentence-transformer embedding model.

        Offline-first: a cached model loads without any network call, so a
        DNS blip cannot break search.
        """
        if self.embedding_model is not None:
            return
        
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        try:
            self.embedding_model = SentenceTransformer(
                settings.embedding_model, local_files_only=True
            )
        except KeyboardInterrupt:
            raise
        except Exception as local_error:
            logger.warning(
                f"Embedding model not in local cache ({local_error}); downloading..."
            )
            self.embedding_model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded successfully")
    
    @staticmethod
    def _embedding_cache_key(text: str, normalize_embeddings: bool) -> str:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return f"{int(normalize_embeddings)}:{digest}"
    
    def _encode(
        self,
        texts: List[str],
        normalize_embeddings: bool = False
    ) -> List[List[float]]:
        """Encode texts, reusing cached vectors for identical inputs.

        Cuts cost and latency: repeated queries and re-uploaded documents never
        reach the model twice.
        """
        if self.embedding_model is None:
            raise RuntimeError("Embedding model unavailable")
        
        results: List[Optional[List[float]]] = [None] * len(texts)
        pending = []
        
        for index, text in enumerate(texts):
            key = self._embedding_cache_key(text, normalize_embeddings)
            cached = self._embedding_cache.get(key)
            if cached is not None:
                self._embedding_cache.move_to_end(key)
                self.embedding_cache_hits += 1
                results[index] = cached
            else:
                pending.append((index, key, text))
        
        if pending:
            vectors = self.embedding_model.encode(
                [item[2] for item in pending],
                normalize_embeddings=normalize_embeddings,
            )
            for (index, key, _), vector in zip(pending, vectors):
                as_list = [float(x) for x in vector]
                results[index] = as_list
                self.embedding_cache_misses += 1
                self._embedding_cache[key] = as_list
                self._embedding_cache.move_to_end(key)
            while len(self._embedding_cache) > self._embedding_cache_max:
                self._embedding_cache.popitem(last=False)
        
        return results
    
    def embedding_cache_stats(self) -> Dict:
        total = self.embedding_cache_hits + self.embedding_cache_misses
        return {
            "entries": len(self._embedding_cache),
            "max_entries": self._embedding_cache_max,
            "hits": self.embedding_cache_hits,
            "misses": self.embedding_cache_misses,
            "hit_rate": round(self.embedding_cache_hits / total, 3) if total else 0.0,
        }
    
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
        
        # Generate embeddings (cached: identical text is never encoded twice)
        embeddings = self._encode(chunks)
        
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
        
        if self.embedding_model is None:
            raise RuntimeError(
                "Embedding model unavailable - check the server log for the "
                "model download error"
            )
        
        logger.info(f"Searching for: '{query}' (user: {user_id}, top_k: {top_k})")
        
        # Generate query embedding (cached)
        query_embedding = self._encode([query])[0]
        
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
    
    # ------------------------------------------------------------------
    # Hybrid search (vector + BM25 keyword, fused with RRF)
    # ------------------------------------------------------------------
    
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Lowercase alphanumeric tokenization for keyword matching."""
        return re.findall(r"[a-z0-9]+", (text or "").lower())
    
    def _bm25_search(
        self,
        query: str,
        user_id: int,
        document_ids: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Lightweight BM25 keyword search over the user's chunks.

        Fine for small corpora (thousands of chunks or fewer). Catches the
        exact names, IDs and codes that pure vector search misses.
        """
        where_filter = {"user_id": str(user_id)}
        if document_ids:
            where_filter = {
                "$and": [
                    {"user_id": str(user_id)},
                    {"document_id": {"$in": document_ids}}
                ]
            }
        
        data = self.collection.get(
            where=where_filter,
            include=["documents", "metadatas"]
        )
        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not ids:
            return []
        
        tokenized = [self._tokenize(d) for d in docs]
        query_terms = self._tokenize(query)
        if not query_terms:
            return []
        
        k1, b = 1.5, 0.75
        doc_lengths = [len(t) for t in tokenized]
        avgdl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0
        
        df = {}
        for tokens in tokenized:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1
        n_docs = len(tokenized)
        idf = {
            term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        
        scored = []
        for i, tokens in enumerate(tokenized):
            tf = Counter(tokens)
            score = 0.0
            for term in query_terms:
                if term not in tf:
                    continue
                t = tf[term]
                denom = t + k1 * (1 - b + b * doc_lengths[i] / avgdl)
                score += idf.get(term, 0.0) * (t * (k1 + 1)) / denom
            if score > 0:
                scored.append((i, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for i, score in scored[:limit]:
            meta = metas[i] if i < len(metas) else {}
            results.append({
                "id": ids[i],
                "document_id": meta.get("document_id", ""),
                "document_name": meta.get("document_name", ""),
                "chunk_text": docs[i],
                # Raw BM25 score; only its rank matters in RRF fusion.
                "relevance_score": score,
                "metadata": meta,
            })
        return results
    
    def _rrf_fuse(
        self,
        ranked_lists: List[List[Dict]],
        top_k: int,
        k: int = 60
    ) -> List[Dict]:
        """
        Reciprocal Rank Fusion: combine multiple ranked lists without caring
        about their score scales (cosine 0..1 vs BM25). score = 1 / (k + rank).
        """
        scores = {}
        entries = {}
        for results in ranked_lists:
            for rank, r in enumerate(results, start=1):
                key = r["id"]
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
                entries.setdefault(key, r)
        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [entries[key] for key, _ in fused]
    
    def search_hybrid(
        self,
        query: str,
        user_id: int,
        top_k: int = 5,
        document_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Hybrid retrieval: vector similarity + BM25 keyword search, fused with
        RRF. Returns the same result shape as search().
        """
        self.initialize()
        self.load_embedding_model()
        
        logger.info(f"Hybrid search for: '{query}' (user: {user_id}, top_k: {top_k})")
        
        vector_results = self.search(
            query=query,
            user_id=user_id,
            top_k=top_k * 2,
            document_ids=document_ids
        )
        keyword_results = self._bm25_search(
            query=query,
            user_id=user_id,
            document_ids=document_ids,
            limit=top_k * 2
        )
        
        fused = self._rrf_fuse(
            [vector_results, keyword_results],
            top_k=top_k,
            k=settings.hybrid_rrf_k
        )
        logger.info(f"Hybrid search: {len(vector_results)} vector + "
                    f"{len(keyword_results)} keyword -> {len(fused)} fused")
        return fused
    
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
