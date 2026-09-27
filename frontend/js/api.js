// API Configuration
// Automatically detect the correct API base URL
function getAPIBaseURL() {
    const hostname = window.location.hostname;
    const port = window.location.port;
    
    // In Docker with nginx proxy, use /api
    if (port === '80' || port === '' || hostname === 'localhost' && port === '80') {
        return '/api';
    }
    
    // Direct access to backend (development)
    if (port === '8000') {
        return '';
    }
    
    // Default to /api for production
    return '/api';
}

const API_BASE_URL = getAPIBaseURL();
console.log('API Base URL:', API_BASE_URL, 'Location:', window.location.href);

// API Client
class APIClient {
    constructor() {
        this.baseURL = API_BASE_URL;
        this.token = localStorage.getItem('token');
    }

    setToken(token) {
        this.token = token;
        localStorage.setItem('token', token);
    }

    clearToken() {
        this.token = null;
        localStorage.removeItem('token');
    }

    getToken() {
        return this.token;
    }

    getHeaders(includeAuth = true) {
        const headers = {
            'Content-Type': 'application/json'
        };
        
        if (includeAuth && this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        
        return headers;
    }

    /**
     * Pydantic messages are precise but robotic. Translate the common ones so
     * people see "must be at least 8 characters" instead of
     * "String should have at least 8 characters".
     */
    static humanizeValidationMessage(msg) {
        if (!msg) return msg;
        return msg
            .replace(/^String should have at least (\d+) characters?$/i,
                'must be at least $1 characters')
            .replace(/^String should have at most (\d+) characters?$/i,
                'must be at most $1 characters')
            .replace(/^String should match pattern.*$/i,
                'contains characters that are not allowed here')
            .replace(/value is not a valid email address/i,
                'is not a valid email address')
            .replace(/^Field required$/i, 'is required')
            .replace(/^Input should be a valid (.*)$/i, 'must be a valid $1');
    }

    /**
     * Turn an error payload into a readable sentence.
     *
     * FastAPI sends validation failures as a LIST of objects, which used to be
     * stringified straight into the UI as "[object Object]".
     */
    static formatError(data, status) {
        const detail = data && data.detail;

        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }

        if (Array.isArray(detail)) {
            const messages = detail.map((item) => {
                if (typeof item === 'string') return item;
                if (item && typeof item === 'object') {
                    const field = Array.isArray(item.loc)
                        ? item.loc.filter((part) => part !== 'body' && part !== 'query').join('.')
                        : '';
                    let msg = item.msg || item.message || 'Invalid value';
                    msg = msg.replace(/^Value error,\s*/i, '');
                    msg = APIClient.humanizeValidationMessage(msg);
                    return field ? `${field}: ${msg}` : msg;
                }
                return String(item);
            }).filter(Boolean);

            if (messages.length) return messages.join('\n');
        }

        if (detail && typeof detail === 'object') {
            return detail.message || JSON.stringify(detail);
        }

        return `Request failed (HTTP ${status}).`;
    }

    /**
     * Turn any thrown error into { title, message, hint } for the UI.
     *
     * One place decides how the app talks about failure, so every surface
     * (toast, form, chat bubble) stays consistent.
     */
    static friendlyError(error) {
        const status = (error && error.status) || 0;
        const raw = (error && error.message) || '';
        const lower = raw.toLowerCase();

        if (error && error.isNetwork) {
            return {
                title: "Can't reach the server",
                message: 'The backend is not responding.',
                hint: "If you're running it locally, start the server and try again. Nothing you typed was lost."
            };
        }

        // Common, specific cases first
        if (lower.includes('already registered') || lower.includes('already exists')) {
            return {
                title: 'That account already exists',
                message: raw,
                hint: 'Try logging in instead, or use a different username or email.'
            };
        }

        if (lower.includes('limit reached') || lower.includes('more document')) {
            return {
                title: 'Document limit reached',
                message: raw,
                hint: 'Delete a document from the sidebar, then upload again.'
            };
        }

        if (status === 401) {
            return {
                title: 'Sign-in required',
                message: raw || 'Your session has expired. Please log in again.',
                hint: raw.toLowerCase().includes('incorrect') ? 'Check the spelling and try again.' : null
            };
        }

        if (status === 403) {
            return { title: 'Not allowed', message: raw || "You don't have permission to do that.", hint: null };
        }

        if (status === 404) {
            return { title: 'Not found', message: raw || 'That item no longer exists.', hint: 'Refresh the page and try again.' };
        }

        if (status === 413) {
            return { title: 'File too large', message: raw || 'That file is over the size limit.', hint: 'Try a smaller file.' };
        }

        if (status === 422) {
            return {
                title: 'Please check your input',
                message: raw || 'Some values were rejected.',
                hint: null
            };
        }

        if (status === 429) {
            return { title: 'Too many requests', message: 'Slow down for a moment.', hint: 'Wait a few seconds, then try again.' };
        }

        if (status >= 500) {
            return {
                title: 'Server problem',
                message: raw || 'The server hit an unexpected error.',
                hint: 'This is usually temporary - try again in a moment.'
            };
        }

        if (status === 400) {
            return { title: 'Request rejected', message: raw || 'The server could not accept that request.', hint: null };
        }

        return {
            title: 'Something went wrong',
            message: raw || 'An unexpected error occurred.',
            hint: status ? `HTTP ${status}` : null
        };
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            ...options,
            headers: {
                ...this.getHeaders(options.auth !== false),
                ...options.headers
            }
        };

