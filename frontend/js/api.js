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

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            ...options,
            headers: {
                ...this.getHeaders(options.auth !== false),
                ...options.headers
            }
        };

        try {
            console.log('Making request to:', url);
            const response = await fetch(url, config);
            
            // Check content type before parsing
            const contentType = response.headers.get('content-type');
            console.log('Response content-type:', contentType, 'status:', response.status);
            
            // If not JSON, log the text response for debugging
            if (!contentType || !contentType.includes('application/json')) {
                const text = await response.text();
                console.error('Expected JSON but got:', contentType, '\nResponse:', text.substring(0, 500));
                throw new Error(`Server returned ${contentType} instead of JSON. Status: ${response.status}`);
            }

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || `HTTP error! status: ${response.status}`);
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
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
            throw new Error(error.message || 'Registration failed');
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
            throw new Error(error.message || 'Login failed');
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
                    const errorData = JSON.parse(xhr.responseText);
                    reject(new Error(errorData.detail || `Upload failed: ${xhr.statusText}`));
                }
            });

            xhr.addEventListener('error', () => {
                reject(new Error('Upload failed'));
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
                    const errorData = JSON.parse(xhr.responseText);
                    reject(new Error(errorData.detail || `Upload failed: ${xhr.statusText}`));
                }
            });

            xhr.addEventListener('error', () => {
                reject(new Error('Upload failed - Network error'));
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
