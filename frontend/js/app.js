// Main app initialization and utilities

// Toast notifications
//
// Built with DOM nodes + textContent (never innerHTML for server text), so a
// filename or server message can never inject markup. Supports either
// showToast(title, message, type, duration) or showToast({ title, message }).
function showToast(title, message, type = 'success', duration = 4200) {
    if (title && typeof title === 'object') {
        ({ title, message, type = 'success', duration = 4200 } = title);
    }

    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    // Collapse identical repeats (the same failure often fires twice)
    const signature = `${type}|${title}|${message}`;
    const duplicate = Array.from(container.children)
        .find((child) => child.dataset.signature === signature);
    if (duplicate) return duplicate;

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-triangle-exclamation'
    };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.dataset.signature = signature;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

    const iconWrap = document.createElement('div');
    iconWrap.className = 'toast-icon';
    const icon = document.createElement('i');
    icon.className = `fas ${icons[type] || 'fa-info-circle'}`;
    iconWrap.appendChild(icon);

    const content = document.createElement('div');
    content.className = 'toast-content';

    const titleEl = document.createElement('div');
    titleEl.className = 'toast-title';
    titleEl.textContent = title || '';
    content.appendChild(titleEl);

    if (message) {
        const messageEl = document.createElement('div');
        messageEl.className = 'toast-message';
        messageEl.textContent = message;
        content.appendChild(messageEl);
    }

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '\u00d7';
    close.addEventListener('click', () => removeToast(toast));

    toast.append(iconWrap, content, close);
    container.appendChild(toast);

    // Keep the stack short so a burst of errors can't cover the screen
    while (container.children.length > 4) {
        removeToast(container.firstElementChild);
    }

    // Errors deserve longer on screen than confirmations
    const life = type === 'error' && duration === 4200 ? 8000 : duration;
    if (life > 0) setTimeout(() => removeToast(toast), life);

    return toast;
}

function removeToast(toast) {
    if (!toast || !toast.parentElement) return;
    toast.style.animation = 'slideOutRight 0.22s ease forwards';
    setTimeout(() => toast.remove(), 220);
}

/**
 * Explain a failure anywhere in the app the same way.
 * Falls back to plain text if the API client has not loaded yet.
 */
function errorText(error) {
    const info = (typeof APIClient !== 'undefined' && APIClient.friendlyError)
        ? APIClient.friendlyError(error)
        : { title: 'Something went wrong', message: (error && error.message) || String(error), hint: null };
    return {
        title: info.title || 'Something went wrong',
        text: info.hint ? `${info.message}\n${info.hint}` : (info.message || '') 
    };
}

function showErrorToast(error, fallbackTitle = 'Something went wrong') {
    const info = errorText(error);
    return showToast(info.title || fallbackTitle, info.text, 'error');
}

// Last line of defence: nothing should ever fail silently in the console only.
let lastUnexpectedReport = 0;
function reportUnexpectedError(detail) {
    const now = Date.now();
    if (now - lastUnexpectedReport < 5000) return; // don't spam the user
    lastUnexpectedReport = now;
    console.error('Unexpected UI error:', detail);
    showToast(
        'Something went wrong',
        'An unexpected error occurred in the interface. Your documents are safe - please try that again.',
        'error'
    );
}

window.addEventListener('unhandledrejection', (event) => {
    reportUnexpectedError(event.reason);
});

window.addEventListener('error', (event) => {
    // Ignore resource-load failures (fonts, icons); only real script errors
    if (event.error) reportUnexpectedError(event.error);
});

// Theme toggle
let isDarkTheme = true;

function initTheme() {
    const themeToggle = document.getElementById('themeToggle');
    const savedTheme = localStorage.getItem('theme') || 'dark';
    
    isDarkTheme = savedTheme === 'dark';
    applyTheme();
    
    themeToggle.addEventListener('click', toggleTheme);
}

function toggleTheme() {
    isDarkTheme = !isDarkTheme;
    applyTheme();
    localStorage.setItem('theme', isDarkTheme ? 'dark' : 'light');
    
    showToast(
        'Theme changed',
        `Switched to ${isDarkTheme ? 'dark' : 'light'} mode`,
        'success'
    );
}

