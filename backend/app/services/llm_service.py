"""Google Gemini LLM service with Redis caching"""

import google.generativeai as genai
from typing import List, Dict, Optional, Iterator
import json
import re
import os
import time
import socket
import ssl
import certifi
import httpx
import hashlib
from collections import OrderedDict

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Matches markdown heading markers (#, ##, ### ...) at the start of a line
_HEADING_MARK_RE = re.compile(r'^\s{0,3}#{1,6}\s*', re.MULTILINE)

# Matches a model-generated "#### ** Sources" / "## References" heading line.
# The UI renders its own citations block, so anything from this heading onward
# is cut from the answer.
_SOURCES_HEADING_RE = re.compile(
    r'^\s{0,3}(?:#{1,6}\s*\**\s*|\*{1,2}\s*)(?:sources?|references?)\s*\*{0,2}\s*:?\s*$',
    re.IGNORECASE | re.MULTILINE
)

# Same check for a single sanitized line (streaming path)
_BARE_SOURCES_LINE_RE = re.compile(
    r'^\s*\**\s*(?:sources?|references?)\s*\**\s*:?\s*$',
    re.IGNORECASE
)

# Lines containing only markdown emphasis markers (dangling ** or __)
_LONE_MARKS_RE = re.compile(r'^\s{0,3}(?:\*{1,3}|_{1,3})\s*$', re.MULTILINE)

# Space left in front of punctuation after a citation is removed
_SPACE_BEFORE_PUNCT_RE = re.compile(r'\s+([.,;:])')

# Honest message used whenever the LLM cannot be reached. It must NOT look
# like an answer about the user's documents.
SERVICE_UNAVAILABLE_MESSAGE = (
    "The AI service is temporarily unavailable. "
    "Please try again in a moment."
)


class LLMUnavailableError(RuntimeError):
    """Raised when the LLM could not produce an answer (outage, quota, network).

    Callers must not substitute fabricated text or raw document excerpts:
    they should report the outage honestly to the client.
    """


def sanitize_answer(text: str) -> str:
    """Clean LLM output for professional chat rendering.

    - Cuts everything from a "Sources" / "References" heading onward
      (the UI displays citations itself, see chat.js message-sources).
    - Strips markdown heading markers (#, ##, ###) from remaining lines.
    - Removes dangling emphasis markers (lone ** lines).
    - Keeps inline [Source N] citations so every claim stays traceable.
    """
    if not text:
        return text
    cut = _SOURCES_HEADING_RE.search(text)
    if cut:
        text = text[:cut.start()].rstrip()
    text = _HEADING_MARK_RE.sub('', text)
    text = _LONE_MARKS_RE.sub('', text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r'\1', text)
    text = re.sub(r' {2,}', ' ', text)
    return text


class LLMService:
    """Service for interacting with Google Gemini API with caching"""
    
    def __init__(self):
        """Initialize Gemini client and Redis cache"""
        self.client = None
        self.deepseek_client = None
        self._use_deepseek = False
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
        
        # In-process answer cache used when Redis is unavailable (bounded, TTL'd)
        self._local_answers: "OrderedDict[str, tuple]" = OrderedDict()
        self._local_answer_max = 256
    
    def _get_cache_key(self, question: str, context_summary: str) -> str:
        """Generate cache key from question and context"""
        content = f"{question}:{context_summary}"
        # v2: invalidates answers cached before the citation/sources sanitizer
        return f"llm_answer:v2:{hashlib.md5(content.encode()).hexdigest()}"
    
    def _get_cached_answer(self, cache_key: str) -> Optional[str]:
        """Get cached answer if available (Redis first, then in-process)."""
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    logger.info("✓ Cache HIT (Redis) - Returning cached answer")
                    # Defense-in-depth: sanitize cached answers too, in case a
                    # stale entry slipped through an older version
                    return sanitize_answer(cached)
            except Exception as e:
                logger.warning(f"Cache read error: {e}")
        
        # In-process fallback: caching must work without Redis too
        entry = self._local_answers.get(cache_key)
        if entry:
            answer, stored_at = entry
            if time.time() - stored_at <= settings.cache_ttl:
                self._local_answers.move_to_end(cache_key)
                logger.info("✓ Cache HIT (in-process) - Returning cached answer")
                return sanitize_answer(answer)
            del self._local_answers[cache_key]
        
        return None
    
    def _cache_answer(self, cache_key: str, answer: str):
        """Cache the answer (Redis when available, in-process otherwise)."""
        if self.redis_client:
            try:
                self.redis_client.setex(
                    cache_key,
                    settings.cache_ttl,  # TTL from settings (default 3600s = 1 hour)
                    answer
                )
                logger.info("✓ Answer cached for future requests (Redis)")
                return
            except Exception as e:
                logger.warning(f"Cache write error: {e}")
        
        self._local_answers[cache_key] = (answer, time.time())
        self._local_answers.move_to_end(cache_key)
        while len(self._local_answers) > self._local_answer_max:
            self._local_answers.popitem(last=False)
        logger.info("Answer cached for future requests (in-process)")
    
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
        Check if network connection to the LLM API is available
        
        Returns:
            True if network is reachable
        """
        # Cache network check for 30 seconds
        current_time = time.time()
        if current_time - self.last_network_check < 30:
            return self.network_available
        
        self.last_network_check = current_time
        
        try:
            # Check the active provider's API endpoint
            host = (
                "api.deepseek.com" if self._use_deepseek
                else "generativelanguage.googleapis.com"
            )
            socket.create_connection((host, 443), timeout=5)
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
                # Quota/rate-limit errors (HTTP 429) are retryable too, but the
                # sleep must honour the provider's per-minute limits (60s).
                is_quota = ('429' in error_str or 'quota' in error_str
                            or 'rate limit' in error_str)
                if is_quota:
                    delay = 60
                
                if (is_retryable or is_quota) and attempt < max_retries - 1:
                    # Don't spin forever waiting out a quota window
                    if is_quota and attempt >= 2:
                        logger.error(
                            f"Quota error persists after {attempt + 1} attempts: {str(e)}"
                        )
                        raise e
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
                if not (is_retryable or is_quota):
                    logger.error(f"Non-retryable error: {str(e)}")
                raise e
        
        # All retries failed
        raise last_error
    
    def initialize(self):
        """Configure the LLM provider(s).

        Text generation (answers, summaries, query transformation) uses the
        provider selected by settings.llm_provider. Gemini remains available
        for image captioning (vision) whenever a Gemini key is present.
        """
        if self.client is not None or self.deepseek_client is not None:
            return
        
        self.api_key = settings.get_api_key()
        
        if settings.llm_provider == "deepseek":
            if not settings.deepseek_api_key:
                raise ValueError(
                    "DeepSeek API key not found. Please set DEEPSEEK_API_KEY in .env file"
                )
            
            logger.info(f"Initializing DeepSeek API (model: {settings.deepseek_model})...")
            try:
                from openai import OpenAI
                
                self.deepseek_client = OpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                )
                self._use_deepseek = True
                logger.info("DeepSeek client ready")
            except Exception as e:
                logger.error(f"Failed to configure DeepSeek API: {e}")
                raise
            
            # Gemini (vision) stays available for image captioning
            if self.api_key:
                try:
                    os.environ['GOOGLE_API_KEY'] = self.api_key
                    genai.configure(api_key=self.api_key)
                    self.client = genai
                    logger.info("Gemini vision configured (image captioning fallback)")
                except Exception as e:
                    logger.warning(f"Gemini vision not configured: {e}")
            return
        
        # Default: Gemini for everything
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
            self._use_deepseek = False
            logger.info(f"Gemini API initialized with model: {settings.gemini_model}")
        except Exception as e:
            logger.error(f"Failed to configure Gemini API: {e}")
            raise
    
    def _deepseek_chat(self, prompt: str, temperature=None, max_tokens=None, stream=False):
        """Call the DeepSeek chat completions API (OpenAI-compatible)."""
        kwargs = {
            "model": settings.deepseek_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if stream:
            kwargs["stream"] = True
        return self.deepseek_client.chat.completions.create(**kwargs)
    
    def generate_answer(
        self,
        question: str,
        context_chunks: List[Dict],
        chat_history: Optional[List[Dict]] = None,
        strict_mode: bool = False
    ) -> str:
        """
        Generate answer using Gemini, grounded strictly in the provided context + CACHING
        
        Args:
            question: User's question
            context_chunks: Relevant document chunks (can be empty)
            chat_history: Optional conversation history
            strict_mode: If True, only answer from provided context (for document-only mode)
        
        Returns:
            Generated answer - grounded in the context, or the abstain sentence
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
        
        # Pre-flight network check: only for the Gemini path. The DeepSeek
        # client fails fast on its own (and is retried below).
        if not self._use_deepseek and not self._check_network_connectivity():
            logger.error("No network connectivity to the LLM API")
            raise LLMUnavailableError("no network connectivity to the LLM API")
        
        # Build the grounded prompt
        prompt = self._build_prompt(question, context, chat_history, strict_mode)
        
        try:
            # Generate response with retry logic
            def _generate():
                if self._use_deepseek:
                    resp = self._deepseek_chat(
                        prompt,
                        temperature=settings.gemini_temperature,
                        max_tokens=settings.gemini_max_tokens,
                    )
                    return resp.choices[0].message.content or ""
                
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
            
            # Sanitize: strip markdown headings (###) for professional rendering
            answer = sanitize_answer(answer)
            
            # Cache the answer for future requests
            self._cache_answer(cache_key, answer)
            
            logger.info(f"Generated answer ({len(answer)} chars)")
            return answer
        
        except Exception as e:
            logger.error(f"Error generating answer: {str(e)}")
            # Never fabricate an answer, and never pass off raw excerpts as
            # one. Report the outage honestly and let the API layer respond.
            raise LLMUnavailableError(str(e)) from e
    
    # ------------------------------------------------------------------
    # NOTE: _generate_intelligent_fallback() and _generate_offline_response()
    # below are no longer used by the answer path. Failures now raise
    # LLMUnavailableError so the API returns an honest "service unavailable"
    # response instead of passing raw document excerpts off as an answer.
    # Kept temporarily for reference; safe to delete in a cleanup pass.
    # ------------------------------------------------------------------

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

I encountered a temporary issue connecting to the full AI service, but I found relevant information:

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

⚠️ I'm currently unable to connect to the AI service due to a network issue. However, I want to help you!

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

**Note:** Once the AI connection is restored, I'll be able to provide a much more comprehensive, analyzed answer with:
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
        
        # Pre-flight network check (Gemini path only - see generate_answer)
        if not self._use_deepseek and not self._check_network_connectivity():
            logger.error("No network connectivity for streaming")
            yield SERVICE_UNAVAILABLE_MESSAGE
            return
        
        # Build context and prompt
        context = self._build_context(context_chunks)
        prompt = self._build_prompt(question, context, chat_history)
        
        try:
            # Produce raw text pieces from the active provider
            def _text_iterator():
                if self._use_deepseek:
                    stream = self._deepseek_chat(
                        prompt,
                        temperature=settings.gemini_temperature,
                        max_tokens=settings.gemini_max_tokens,
                        stream=True,
                    )
                    for chunk in stream:
                        if chunk.choices:
                            delta = chunk.choices[0].delta
                            content = getattr(delta, "content", None)
                            if content:
                                yield content
                else:
                    model = genai.GenerativeModel(settings.gemini_model)
                    response = model.generate_content(prompt, stream=True)
                    for chunk in response:
                        if hasattr(chunk, 'text') and chunk.text:
                            yield chunk.text
            
            # Line-buffered output: heading marks (###) can be split across
            # chunks, so only complete lines are sanitized and emitted.
            # Once the model starts writing its own "Sources" section, the
            # rest of the stream is dropped entirely (the UI shows citations).
            pending = ""
            sources_seen = False
            for piece in _text_iterator():
                if sources_seen:
                    break
                pending += piece
                lines = pending.split("\n")
                pending = lines.pop()  # keep possibly-incomplete last line
                for line in lines:
                    clean = sanitize_answer(line)
                    if _BARE_SOURCES_LINE_RE.match(clean):
                        sources_seen = True
                        break
                    yield clean + "\n"
            if pending and not sources_seen:
                clean = sanitize_answer(pending)
                if not _BARE_SOURCES_LINE_RE.match(clean):
                    yield clean
        
        except Exception as e:
            logger.error(f"Error in streaming generation: {str(e)}")
            yield SERVICE_UNAVAILABLE_MESSAGE
    
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
        """Build the prompt for Gemini - document-grounded, honest mode.

        The model answers ONLY from the provided context chunks. If the
        context does not contain the answer it must return the abstain
        sentence, never a general-knowledge guess.
        """
        
        system_message = """You are a document question-answering assistant.

YOUR ONLY JOB: answer the user's question using ONLY the DOCUMENT CONTEXT
provided below. You are not a general chatbot.

GROUNDING RULES (STRICTLY ENFORCED):
1. Use only facts that appear in the DOCUMENT CONTEXT. Never add facts from
   outside knowledge or from your training data - even if you are sure.
2. REASONING OVER THE CONTEXT IS ALLOWED AND EXPECTED. You may count, total,
   compare, rank and draw conclusions that follow directly from those facts.
   Example: if the context shows "Physics A1, Chemistry B2, Biology B3", you
   may say the science results are strong and explain why.
   Never present an inference as though the document itself stated it.
3. If a conclusion needs information the context does not contain (for example
   an institution's admission requirements), give what the context does
   support, then say plainly that the documents do not state the rest.
4. Only when the context contains nothing relevant to the question, reply with
   exactly this sentence and nothing else: I couldn't find that in your documents.
5. Cite the source of every factual claim inline as [Source N], e.g.
   "The warranty is 3 years [Source 2]."
6. Never speculate about things the context does not mention, and never invent
   numbers, dates, names, grades or codes.
7. If no DOCUMENT CONTEXT is provided, reply with exactly the abstain sentence.

FORMATTING RULES:
1. NEVER use markdown headings (#, ##, ###, ####). Start directly with your answer.
2. Write in plain paragraphs, short bullet lists (- item), and bold (**text**)
   for emphasis only. No emojis inside answers.
3. NEVER add a "Sources", "References", or "Bibliography" section at the end.
   Inline [Source N] markers are enough.
4. Never paste document excerpts back into your answer, and never leave
   dangling ** or __ marks alone on a line.

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
QUESTION: {question}

ANSWER:
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
                if self._use_deepseek:
                    resp = self._deepseek_chat(
                        prompt,
                        temperature=0.3,
                        max_tokens=settings.gemini_max_tokens,
                    )
                    return resp.choices[0].message.content or ""
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
            if self._use_deepseek:
                resp = self._deepseek_chat(prompt, temperature=0.0, max_tokens=100)
                transformed = (resp.choices[0].message.content or "").strip()
            else:
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
