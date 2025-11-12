"""Main FastAPI application with all endpoints"""

import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.models.schemas import (
    UserCreate, UserLogin, Token, User,
    DocumentResponse, QuestionRequest, AnswerResponse,
    EnhancedQuestionRequest, MultimodalQuestionRequest,
    ChatSessionCreate, ChatSession, ChatMessage,
    HealthResponse, ServiceStatus, Source
)
from app.services.user_service import user_service
from app.services.document_processor import document_processor
from app.services.vector_store import vector_store
from app.services.llm_service import llm_service
from app.services.chat_service import chat_service
from app.services.rag_enhanced import enhanced_rag
from app.services.image_processor import image_processor
from app.services.cleanup_service import cleanup_service
from app.utils.auth import create_access_token, get_current_user_id
from app.utils.file_handler import (
    validate_and_save_document,
    validate_and_save_image,
    delete_file,
    delete_directory
)
from app.utils.logging_config import setup_logging, get_logger

# Setup logging
setup_logging(level="INFO" if not settings.debug else "DEBUG")
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("=" * 80)
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info("=" * 80)
    
    try:
        # Initialize services
        logger.info("Initializing services...")
        
        # Initialize vector store (but NOT the embedding model yet - lazy load on first use)
        vector_store.initialize()
        # vector_store.load_embedding_model()  # REMOVED: Load on demand instead
        
        # Initialize LLM service
        llm_service.initialize()
        
        # Test Redis connection (optional)
        if settings.cache_enabled:
            try:
                import redis
                redis_client = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    socket_connect_timeout=2
                )
                redis_client.ping()
                logger.info("✓ Redis cache available")
            except Exception as e:
                logger.warning(f"Redis cache unavailable (continuing without it): {str(e)}")
        
        # Create necessary directories
        os.makedirs(settings.upload_dir, exist_ok=True)
        os.makedirs(settings.image_dir, exist_ok=True)
        
        logger.info("=" * 80)
        logger.info("✓ All services initialized successfully")
        logger.info("✓ Embedding model will load on first use (faster startup)")
        logger.info(f"✓ Server ready at http://localhost:8000")
        logger.info(f"✓ API documentation at http://localhost:8000/docs")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"✗ Failed to initialize services: {str(e)}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-ready RAG Document Chat System with multimodal support",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for frontend
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ==================== Public Endpoints ====================