        let response;
        try {
            response = await fetch(url, config);
        } catch (networkError) {
            // Server down, DNS failure, offline, CORS...
            console.error('Network error for', url, networkError);
            const err = new Error("Can't reach the server.");
            err.status = 0;
            err.isNetwork = true;
            throw err;
        }

        const contentType = response.headers.get('content-type') || '';
        let data = null;

        if (contentType.includes('application/json')) {
            try {
                data = await response.json();
            } catch (parseError) {
                console.error('Invalid JSON from', url, parseError);
                data = null;
            }
        } else {
            // e.g. an HTML error page served by a proxy
            const text = await response.text();
            console.error('Expected JSON but got', contentType, 'status', response.status, text.slice(0, 300));
        }

        if (!response.ok) {
            const error = new Error(APIClient.formatError(data, response.status));
            error.status = response.status;
            error.payload = data;

            // An AUTHENTICATED request was rejected: the token expired or was revoked.
            if (response.status === 401 && options.auth !== false) {
                this.clearToken();
                window.dispatchEvent(new CustomEvent('auth:expired'));
            }

            throw error;
        }

        if (data === null) {
            const error = new Error('The server returned an unexpected response.');
            error.status = response.status;
            throw error;
        }

        return data;
    }

    // Auth endpoints
    async register(username, email, password) {
        try {
            const data = await this.request('/register', {
                method: 'POST',
                auth: false,
                body: JSON.stringify({ username, email, password })
            });
            if (data && data.access_token) {
                this.setToken(data.access_token);
            }
            return data;
        } catch (error) {
            console.error('Register API error:', error);
            throw error; // keep status/payload so the UI can explain it
        }
    }

    async login(username, password) {
        try {
            const data = await this.request('/login', {
                method: 'POST',
                auth: false,
                body: JSON.stringify({ username, password })
            });
            if (data && data.access_token) {
                this.setToken(data.access_token);
            }
            return data;
        } catch (error) {
            console.error('Login API error:', error);
            throw error; // keep status/payload so the UI can explain it
        }
    }

    async getCurrentUser() {
        return await this.request('/me');
    }

    // Document endpoints
    async uploadDocument(file, onProgress) {
        const formData = new FormData();
        formData.append('file', file);

        const xhr = new XMLHttpRequest();

        return new Promise((resolve, reject) => {
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    const percentComplete = (e.loaded / e.total) * 100;
                    onProgress(percentComplete);
                }
            });

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    let errorData = null;
                    try { errorData = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
                    const err = new Error(APIClient.formatError(errorData, xhr.status));
                    err.status = xhr.status;
                    if (xhr.status === 401) {
                        this.clearToken();
                        window.dispatchEvent(new CustomEvent('auth:expired'));
                    }
                    reject(err);
                }
            });

            xhr.addEventListener('error', () => {
                const err = new Error("Upload couldn't reach the server.");
                err.status = 0;
                err.isNetwork = true;
                reject(err);
            });

            xhr.open('POST', `${this.baseURL}/upload`);
            xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
            xhr.send(formData);
        });
    }

    async uploadMultipleDocuments(files, onProgress) {
        const formData = new FormData();
        
        // Append all files with the same field name 'files'
        files.forEach(file => {
            formData.append('files', file);
        });

        const xhr = new XMLHttpRequest();

        return new Promise((resolve, reject) => {
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    const percentComplete = (e.loaded / e.total) * 100;
                    onProgress(percentComplete);
                }
            });

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    let errorData = null;
                    try { errorData = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
                    const err = new Error(APIClient.formatError(errorData, xhr.status));
                    err.status = xhr.status;
                    if (xhr.status === 401) {
                        this.clearToken();
                        window.dispatchEvent(new CustomEvent('auth:expired'));
                    }
                    reject(err);
                }
            });

            xhr.addEventListener('error', () => {
                const err = new Error("Upload couldn't reach the server.");
                err.status = 0;
                err.isNetwork = true;
                reject(err);
            });

            xhr.open('POST', `${this.baseURL}/upload`);
            xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
            xhr.send(formData);
        });
    }

    async listDocuments() {
        return await this.request('/documents');
    }

    async deleteDocument(documentId) {
        return await this.request(`/documents/${documentId}`, {
            method: 'DELETE'
        });
    }

    // Chat endpoints
    async askQuestion(question, topK = 3) {
        return await this.request('/ask', {
            method: 'POST',
            body: JSON.stringify({ question, top_k: topK })
        });
    }

    async askQuestionEnhanced(question, sessionId = null, useReranking = true, topK = 5) {
        return await this.request('/ask/enhanced', {
            method: 'POST',
            body: JSON.stringify({ 
                question, 
                session_id: sessionId,
                use_reranking: useReranking,
                top_k: topK 
            })
        });
    }

    // Chat session endpoints
    async createChatSession(title = 'New Conversation') {
        return await this.request('/chat/sessions', {
            method: 'POST',
            body: JSON.stringify({ title })
        });
    }

    async listChatSessions() {
        return await this.request('/chat/sessions');
    }

    async getChatHistory(sessionId) {
        return await this.request(`/chat/sessions/${sessionId}`);
    }

    async deleteChatSession(sessionId) {
        return await this.request(`/chat/sessions/${sessionId}`, {
            method: 'DELETE'
        });
    }

    // Health check
    async healthCheck() {
        return await this.request('/health', { auth: false });
    }
}

// Global API instance
const api = new APIClient();
