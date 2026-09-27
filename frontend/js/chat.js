// Chat functionality
let currentSessionId = null;
let messages = [];
let isTyping = false;
let currentTypingTimeout = null;
let speechSynthesis = window.speechSynthesis;
let currentUtterance = null;
let isSpeaking = false;
let resizeRafId = null;
let scrollRafId = null;
let currentTypingTarget = null;
let currentTypingText = null;

function scheduleTextareaResize(textarea) {
    if (resizeRafId) {
        return;
    }

    resizeRafId = requestAnimationFrame(() => {
        resizeRafId = null;
        const previousHeight = textarea.style.height;
        textarea.style.height = 'auto';
        const nextHeight = `${textarea.scrollHeight}px`;
        if (previousHeight !== nextHeight) {
            textarea.style.height = nextHeight;
        }
    });
}

function scheduleScrollToBottom() {
    if (scrollRafId) {
        return;
    }

    scrollRafId = requestAnimationFrame(() => {
        scrollRafId = null;
        const messagesContainer = document.getElementById('chatMessages');
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    });
}

function finalizeTyping() {
    if (currentTypingTarget && currentTypingText !== null) {
        currentTypingTarget.innerHTML = formatMessageText(currentTypingText);
        currentTypingTarget = null;
        currentTypingText = null;
    }
}

function initChat() {
    setupChatHandlers();
    initializeSpeech();
}

function initializeSpeech() {
    // Initialize speech synthesis
    if ('speechSynthesis' in window) {
        console.log('✅ Text-to-Speech is available');
    } else {
        console.log('❌ Text-to-Speech not supported in this browser');
    }
}

function setupChatHandlers() {
    // Send button
    document.getElementById('sendBtn').addEventListener('click', sendMessage);
    
    // Stop button (will be visible during typing)
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
        stopBtn.addEventListener('click', stopTyping);
    }
    
    // Message input
    const messageInput = document.getElementById('messageInput');
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Auto-resize textarea
    messageInput.addEventListener('input', () => {
        scheduleTextareaResize(messageInput);
        if (isTyping) {
            stopTyping();
        }
    });
    
    // Handle keyboard visibility on mobile
    if (window.innerWidth <= 768) {
        messageInput.addEventListener('focus', () => {
            // Scroll to bottom when keyboard opens
            setTimeout(() => {
                const chatMessages = document.getElementById('chatMessages');
                if (chatMessages) {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }
            }, 300);
        });
        
        messageInput.addEventListener('blur', () => {
            // Reset scroll behavior when keyboard closes
            setTimeout(() => {
                window.scrollTo(0, 0);
            }, 100);
        });
    }
    
    // New chat button
    document.getElementById('newChatBtn').addEventListener('click', createNewChat);
}

