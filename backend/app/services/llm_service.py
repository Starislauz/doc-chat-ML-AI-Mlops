"""Google Gemini LLM service with Redis caching"""

import google.generativeai as genai
from typing import List, Dict, Optional, Iterator
import json
import os
import time
import socket
import ssl
import certifi
import httpx
import hashlib

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class LLMService:
    """Service for interacting with Google Gemini API with caching"""
    
    def __init__(self):
        """Initialize Gemini client and Redis cache"""
        self.client = None
        self.api_key = None
        self.network_available = True
        self.last_network_check = 0
        self.http_client = None
        self.redis_client = None
        logger.info("LLMService initialized (lazy loading)")
        
        # Initialize Redis cache if enabled
        if settings.cache_enabled:
            try:
                import redis
                self.redis_client = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    socket_connect_timeout=2,
                    decode_responses=True
                )
                self.redis_client.ping()
                logger.info("✓ Redis cache connected for LLM service")
            except Exception as e:
                logger.warning(f"Redis cache unavailable: {e}")
                self.redis_client = None
    
    def _get_cache_key(self, question: str, context_summary: str) -> str:
        """Generate cache key from question and context"""
        content = f"{question}:{context_summary}"
        return f"llm_answer:{hashlib.md5(content.encode()).hexdigest()}"
    
    def _get_cached_answer(self, cache_key: str) -> Optional[str]:
        """Get cached answer if available"""
        if not self.redis_client:
            return None
        
        try:
            cached = self.redis_client.get(cache_key)
            if cached:
                logger.info("✓ Cache HIT - Returning cached answer")
                return cached
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
        
        return None
    
    def _cache_answer(self, cache_key: str, answer: str):
        """Cache the answer"""
        if not self.redis_client:
            return
        
        try:
            self.redis_client.setex(
                cache_key,
                settings.cache_ttl,  # TTL from settings (default 3600s = 1 hour)
                answer
            )
            logger.info("✓ Answer cached for future requests")
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
    
    def _create_http_client(self) -> httpx.Client:
        """
        Create HTTP client with custom SSL settings for better compatibility
        
        Returns:
            Configured httpx.Client
        """
        try:
            # Try with certifi certificates first (most compatible)
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            
            # Set TLS version to be more permissive (some proxies/firewalls need this)
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
            
            logger.info("Created HTTP client with certifi SSL context")
        except Exception as e:
            logger.warning(f"Failed to create strict SSL context: {e}, using default")
            ssl_context = ssl.create_default_context()
        
        # Create HTTP client with timeout and retry settings
        http_client = httpx.Client(
            timeout=httpx.Timeout(
                connect=10.0,  # Connection timeout
                read=60.0,     # Read timeout (important for long responses)
                write=10.0,    # Write timeout
                pool=10.0      # Pool timeout
            ),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0
            ),
            verify=ssl_context,
            http2=True,  # Enable HTTP/2 for better performance
            follow_redirects=True
        )
        
        return http_client
    
    
    def _check_network_connectivity(self) -> bool:
        """
        Check if network connection to Google API is available
        
        Returns:
            True if network is reachable
        """
        # Cache network check for 30 seconds
        current_time = time.time()
        if current_time - self.last_network_check < 30:
            return self.network_available
        
        self.last_network_check = current_time
        
        try:
            # Try to resolve Google's API endpoint
            socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=5)
            self.network_available = True
            logger.info("Network connectivity check: OK")
            return True
        except (socket.gaierror, socket.timeout, OSError) as e:
            self.network_available = False
            logger.warning(f"Network connectivity check failed: {str(e)}")
            return False
    
    def _retry_with_backoff(self, func, max_retries=3, initial_delay=1):
        """
        Retry function with exponential backoff
        
        Args:
            func: Function to retry
            max_retries: Maximum number of retries
            initial_delay: Initial delay in seconds
        
        Returns:
            Function result
        """
        delay = initial_delay
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Check if it's a retryable error (network, SSL, timeout, connection)
                retryable_errors = [
                    '11001', 'getaddrinfo', 'connection', 'timeout', 'network',
                    'ssl', 'eof occurred', 'unexpected_eof', 'certificate',
                    'handshake', 'protocol', 'broken pipe', 'connection reset'
                ]
                
                is_retryable = any(err in error_str for err in retryable_errors)
                
                if is_retryable and attempt < max_retries - 1:
                    logger.warning(f"Retryable error on attempt {attempt + 1}/{max_retries}: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                    
                    # Recreate HTTP client on SSL errors
                    if 'ssl' in error_str or 'eof' in error_str or 'protocol' in error_str:
                        logger.info("Recreating HTTP client due to SSL/connection error")
                        try:
                            if self.http_client:
                                self.http_client.close()
                            self.http_client = self._create_http_client()
                        except Exception as client_error:
                            logger.warning(f"Failed to recreate HTTP client: {client_error}")
                    
                    continue
                
                # For non-retryable errors or last attempt, raise
                if not is_retryable:
                    logger.error(f"Non-retryable error: {str(e)}")
                raise e
        
        # All retries failed
        raise last_error
    
    def initialize(self):
        """Configure Gemini API"""
        if self.client is not None:
            return
        
        self.api_key = settings.get_api_key()
        
        if not self.api_key:
            raise ValueError(
                "Gemini API key not found. Please set GEMINI_API_KEY or GOOGLE_API_KEY in .env file"
            )
        
        logger.info("Initializing Gemini API...")
        
        # Set API key as environment variable for the client
        os.environ['GOOGLE_API_KEY'] = self.api_key
        
        # Configure Gemini API (google-generativeai uses genai.configure, not Client)
        try:
            genai.configure(api_key=self.api_key)
            self.client = genai  # Store reference to the module for compatibility
            logger.info(f"Gemini API initialized with model: {settings.gemini_model}")
        except Exception as e:
            logger.error(f"Failed to configure Gemini API: {e}")
            raise
    
    def generate_answer(
        self,
        question: str,
        context_chunks: List[Dict],
        chat_history: Optional[List[Dict]] = None,
        strict_mode: bool = False
    ) -> str:
        """
        Generate answer using Gemini with SUPER INTERACTIVE mode + CACHING
        
        Args:
            question: User's question
            context_chunks: Relevant document chunks (can be empty)
            chat_history: Optional conversation history
            strict_mode: If True, only answer from provided context (for document-only mode)
        
        Returns:
            Generated answer - ALWAYS helpful and educational
        """
        self.initialize()
        
        logger.info(f"Generating answer for: '{question}' (strict_mode={strict_mode})")
        
        # Build context from chunks
        context = self._build_context(context_chunks)
        
        # Generate cache key (simpler summary for caching)
        context_summary = f"{len(context_chunks)}_chunks" if context_chunks else "no_context"
        cache_key = self._get_cache_key(question, context_summary)
        
        # Check cache first (HUGE speed boost!)
        cached_answer = self._get_cached_answer(cache_key)
        if cached_answer:
            return cached_answer
        
        # Cache miss - generate new answer
        logger.info("Cache MISS - Generating new answer...")
        
        # Check network connectivity first
        if not self._check_network_connectivity():
            logger.error("No network connectivity to Google API")
            return self._generate_offline_response(question, context_chunks)
        
        # Build SUPER INTERACTIVE prompt
        prompt = self._build_prompt(question, context, chat_history, strict_mode)
        
        try:
            # Generate response with retry logic
            def _generate():
                model = genai.GenerativeModel(settings.gemini_model)
                
                # SPEED OPTIMIZATION: Configure generation for faster responses
                generation_config = {
                    "temperature": settings.gemini_temperature,
                    "max_output_tokens": settings.gemini_max_tokens,
                    "top_p": 0.8,  # Faster sampling
                    "top_k": 40    # Faster token selection
                }
                
                response = model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                return response.text
            
            answer = self._retry_with_backoff(_generate, max_retries=5, initial_delay=2)
            
            # Cache the answer for future requests
            self._cache_answer(cache_key, answer)
            
            logger.info(f"Generated answer ({len(answer)} chars)")
            return answer
        
        except Exception as e:
            logger.error(f"Error generating answer: {str(e)}")
            error_str = str(e).lower()
            
            # Check if it's a network/SSL/connection error
            network_errors = [
                '11001', 'getaddrinfo', 'connection', 'timeout', 'network',
                'ssl', 'eof occurred', 'unexpected_eof', 'certificate',
                'handshake', 'protocol'
            ]
            
            if any(err in error_str for err in network_errors):
                logger.warning("Network/SSL error detected, providing offline response")
                return self._generate_offline_response(question, context_chunks)
            
            # For other errors, provide intelligent fallback
            return self._generate_intelligent_fallback(question, context_chunks, error_str)
    
    def _generate_intelligent_fallback(self, question: str, context_chunks: List[Dict], error_msg: str) -> str:
        """
        Generate intelligent fallback when AI generation fails
        
        Args:
            question: User's question
            context_chunks: Retrieved context
            error_msg: Error message
        
        Returns:
            Helpful fallback response
        """
        logger.info("Generating intelligent fallback response")
        
        if context_chunks:
            # We have document context, show it intelligently
            response = f"""🤖 **AI Assistant** (Processing Issue)

**Your Question:** {question}

I encountered a temporary issue connecting to the full Gemini AI, but I found relevant information:

📚 **Relevant Content:**

"""
            for i, chunk in enumerate(context_chunks[:2], 1):
                doc_name = chunk.get('document_name', 'Unknown')
                chunk_text = chunk.get('chunk_text', '')
                response += f"**From {doc_name}:**\n{chunk_text[:400]}...\n\n"
            
            response += "\n💡 Please try asking again in a moment for a complete AI-analyzed answer!"
            return response
        
        # No context, provide helpful guidance
        return f"""🤖 **AI Assistant**

**Your Question:** {question}

I'm ready to help! However, I encountered a brief technical issue. Here's what you can do:

1. **Try Again:** Refresh and ask your question again
2. **Upload Documents:** If you have relevant files, upload them first
3. **Rephrase:** Try asking the question in a different way
4. **Wait a Moment:** Sometimes a brief wait resolves connection issues

**Remember:** This system is powered by Anthony's AI, which can help with:
- Educational questions and explanations
- Research and analysis
- Document understanding
- Homework and study help
- Concept breakdowns
- And virtually any topic!

I'm here to help you learn and understand! 🎓"""
    
    def _generate_offline_response(self, question: str, context_chunks: List[Dict]) -> str:
        """
        Generate INTELLIGENT response when network is unavailable
        Uses retrieved context + smart formatting
        
        Args:
            question: User's question
            context_chunks: Retrieved context chunks
        
        Returns:
            Formatted helpful response
        """
        logger.info("Generating INTELLIGENT offline response from context")
        
        if not context_chunks:
            return f"""🤖 **AI Assistant Response** (Offline Mode)

**Your Question:** {question}

⚠️ I'm currently unable to connect to the Gemini AI service due to a network issue. However, I want to help you!

**What I Can Do:**
While I can't access my full AI capabilities right now, here's what I recommend:

1. **Check Your Connection:** Verify your internet is working
2. **Try Again Soon:** Network issues are usually temporary
3. **Upload Documents:** If you have relevant documents, upload them so I can search locally
4. **Ask Specific Questions:** Once connected, I can provide detailed explanations about any topic

**Note:** This system is powered by Anthony's AI, which provides comprehensive answers to:
- Study questions and homework help
- Research and explanations
- Concept clarifications
- Document analysis
- And much more!

Once the connection is restored, I'll be able to give you a complete answer! 🚀"""
        
        # Format context chunks into an intelligent response
        response = f"""🤖 **AI Assistant Response** (Offline Mode)

**Your Question:** {question}

⚠️ I'm currently unable to connect to the full AI service, but I found relevant information in your uploaded documents:

📚 **Information from Your Documents:**

"""
        
        for i, chunk in enumerate(context_chunks[:3], 1):  # Show top 3 chunks
            doc_name = chunk.get('document_name', 'Unknown')
            chunk_text = chunk.get('chunk_text', chunk.get('caption', ''))
            score = chunk.get('relevance_score', 0)
            
            response += f"\n**[Document {i}]** {doc_name} (Relevance: {score:.0%})\n\n"
            response += f"{chunk_text[:600]}{'...' if len(chunk_text) > 600 else ''}\n\n"
            response += "---\n"
        
        response += f"""
💡 **Quick Summary:**
Based on these document excerpts, the information relates to your question about "{question}".

**Note:** Once the Gemini AI connection is restored, I'll be able to provide a much more comprehensive, analyzed answer with:
- Detailed explanations
- Connected concepts
- Examples and illustrations
- Step-by-step breakdowns
- Additional context

**Troubleshooting:** Check your internet connection, firewall settings, or try again in a moment.
"""
        
        return response
    
    def generate_answer_stream(
        self,
        question: str,
        context_chunks: List[Dict],
        chat_history: Optional[List[Dict]] = None
    ) -> Iterator[str]:
        """
        Generate answer with streaming
        
        Args:
            question: User's question
            context_chunks: Relevant document chunks
            chat_history: Optional conversation history
        
        Yields:
            Answer chunks
        """
        self.initialize()
        
        logger.info(f"Generating streaming answer for: '{question}'")
        
        # Check network connectivity
        if not self._check_network_connectivity():
            logger.error("No network connectivity for streaming")
            yield self._generate_offline_response(question, context_chunks)
            return
        
        # Build context and prompt
        context = self._build_context(context_chunks)
        prompt = self._build_prompt(question, context, chat_history)
        
        try:
            # Generate streaming response using new SDK
            model = genai.GenerativeModel(settings.gemini_model)
            response = model.generate_content(prompt, stream=True)
            
            for chunk in response:
                if hasattr(chunk, 'text') and chunk.text:
                    yield chunk.text
        
        except Exception as e:
            logger.error(f"Error in streaming generation: {str(e)}")
            error_str = str(e).lower()
            
            # Check if it's a network error
            if any(err in error_str for err in ['11001', 'getaddrinfo', 'connection', 'timeout', 'network']):
                logger.warning("Network error during streaming, providing offline response")
                yield "\n\n⚠️ **Network Error**\n\n"
                yield self._generate_offline_response(question, context_chunks)
            else:
                yield f"\n\n[Error: {str(e)}]"
    
    def _build_context(self, chunks: List[Dict]) -> str:
        """Build context string from chunks"""
        if not chunks:
            return "No relevant context found."
        
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            doc_name = chunk.get('document_name', 'Unknown')
            chunk_text = chunk.get('chunk_text', chunk.get('caption', ''))
            score = chunk.get('relevance_score', 0)
            
            context_parts.append(
                f"[Source {i}] {doc_name} (relevance: {score:.2f})\n{chunk_text}"
            )
        
        return "\n\n".join(context_parts)
    
    def _build_prompt(
        self,
        question: str,
        context: str,
        chat_history: Optional[List[Dict]] = None,
        strict_mode: bool = False
    ) -> str:
        """Build prompt for Gemini - SUPER INTERACTIVE MODE"""
        
        if strict_mode:
            # Get branding info
            from app.config.settings import settings
            author_name = settings.app_author
            
            system_message = f"""You are a highly intelligent AI teaching assistant created by {author_name}.

🎯 YOUR MISSION:
Help students learn, understand, and discover knowledge through intelligent conversation.

📚 DOCUMENT-FIRST APPROACH:
1. If documents are provided, analyze them thoroughly and answer from the content
2. Cite sources: [Source N] when using document information
3. If documents don't contain the answer but are related, acknowledge what's in the documents first

🧠 INTELLIGENT ASSISTANCE:
Even if information isn't in documents:
- Provide educational explanations and context
- Break down complex topics simply
- Offer examples and analogies
- Guide students to understanding
- Suggest related topics to explore

💬 INTERACTION STYLE:
- Be conversational and engaging
- Ask clarifying questions when needed
- Encourage critical thinking
- Provide step-by-step explanations
- Use examples to illustrate points
- Be supportive and encouraging

❌ NEVER SAY:
- "I don't have information about this"
- "This is not available"
- "I can't help with that"

✅ INSTEAD DO:
- "Let me explain this concept..."
- "Based on what I know about this topic..."
- "Here's how this works..."
- "Let me break this down for you..."

"""
        else:
            # Get branding info
            from app.config.settings import settings
            author_name = settings.app_author
            branded_name = settings.branded_name
            branding_style = settings.branding_style
            
            # Create intro based on branding style
            if branding_style == "professional":
                intro = f"I'm {author_name}'s AI assistant"
            else:
                intro = f"I'm {branded_name}, powered by {author_name}"
            
            system_message = f"""You are an EXTREMELY INTELLIGENT and HELPFUL AI assistant created by {author_name}.

👋 INTRODUCTION:
{intro}, here to help you with document analysis and any questions you have.

🌟 YOUR SUPERPOWER:
You are a knowledge expert that can help with ANYTHING - whether from uploaded documents or your vast training knowledge.

🎯 DUAL-MODE OPERATION:

**MODE 1: Document-Based (If context provided)**
- Analyze documents thoroughly
- Extract key information
- Cite sources [Source N]
- Connect document content to the question

**MODE 2: General Knowledge (Always available)**
- Explain concepts clearly
- Provide educational content
- Answer research questions
- Help with homework and learning
- Offer examples and illustrations
- Break down complex topics

💡 INTERACTION PRINCIPLES:

1. **Always Be Helpful**: Never refuse to answer. Always try to assist.

2. **Be Educational**: Explain concepts, don't just answer. Help students LEARN.

3. **Be Engaging**: Use examples, analogies, and clear language.

4. **Be Thorough**: Provide comprehensive answers with context.

5. **Be Smart**: 
   - If documents exist: Use them + your knowledge
   - If no documents: Use your vast knowledge
   - If unclear: Ask clarifying questions

6. **Be Interactive**:
   - "Let me explain..."
   - "Here's what you need to know..."
   - "Think of it this way..."
   - "For example..."

❌ FORBIDDEN PHRASES:
- "I don't have enough information"
- "I can't help with that"
- "This is not available"
- "I don't know"

✅ POWER PHRASES:
- "Great question! Let me explain..."
- "Here's a comprehensive answer..."
- "Based on my knowledge..."
- "Let me break this down..."
- "Here's what's interesting about this..."
- "To help you understand..."

🎓 SUBJECT AREAS YOU MASTER:
- Science, Math, Technology
- History, Literature, Arts
- Programming, Data Science
- Business, Economics
- Languages, Writing
- Research Methods
- Study Skills
- And literally everything else!

Remember: You're an advanced AI assistant created by {author_name}. Use that power to EDUCATE and ASSIST fearlessly!

"""
        
        # Add chat history if available
        history_text = ""
        if chat_history:
            history_text = "\n📜 CONVERSATION HISTORY:\n"
            for msg in chat_history[-5:]:  # Last 5 messages
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                emoji = "👤" if role == "user" else "🤖"
                history_text += f"{emoji} {role.upper()}: {content}\n"
            history_text += "\n"
        
        # Build context section
        context_section = ""
        if context and context != "No relevant context found.":
            context_section = f"""📚 DOCUMENT CONTEXT AVAILABLE:
{context}

"""
        
        prompt = f"""{system_message}
{history_text}
{context_section}
❓ STUDENT'S QUESTION: {question}

💬 YOUR COMPREHENSIVE, HELPFUL RESPONSE:
"""
        
        return prompt
    
    def generate_image_caption(self, image_path: str) -> str:
        """
        Generate caption for an image using Gemini Vision
        
        Args:
            image_path: Path to image file
        
        Returns:
            Generated caption
        """
        self.initialize()
        
        logger.info(f"Generating caption for image: {image_path}")
        
        # Check network connectivity
        if not self._check_network_connectivity():
            logger.warning("No network connectivity for image captioning")
            return f"Image: {os.path.basename(image_path)} (Network unavailable for AI description)"
        
        try:
            # Read image file
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            # Detect MIME type from file extension
            ext = os.path.splitext(image_path)[1].lower()
            mime_type_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp',
                '.webp': 'image/webp',
                '.tiff': 'image/tiff',
                '.tif': 'image/tiff'
            }
            mime_type = mime_type_map.get(ext, 'image/jpeg')  # Default to JPEG
            
            logger.info(f"Processing image with MIME type: {mime_type}")
            
            # Generate caption using vision model
            prompt = """Describe this image in detail. Extract and transcribe ANY TEXT you see in the image EXACTLY as it appears.

Include:
1. ALL TEXT visible in the image (transcribe it word-for-word)
2. Main objects and subjects
3. Actions or activities
4. Setting and context
5. Important visual details

If there is text in the image, start your response with "TEXT FOUND:" followed by the exact text.

Provide a clear, comprehensive description that would be useful for search and retrieval."""
            
            # Use multimodal content with retry logic
            def _generate_caption():
                try:
                    # Upload the file to Gemini first
                    uploaded_file = genai.upload_file(path=image_path)
                    
                    # Generate content using the uploaded file
                    model = genai.GenerativeModel(settings.gemini_model)
                    response = model.generate_content([prompt, uploaded_file])
                    
                    # Clean up the uploaded file
                    try:
                        genai.delete_file(name=uploaded_file.name)
                    except:
                        pass  # Ignore cleanup errors
                    
                    return response.text
                except Exception as upload_error:
                    # Fallback: Try using PIL Image object (alternative method)
                    logger.warning(f"File upload failed, trying PIL Image method: {str(upload_error)}")
                    from PIL import Image as PILImage
                    
                    pil_image = PILImage.open(image_path)
                    
                    model = genai.GenerativeModel(settings.gemini_model)
                    response = model.generate_content([prompt, pil_image])
                    return response.text
            
            caption = self._retry_with_backoff(_generate_caption, max_retries=3, initial_delay=2)
            
            logger.info(f"Generated caption ({len(caption)} chars)")
            logger.info(f"Caption preview: {caption[:200]}")
            return caption
        
        except Exception as e:
            logger.error(f"Error generating image caption: {str(e)}", exc_info=True)
            error_str = str(e).lower()
            
            # Check if it's a network error
            if any(err in error_str for err in ['11001', 'getaddrinfo', 'connection', 'timeout', 'network']):
                logger.warning("Network error during image captioning")
                return f"Image: {os.path.basename(image_path)} (Network error prevented AI description: {str(e)})"
            
            # Return basic caption for other errors
            return f"Image from document (caption generation failed: {str(e)})"
    
    def generate_document_summary(self, full_text: str, filename: str, max_length: int = 3000) -> str:
        """
        Generate a comprehensive summary of document content
        
        Args:
            full_text: Full text of the document
            filename: Name of the document
            max_length: Maximum length of text to summarize (to avoid token limits)
        
        Returns:
            Document summary
        """
        self.initialize()
        
        logger.info(f"Generating summary for document: {filename} ({len(full_text)} chars)")
        
        # Truncate text if too long (keep first and last parts for context)
        if len(full_text) > max_length:
            half = max_length // 2
            text_to_summarize = full_text[:half] + "\n\n[... middle content omitted ...]\n\n" + full_text[-half:]
            logger.info(f"Text truncated to {max_length} chars for summarization")
        else:
            text_to_summarize = full_text
        
        prompt = f"""You are a document analysis assistant. Analyze this document and provide a comprehensive summary.

Document Name: {filename}

Document Content:
{text_to_summarize}

Please provide:
1. **Main Topic**: What is this document about? (2-3 sentences)
2. **Key Points**: List 5-7 most important points or sections
3. **Content Type**: What kind of information does it contain? (e.g., research paper, business report, tutorial, story, etc.)
4. **Useful For**: What questions or topics can this document help answer?

Format your response clearly with these sections. Be specific and detailed."""
        
        try:
            def _generate_summary():
                model = genai.GenerativeModel(settings.gemini_model)
                response = model.generate_content(prompt)
                return response.text
            
            summary = self._retry_with_backoff(_generate_summary, max_retries=3, initial_delay=1)
            logger.info(f"Summary generated successfully ({len(summary)} chars)")
            return summary.strip()
        
        except Exception as e:
            logger.error(f"Error generating document summary: {str(e)}")
            
            # Fallback: Create basic summary from text analysis
            word_count = len(full_text.split())
            char_count = len(full_text)
            lines = full_text.split('\n')
            non_empty_lines = [l for l in lines if l.strip()]
            
            # Extract first few lines as preview
            preview_lines = non_empty_lines[:5] if len(non_empty_lines) >= 5 else non_empty_lines
            preview = '\n'.join(preview_lines)[:300]
            
            fallback_summary = f"""**Document: {filename}**

**Statistics:**
- {word_count} words
- {len(non_empty_lines)} lines of content

**Preview:**
{preview}{'...' if len(full_text) > 300 else ''}

**Note:** This document has been successfully processed and indexed for search. You can ask questions about its content.

*Automatic AI summary temporarily unavailable - you can still query the full document content.*"""
            
            logger.info("Using fallback summary due to AI generation error")
            return fallback_summary
    
    def transform_query(self, question: str, chat_history: List[Dict]) -> str:
        """
        Transform query to resolve coreferences and improve retrieval
        
        Args:
            question: User's question
            chat_history: Conversation history
        
        Returns:
            Transformed query
        """
        self.initialize()
        
        if not chat_history:
            return question
        
        logger.info(f"Transforming query: '{question}'")
        
        # Build history context
        history_text = ""
        for msg in chat_history[-3:]:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            history_text += f"{role.upper()}: {content}\n"
        
        prompt = f"""Given the conversation history, rewrite the last question to be self-contained and clear.
Resolve any pronouns or references to previous messages.

Conversation History:
{history_text}

Current Question: {question}

Rewritten Question (be concise, keep the same meaning):"""
        
        try:
            model = genai.GenerativeModel(settings.gemini_model)
            response = model.generate_content(prompt)
            transformed = response.text.strip()
            
            logger.info(f"Transformed query: '{transformed}'")
            return transformed
        
        except Exception as e:
            logger.error(f"Error transforming query: {str(e)}")
            return question
    
    def cleanup(self):
        """Cleanup resources (close HTTP client)"""
        if self.http_client:
            try:
                self.http_client.close()
                logger.info("HTTP client closed successfully")
            except Exception as e:
                logger.warning(f"Error closing HTTP client: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup"""
        self.cleanup()


# Global LLM service instance
llm_service = LLMService()
