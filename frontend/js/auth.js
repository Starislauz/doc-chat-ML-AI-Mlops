// Authentication handling
let currentUser = null;

// Initialize auth
document.addEventListener('DOMContentLoaded', () => {
    testBackendConnection();
    initAuth();
    setupPageCloseCleanup();
});

async function testBackendConnection() {
    try {
        console.log('Testing backend connection...');
        const health = await api.healthCheck();
        console.log('✅ Backend connected successfully:', health);
    } catch (error) {
        console.error('❌ Backend connection failed:', error);
        console.error('Make sure the backend container is running and accessible');
        
        // Show a user-friendly message
        setTimeout(() => {
            const errorDiv = document.getElementById('loginError') || document.getElementById('registerError');
            if (errorDiv && !api.getToken()) {
                errorDiv.textContent = '⚠️ Unable to connect to server. Please refresh the page or contact support.';
                errorDiv.classList.add('active');
            }
        }, 1000);
    }
}

function setupPageCloseCleanup() {
    // Cleanup on page close/refresh (if user is logged in)
    window.addEventListener('beforeunload', (event) => {
        if (api.getToken()) {
            // Use sendBeacon for reliable cleanup on page close
            const url = `${api.baseURL}/cleanup/user`;
            const token = api.getToken();
            
            // sendBeacon is more reliable than fetch for page unload
            navigator.sendBeacon(url, JSON.stringify({
                headers: { 'Authorization': `Bearer ${token}` }
            }));
            
            console.log('🧹 Cleanup triggered on page close');
        }
    });
}

function initAuth() {
    const token = localStorage.getItem('token');
    
    if (token) {
        // Try to load user
        loadCurrentUser();
    } else {
        showAuthModal();
    }
    
    // Setup form handlers
    setupAuthForms();
}

function setupAuthForms() {
    // Tab switching
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            switchAuthTab(tabName);
        });
    });
    
    // Login form
    document.getElementById('loginForm').addEventListener('submit', handleLogin);
    
    // Register form
    document.getElementById('registerForm').addEventListener('submit', handleRegister);
    
    // Logout button
    document.getElementById('logoutBtn').addEventListener('click', handleLogout);
}

function switchAuthTab(tabName) {
    // Update tabs
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    
    // Update forms
    document.querySelectorAll('.auth-form').forEach(form => {
        form.classList.toggle('active', form.id === `${tabName}Form`);
    });
    
    // Clear errors
    clearAuthErrors();
}

async function handleLogin(e) {
    e.preventDefault();
    
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    const errorEl = document.getElementById('loginError');
    
    try {
        errorEl.classList.remove('active');
        console.log('Attempting login for:', username);
        
        const data = await api.login(username, password);
        
        currentUser = data.user;
        showToast('Welcome back!', `Logged in as ${username}`, 'success');
        hideAuthModal();
        showMainApp();
        loadUserData();
        
    } catch (error) {
        console.error('Login error:', error);
        let errorMessage = error.message;
        
        // Provide helpful error messages
        if (errorMessage.includes('JSON')) {
            errorMessage = 'Unable to connect to server. Please make sure the backend is running.';
        } else if (errorMessage.includes('Failed to fetch')) {
            errorMessage = 'Network error. Please check your connection and try again.';
        }
        
        errorEl.textContent = errorMessage;
        errorEl.classList.add('active');
    }
}

async function handleRegister(e) {
    e.preventDefault();
    
    const username = document.getElementById('registerUsername').value;
    const email = document.getElementById('registerEmail').value;
    const password = document.getElementById('registerPassword').value;
    const errorEl = document.getElementById('registerError');
    
    try {
        errorEl.classList.remove('active');
        console.log('Attempting registration for:', username);
        
        const data = await api.register(username, email, password);
        
        currentUser = data.user;
        showToast('Account created!', `Welcome, ${username}!`, 'success');
        hideAuthModal();
        showMainApp();
        loadUserData();
        
    } catch (error) {
        console.error('Registration error:', error);
        let errorMessage = error.message;
        
        // Provide helpful error messages
        if (errorMessage.includes('JSON')) {
            errorMessage = 'Unable to connect to server. Please make sure the backend is running.';
        } else if (errorMessage.includes('Failed to fetch')) {
            errorMessage = 'Network error. Please check your connection and try again.';
        }
        
        errorEl.textContent = errorMessage;
        errorEl.classList.add('active');
    }
}

async function loadCurrentUser() {
    try {
        currentUser = await api.getCurrentUser();
        hideAuthModal();
        showMainApp();
        loadUserData();
    } catch (error) {
        // Token invalid, show auth
        api.clearToken();
        showAuthModal();
    }
}

function loadUserData() {
    if (currentUser) {
        document.getElementById('userName').textContent = currentUser.username;
        document.getElementById('userEmail').textContent = currentUser.email;
    }
    
    // Load documents and chats
    loadDocuments();
    createNewChat();
}

function handleLogout() {
    // Call cleanup endpoint before logging out
    cleanupUserDocuments();
    
    api.clearToken();
    currentUser = null;
    showAuthModal();
    hideMainApp();
    showToast('Logged out', 'Come back soon! Your documents have been cleaned up.', 'success');
}

async function cleanupUserDocuments() {
    try {
        const response = await fetch(`${api.baseURL}/cleanup/user`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${api.getToken()}`
            }
        });
        
        if (response.ok) {
            const result = await response.json();
            console.log('✅ Cleanup successful:', result);
        }
    } catch (error) {
        console.error('Cleanup failed:', error);
        // Don't block logout on cleanup failure
    }
}

function showAuthModal() {
    document.getElementById('authModal').classList.add('active');
}

function hideAuthModal() {
    document.getElementById('authModal').classList.remove('active');
}

function showMainApp() {
    document.getElementById('mainApp').classList.add('active');
}

function hideMainApp() {
    document.getElementById('mainApp').classList.remove('active');
}

function clearAuthErrors() {
    document.querySelectorAll('.error-message').forEach(el => {
        el.classList.remove('active');
        el.textContent = '';
    });
}