function applyTheme() {
    const icon = document.querySelector('#themeToggle i');
    
    if (isDarkTheme) {
        document.body.removeAttribute('data-theme');
        icon.className = 'fas fa-moon';
    } else {
        document.body.setAttribute('data-theme', 'light');
        icon.className = 'fas fa-sun';
    }
}

// Settings
function initSettings() {
    const settingsBtn = document.getElementById('settingsBtn');
    
    settingsBtn.addEventListener('click', () => {
        showToast('Settings', 'Settings panel coming soon!', 'success');
    });
}

// Mobile menu
function initMobileMenu() {
    const menuBtn = document.getElementById('mobileMenuBtn');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    if (!menuBtn || !sidebar || !overlay) {
        console.warn('Mobile menu elements not found');
        return;
    }
    
    // Toggle sidebar when menu button is clicked
    menuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMobileSidebar();
    });
    
    // Close sidebar when overlay is clicked
    overlay.addEventListener('click', () => {
        closeMobileSidebar();
    });

    // Explicit close button inside the drawer
    const closeBtn = document.getElementById('closeSidebarBtn');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeMobileSidebar());
    }

    // Escape closes the drawer
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeMobileSidebar();
    });
    
    // Close sidebar when a document is selected (mobile only)
    sidebar.addEventListener('click', (e) => {
        if (window.innerWidth <= 768) {
            const docItem = e.target.closest('.document-item');
            if (docItem) {
                setTimeout(closeMobileSidebar, 300); // Delay to show selection
            }
        }
    });
    
    // Handle window resize
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (window.innerWidth > 768) {
                closeMobileSidebar();
            }
        }, 250);
    });
}

function toggleMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    if (sidebar && overlay) {
        const isOpen = sidebar.classList.contains('mobile-open');
        
        if (isOpen) {
            closeMobileSidebar();
        } else {
            sidebar.classList.add('mobile-open');
            overlay.classList.add('active');
            document.body.style.overflow = 'hidden'; // Prevent background scroll
        }
    }
}

function closeMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    if (sidebar && overlay) {
        sidebar.classList.remove('mobile-open');
        overlay.classList.remove('active');
        document.body.style.overflow = ''; // Restore scroll
    }
}

// Keyboard shortcuts
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K: Focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            document.getElementById('searchDocs').focus();
        }
        
        // Ctrl/Cmd + U: Upload
        if ((e.ctrlKey || e.metaKey) && e.key === 'u') {
            e.preventDefault();
            openUploadModal();
        }
        
        // Ctrl/Cmd + N: New chat
        if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
            e.preventDefault();
            createNewChat();
        }
        
        // Escape: Close modals
        if (e.key === 'Escape') {
            closeUploadModal();
        }
    });
}

// Error handling
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    showToast('Error', 'Something went wrong. Please try again.', 'error');
});

// Check API health on startup
async function checkAPIHealth() {
    try {
        const health = await api.healthCheck();
        console.log('API Health:', health);
        
        // Health check notifications disabled - check console logs if needed
        // if (health.status !== 'healthy') {
        //     showToast(
        //         'System Status',
        //         `API is ${health.status}. Some features may be limited.`,
        //         'warning'
        //     );
        // }
    } catch (error) {
        console.error('Health check failed:', error);
        // Connection error notifications disabled - check console logs if needed
        // showToast(
        //     'Connection Error',
        //     'Unable to connect to the server. Please check if the API is running.',
        //     'error'
        // );
    }
}

