"""Application settings and configuration"""

import os
from pathlib import Path
from typing import List, Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from dotenv import load_dotenv

# Load .env from multiple possible locations
possible_env_paths = [
    Path(".env"),  # Current directory
    Path("../.env"),  # Parent directory
    Path(__file__).parent.parent.parent.parent / ".env"  # Project root
]

for env_path in possible_env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=False, verbose=False)
        break


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # App Information
    app_name: str = "RAG Document Chat API"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Branding & Customization
    app_author: str = "Anthony Njoku"
    branding_style: str = "professional"  # Options: "professional" or "branded"
    branded_name: str = "AnthonyAI"  # Used when branding_style="branded"
    author_tagline: str = "AI/ML Engineer & MLops Specialist"
    author_bio: str = "AI/ML and MLops Engineer specializing in intelligent systems, backend architecture, and production-ready machine learning solutions. Expertise in building scalable AI applications, document processing pipelines, and robust backend infrastructures."
    author_email: str = "anthony@example.com"  # Update with your real email
    author_linkedin: str = "https://www.linkedin.com/in/anthony-emeka-6227782a1/"
    author_github: str = "https://github.com/starislauz"
    author_portfolio: str = "https://starislauz.github.io/myportfolio.com/"
    
    # Security
    secret_key: str = Field(
        default="09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
        description="Secret key for JWT token generation"
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days
    
    # File Upload Settings
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    allowed_extensions: List[str] = [".pdf", ".txt", ".md", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]
    allowed_image_extensions: List[str] = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"]
    max_image_size: int = 5 * 1024 * 1024  # 5 MB
    max_files_per_upload: int = 5  # Allow up to 5 files per upload
    upload_dir: str = "./uploads"
    image_dir: str = "./images"
    
    # Document Processing
    # Phase 3.2: structure-aware chunking. Chunks are packed along section and
    # paragraph boundaries up to chunk_size chars (not cut every N chars),
    # which keeps each chunk semantically coherent for retrieval and reranking.
    chunk_size: int = 1200
    chunk_overlap: int = 150
    
    # Embedding Model
    embedding_model: str = "all-MiniLM-L6-v2"
    
    # LLM Settings
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    google_api_key: str = Field(default="", description="Alternative Google API key")
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.7
    gemini_max_tokens: int = 2048

    # LLM provider for text generation: "deepseek" (recommended) or "gemini".
    # Gemini is still used for image captioning (vision) when its key is set,
    # because deepseek-chat has no vision support.
    llm_provider: str = "gemini"
    deepseek_api_key: str = Field(default="", description="DeepSeek API key")
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    
    # RAG Settings
    default_top_k: int = 5
    rerank_top_k: int = 3
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    enable_reranking: bool = True

    # Honesty guard: chunks scoring below the threshold are never sent to the
    # LLM. If nothing clears the bar, the API returns the abstain sentence.
    # - relevance_threshold: cosine similarity (0..1), used by vector-only paths.
    #   This scale is meaningful (higher = more similar).
    # - rerank_threshold: cross-encoder score used after re-ranking. Cross-encoder
    #   logits are NOT calibrated (0 is not a relevance boundary - a chunk
    #   containing the answer has measured -0.92 here), so this defaults to None:
    #   the top_k re-ranked chunks are used by rank order. Set a float to
    #   re-enable an absolute cutoff. Honesty is still enforced by the prompt,
    #   which abstains whenever the context does not contain the answer.
    relevance_threshold: float = 0.35
    rerank_threshold: Optional[float] = None

    # Hybrid search (Phase 3.1): fuse vector similarity with BM25 keyword
    # search (Reciprocal Rank Fusion) before re-ranking.
    # Measurement history (this is why it is ON):
    #   - On the synthetic golden set it tied with vector-only (Recall 1.000,
    #     MRR 0.899) - Config E2 vs Config F in eval/results/history.csv.
    #   - On real documents (a photo certificate + a multi-page PDF) vector-only
    #     missed literal codes entirely: "How many A1 is there?" returned five
    #     chunks from the wrong document. BM25 is exactly what matches literal
    #     codes, IDs and part numbers.
    # Set ENABLE_HYBRID_SEARCH=false to fall back to vector-only.
    enable_hybrid_search: bool = True
    hybrid_rrf_k: int = 60  # RRF constant: 60 = standard value

    # Semantic answer cache (Phase 4.2): reuse an answer when the same user asks
    # a near-identical question about an unchanged document set. Only used for
    # questions asked without conversation history.
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.95   # cosine similarity to count as same question
    semantic_cache_ttl: int = 3600           # seconds
    semantic_cache_max_entries: int = 200    # per user/document-set bucket
    
    # Database Settings
    chroma_db_path: str = "./backend/chroma_db"
    users_db_path: str = "./backend/users.db"
    chat_db_path: str = "./backend/chat_history.db"
    ingestion_db_path: str = "./backend/ingestion_jobs.db"
    
    # Redis Cache (Optional)
    redis_host: str = "localhost"
    redis_port: int = 6379
    cache_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour
    
    # CORS Settings - use Union to accept both string and list
    cors_origins: Union[str, List[str]] = "*"
    
    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from environment variable"""
        if isinstance(v, str):
            # Handle wildcard or comma-separated list
            if v.strip() == '*':
                return ['*']
            else:
                return [origin.strip() for origin in v.split(',') if origin.strip()]
        return v
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra="allow"
    )
    
    def get_api_key(self) -> str:
        """Get API key, checking both GEMINI_API_KEY and GOOGLE_API_KEY"""
        return self.gemini_api_key or self.google_api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")


# Global settings instance
settings = Settings()
