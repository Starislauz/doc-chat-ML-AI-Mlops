// Authentication handling
let currentUser = null;

// Initialize auth
document.addEventListener('DOMContentLoaded', () => {
    testBackendConnection();
    initAuth();
    setupPageCloseCleanup();

    // The API client fires this when an authenticated request is rejected
    window.addEventListener('auth:expired', handleSessionExpired);
});

let sessionExpiryHandled = false;

/**
 * The stored token was rejected by the server (expired, revoked, restarted
 * with a new SECRET_KEY). Send the user back to the login screen with a clear
 * explanation instead of leaving them stuck on failing requests.
 */
function handleSessionExpired() {
    if (sessionExpiryHandled) return;
    sessionExpiryHandled = true;

    api.clearToken();
    currentUser = null;
    showAuthModal();

    const errorEl = document.getElementById('loginError');
    if (errorEl) {
        errorEl.textContent = 'Your session expired, so you were signed out. Please log in again.';
        errorEl.classList.add('active');
    }

    showToast(
        'Signed out',
        'Your session expired for security. Please log in again - nothing was lost.',
        'warning',
        7000
    );

    setTimeout(() => { sessionExpiryHandled = false; }, 3000);
}

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
                errorDiv.textContent = 'Unable to connect to server. Please refresh the page or contact support.';
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
        const info = APIClient.friendlyError(error);
        errorEl.textContent = info.hint ? `${info.message}\n${info.hint}` : info.message;
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
        const info = APIClient.friendlyError(error);
        errorEl.textContent = info.hint ? `${info.message}\n${info.hint}` : info.message;
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

async function handleLogout() {
    // Revoke the token server-side so it can never be reused
    try {
        const token = api.getToken();
        if (token) {
            await fetch(`${api.baseURL}/logout`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
        }
    } catch (error) {
        console.error('Logout revocation failed:', error);
        // Never block the user on revocation failure - still log out locally
    }

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