async function createNewChat() {
    try {
        const session = await api.createChatSession('New Conversation');
        currentSessionId = session.session_id;
        messages = [];
        clearChatMessages();
        showWelcomeMessage();
        showToast('New chat started', 'Ask me anything about your documents', 'success');
    } catch (error) {
        console.error('Failed to create chat:', error);
        showToast('Error', 'Failed to create chat session', 'error');
        // Still allow chat without session
        currentSessionId = null;
        messages = [];
        clearChatMessages();
        showWelcomeMessage();
    }
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const question = input.value.trim();
    
    if (!question) return;
    
    // Check if user has documents FIRST - before doing anything
    // Access documents from window object (set by documents.js)
    const hasDocuments = window.documents && window.documents.length > 0;
    
    console.log('📊 Document check:', { 
        hasDocuments, 
        documentCount: window.documents?.length || 0,
        documents: window.documents 
    });
    
    // CRITICAL: Block chat if no documents uploaded
    if (!hasDocuments) {
        // Show upload reminder in the chat
        showToast(
            'Upload Required',
            'Please upload at least one document before chatting.',
            'warning',
            4000
        );
        
        // Flash the upload button to guide user
        const uploadBtn = document.getElementById('uploadBtn');
        if (uploadBtn) {
            uploadBtn.style.animation = 'pulse 0.5s ease-in-out 3';
            setTimeout(() => {
                uploadBtn.style.animation = '';
            }, 1500);
        }
        
        // Don't clear the input, let user try again after upload
        return;
    }
    
    // Clear input
    input.value = '';
    input.style.height = 'auto';
    
    // Hide welcome message
    hideWelcomeMessage();
    
    // Add user message
    addMessage('user', question);
    
    // Show typing indicator
    showTypingIndicator();
    
    // User has documents, proceed with API call
    try {
        // Send to API with enhanced features
        const response = await api.askQuestionEnhanced(
            question,
            currentSessionId,
            true, // use reranking
            5 // top k
        );
        
        // Remove typing indicator
        hideTypingIndicator();
        
        // Add assistant message with animation
        addMessageWithAnimation('assistant', response.answer, response.sources);
        
        // Scroll to bottom
        scrollToBottom();
        
    } catch (error) {
        hideTypingIndicator();
        
        console.error('❌ Chat error:', error);
        
        // Parse error details
        const info = APIClient.friendlyError(error);
        let errorTitle = info.title;
        let errorDetails = info.hint ? `${info.message} ${info.hint}` : info.message;
        
        // Check for specific error types
        if (error.status === 422) {
            errorTitle = 'Upload a document first';
            errorDetails = 'The server could not process that request. This usually means you need to upload documents first.';

            // Show upload prompt
            const errorMessage = `**${errorTitle}**

${errorDetails}

**Next steps:**
- Upload at least one document (PDF, DOCX, TXT, or image)
- Wait for processing to complete
- Try your question again`;
            
            addMessageWithAnimation('assistant', errorMessage);
        } else {
            // Generic error message
            const errorMessage = `**${errorTitle}**

**Details:** ${errorDetails}

**Troubleshooting:**
- Check your internet connection
- Make sure the server is running
- Refresh the page and try again
- Make sure you have documents uploaded`;
            
            addMessageWithAnimation('assistant', errorMessage);
        }
        
        // Show toast notification
        showErrorToast(error, 'Chat failed');
    }
}

function addMessage(role, content, sources = null) {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
    
    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    messageText.innerHTML = formatMessageText(content);
    
    messageContent.appendChild(messageText);
    
    // Add sources if available
    if (sources && sources.length > 0) {
        const sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'message-sources';
        
        const sourcesTitle = document.createElement('h4');
        sourcesTitle.innerHTML = '<i class="fas fa-book"></i> Sources';
        sourcesDiv.appendChild(sourcesTitle);
        
        sources.forEach(source => {
            const sourceItem = document.createElement('div');
            sourceItem.className = 'source-item';
            
            const sourceName = document.createElement('div');
            sourceName.className = 'source-name';
            sourceName.textContent = source.document_name;
            
            const sourceText = document.createElement('div');
            sourceText.className = 'source-text';
            sourceText.textContent = source.chunk_text.substring(0, 150) + '...';
            
            sourceItem.appendChild(sourceName);
            sourceItem.appendChild(sourceText);
            sourcesDiv.appendChild(sourceItem);
        });
        
        messageContent.appendChild(sourcesDiv);
    }
    
    // Add timestamp
    const timestamp = document.createElement('div');
    timestamp.className = 'message-time';
    timestamp.textContent = new Date().toLocaleTimeString();
    messageContent.appendChild(timestamp);
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    messagesContainer.appendChild(messageDiv);
    
    // Store message
    messages.push({ role, content, sources, timestamp: new Date() });
    
    // Scroll to bottom
    scrollToBottom();
}