@app.get("/")
async def root():
    """Serve the frontend UI"""
    frontend_index = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "status": "operational",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check endpoint"""
    services = []
    
    # Check vector store
    try:
        vector_store.initialize()
        services.append(ServiceStatus(
            name="ChromaDB",
            status="operational",
            message=f"Collections: {vector_store.collection.count()} documents"
        ))
    except Exception as e:
        services.append(ServiceStatus(
            name="ChromaDB",
            status="down",
            message=str(e)
        ))
    
    # Check embedding model
    try:
        vector_store.load_embedding_model()
        services.append(ServiceStatus(
            name="Embedding Model",
            status="operational",
            message=settings.embedding_model
        ))
    except Exception as e:
        services.append(ServiceStatus(
            name="Embedding Model",
            status="down",
            message=str(e)
        ))
    
    # Check LLM service
    try:
        llm_service.initialize()
        services.append(ServiceStatus(
            name="Gemini LLM",
            status="operational",
            message=settings.gemini_model
        ))
    except Exception as e:
        services.append(ServiceStatus(
            name="Gemini LLM",
            status="down",
            message=str(e)
        ))
    
    # Check database
    try:
        user_service.get_db_connection().close()
        services.append(ServiceStatus(
            name="User Database",
            status="operational"
        ))
    except Exception as e:
        services.append(ServiceStatus(
            name="User Database",
            status="down",
            message=str(e)
        ))
    
    # Check Redis (optional)
    if settings.cache_enabled:
        try:
            import redis
            redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                socket_connect_timeout=2
            )
            redis_client.ping()
            services.append(ServiceStatus(
                name="Redis Cache",
                status="operational"
            ))
        except Exception as e:
            services.append(ServiceStatus(
                name="Redis Cache",
                status="degraded",
                message="Optional service unavailable"
            ))
    
    # Determine overall status
    statuses = [s.status for s in services]
    if all(s == "operational" for s in statuses):
        overall_status = "healthy"
    elif any(s == "down" for s in statuses):
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"
    
    return HealthResponse(
        status=overall_status,
        services=services
    )


@app.get("/branding")
async def get_branding():
    """Get application branding and author information"""
    return {
        "author": settings.app_author,
        "branding_style": settings.branding_style,
        "branded_name": settings.branded_name,
        "tagline": settings.author_tagline,
        "bio": settings.author_bio,
        "contact": {
            "email": settings.author_email,
            "linkedin": settings.author_linkedin,
            "github": settings.author_github,
            "portfolio": settings.author_portfolio
        },
        "app_name": settings.app_name,
        "app_version": settings.app_version
    }


@app.post("/register", response_model=Token)
async def register(user_data: UserCreate):
    """Register a new user"""
    logger.info(f"Registration attempt: {user_data.username}")
    
    try:
        # Create user
        user = user_service.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password
        )
        
        # Create access token
        access_token = create_access_token(
            data={
                "sub": user['username'],
                "user_id": user['id'],
                "email": user['email']
            }
        )
        
        # Format user response
        user_response = User(
            id=user['id'],
            username=user['username'],
            email=user['email'],
            is_active=user['is_active'],
            created_at=datetime.fromisoformat(user['created_at'])
        )
        
        logger.info(f"User registered successfully: {user['username']}")
        
        return Token(
            access_token=access_token,
            user=user_response
        )
    
    except ValueError as e:
        logger.warning(f"Registration failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )


@app.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    """Login and get access token"""
    logger.info(f"Login attempt: {credentials.username}")
    
    # Authenticate user
    user = user_service.authenticate_user(
        username=credentials.username,
        password=credentials.password
    )
    
    if not user:
        logger.warning(f"Login failed for: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token = create_access_token(
        data={
            "sub": user['username'],
            "user_id": user['id'],
            "email": user['email']
        }
    )
    
    # Format user response
    user_response = User(
        id=user['id'],
        username=user['username'],
        email=user['email'],
        is_active=user['is_active'],
        created_at=datetime.fromisoformat(user['created_at'])
    )
    
    logger.info(f"User logged in: {user['username']}")
    
    return Token(
        access_token=access_token,
        user=user_response
    )


# ==================== Protected Endpoints ====================

@app.get("/me", response_model=User)
async def get_current_user_info(user_id: int = Depends(get_current_user_id)):
    """Get current user information"""
    user = user_service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return User(
        id=user['id'],
        username=user['username'],
        email=user['email'],
        is_active=user['is_active'],
        created_at=datetime.fromisoformat(user['created_at'])
    )


@app.post("/upload", response_model=List[DocumentResponse])
async def upload_documents(
    files: List[UploadFile] = File(...),
    user_id: int = Depends(get_current_user_id)
):
    """Upload and process multiple documents (up to 5 files including images) with automatic summarization"""
    logger.info(f"Document upload: {len(files)} files (user: {user_id})")
    
    # Check document limit FIRST
    limit_status = cleanup_service.check_user_document_limit(user_id)
    current_count = limit_status.get('current_documents', 0)
    max_allowed = limit_status.get('max_documents', 3)
    
    # Calculate how many documents user can still upload
    available_slots = max_allowed - current_count
    
    if available_slots <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document limit reached! You have {current_count} documents (max: {max_allowed}). "
                   f"Please delete some documents before uploading new ones."
        )
    
    if len(files) > available_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You can only upload {available_slots} more document(s). "
                   f"Current: {current_count}/{max_allowed}. Please delete some documents first."
        )
    
    # Validate file count
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {settings.max_files_per_upload} files allowed per upload"
        )
    
    if len(files) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )
    
    responses = []
    errors = []
    
    for file in files:
        try:
            logger.info(f"Processing file: {file.filename}")
            
            # Validate and save file
            file_path, file_type, file_size = await validate_and_save_document(file, user_id)
            
            # Process document (including images with OCR)
            full_text, chunks = document_processor.process_document(file_path, file_type)
            
            # Generate document ID
            document_id = str(uuid.uuid4())
            
            # Fast upload - skip automatic summarization for speed
            # Summary can be generated on-demand later if needed
            summary = f"Document: {file.filename} ({len(chunks)} sections, {len(full_text)} characters)"
            
            # Add to vector store without AI summary (MUCH faster!)
            chunk_count = vector_store.add_document(
                document_id=document_id,
                document_name=file.filename,
                chunks=chunks,
                user_id=user_id,
                metadata={
                    "file_type": file_type,
                    "file_size": file_size,
                    "file_path": file_path,
                    "summary": summary,
                    "full_text_length": len(full_text)
                }
            )
            
            logger.info(f"Document uploaded successfully: {document_id} ({chunk_count} chunks)")
            
            responses.append(DocumentResponse(
                id=document_id,
                filename=file.filename,
                file_type=file_type,
                file_size=file_size,
                chunk_count=chunk_count,
                uploaded_at=datetime.utcnow(),
                user_id=user_id,
                summary=summary  # Include summary in response
            ))
        
        except Exception as e:
            logger.error(f"Error processing {file.filename}: {str(e)}")
            errors.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    # If all files failed, raise error
    if len(responses) == 0 and len(errors) > 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process all files: {errors}"
        )
    
    # Log any partial failures
    if len(errors) > 0:
        logger.warning(f"Partial upload success. Errors: {errors}")
    
    return responses


@app.post("/upload/multimodal", response_model=DocumentResponse)
async def upload_document_multimodal(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id)
):
    """Upload document with image extraction and captioning"""
    logger.info(f"Multimodal upload: {file.filename} (user: {user_id})")
    
    try:
        # Validate and save file
        file_path, file_type, file_size = await validate_and_save_document(file, user_id)
        
        # Process document
        full_text, chunks = document_processor.process_document(file_path, file_type)
        
        # Generate document ID
        document_id = str(uuid.uuid4())
        
        # Add text chunks to vector store
        chunk_count = vector_store.add_document(
            document_id=document_id,
            document_name=file.filename,
            chunks=chunks,
            user_id=user_id,
            metadata={
                "file_type": file_type,
                "file_size": file_size,
                "file_path": file_path
            }
        )
        
        # Extract and process images if PDF
        image_count = 0
        if file_type == ".pdf":
            images = image_processor.extract_images_from_pdf(file_path, document_id, user_id)
            
            for img_info in images:
                try:
                    # Generate caption
                    caption = llm_service.generate_image_caption(img_info['path'])
                    
                    # Add to vector store
                    vector_store.add_image(
                        image_id=img_info['image_id'],
                        document_id=document_id,
                        caption=caption,
                        user_id=user_id,
                        metadata={
                            "filename": img_info['filename'],
                            "page_number": img_info['page_number'],
                            "width": img_info['width'],
                            "height": img_info['height']
                        }
                    )
                    image_count += 1
                
                except Exception as e:
                    logger.error(f"Failed to process image: {str(e)}")
        
        logger.info(f"Multimodal upload complete: {chunk_count} chunks, {image_count} images")
        
        return DocumentResponse(
            id=document_id,
            filename=file.filename,
            file_type=file_type,
            file_size=file_size,
            chunk_count=chunk_count,
            uploaded_at=datetime.utcnow(),
            user_id=user_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multimodal upload error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {str(e)}"
        )


@app.post("/upload/image")
async def upload_standalone_image(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id)
):
    """Upload standalone image"""
    logger.info(f"Image upload: {file.filename} (user: {user_id})")
    
    try:
        # Generate document ID for standalone image
        document_id = f"img_{uuid.uuid4()}"
        
        # Save image
        file_path, file_size = await validate_and_save_image(file, user_id, document_id)
        
        # Process image
        img_info = image_processor.process_image_file(file_path, document_id, user_id)
        
        # Generate caption
        caption = llm_service.generate_image_caption(file_path)
        
        # Add to vector store
        vector_store.add_image(
            image_id=img_info['image_id'],
            document_id=document_id,
            caption=caption,
            user_id=user_id,
            metadata={
                "filename": img_info['filename'],
                "width": img_info['width'],
                "height": img_info['height'],
                "standalone": True
            }
        )
        
        logger.info(f"Image uploaded: {document_id}")
        
        return {
            "message": "Image uploaded successfully",
            "document_id": document_id,
            "image_id": img_info['image_id'],
            "filename": file.filename,
            "caption": caption
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image upload error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload image: {str(e)}"
        )


@app.get("/documents", response_model=List[DocumentResponse])
async def list_documents(user_id: int = Depends(get_current_user_id)):
    """List all documents for current user with summaries"""
    logger.info(f"Listing documents for user {user_id}")
    
    try:
        documents = vector_store.list_user_documents(user_id)
        
        response = []
        for doc in documents:
            # Extract summary from metadata if available
            summary = doc.get('summary', None)
            
            response.append(DocumentResponse(
                id=doc['id'],
                filename=doc['document_name'],
                file_type=doc.get('file_type', ""),
                file_size=doc.get('file_size', 0),
                chunk_count=doc['chunk_count'],
                uploaded_at=datetime.fromisoformat(doc['created_at']) if doc['created_at'] else datetime.utcnow(),
                user_id=user_id,
                summary=summary
            ))
        
        return response
    
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents"
        )


@app.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document_details(
    document_id: str,
    user_id: int = Depends(get_current_user_id)
):
    """Get detailed information about a specific document including its summary"""
    logger.info(f"Getting details for document {document_id} (user: {user_id})")
    
    try:
        documents = vector_store.list_user_documents(user_id)
        doc = next((d for d in documents if d['id'] == document_id), None)
        
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        return DocumentResponse(
            id=doc['id'],
            filename=doc['document_name'],
            file_type=doc.get('file_type', ''),
            file_size=doc.get('file_size', 0),
            chunk_count=doc['chunk_count'],
            uploaded_at=datetime.fromisoformat(doc['created_at']) if doc.get('created_at') else datetime.utcnow(),
            user_id=user_id,
            summary=doc.get('summary')
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get document details"
        )


@app.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    user_id: int = Depends(get_current_user_id)
):
    """Delete a document and its chunks"""
    logger.info(f"Deleting document {document_id} for user {user_id}")
    
    try:
        # Delete from vector store
        deleted_count = vector_store.delete_document(document_id, user_id)
        
        if deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Delete files
        upload_dir = os.path.join(settings.upload_dir, str(user_id))
        image_dir = os.path.join(settings.image_dir, str(user_id), document_id)
        
        delete_directory(image_dir)
        
        logger.info(f"Document deleted: {document_id}")
        
        return {
            "message": "Document deleted successfully",
            "document_id": document_id,
            "chunks_deleted": deleted_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )


@app.post("/ask", response_model=AnswerResponse)
async def ask_question(
    request: QuestionRequest,
    user_id: int = Depends(get_current_user_id)
):
    """SUPER INTERACTIVE question answering - Works with OR without documents!"""
    logger.info(f"Question from user {user_id}: {request.question}")
    
    try:
        # Search for relevant chunks (even if no documents, we'll still answer!)
        results = vector_store.search(
            query=request.question,
            user_id=user_id,
            top_k=request.top_k
        )
        
        # Generate answer in SUPER INTERACTIVE mode - ALWAYS helpful!
        # Gemini AI will use documents if available, or general knowledge if not
        answer = llm_service.generate_answer(
            question=request.question,
            context_chunks=results,  # Can be empty, AI still answers!
            strict_mode=False  # SUPER INTERACTIVE: Always helpful!
        )
        
        # Format sources (if any)
        sources = [
            Source(
                document_id=r['document_id'],
                document_name=r['document_name'],
                chunk_text=r['chunk_text'],
                relevance_score=r['relevance_score'],
                page_number=r.get('metadata', {}).get('page_number')
            )
            for r in results
        ] if results else []
        
        return AnswerResponse(
            answer=answer,
            sources=sources,
            question=request.question
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error answering question: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to answer question: {str(e)}"
        )


@app.post("/ask/enhanced", response_model=AnswerResponse)
async def ask_question_enhanced(
    request: EnhancedQuestionRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Enhanced question answering with query transformation and re-ranking"""
    logger.info(f"Enhanced question from user {user_id}: {request.question}")
    
    try:
        # Get chat history if session provided
        chat_history = []
        if request.session_id:
            messages = chat_service.get_session_history(request.session_id, user_id, limit=10)
            chat_history = [
                {"role": m['role'], "content": m['content']}
                for m in messages
            ]
        
        # Transform query if there's history
        query = request.question
        if chat_history:
            query = llm_service.transform_query(request.question, chat_history)
        
        # Search for relevant chunks
        top_k_search = request.top_k * 2 if request.use_reranking else request.top_k
        results = vector_store.search(
            query=query,
            user_id=user_id,
            top_k=top_k_search
        )
        
        # Re-rank results if available and requested
        if results and request.use_reranking and len(results) > 1:
            results = enhanced_rag.rerank_results(
                query=request.question,
                results=results,
                top_k=request.top_k
            )
        elif results:
            results = results[:request.top_k]
        
        # Generate answer with history
        answer = llm_service.generate_answer(
            question=request.question,
            context_chunks=results,
            chat_history=chat_history,
            strict_mode=False
        )
        
        # Format sources
        sources = [
            Source(
                document_id=r['document_id'],
                document_name=r['document_name'],
                chunk_text=r['chunk_text'],
                relevance_score=r.get('rerank_score', r['relevance_score']),
                page_number=r.get('metadata', {}).get('page_number')
            )
            for r in results
        ] if results else []
        
        # Save to chat history if session exists
        if request.session_id:
            # Create session if it doesn't exist
            session = chat_service.get_session(request.session_id, user_id)
            if not session:
                chat_service.create_session(user_id, "New Conversation")
            
            chat_service.add_message(request.session_id, "user", request.question)
            chat_service.add_message(
                request.session_id,
                "assistant",
                answer,
                sources=[s.dict() for s in sources]
            )
        
        return AnswerResponse(
            answer=answer,
            sources=sources,
            question=request.question
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in enhanced QA: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to answer question: {str(e)}"
        )


