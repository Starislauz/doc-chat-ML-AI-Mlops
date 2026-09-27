// Document management
let documents = [];
let selectedFiles = [];

// Make documents globally accessible for chat.js
window.documents = documents;

function initDocuments() {
    setupDocumentHandlers();
}

function setupDocumentHandlers() {
    // Upload button
    document.getElementById('uploadBtn').addEventListener('click', openUploadModal);
    
    // File input - ENABLE MULTIPLE
    const fileInput = document.getElementById('fileInput');
    fileInput.setAttribute('multiple', 'multiple');
    fileInput.addEventListener('change', handleFileSelect);
    
    // Drag and drop
    const uploadArea = document.getElementById('uploadArea');
    
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });
    
    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.add('dragover');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.remove('dragover');
        }, false);
    });
    
    uploadArea.addEventListener('drop', handleDrop, false);
    
    // Search documents
    document.getElementById('searchDocs').addEventListener('input', filterDocuments);
}

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

function openUploadModal() {
    // Check document limit before allowing upload
    checkDocumentLimit();
    
    selectedFiles = [];
    updateFilePreview();
    document.getElementById('uploadModal').classList.add('active');
}

async function checkDocumentLimit() {
    try {
        const limitStatus = await api.request('/cleanup/limit-status');
        
        if (!limitStatus.can_upload) {
            showToast(
                'Document Limit Reached',
                `You have ${limitStatus.current_documents}/${limitStatus.max_documents} documents. Please delete some documents before uploading new ones.`,
                'error'
            );
            closeUploadModal();
            return false;
        }
        
        if (limitStatus.current_documents >= limitStatus.max_documents - 1) {
            showToast(
                'Warning',
                `You have ${limitStatus.current_documents}/${limitStatus.max_documents} documents. You can only upload ${limitStatus.max_documents - limitStatus.current_documents} more.`,
                'warning'
            );
        }
        
        return true;
    } catch (error) {
        console.error('Failed to check document limit:', error);
        return true; // Allow upload on error
    }
}

function closeUploadModal() {
    selectedFiles = [];
    document.getElementById('uploadModal').classList.remove('active');
    document.getElementById('uploadProgress').style.display = 'none';
    document.getElementById('uploadArea').style.display = 'block';
    document.getElementById('fileInput').value = '';
    document.getElementById('filePreview').style.display = 'none';
}

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = Array.from(dt.files);
    
    if (files.length > 0) {
        addFiles(files);
    }
}

function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
        addFiles(files);
    }
}