// Add message with typing animation
function addMessageWithAnimation(role, content, sources = null) {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role} message-animating`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
    
    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    
    messageContent.appendChild(messageText);
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    messagesContainer.appendChild(messageDiv);
    
    // Show stop button during typing
    isTyping = true;
    currentTypingTarget = messageText;
    currentTypingText = content;
    showStopButton();
    
    // Animate text appearing
    typeWriter(messageText, content, 0, () => {
        // Add speaker button for assistant messages
        if (role === 'assistant' && 'speechSynthesis' in window) {
            const speakerBtn = document.createElement('button');
            speakerBtn.className = 'speaker-btn';
            speakerBtn.dataset.messageText = content;
            speakerBtn.title = 'Read aloud';
            speakerBtn.innerHTML = '<i class="fas fa-volume-up"></i>';
            speakerBtn.onclick = () => toggleSpeech(content);
            
            const messageActions = document.createElement('div');
            messageActions.className = 'message-actions';
            messageActions.appendChild(speakerBtn);
            messageContent.appendChild(messageActions);
        }
        
        // Add sources after text finishes
        if (sources && sources.length > 0) {
            const sourcesDiv = document.createElement('div');
            sourcesDiv.className = 'message-sources';
            sourcesDiv.style.opacity = '0';
            
            const sourcesTitle = document.createElement('h4');
            sourcesTitle.innerHTML = '<i class="fas fa-book"></i> Sources';
            sourcesDiv.appendChild(sourcesTitle);
            
            sources.forEach(source => {
                const sourceItem = document.createElement('div');
                sourceItem.className = 'source-item';
                
                const sourceName = document.createElement('div');
                sourceName.className = 'source-name';
                sourceName.textContent = source.document_name;
                
                const sourceText = document.createElement('div');
                sourceText.className = 'source-text';
                sourceText.textContent = source.chunk_text.substring(0, 150) + '...';
                
                sourceItem.appendChild(sourceName);
                sourceItem.appendChild(sourceText);
                sourcesDiv.appendChild(sourceItem);
            });
            
            messageContent.appendChild(sourcesDiv);
            
            // Fade in sources
            setTimeout(() => {
                sourcesDiv.style.transition = 'opacity 0.5s ease';
                sourcesDiv.style.opacity = '1';
            }, 100);
        }
        
        // Add timestamp
        const timestamp = document.createElement('div');
        timestamp.className = 'message-time';
        timestamp.textContent = new Date().toLocaleTimeString();
        messageContent.appendChild(timestamp);
        
        messageDiv.classList.remove('message-animating');
        
        // Auto-play speech if enabled (optional - can be toggled by user)
        // Uncomment the line below to enable auto-speech:
        // if (role === 'assistant') speakText(content);
    });
    
    // Store message
    messages.push({ role, content, sources, timestamp: new Date() });
    
    // Scroll to bottom
    scrollToBottom();
}

// Typewriter effect for messages
function typeWriter(element, text, index, callback) {
    if (!isTyping) {
        // User stopped typing
        finalizeTyping();
        hideStopButton();
        if (callback) callback();
        return;
    }
    
    if (index < text.length) {
        const nextIndex = Math.min(text.length, index + 3);
        const currentText = text.substring(0, nextIndex);
        element.textContent = currentText;

        // Scroll to bottom during typing (throttled)
        scheduleScrollToBottom();
        
        // Vary speed for natural typing effect
        const char = text[nextIndex - 1];
        let delay = 20; // Default fast typing
        
        if (char === '.' || char === '!' || char === '?') {
            delay = 300; // Pause at end of sentences
        } else if (char === ',' || char === ':') {
            delay = 150; // Small pause at commas
        } else if (char === '\n') {
            delay = 100; // Pause at line breaks
        }
        
        currentTypingTimeout = setTimeout(() => typeWriter(element, text, nextIndex, callback), delay);
    } else {
        isTyping = false;
        hideStopButton();
        finalizeTyping();
        if (callback) callback();
    }
}

// Stop typing animation
function stopTyping() {
    isTyping = false;
    if (currentTypingTimeout) {
        clearTimeout(currentTypingTimeout);
        currentTypingTimeout = null;
    }
    finalizeTyping();
    hideStopButton();
    stopSpeaking();
}

// Show/Hide stop button
function showStopButton() {
    const stopBtn = document.getElementById('stopBtn');
    const sendBtn = document.getElementById('sendBtn');
    if (stopBtn && sendBtn) {
        stopBtn.style.display = 'flex';
        sendBtn.style.display = 'none';
    }
}

function hideStopButton() {
    const stopBtn = document.getElementById('stopBtn');
    const sendBtn = document.getElementById('sendBtn');
    if (stopBtn && sendBtn) {
        stopBtn.style.display = 'none';
        sendBtn.style.display = 'flex';
    }
}

// Text-to-Speech functions
function speakText(text) {
    // Stop any ongoing speech
    stopSpeaking();
    
    // Remove markdown formatting for speech
    const cleanText = text
        .replace(/\*\*(.*?)\*\*/g, '$1') // Remove bold
        .replace(/\*(.*?)\*/g, '$1')     // Remove italic
        .replace(/\n/g, '. ')             // Replace newlines with pauses
        .replace(/- /g, '');              // Remove list markers
    
    // Create speech utterance
    currentUtterance = new SpeechSynthesisUtterance(cleanText);
    
    // Configure voice
    currentUtterance.rate = 1.0;  // Speed (0.1 to 10)
    currentUtterance.pitch = 1.0; // Pitch (0 to 2)
    currentUtterance.volume = 1.0; // Volume (0 to 1)
    
    // Try to use a good voice
    const voices = speechSynthesis.getVoices();
    const preferredVoice = voices.find(voice => 
        voice.lang.startsWith('en') && 
        (voice.name.includes('Google') || voice.name.includes('Microsoft'))
    );
    if (preferredVoice) {
        currentUtterance.voice = preferredVoice;
    }
    
    // Event handlers
    currentUtterance.onstart = () => {
        isSpeaking = true;
        updateSpeakerButton(true);
    };
    
    currentUtterance.onend = () => {
        isSpeaking = false;
        currentUtterance = null;
        updateSpeakerButton(false);
    };
    
    currentUtterance.onerror = (event) => {
        console.error('Speech error:', event);
        isSpeaking = false;
        currentUtterance = null;
        updateSpeakerButton(false);
    };
    
    // Speak!
    speechSynthesis.speak(currentUtterance);
}

function stopSpeaking() {
    if (speechSynthesis.speaking) {
        speechSynthesis.cancel();
    }
    isSpeaking = false;
    currentUtterance = null;
    updateSpeakerButton(false);
}

function toggleSpeech(text) {
    if (isSpeaking) {
        stopSpeaking();
    } else {
        speakText(text);
    }
}

function updateSpeakerButton(speaking) {
    // Update all speaker buttons
    document.querySelectorAll('.speaker-btn').forEach(btn => {
        const icon = btn.querySelector('i');
        if (speaking && btn.dataset.messageText) {
            icon.className = 'fas fa-stop-circle';
            btn.title = 'Stop speaking';
        } else {
            icon.className = 'fas fa-volume-up';
            btn.title = 'Read aloud';
        }
    });
}

// Escape HTML so model output can never inject markup (XSS-safe)
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Format message text (convert limited markdown to HTML, heading-free)
function formatMessageText(text) {
    if (!text) return '';

    // XSS-safe base: escape everything first, then re-add safe markup
    let safe = escapeHtml(text);

    // Cut everything from a trailing "Sources"/"References" heading onward.
    // The UI renders its own citation block, so the model's pasted source
    // section is hidden entirely.
    const sourcesHeading = /^\s{0,3}(?:#{1,6}\s*\**\s*|\*{1,2}\s*)(sources?|references?)\s*\*{0,2}\s*:?\s*$/im;
    const cutAt = safe.search(sourcesHeading);
    if (cutAt !== -1) {
        safe = safe.substring(0, cutAt).trim();
    }

    // Strip markdown headings (###, ##, #) - answers render professionally
    safe = safe.replace(/^\s{0,3}#{1,6}\s*/gm, '');

    // Drop lines containing only dangling emphasis markers (** or __)
    safe = safe.replace(/^\s{0,3}(?:\*{1,3}|_{1,3})\s*$/gm, '');

    // Strip inline [Source N] citation brackets - the UI shows real sources
    // under each answer, so these are noise in the text
    safe = safe.replace(/\s*\[[^\]\n]*\bSources?\b[^\]\n]*\]/g, '');
    safe = safe.replace(/\s+([.,;:])/g, '$1');
    safe = safe.replace(/ {2,}/g, ' ');

    // Bold **text**
    safe = safe.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Italic *text*
    safe = safe.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

    // Inline code `text`
    safe = safe.replace(/`([^`\n]+)`/g, '<code>$1</code>');

    // Bullet lines (- or *)
    safe = safe.replace(/^[ \t]*[-*] (.*)$/gm, '• $1');

    // Line breaks
    safe = safe.replace(/\n/g, '<br>');

    return safe;
}

