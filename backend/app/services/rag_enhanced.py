"""Enhanced RAG with re-ranking and query transformation"""

from typing import List, Dict, Optional
from sentence_transformers import CrossEncoder

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class EnhancedRAG:
    """Service for advanced RAG features including re-ranking"""
    
    def __init__(self):
        """Initialize enhanced RAG"""
        self.reranker = None
        self.reranker_load_failures = 0
        logger.info("EnhancedRAG initialized (lazy loading)")
    
    def load_reranker(self):
        """Load the cross-encoder re-ranking model.

        Offline-first: a cached model loads without any network call, so a
        DNS blip cannot break a request. If loading fails, the service keeps
        working without re-ranking instead of raising a 500.
        """
        if self.reranker is not None:
            return
        if self.reranker_load_failures >= 3:
            logger.warning("Re-ranker disabled after repeated load failures")
            return
        
        logger.info(f"Loading re-ranker model: {settings.rerank_model}")
        try:
            self.reranker = CrossEncoder(
                settings.rerank_model, local_files_only=True
            )
        except KeyboardInterrupt:
            raise
        except Exception as local_error:
            logger.warning(
                f"Re-ranker not in local cache ({local_error}); downloading..."
            )
            try:
                self.reranker = CrossEncoder(settings.rerank_model)
            except KeyboardInterrupt:
                raise
            except Exception as download_error:
                self.reranker_load_failures += 1
                logger.error(
                    f"Could not load re-ranker ({download_error}). "
                    f"Continuing WITHOUT re-ranking - retrieval order will be used."
                )
                self.reranker = None
                return
        
        self.reranker_load_failures = 0
        logger.info("Re-ranker model loaded successfully")
    
    @property
    def reranker_available(self) -> bool:
        """True when scores from the last rerank pass are cross-encoder scores."""
        return self.reranker is not None
    
    def rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_k: Optional[int] = None
    ) -> List[Dict]:
        """
        Re-rank search results using cross-encoder
        
        Args:
            query: Search query
            results: Initial search results
            top_k: Number of top results to keep
        
        Returns:
            Re-ranked results
        """
        if not results:
            return results
        
        self.load_reranker()
        
        # No re-ranker (e.g. model not downloadable): degrade gracefully by
        # keeping the retrieval order instead of failing the request.
        if self.reranker is None:
            logger.warning("Re-ranker unavailable - using retrieval order")
            return results[:top_k] if top_k else results
        
        logger.info(f"Re-ranking {len(results)} results")
        
        # Prepare query-document pairs
        pairs = []
        for result in results:
            chunk_text = result.get('chunk_text', result.get('caption', ''))
            pairs.append([query, chunk_text])
        
        # Get scores from cross-encoder
        scores = self.reranker.predict(pairs)
        
        # Add rerank scores to results
        for i, result in enumerate(results):
            result['rerank_score'] = float(scores[i])
        
        # Sort by rerank score
        reranked = sorted(results, key=lambda x: x['rerank_score'], reverse=True)
        
        # Keep top-k
        if top_k:
            reranked = reranked[:top_k]
        
        logger.info(f"Re-ranked results, kept top {len(reranked)}")
        return reranked
    
    def apply_relevance_cutoff(
        self,
        results: List[Dict],
        threshold: float,
        max_chunks: int,
        score_key: str = "relevance_score"
    ) -> List[Dict]:
        """
        Drop chunks that score below the relevance threshold.

        Barely-relevant chunks are the main source of hallucination: if the
        LLM sees them it will try to use them. If nothing clears the bar an
        empty list is returned and the caller must abstain.

        Args:
            results: Candidate chunks (any order).
            threshold: Minimum score (inclusive) for a chunk to be kept, or
                None to disable the score cutoff (rank order is then used).
            max_chunks: Hard cap on how many chunks to keep.
            score_key: Which score field to compare ('relevance_score',
                'rerank_score', or 'weighted_score').

        Returns:
            Chunks at/above threshold, best first, capped at max_chunks.
        """
        if not results:
            return []
        
        if threshold is None:
            # No score cutoff: cross-encoder logits are uncalibrated, so rank
            # order decides. Honesty is enforced by the prompt, which abstains
            # when the context does not contain the answer.
            ordered = sorted(
                results,
                key=lambda r: r.get(score_key) if r.get(score_key) is not None else 0.0,
                reverse=True
            )
            return ordered[:max_chunks]
        
        above = [
            r for r in results
            if r.get(score_key) is not None and r[score_key] >= threshold
        ]
        above.sort(key=lambda r: r.get(score_key, 0.0), reverse=True)
        return above[:max_chunks]
    
    def generate_query_variations(self, query: str) -> List[str]:
        """
        Generate variations of the query for better retrieval
        
        Args:
            query: Original query
        
        Returns:
            List of query variations
        """
        # Simple query variations (can be enhanced with LLM)
        variations = [query]
        
        # Add question variations
        if not query.endswith('?'):
            variations.append(query + '?')
        
        # Add lowercase version
        if query != query.lower():
            variations.append(query.lower())
        
        # Add title case version
        if query != query.title():
            variations.append(query.title())
        
        return list(set(variations))
    
    def merge_multimodal_results(
        self,
        text_results: List[Dict],
        image_results: List[Dict],
        text_weight: float = 0.7,
        image_weight: float = 0.3
    ) -> List[Dict]:
        """
        Merge and rank text and image results
        
        Args:
            text_results: Text search results
            image_results: Image search results
            text_weight: Weight for text results
            image_weight: Weight for image results
        
        Returns:
            Merged and ranked results
        """
        # Add source type and weighted score
        for result in text_results:
            result['source_type'] = 'text'
            result['weighted_score'] = result.get('relevance_score', 0) * text_weight
        
        for result in image_results:
            result['source_type'] = 'image'
            result['weighted_score'] = result.get('relevance_score', 0) * image_weight
        
        # Merge and sort by weighted score
        all_results = text_results + image_results
        merged = sorted(all_results, key=lambda x: x['weighted_score'], reverse=True)
        
        logger.info(f"Merged {len(text_results)} text + {len(image_results)} image results")
        return merged
    
    def extract_keywords(self, text: str, max_keywords: int = 5) -> List[str]:
        """
        Extract keywords from text for query expansion
        
        Args:
            text: Input text
            max_keywords: Maximum number of keywords
        
        Returns:
            List of keywords
        """
        # Simple keyword extraction (can be enhanced with NLP)
        words = text.lower().split()
        
        # Filter stopwords
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these',
            'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which',
            'who', 'when', 'where', 'why', 'how'
        }
        
        keywords = [w for w in words if w not in stopwords and len(w) > 3]
        
        # Get most frequent
        from collections import Counter
        keyword_counts = Counter(keywords)
        top_keywords = [k for k, _ in keyword_counts.most_common(max_keywords)]
        
        return top_keywords
    
    def calculate_diversity_score(self, results: List[Dict]) -> float:
        """
        Calculate diversity of results (different documents)
        
        Args:
            results: Search results
        
        Returns:
            Diversity score (0-1)
        """
        if not results:
            return 0.0
        
        unique_docs = len(set(r.get('document_id', '') for r in results))
        total_results = len(results)
        
        return unique_docs / total_results if total_results > 0 else 0.0
    
    def diversify_results(
        self,
        results: List[Dict],
        target_diversity: float = 0.5
    ) -> List[Dict]:
        """
        Diversify results to include multiple documents
        
        Args:
            results: Search results
            target_diversity: Target diversity ratio
        
        Returns:
            Diversified results
        """
        if not results:
            return results
        
        # Group by document
        doc_groups = {}
        for result in results:
            doc_id = result.get('document_id', 'unknown')
            if doc_id not in doc_groups:
                doc_groups[doc_id] = []
            doc_groups[doc_id].append(result)
        
        # Round-robin selection from different documents
        diversified = []
        max_per_doc = max(1, int(len(results) * target_diversity))
        
        while len(diversified) < len(results):
            added = False
            for doc_id, group in doc_groups.items():
                if group and len([r for r in diversified if r.get('document_id') == doc_id]) < max_per_doc:
                    diversified.append(group.pop(0))
                    added = True
            
            if not added:
                break
        
        logger.info(f"Diversified results: {len(doc_groups)} documents represented")
        return diversified


# Global enhanced RAG instance
enhanced_rag = EnhancedRAG()