function addFiles(files) {
    const maxFiles = 5;
    const allowedExtensions = ['.pdf', '.txt', '.md', '.docx', '.doc', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'];
    
    // Check max files
    if (selectedFiles.length + files.length > maxFiles) {
        showToast('Too many files', `You can upload up to ${maxFiles} files at once`, 'error');
        return;
    }
    
    // Validate and add files
    files.forEach(file => {
        const fileExt = '.' + file.name.split('.').pop().toLowerCase();
        
        if (!allowedExtensions.includes(fileExt)) {
            showToast('Invalid file type', `${file.name} - Please upload PDF, DOCX, TXT, or image files`, 'error');
            return;
        }
        
        const maxSize = 10 * 1024 * 1024; // 10MB
        if (file.size > maxSize) {
            showToast('File too large', `${file.name} - Please upload files smaller than 10MB`, 'error');
            return;
        }
        
        selectedFiles.push(file);
    });
    
    updateFilePreview();
}

function updateFilePreview() {
    const previewContainer = document.getElementById('filePreview');
    const previewList = document.getElementById('previewList');
    const uploadButton = document.getElementById('startUploadBtn');
    
    if (selectedFiles.length === 0) {
        previewContainer.style.display = 'none';
        return;
    }
    
    previewContainer.style.display = 'block';
    previewList.innerHTML = '';
    
    selectedFiles.forEach((file, index) => {
        const fileExt = '.' + file.name.split('.').pop().toLowerCase();
        const isImage = ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'].includes(fileExt);
        
        const fileItem = document.createElement('div');
        fileItem.className = 'file-preview-item';
        fileItem.innerHTML = `
            <div class="file-icon"><i class="fas ${isImage ? 'fa-image' : 'fa-file'}"></i></div>
            <div class="file-details">
                <div class="file-name">${file.name}</div>
                <div class="file-size">${formatFileSize(file.size)}</div>
            </div>
            <button class="remove-file-btn" onclick="removeFile(${index})">
                <i class="fas fa-times"></i>
            </button>
        `;
        
        previewList.appendChild(fileItem);
    });
    
    // Update upload button
    if (!uploadButton) {
        const btnContainer = document.createElement('div');
        btnContainer.style.cssText = 'text-align: center; margin-top: 15px;';
        btnContainer.innerHTML = `
            <button id="startUploadBtn" class="btn btn-primary" onclick="startUpload()">
                <i class="fas fa-cloud-upload-alt"></i> Upload ${selectedFiles.length} File${selectedFiles.length > 1 ? 's' : ''}
            </button>
        `;
        previewContainer.appendChild(btnContainer);
    } else {
        uploadButton.innerHTML = `<i class="fas fa-cloud-upload-alt"></i> Upload ${selectedFiles.length} File${selectedFiles.length > 1 ? 's' : ''}`;
    }
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    updateFilePreview();
}

async function startUpload() {
    if (selectedFiles.length === 0) {
        showToast('No files selected', 'Please select at least one file', 'error');
        return;
    }
    
    // Show progress
    document.getElementById('uploadArea').style.display = 'none';
    document.getElementById('filePreview').style.display = 'none';
    document.getElementById('uploadProgress').style.display = 'block';
    
    try {
        const response = await api.uploadMultipleDocuments(selectedFiles, (progress) => {
            updateUploadProgress(progress);
        });
        
        const successCount = response.length;
        
        // Show success notification with summary preview
        if (successCount > 0) {
            const firstDoc = response[0];
            let message = `${successCount} file${successCount > 1 ? 's' : ''} processed successfully!`;
            
            // If single file and has summary, show preview
            if (successCount === 1 && firstDoc.summary) {
                const summaryPreview = firstDoc.summary.substring(0, 100);
                showToast(
                    'Upload successful', 
                    `${message}\n\nDocument analyzed: ${summaryPreview}...`,
                    'success',
                    5000
                );
            } else {
                showToast('Upload successful', message, 'success');
            }
        }
        
        closeUploadModal();
        
        // Close mobile sidebar on mobile devices
        if (window.innerWidth <= 768) {
            if (typeof window.closeMobileSidebar === 'function') {
                window.closeMobileSidebar();
            }
        }
        
        // Reload documents
        await loadDocuments();
        
        // Refresh welcome message to show documents are available
        if (typeof clearChatMessages === 'function') {
            clearChatMessages();
        }
        
        // If single document, automatically show its summary
        if (successCount === 1 && response[0].summary) {
            setTimeout(() => {
                const doc = response[0];
                documents.push(doc); // Add to local array if not already there
                window.documents = documents; // Update global
                viewDocumentSummary(doc.id, null);
            }, 500);
        }
        
    } catch (error) {
        showErrorToast(error, 'Upload failed');
        document.getElementById('uploadArea').style.display = 'block';
        document.getElementById('uploadProgress').style.display = 'none';
        document.getElementById('filePreview').style.display = 'block';
    }
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function updateUploadProgress(progress) {
    const progressFill = document.querySelector('.progress-fill');
    const statusText = document.getElementById('uploadStatus');
    
    progressFill.style.width = `${progress}%`;
    
    if (progress < 100) {
        statusText.textContent = `Uploading... ${Math.round(progress)}%`;
    } else {
        statusText.textContent = 'Processing document...';
    }
}

async function loadDocuments() {
    const documentList = document.getElementById('documentList');
    documentList.innerHTML = '<div class="loading">Loading documents...</div>';
    
    try {
        documents = await api.listDocuments();
        window.documents = documents; // Update global reference
        console.log('Loaded documents:', documents.length, documents);
        renderDocuments(documents);
        
        // Update chat UI based on document availability
        updateChatUIForDocuments();
    } catch (error) {
        documentList.innerHTML = '<div class="loading">Failed to load documents</div>';
        console.error('Failed to load documents:', error);
        documents = []; // Ensure empty array
        window.documents = documents; // Update global reference
    }
}

function updateChatUIForDocuments() {
    const chatTitle = document.getElementById('chatTitle');
    const chatSubtitle = document.getElementById('chatSubtitle');
    const messageInput = document.getElementById('messageInput');
    
    if (window.documents && window.documents.length > 0) {
        // Enable chat
        if (messageInput) {
            messageInput.disabled = false;
            messageInput.placeholder = 'Ask questions about your documents...';
        }
        if (chatTitle) {
            chatTitle.textContent = 'AI Assistant';
        }
        if (chatSubtitle) {
            chatSubtitle.textContent = `${window.documents.length} document${window.documents.length > 1 ? 's' : ''} available - Ask me anything!`;
        }
    } else {
        // Disable chat - require document upload
        if (messageInput) {
            messageInput.disabled = false; // Keep enabled so they can type
            messageInput.placeholder = 'Please upload documents first to start chatting...';
        }
        if (chatTitle) {
            chatTitle.textContent = 'AI Assistant';
        }
        if (chatSubtitle) {
            chatSubtitle.textContent = 'Upload documents to start chatting';
        }
    }
}

function renderDocuments(docs) {
    const documentList = document.getElementById('documentList');
    
    if (!docs || docs.length === 0) {
        documentList.innerHTML = `
            <div class="loading">
                <p>No documents yet</p>
                <p style="color: #888; font-size: 14px; margin-top: 10px;">Upload documents, PDFs, or images to start chatting!</p>
                <button class="btn btn-small" onclick="openUploadModal()" style="margin-top: 15px;">
                    <i class="fas fa-upload"></i> Upload Documents
                </button>
            </div>
        `;
        return;
    }
    
    documentList.innerHTML = '';
    
    docs.forEach(doc => {
        const fileExt = doc.filename ? '.' + doc.filename.split('.').pop().toLowerCase() : '';
        const isImage = ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'].includes(fileExt);
        const icon = isImage ? '<i class="fas fa-image"></i>' : '<i class="fas fa-file"></i>';
        
        const docItem = document.createElement('div');
        docItem.className = 'document-item';
        
        // Create summary preview if available
        let summaryHTML = '';
        if (doc.summary) {
            // Extract first line or truncate summary for preview
            const summaryPreview = doc.summary.split('\n')[0].substring(0, 150);
            summaryHTML = `
                <div class="doc-summary-preview">
                    ${summaryPreview}${doc.summary.length > 150 ? '...' : ''}
                </div>
            `;
        }
        
        docItem.innerHTML = `
            <div class="doc-icon">${icon}</div>
            <div class="doc-details">
                <div class="doc-name">${doc.filename || 'Untitled'}</div>
                <div class="doc-info">
                    ${doc.chunk_count || 0} chunks • ${formatDate(doc.uploaded_at)}
                </div>
                ${summaryHTML}
            </div>
            <div class="doc-actions">
                <button class="doc-view-btn" onclick="viewDocumentSummary('${doc.id}', event)" title="View full summary">
                    <i class="fas fa-info-circle"></i>
                </button>
                <button class="doc-delete-btn" onclick="deleteDocument('${doc.id}', '${doc.filename}', event)" title="Delete document">
                    <i class="fas fa-trash-alt"></i>
                </button>
            </div>
        `;
        
        docItem.addEventListener('click', (e) => {
            // Don't select if clicking action buttons
            if (!e.target.closest('.doc-actions')) {
                selectDocument(doc);
            }
        });
        
        documentList.appendChild(docItem);
    });
}

async function viewDocumentSummary(documentId, event) {
    // Prevent document selection when clicking view
    if (event) {
        event.stopPropagation();
    }
    
    try {
        // Show loading modal
        showSummaryModal('Loading...', '<div class="loading">Loading document summary...</div>');
        
        // Fetch document details
        const doc = documents.find(d => d.id === documentId);
        
        if (!doc) {
            showToast('Error', 'Document not found', 'error');
            return;
        }
        
        // Format summary for display
        let summaryHTML = '';
        if (doc.summary) {
            // Convert markdown-like formatting to HTML
            summaryHTML = formatSummaryText(doc.summary);
        } else {
            summaryHTML = `
                <p style="color: #888;">No summary available for this document.</p>
                <p style="color: #888; font-size: 14px; margin-top: 10px;">
                    This may occur if the document was uploaded before the summary feature was added,
                    or if there was an error during processing.
                </p>
            `;
        }
        
        // Show in modal
        showSummaryModal(
            doc.filename,
            `
                <div class="document-stats">
                    <div><strong>Chunks:</strong> ${doc.chunk_count}</div>
                    <div><strong>Size:</strong> ${formatFileSize(doc.file_size || 0)}</div>
                    <div><strong>Type:</strong> ${doc.file_type || 'Unknown'}</div>
                    <div><strong>Uploaded:</strong> ${formatDate(doc.uploaded_at)}</div>
                </div>
                <div class="document-summary-content">
                    ${summaryHTML}
                </div>
            `
        );
        
    } catch (error) {
        console.error('Failed to view document summary:', error);
        showToast('Error', 'Could not load document summary', 'error');
    }
}

function formatSummaryText(text) {
    // Convert markdown-like text to HTML
    let formatted = text
        // Bold text **text** or __text__
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/__(.+?)__/g, '<strong>$1</strong>')
        // Bullet points
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
        // Paragraphs
        .split('\n\n').map(para => {
            if (para.includes('<li>')) {
                return '<ul style="margin: 10px 0; padding-left: 20px;">' + para + '</ul>';
            }
            return '<p style="margin: 10px 0;">' + para + '</p>';
        }).join('');
    
    return formatted;
}

function showSummaryModal(title, content) {
    // Create or update modal
    let modal = document.getElementById('summaryModal');
    
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'summaryModal';
        modal.className = 'modal active';
        modal.innerHTML = `
            <div class="modal-overlay" onclick="closeSummaryModal()"></div>
            <div class="modal-content" style="max-width: 700px;">
                <div class="modal-header">
                    <h3 id="summaryModalTitle">${title}</h3>
                    <button class="modal-close" onclick="closeSummaryModal()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="modal-body" id="summaryModalBody">
                    ${content}
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeSummaryModal()">Close</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    } else {
        document.getElementById('summaryModalTitle').innerHTML = title;
        document.getElementById('summaryModalBody').innerHTML = content;
        modal.classList.add('active');
    }
}

function closeSummaryModal() {
    const modal = document.getElementById('summaryModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function selectDocument(doc) {
    // Update UI
    document.querySelectorAll('.document-item').forEach(item => {
        item.classList.remove('active');
    });
    event.currentTarget.classList.add('active');
    
    // Update chat header
    document.getElementById('chatTitle').textContent = doc.filename;
    document.getElementById('chatSubtitle').textContent = `${doc.chunk_count} chunks • Ask questions about this document`;
    
    showToast('Document selected', `Now chatting about ${doc.filename}`, 'success');
}

async function deleteDocument(documentId, filename, event) {
    // Prevent document selection when clicking delete
    if (event) {
        event.stopPropagation();
    }
    
    // Confirmation dialog
    if (!confirm(`Are you sure you want to delete "${filename}"?\n\nThis will permanently remove the document and all its data.`)) {
        return;
    }
    
    try {
        // Show loading toast
        showToast('Deleting...', `Removing ${filename}`, 'info');
        
        // Delete via API
        await api.deleteDocument(documentId);
        
        // Show success
        showToast('Deleted', `${filename} has been deleted`, 'success');
        
        // Reload documents
        await loadDocuments();
        
        // Clear chat if this was the selected document
        const chatTitle = document.getElementById('chatTitle');
        if (chatTitle && chatTitle.textContent.includes(filename)) {
            chatTitle.textContent = 'AI Assistant';
            document.getElementById('chatSubtitle').textContent = 'Upload documents and start asking questions';
        }
        
    } catch (error) {
        console.error('Failed to delete document:', error);
        showErrorToast(error, 'Delete failed');
    }
}

function filterDocuments() {
    const searchTerm = document.getElementById('searchDocs').value.toLowerCase();
    
    if (!searchTerm) {
        renderDocuments(documents);
        return;
    }
    
    const filtered = documents.filter(doc => 
        doc.filename.toLowerCase().includes(searchTerm)
    );
    
    renderDocuments(filtered);
}

function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString();
}

// Initialize documents when DOM is loaded
document.addEventListener('DOMContentLoaded', initDocuments);