// Load branding information
async function loadBranding() {
    try {
        const response = await fetch(`${api.baseURL}/branding`);
        const branding = await response.json();
        
        console.log('Branding loaded:', branding);
        
        // Apply branding based on style
        const isProfessional = branding.branding_style === 'professional';
        const displayName = isProfessional ? branding.author : branding.branded_name;
        
        // Update auth modal
        document.getElementById('authAppTitle').textContent = isProfessional 
            ? branding.app_name 
            : branding.branded_name;
        document.getElementById('authAppSubtitle').textContent = branding.tagline;
        document.getElementById('authAppAuthor').textContent = branding.author;
        
        // Update welcome message
        document.getElementById('welcomeTitle').textContent = isProfessional 
            ? `Welcome to ${branding.app_name}!` 
            : `Welcome to ${branding.branded_name}!`;
        document.getElementById('welcomeSubtitle').textContent = 
            `Upload documents and ask questions. I'm ${displayName}'s AI assistant here to help!`;
        document.getElementById('welcomeAuthor').textContent = isProfessional 
            ? branding.author 
            : `Powered by ${branding.author}`;
        document.getElementById('welcomeTagline').textContent = branding.tagline;
        
        // Update footer branding
        document.getElementById('footerAuthor').textContent = isProfessional 
            ? branding.author 
            : branding.branded_name;
        
        // Update contact links
        if (branding.contact.linkedin) {
            document.getElementById('brandingLinkedIn').href = branding.contact.linkedin;
            document.getElementById('brandingLinkedIn').style.display = 'inline-block';
        }
        if (branding.contact.github) {
            document.getElementById('brandingGitHub').href = branding.contact.github;
            document.getElementById('brandingGitHub').style.display = 'inline-block';
        }
        if (branding.contact.portfolio) {
            document.getElementById('brandingPortfolio').href = branding.contact.portfolio;
            document.getElementById('brandingPortfolio').style.display = 'inline-block';
        }
        
        // Update About modal
        document.getElementById('aboutAppTitle').textContent = isProfessional 
            ? branding.app_name 
            : branding.branded_name;
        document.getElementById('aboutAppTagline').textContent = branding.tagline;
        document.getElementById('aboutAppVersion').textContent = `Version ${branding.app_version}`;
        document.getElementById('aboutAuthorName').textContent = branding.author;
        document.getElementById('aboutAuthorBio').textContent = branding.bio;
        
        // About modal contact links
        if (branding.contact.linkedin) {
            document.getElementById('aboutLinkedIn').href = branding.contact.linkedin;
            document.getElementById('aboutLinkedIn').style.display = 'inline-block';
        }
        if (branding.contact.github) {
            document.getElementById('aboutGitHub').href = branding.contact.github;
            document.getElementById('aboutGitHub').style.display = 'inline-block';
        }
        if (branding.contact.portfolio) {
            document.getElementById('aboutPortfolio').href = branding.contact.portfolio;
            document.getElementById('aboutPortfolio').style.display = 'inline-block';
        }
        if (branding.contact.email) {
            document.getElementById('aboutEmail').href = `mailto:${branding.contact.email}`;
            document.getElementById('aboutEmail').style.display = 'inline-block';
        }
        
        // Update page title
        document.title = isProfessional 
            ? `${branding.app_name} - by ${branding.author}` 
            : `${branding.branded_name} - ${branding.tagline}`;
        
    } catch (error) {
        console.error('Failed to load branding:', error);
        // Use defaults if branding fails to load
    }
}

// About modal functions
function openAboutModal() {
    document.getElementById('aboutModal').classList.add('active');
}

function closeAboutModal() {
    document.getElementById('aboutModal').classList.remove('active');
}

// Initialize everything
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 RAG Document Chat UI initialized');

    document.body.classList.add('performance-mode');
    
    initTheme();
    initSettings();
    initMobileMenu();
    initKeyboardShortcuts();
    checkAPIHealth();
    loadBranding(); // Load branding information
    
    // Setup About button
    const aboutBtn = document.getElementById('aboutBtn');
    if (aboutBtn) {
        aboutBtn.addEventListener('click', openAboutModal);
    }
    
    // Show loading state
    const mainApp = document.getElementById('mainApp');
    if (!mainApp.classList.contains('active')) {
        // Will be shown by auth.js
    }
});

// Service worker for offline support (optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        // Uncomment to enable service worker
        // navigator.serviceWorker.register('/sw.js')
        //     .then(reg => console.log('Service Worker registered:', reg))
        //     .catch(err => console.log('Service Worker registration failed:', err));
    });
}

// Export utilities for use in other modules
window.showToast = showToast;
window.closeUploadModal = closeUploadModal;
window.sendSampleQuestion = sendSampleQuestion;
window.closeMobileSidebar = closeMobileSidebar;
window.closeAboutModal = closeAboutModal;
window.openAboutModal = openAboutModal;
