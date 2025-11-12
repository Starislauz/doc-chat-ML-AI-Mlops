"""Application settings and configuration"""

import os
from pathlib import Path
from typing import List, Union
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
        load_dotenv(env_path, override=False)
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
    chunk_size: int = 500
    chunk_overlap: int = 50
    
    # Embedding Model
    embedding_model: str = "all-MiniLM-L6-v2"
    
    # LLM Settings
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    google_api_key: str = Field(default="", description="Alternative Google API key")
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.7
    gemini_max_tokens: int = 2048
    
    # RAG Settings
    default_top_k: int = 5
    rerank_top_k: int = 3
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    enable_reranking: bool = True
    
    # Database Settings
    chroma_db_path: str = "./backend/chroma_db"
    users_db_path: str = "./backend/users.db"
    chat_db_path: str = "./backend/chat_history.db"
    
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