@app.post("/ask/multimodal", response_model=AnswerResponse)
async def ask_question_multimodal(
    request: MultimodalQuestionRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Question answering with text and image results"""
    logger.info(f"Multimodal question from user {user_id}: {request.question}")
    
    try:
        # Search text chunks
        text_results = vector_store.search(
            query=request.question,
            user_id=user_id,
            top_k=request.top_k
        )
        
        # Search images if requested
        image_results = []
        if request.include_images:
            image_results = vector_store.search_images(
                query=request.question,
                user_id=user_id,
                top_k=request.top_k
            )
        
        # Merge results
        if text_results or image_results:
            merged_results = enhanced_rag.merge_multimodal_results(
                text_results=text_results,
                image_results=image_results
            )
            
            # Take top-k from merged
            merged_results = merged_results[:request.top_k]
            
            # Generate answer
            answer = llm_service.generate_answer(
                question=request.question,
                context_chunks=merged_results
            )
            
            # Format sources
            sources = []
            for r in merged_results:
                source_type = r.get('source_type', 'text')
                if source_type == 'text':
                    sources.append(Source(
                        document_id=r['document_id'],
                        document_name=r['document_name'],
                        chunk_text=r['chunk_text'],
                        relevance_score=r['relevance_score']
                    ))
                else:  # image
                    sources.append(Source(
                        document_id=r['metadata']['document_id'],
                        document_name=f"Image: {r['metadata'].get('filename', 'unknown')}",
                        chunk_text=f"[Image caption: {r['caption']}]",
                        relevance_score=r['relevance_score']
                    ))
        else:
            answer = "I don't have enough information to answer this question."
            sources = []
        
        return AnswerResponse(
            answer=answer,
            sources=sources,
            question=request.question
        )
    
    except Exception as e:
        logger.error(f"Error in multimodal QA: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to answer question: {str(e)}"
        )


@app.post("/ask/stream")
async def ask_question_stream(
    request: QuestionRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Streaming question answering"""
    logger.info(f"Streaming question from user {user_id}: {request.question}")
    
    try:
        # Search for relevant chunks
        results = vector_store.search(
            query=request.question,
            user_id=user_id,
            top_k=request.top_k
        )
        
        if not results:
            async def no_results_stream():
                yield "data: I don't have enough information to answer this question.\n\n"
            
            return StreamingResponse(
                no_results_stream(),
                media_type="text/event-stream"
            )
        
        # Stream answer
        async def answer_stream():
            # Send sources first
            sources_data = [
                {
                    "document_id": r['document_id'],
                    "document_name": r['document_name'],
                    "relevance_score": r['relevance_score']
                }
                for r in results
            ]
            
            import json
            yield f"data: {json.dumps({'sources': sources_data})}\n\n"
            
            # Stream answer
            for chunk in llm_service.generate_answer_stream(
                question=request.question,
                context_chunks=results
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            answer_stream(),
            media_type="text/event-stream"
        )
    
    except Exception as e:
        logger.error(f"Error in streaming QA: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to answer question: {str(e)}"
        )


# ==================== Chat Session Endpoints ====================

@app.post("/chat/sessions", response_model=ChatSession, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    request: ChatSessionCreate,
    user_id: int = Depends(get_current_user_id)
):
    """Create a new chat session"""
    logger.info(f"Creating chat session for user {user_id}")
    
    try:
        session_id = chat_service.create_session(user_id, request.title)
        session = chat_service.get_session(session_id, user_id)
        
        return ChatSession(
            session_id=session['session_id'],
            user_id=session['user_id'],
            title=session['title'],
            created_at=datetime.fromisoformat(session['created_at']),
            updated_at=datetime.fromisoformat(session['updated_at']),
            message_count=session['message_count']
        )
    
    except Exception as e:
        logger.error(f"Error creating chat session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create chat session"
        )


@app.get("/chat/sessions", response_model=List[ChatSession])
async def list_chat_sessions(user_id: int = Depends(get_current_user_id)):
    """List all chat sessions for current user"""
    logger.info(f"Listing chat sessions for user {user_id}")
    
    try:
        sessions = chat_service.list_user_sessions(user_id)
        
        return [
            ChatSession(
                session_id=s['session_id'],
                user_id=s['user_id'],
                title=s['title'],
                created_at=datetime.fromisoformat(s['created_at']),
                updated_at=datetime.fromisoformat(s['updated_at']),
                message_count=s['message_count']
            )
            for s in sessions
        ]
    
    except Exception as e:
        logger.error(f"Error listing sessions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list chat sessions"
        )


@app.get("/chat/sessions/{session_id}", response_model=List[ChatMessage])
async def get_chat_history(
    session_id: str,
    user_id: int = Depends(get_current_user_id)
):
    """Get chat history for a session"""
    logger.info(f"Getting history for session {session_id}")
    
    try:
        messages = chat_service.get_session_history(session_id, user_id)
        
        if not messages and not chat_service.get_session(session_id, user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found"
            )
        
        return [
            ChatMessage(
                message_id=m['message_id'],
                session_id=m['session_id'],
                role=m['role'],
                content=m['content'],
                timestamp=datetime.fromisoformat(m['timestamp']),
                sources=[Source(**s) for s in m['sources']] if m.get('sources') else None
            )
            for m in messages
        ]
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chat history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get chat history"
        )