function showTypingIndicator() {
    const messagesContainer = document.getElementById('chatMessages');
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant';
    typingDiv.id = 'typingIndicator';
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = '<i class="fas fa-robot"></i>';
    
    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    
    const typingIndicator = document.createElement('div');
    typingIndicator.className = 'typing-indicator';
    typingIndicator.innerHTML = `
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    `;
    
    messageContent.appendChild(typingIndicator);
    typingDiv.appendChild(avatar);
    typingDiv.appendChild(messageContent);
    messagesContainer.appendChild(typingDiv);
    
    scrollToBottom();
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

function showWelcomeMessage() {
    const messagesContainer = document.getElementById('chatMessages');
    const welcome = document.querySelector('.welcome-message');
    if (welcome) {
        welcome.style.display = 'block';
    } else {
        // If welcome message doesn't exist, create it
        clearChatMessages();
    }
}

function hideWelcomeMessage() {
    const welcome = document.querySelector('.welcome-message');
    if (welcome) {
        welcome.style.display = 'none';
    }
}

function clearChatMessages() {
    const messagesContainer = document.getElementById('chatMessages');
    const hasDocuments = window.documents && window.documents.length > 0;
    
    if (hasDocuments) {
        // User has documents - show ready-to-chat message
        messagesContainer.innerHTML = `
            <div class="welcome-message">
                <div class="welcome-icon"><i class="fas fa-comments"></i></div>
                <h2>Ready to chat</h2>
                <p>You have <strong>${window.documents.length} document${window.documents.length > 1 ? 's' : ''}</strong> uploaded and ready. Ask me anything about them.</p>

                <div class="welcome-branding" style="text-align: left;">
                    <p style="margin: 6px 0; color: var(--text-secondary);">Try questions like:</p>
                    <p style="margin: 6px 0; color: var(--text-muted);">• "Summarize this document"</p>
                    <p style="margin: 6px 0; color: var(--text-muted);">• "What are the main topics?"</p>
                    <p style="margin: 6px 0; color: var(--text-muted);">• "Explain a concept from my notes"</p>
                    <p style="margin: 6px 0; color: var(--text-muted);">• "Find information about a specific topic"</p>
                </div>
            </div>
        `;
    } else {
        // No documents - show upload instructions
        messagesContainer.innerHTML = `
            <div class="welcome-message">
                <div class="welcome-icon"><i class="fas fa-file-import"></i></div>
                <h2>Welcome to Document Chat</h2>
                <p>Upload a document first, then ask questions about its content.</p>

                <div class="welcome-branding" style="text-align: left;">
                    <p style="margin: 8px 0;"><strong style="color: var(--primary);">Step 1 — Upload documents</strong></p>
                    <p style="margin: 6px 0; color: var(--text-secondary);">Click the upload button in the top-left corner.</p>
                    <p style="margin: 4px 0; color: var(--text-muted);">• PDF, Word, text files, or images</p>
                    <p style="margin: 4px 0; color: var(--text-muted);">• Up to 5 files at once</p>

                    <p style="margin: 14px 0 8px;"><strong style="color: var(--primary);">Step 2 — Start chatting</strong></p>
                    <p style="margin: 6px 0; color: var(--text-secondary);">Type your question and press Enter.</p>
                </div>

                <div class="quick-actions">
                    <button class="quick-action" onclick="document.getElementById('uploadBtn').click()">
                        <i class="fas fa-upload"></i> Upload documents now
                    </button>
                </div>
            </div>
        `;
    }
}

function scrollToBottom() {
    scheduleScrollToBottom();
}

function sendSampleQuestion() {
    const input = document.getElementById('messageInput');
    input.value = 'What are the main topics covered in my documents?';
    input.focus();
    
    // Trigger auto-resize
    scheduleTextareaResize(input);
}

// Initialize chat when DOM is loaded
document.addEventListener('DOMContentLoaded', initChat);
