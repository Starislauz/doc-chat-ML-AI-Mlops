"""Semantic answer cache (Phase 4.2).

Reuses a previous answer when the same user asks a near-identical question
about an unchanged document set.

Deliberately conservative:

* keyed by user AND a fingerprint of their document set, so uploading or
  deleting a document silently invalidates old entries;
* only consulted for questions asked WITHOUT conversation history, so a cached
  answer can never be replayed into a different conversation;
* answers are cached only when they were produced by the LLM (never for
  degraded/service-unavailable responses);
* entries expire after a TTL and the cache is size-bounded.

Query embeddings come from the same model used for retrieval and are served
from the embedding cache, so a lookup costs one encode at most.
"""

import hashlib
import time
from collections import OrderedDict
from typing import Dict, List, Optional

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity for already-normalised vectors."""
    return float(sum(x * y for x, y in zip(a, b)))


class SemanticCache:
    """Embedding-similarity cache for document-grounded answers."""

    def __init__(self):
        # key = "<user_id>:<document fingerprint>" -> list of entries (newest first)
        self._entries: "OrderedDict[str, List[Dict]]" = OrderedDict()
        # user_id -> (timestamp, fingerprint); short TTL so a cache lookup does
        # not re-scan the vector store on every request
        self._fingerprints: Dict[int, tuple] = {}
        self.hits = 0
        self.misses = 0

    # ---------------------------------------------------------------- internals
    def _embed(self, text: str) -> Optional[List[float]]:
        try:
            from .vector_store import vector_store
            vector_store.load_embedding_model()
            if vector_store.embedding_model is None:
                return None
            vector = vector_store._encode([text], normalize_embeddings=True)[0]
            return vector
        except Exception as exc:
            logger.warning(f"Semantic cache embedding failed: {exc}")
            return None

    def _fingerprint(self, user_id: int) -> str:
        """Hash of the user's current document set (invalidates stale entries)."""
        cached = self._fingerprints.get(user_id)
        if cached and time.time() - cached[0] < 60:
            return cached[1]
        
        try:
            from .vector_store import vector_store
            docs = vector_store.list_user_documents(user_id) or []
            ids = sorted(str(doc.get("id", "")) for doc in docs)
        except Exception as exc:
            logger.warning(f"Semantic cache fingerprint failed: {exc}")
            ids = []
        
        fingerprint = hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:16]
        self._fingerprints[user_id] = (time.time(), fingerprint)
        return fingerprint

    def _prune(self, bucket: List[Dict]) -> List[Dict]:
        cutoff = time.time() - settings.semantic_cache_ttl
        return [entry for entry in bucket if entry["ts"] >= cutoff]

    # --------------------------------------------------------------- public API
    def get(self, question: str, user_id: int) -> Optional[Dict]:
        """Return a cached answer for a near-identical question, or None."""
        if not settings.semantic_cache_enabled:
            return None

        embedding = self._embed(question)
        if embedding is None:
            return None

        key = f"{user_id}:{self._fingerprint(user_id)}"
        bucket = self._prune(self._entries.get(key, []))
        if bucket:
            self._entries[key] = bucket

        best, best_similarity = None, 0.0
        for entry in bucket:
            similarity = _cosine(embedding, entry["embedding"])
            if similarity > best_similarity:
                best, best_similarity = entry, similarity

        if best is not None and best_similarity >= settings.semantic_cache_threshold:
            self.hits += 1
            logger.info(
                f"Semantic cache HIT (similarity {best_similarity:.3f}) "
                f"for: {question[:60]}"
            )
            return {
                "answer": best["answer"],
                "sources": best["sources"],
                "matched_question": best["question"],
                "similarity": round(best_similarity, 4),
            }

        self.misses += 1
        return None

    def put(self, question: str, user_id: int, answer: str, sources: List[Dict]) -> None:
        """Store an answer for this question and document set."""
        if not settings.semantic_cache_enabled:
            return

        embedding = self._embed(question)
        if embedding is None:
            return

        key = f"{user_id}:{self._fingerprint(user_id)}"
        bucket = self._prune(self._entries.get(key, []))
        bucket.insert(0, {
            "question": question,
            "embedding": embedding,
            "answer": answer,
            "sources": sources,
            "ts": time.time(),
        })
        del bucket[settings.semantic_cache_max_entries:]
        self._entries[key] = bucket
        self._entries.move_to_end(key)

        # Bound the number of user/document-set buckets
        while len(self._entries) > 500:
            self._entries.popitem(last=False)

    def stats(self) -> Dict:
        total = self.hits + self.misses
        return {
            "enabled": settings.semantic_cache_enabled,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "buckets": len(self._entries),
            "threshold": settings.semantic_cache_threshold,
            "ttl_seconds": settings.semantic_cache_ttl,
        }


# Global cache instance
semantic_cache = SemanticCache()