@app.delete("/chat/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id)
):
    """Delete a chat session"""
    logger.info(f"Deleting session {session_id}")
    
    try:
        deleted = chat_service.delete_session(session_id, user_id)
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found"
            )
        
        return {
            "message": "Chat session deleted successfully",
            "session_id": session_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete chat session"
        )


# ==================== Image Endpoints ====================

@app.get("/images/{document_id}/{filename}")
async def get_image(
    document_id: str,
    filename: str,
    user_id: int = Depends(get_current_user_id)
):
    """Get an image file"""
    logger.info(f"Image request: {document_id}/{filename} (user: {user_id})")
    
    try:
        # Construct image path
        image_path = os.path.join(settings.image_dir, str(user_id), document_id, filename)
        
        # Check if file exists
        if not os.path.exists(image_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found"
            )
        
        # Verify ownership via vector store
        # (Images are stored with user_id metadata)
        
        return FileResponse(
            image_path,
            media_type="image/png",
            filename=filename
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve image"
        )


# ==================== Cleanup Endpoints ====================

@app.post("/cleanup/user")
async def cleanup_user_documents(
    user_id: int = Depends(get_current_user_id)
):
    """
    Clean up ALL documents for current user (called on logout/page close)
    This helps manage storage space by removing documents when user leaves
    """
    logger.info(f"🧹 User cleanup requested for user {user_id}")
    
    try:
        result = cleanup_service.cleanup_user_documents(user_id)
        
        return {
            "message": "User documents cleaned up successfully",
            "result": result
        }
    
    except Exception as e:
        logger.error(f"Error during user cleanup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup user documents"
        )


@app.get("/cleanup/limit-status")
async def check_document_limit(
    user_id: int = Depends(get_current_user_id)
):
    """
    Check if user has reached document upload limit
    Returns limit status and recommendations
    """
    try:
        limit_status = cleanup_service.check_user_document_limit(user_id)
        
        return limit_status
    
    except Exception as e:
        logger.error(f"Error checking document limit: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check document limit"
        )


@app.get("/cleanup/storage-stats")
async def get_storage_statistics(
    user_id: int = Depends(get_current_user_id)
):
    """
    Get storage statistics for current user
    Shows how much space their documents are using
    """
    try:
        stats = cleanup_service.get_storage_stats(user_id)
        
        return stats
    
    except Exception as e:
        logger.error(f"Error getting storage stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get storage statistics"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
