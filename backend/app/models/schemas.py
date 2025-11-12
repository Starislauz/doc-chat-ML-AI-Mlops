"""Pydantic models for request/response validation"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime


# User Models
class UserCreate(BaseModel):
    """User registration request"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    """User login request"""
    username: str
    password: str


class User(BaseModel):
    """User response model"""
    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    user: User


# Document Models
class DocumentUpload(BaseModel):
    """Document upload metadata"""
    filename: str
    file_type: str
    file_size: int


class DocumentResponse(BaseModel):
    """Document information response"""
    id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    uploaded_at: datetime
    user_id: int
    summary: Optional[str] = None  # AI-generated summary of document content


# Question & Answer Models
class QuestionRequest(BaseModel):
    """Basic question request"""
    question: str = Field(..., min_length=3)
    top_k: Optional[int] = Field(default=5, ge=1, le=20)


class Source(BaseModel):
    """Source document chunk"""
    document_id: str
    document_name: str
    chunk_text: str
    relevance_score: float
    page_number: Optional[int] = None


class AnswerResponse(BaseModel):
    """Answer with sources"""
    answer: str
    sources: List[Source]
    question: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EnhancedQuestionRequest(BaseModel):
    """Enhanced question with chat context"""
    question: str = Field(..., min_length=3)
    session_id: Optional[str] = None
    top_k: Optional[int] = Field(default=5, ge=1, le=20)
    use_reranking: Optional[bool] = False  # DISABLED for 2-3x faster responses!


class MultimodalQuestionRequest(BaseModel):
    """Multimodal question (text + images)"""
    question: str = Field(..., min_length=3)
    include_images: Optional[bool] = True
    top_k: Optional[int] = Field(default=5, ge=1, le=20)


# Chat Models
class ChatSessionCreate(BaseModel):
    """Create new chat session"""
    title: Optional[str] = Field(default="New Conversation")


class ChatSession(BaseModel):
    """Chat session information"""
    session_id: str
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ChatMessage(BaseModel):
    """Chat message"""
    message_id: int
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    sources: Optional[List[Source]] = None


# Health Check
class ServiceStatus(BaseModel):
    """Individual service status"""
    name: str
    status: str  # "operational", "degraded", "down"
    message: Optional[str] = None


class HealthResponse(BaseModel):
    """System health check response"""
    status: str  # "healthy", "degraded", "unhealthy"
    services: List[ServiceStatus]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Error Response
class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
