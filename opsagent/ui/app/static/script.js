// ============================================================
// State Management
// ============================================================
let conversations = [];
let currentConversationId = null;
let selectedModel = 'gpt-4o-mini';
let userInfo = null;
let openDropdown = null;  // Track which dropdown is open

// Video state management
let currentView = 'chat';  // 'chat', 'video-gallery', 'video-player'
let currentVideoUrl = null;
let currentVideoTitle = null;

// ============================================================
// API Client Functions
// ============================================================
const API_BASE = '';  // Same origin

async function fetchUser() {
    const res = await fetch(`${API_BASE}/api/user`);
    return res.json();
}

async function fetchConversations() {
    const res = await fetch(`${API_BASE}/api/conversations`);
    conversations = await res.json();
    return conversations;
}

async function fetchConversation(id) {
    const res = await fetch(`${API_BASE}/api/conversations/${id}`);
    return res.json();
}

async function createConversation() {
    const res = await fetch(`${API_BASE}/api/conversations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: selectedModel })
    });
    return res.json();
}

async function renameConversation(id, title) {
    const res = await fetch(`${API_BASE}/api/conversations/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
    });
    return res.json();
}

async function deleteConversation(id) {
    await fetch(`${API_BASE}/api/conversations/${id}`, {
        method: 'DELETE'
    });
}

async function sendMessage(id, message) {
    const res = await fetch(`${API_BASE}/api/conversations/${id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
    });
    return res.json();
}

async function fetchModels() {
    const res = await fetch(`${API_BASE}/api/models`);
    return res.json();
}

async function fetchVideos() {
    try {
        const res = await fetch(`${API_BASE}/api/videos`);
        const data = await res.json();
        return data.videos || [];
    } catch (error) {
        console.error('Error fetching videos:', error);
        return [];
    }
}

// ============================================================
// Dropdown Management
// ============================================================
function closeAllDropdowns() {
    // Close all chat menu dropdowns
    document.querySelectorAll('.menu-wrapper.open').forEach(wrapper => {
        wrapper.classList.remove('open');
    });
    // Close model selector
    document.getElementById('model-selector-container').classList.remove('open');
    openDropdown = null;
}

// ============================================================
// Navigation Item Active State
// ============================================================
function setActiveNavItem(itemId) {
    // Remove active class from all nav items
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });

    // Remove active class from all chat items
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });

    // Add active class to specified item
    if (itemId) {
        const item = document.getElementById(itemId);
        if (item) {
            item.classList.add('active');
        }
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.menu-wrapper') && !e.target.closest('.model-selector-container')) {
        closeAllDropdowns();
    }
});

// ============================================================
// UI Rendering Functions
// ============================================================
function renderUserInfo() {
    const avatarDiv = document.getElementById('user-avatar');
    const userNameSpan = document.getElementById('user-name');
    const userTagSpan = document.getElementById('user-tag');

    if (userInfo.mode === 'local') {
        avatarDiv.textContent = 'L';
        userNameSpan.textContent = 'Local Mode';
        userTagSpan.textContent = '';
    } else if (userInfo.mode === 'local_psql') {
        avatarDiv.textContent = userInfo.user_name.charAt(0).toUpperCase();
        userNameSpan.textContent = userInfo.user_name;
        userTagSpan.textContent = 'Test (PostgreSQL)';
    } else if (userInfo.mode === 'local_redis') {
        avatarDiv.textContent = userInfo.user_name.charAt(0).toUpperCase();
        userNameSpan.textContent = userInfo.user_name;
        userTagSpan.textContent = 'Test (Redis)';
    } else {
        avatarDiv.textContent = userInfo.user_name.charAt(0).toUpperCase();
        userNameSpan.textContent = userInfo.user_name;
        // userTagSpan.textContent = 'Plus';
    }
}

function renderConversationsList() {
    const chatListDiv = document.getElementById('chat-list');
    chatListDiv.innerHTML = '';

    if (conversations.length === 0) {
        chatListDiv.innerHTML = '<div style="padding: 12px; color: #999; font-size: 0.85rem;">No chats yet</div>';
        return;
    }

    conversations.forEach(convo => {
        const chatItemDiv = document.createElement('div');
        // Add 'active' class if this is the current conversation
        chatItemDiv.className = convo.id === currentConversationId ? 'chat-item active' : 'chat-item';
        chatItemDiv.innerHTML = `
            <span class="chat-title" data-id="${convo.id}">${convo.title}</span>
            <div class="menu-wrapper" data-menu-id="${convo.id}">
                <button class="options-trigger">
                    <svg class="icon icon-sm" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="1"></circle>
                        <circle cx="19" cy="12" r="1"></circle>
                        <circle cx="5" cy="12" r="1"></circle>
                    </svg>
                </button>
                <div class="dropdown-menu">
                    <div class="menu-item" data-action="rename" data-id="${convo.id}">
                        <svg class="icon icon-sm" viewBox="0 0 24 24">
                            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
                        </svg>
                        Rename
                    </div>
                    <div class="menu-item delete" data-action="delete" data-id="${convo.id}">
                        <svg class="icon icon-sm" viewBox="0 0 24 24">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                        Delete
                    </div>
                </div>
            </div>
        `;

        // Click handler for chat title
        chatItemDiv.querySelector('.chat-title').addEventListener('click', () => {
            selectConversation(convo.id);
        });

        // Click handler for options trigger (3-dots button)
        const menuWrapper = chatItemDiv.querySelector('.menu-wrapper');
        const trigger = chatItemDiv.querySelector('.options-trigger');
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            const wasOpen = menuWrapper.classList.contains('open');
            closeAllDropdowns();
            if (!wasOpen) {
                menuWrapper.classList.add('open');
                openDropdown = convo.id;
            }
        });

        chatListDiv.appendChild(chatItemDiv);
    });

    // Attach menu item handlers
    document.querySelectorAll('.menu-item').forEach(item => {
        item.addEventListener('click', handleMenuAction);
    });
}

function renderWelcomeScreen() {
    const chatCanvas = document.getElementById('chat-canvas');
    chatCanvas.className = 'chat-canvas welcome';

    // Clear nav item active state
    setActiveNavItem(null);

    const firstName = userInfo.user_name.split(' ')[0];
    chatCanvas.innerHTML = `
        <div class="chat-content-wrapper" style="align-items: center; justify-content: center;">
            <h1 class="welcome-text welcome-title">DAPE OpsAgent Manager</h1>
            <h2 class="welcome-text welcome-subtitle">How can I help, ${firstName}</h2>
        </div>
        <div class="input-wrapper">
            <div class="input-box">
                <button class="icon-btn">
                    <svg class="icon" viewBox="0 0 24 24">
                        <line x1="12" y1="5" x2="12" y2="19"></line>
                        <line x1="5" y1="12" x2="19" y2="12"></line>
                    </svg>
                </button>
                <input type="text" class="input-text" placeholder="Ask anything" id="message-input">
                <button class="icon-btn" id="send-btn">
                    <svg class="icon" style="fill:#999; stroke:none;" viewBox="0 0 24 24">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path>
                    </svg>
                </button>
            </div>
        </div>
    `;

    attachInputHandlers();
}

function renderConversation(convo) {
    const chatCanvas = document.getElementById('chat-canvas');
    chatCanvas.className = 'chat-canvas';

    // Clear nav item active state
    setActiveNavItem(null);

    const messagesHtml = convo.messages.map(msg => `
        <div class="message ${msg.role}">
            <div class="message-role">${msg.role === 'user' ? 'You' : 'Assistant'}</div>
            <div class="message-content">${escapeHtml(msg.content)}</div>
        </div>
    `).join('');

    chatCanvas.innerHTML = `
        <div class="messages-container">
            ${messagesHtml}
        </div>
        <div class="input-wrapper">
            <div class="input-box">
                <button class="icon-btn">
                    <svg class="icon" viewBox="0 0 24 24">
                        <line x1="12" y1="5" x2="12" y2="19"></line>
                        <line x1="5" y1="12" x2="19" y2="12"></line>
                    </svg>
                </button>
                <input type="text" class="input-text" placeholder="Message…" id="message-input">
                <button class="icon-btn" id="send-btn">
                    <svg class="icon" style="fill:#999; stroke:none;" viewBox="0 0 24 24">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path>
                    </svg>
                </button>
            </div>
        </div>
    `;

    attachInputHandlers();

    // Scroll to bottom - scroll the chat canvas itself
    setTimeout(() => {
        chatCanvas.scrollTop = chatCanvas.scrollHeight;
    }, 0);
}

function renderVideoGallery(videos) {
    currentView = 'video-gallery';
    const canvas = document.getElementById('chat-canvas');
    canvas.className = 'chat-canvas video-gallery';

    // Highlight video recording button in sidebar
    setActiveNavItem('video-recording-btn');

    if (videos.length === 0) {
        canvas.innerHTML = `
            <div class="empty-state">
                <p>No videos found</p>
                <p class="subtitle">Upload videos to the standup-recordings container</p>
            </div>
        `;
        return;
    }

    canvas.innerHTML = `
        <div class="video-gallery-view">
            <div class="video-grid">
                ${videos.map(video => `
                    <div class="video-card" onclick="selectVideo('${escapeHtml(video.blob_url)}', '${escapeHtml(video.title)}')">
                        <div class="video-thumbnail">
                            <video src="${escapeHtml(video.blob_url)}" preload="metadata"></video>
                            <div class="play-overlay">
                                <svg class="play-icon" viewBox="0 0 24 24" fill="white">
                                    <path d="M8 5v14l11-7z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="video-info">
                            <h3 class="video-title">${escapeHtml(video.title)}</h3>
                            <p class="video-meta">${video.size_mb} MB</p>
                        </div>
                    </div>
                `).join('')}
            </div>
            <div class="input-wrapper">
                <div class="input-box">
                    <button class="icon-btn">
                        <svg class="icon" viewBox="0 0 24 24">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                    </button>
                    <input type="text" class="input-text" placeholder="Ask anything" id="gallery-message-input">
                    <button class="icon-btn" id="gallery-send-btn">
                        <svg class="icon" style="fill:#999; stroke:none;" viewBox="0 0 24 24">
                            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path>
                        </svg>
                    </button>
                </div>
            </div>
        </div>
    `;

    attachGalleryInputHandlers();
}

function selectVideo(videoUrl, title) {
    currentView = 'video-player';
    currentVideoUrl = videoUrl;
    currentVideoTitle = title;
    renderVideoPlayer();
}

function renderVideoPlayer() {
    const canvas = document.getElementById('chat-canvas');
    canvas.className = 'chat-canvas video-player';

    // Highlight video recording button in sidebar
    setActiveNavItem('video-recording-btn');

    canvas.innerHTML = `
        <div class="video-player-view">
            <h2 class="video-title">${escapeHtml(currentVideoTitle)}</h2>
            <div class="video-container">
                <button class="close-video-btn" onclick="backToGallery()" title="Back to videos">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
                <video src="${escapeHtml(currentVideoUrl)}" controls autoplay controlsList="nodownload">
                    Your browser does not support the video tag.
                </video>
            </div>
            <div class="input-wrapper">
                <div class="input-box">
                    <button class="icon-btn">
                        <svg class="icon" viewBox="0 0 24 24">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                    </button>
                    <input type="text" class="input-text" placeholder="Ask about this video…" id="video-message-input">
                    <button class="icon-btn" id="video-send-btn">
                        <svg class="icon" style="fill:#999; stroke:none;" viewBox="0 0 24 24">
                            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path>
                        </svg>
                    </button>
                </div>
            </div>
        </div>
    `;

    attachVideoInputHandlers();
}

async function backToGallery() {
    const videos = await fetchVideos();
    renderVideoGallery(videos);
}

async function handleVideoMessage() {
    const input = document.getElementById('video-message-input');
    const message = input.value.trim();

    if (!message) return;

    // Create message with video context
    const messageWithContext = `${message}\n\nadd ${currentVideoTitle} as context`;

    input.value = '';
    input.disabled = true;

    try {
        // Create new conversation
        const newConvo = await createConversation();
        currentConversationId = newConvo.id;

        // Send message with video context
        await sendMessage(currentConversationId, messageWithContext);

        // Switch back to chat view
        currentView = 'chat';

        // Refresh conversations list
        await fetchConversations();
        renderConversationsList();

        // Load and display the new conversation
        const convo = await fetchConversation(currentConversationId);
        renderConversation(convo);
    } catch (error) {
        console.error('Error sending video message:', error);
        alert('Failed to send message. Please try again.');
    } finally {
        input.disabled = false;
    }
}

function attachVideoInputHandlers() {
    const input = document.getElementById('video-message-input');
    const sendBtn = document.getElementById('video-send-btn');

    if (sendBtn) {
        sendBtn.addEventListener('click', handleVideoMessage);
    }

    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleVideoMessage();
            }
        });
    }
}

async function handleGalleryMessage() {
    const input = document.getElementById('gallery-message-input');
    const message = input.value.trim();

    if (!message) return;

    input.value = '';
    input.disabled = true;

    try {
        // Create new conversation (just like normal chat)
        const newConvo = await createConversation();
        currentConversationId = newConvo.id;

        // Send message without video context
        await sendMessage(currentConversationId, message);

        // Switch back to chat view
        currentView = 'chat';

        // Refresh conversations list
        await fetchConversations();
        renderConversationsList();

        // Load and display the new conversation
        const convo = await fetchConversation(currentConversationId);
        renderConversation(convo);
    } catch (error) {
        console.error('Error sending gallery message:', error);
        alert('Failed to send message. Please try again.');
    } finally {
        input.disabled = false;
    }
}

function attachGalleryInputHandlers() {
    const input = document.getElementById('gallery-message-input');
    const sendBtn = document.getElementById('gallery-send-btn');

    if (sendBtn) {
        sendBtn.addEventListener('click', handleGalleryMessage);
    }

    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleGalleryMessage();
            }
        });
    }
}

function renderModelSelector() {
    const modelMenu = document.getElementById('model-menu');
    const modelDisplay = document.getElementById('current-model-display');
    const modelVersion = document.getElementById('current-model-version');

    // Update display
    modelDisplay.textContent = 'ChatGPT';
    if (selectedModel === 'gpt-4o-mini') {
        modelVersion.textContent = '4o-mini';
    } else if (selectedModel === 'gpt-4o') {
        modelVersion.textContent = '4o';
    } else if (selectedModel === 'gpt-4.1') {
        modelVersion.textContent = '4.1';
    } else if (selectedModel === 'gpt-3.5-turbo') {
        modelVersion.textContent = '3.5';
    } else {
        modelVersion.textContent = selectedModel;
    }

    // Render model options
    fetchModels().then(models => {
        modelMenu.innerHTML = models.map(model => {
            const displayName = model.replace('gpt-', 'GPT-').replace('local-llm', 'Local LLM');
            return `<div class="model-option" data-model="${model}">${displayName}</div>`;
        }).join('');

        // Attach click handlers to model options
        document.querySelectorAll('.model-option').forEach(option => {
            option.addEventListener('click', async (e) => {
                e.stopPropagation();
                selectedModel = option.dataset.model;
                renderModelSelector();
                closeAllDropdowns();

                // Sync selected model to current conversation
                await syncModelToCurrentConversation();
            });
        });
    });
}

function initModelSelector() {
    // Toggle model selector dropdown (attach once during initialization)
    const triggerBtn = document.getElementById('model-trigger-btn');
    const container = document.getElementById('model-selector-container');

    triggerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const wasOpen = container.classList.contains('open');
        closeAllDropdowns();
        if (!wasOpen) {
            container.classList.add('open');
        }
    });
}

// ============================================================
// Model Sync Helper
// ============================================================
async function syncModelToCurrentConversation() {
    // If there's a current conversation, update its model
    if (currentConversationId) {
        const convo = conversations.find(c => c.id === currentConversationId);
        if (convo && convo.model !== selectedModel) {
            // Update via API (without updating last_modified)
            await fetch(`${API_BASE}/api/conversations/${currentConversationId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: selectedModel })
            });

            // Update local state
            convo.model = selectedModel;
        }
    }
}

// ============================================================
// Event Handlers
// ============================================================
async function handleNewChat() {
    const newConvo = await createConversation();
    currentConversationId = newConvo.id;
    await fetchConversations();
    // Clear nav item highlighting (chat items are handled in renderConversationsList)
    setActiveNavItem(null);
    renderConversationsList();
    renderWelcomeScreen();
}

async function selectConversation(id) {
    currentConversationId = id;

    // Load full conversation if messages not loaded
    let convo = conversations.find(c => c.id === id);
    if (!convo || !convo.messages || convo.messages.length === 0) {
        convo = await fetchConversation(id);
        // Update in local array
        const index = conversations.findIndex(c => c.id === id);
        if (index !== -1) {
            conversations[index] = convo;
        }
    }

    // Update selected model to match conversation's model
    if (convo.model && convo.model !== selectedModel) {
        selectedModel = convo.model;
        renderModelSelector();
    }

    // Clear nav item highlighting (chat items are handled in renderConversationsList)
    setActiveNavItem(null);

    if (convo.messages.length === 0) {
        renderWelcomeScreen();
    } else {
        renderConversation(convo);
    }

    // Re-render sidebar to update active chat highlighting
    renderConversationsList();
}

async function handleMenuAction(e) {
    e.stopPropagation();
    const action = e.currentTarget.dataset.action;
    const id = e.currentTarget.dataset.id;

    closeAllDropdowns();

    if (action === 'rename') {
        startInlineRename(id);
    } else if (action === 'delete') {
        // Delete immediately without confirmation
        await deleteConversation(id);

        if (currentConversationId === id) {
            // If deleted current chat, create new one
            await handleNewChat();
        } else {
            // Just refresh the list
            await fetchConversations();
            renderConversationsList();
        }
    }
}

function startInlineRename(id) {
    const convo = conversations.find(c => c.id === id);
    if (!convo) return;

    // Find the chat item and title element
    const chatItems = document.querySelectorAll('.chat-item');
    let targetChatItem = null;
    chatItems.forEach(item => {
        const titleSpan = item.querySelector('.chat-title');
        if (titleSpan && titleSpan.dataset.id === id) {
            targetChatItem = item;
        }
    });

    if (!targetChatItem) return;

    const titleSpan = targetChatItem.querySelector('.chat-title');
    const currentTitle = convo.title;

    // Create input element
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentTitle;
    input.className = 'chat-title-input';
    input.style.cssText = `
        flex: 1;
        background: white;
        border: 1px solid #d1d5db;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 0.95rem;
        font-family: inherit;
        color: var(--text-primary);
        outline: none;
        margin-right: 8px;
    `;

    // Replace title span with input
    titleSpan.replaceWith(input);
    input.focus();
    input.select();

    // Handle save on Enter
    const saveRename = async () => {
        const newTitle = input.value.trim();
        if (newTitle && newTitle !== currentTitle) {
            await renameConversation(id, newTitle);
            await fetchConversations();
        }
        renderConversationsList();
    };

    // Handle cancel on Escape or blur
    const cancelRename = () => {
        renderConversationsList();
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            saveRename();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelRename();
        }
    });

    input.addEventListener('blur', saveRename);

    // Prevent clicks from propagating
    input.addEventListener('click', (e) => {
        e.stopPropagation();
    });
}

async function handleSendMessage() {
    const input = document.getElementById('message-input');
    const message = input.value.trim();

    if (!message) return;

    // Create new chat if needed
    if (!currentConversationId) {
        const newConvo = await createConversation();
        currentConversationId = newConvo.id;
    }

    input.value = '';
    input.disabled = true;

    try {
        // Send message
        await sendMessage(currentConversationId, message);

        // Refresh conversations list (chat moved to top)
        await fetchConversations();
        renderConversationsList();

        // Reload current conversation
        const convo = await fetchConversation(currentConversationId);
        renderConversation(convo);
    } catch (error) {
        console.error('Error sending message:', error);
        alert('Failed to send message. Please try again.');
    } finally {
        input.disabled = false;
    }
}

function attachInputHandlers() {
    const input = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');

    if (sendBtn) {
        sendBtn.addEventListener('click', handleSendMessage);
    }

    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
            }
        });
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================
// Initialization
// ============================================================
async function init() {
    // Load user info
    userInfo = await fetchUser();
    renderUserInfo();

    // Initialize model selector (attach event listener once)
    initModelSelector();

    // Render model selector display
    renderModelSelector();

    // Load conversations
    await fetchConversations();
    renderConversationsList();

    // Select first conversation or show welcome
    if (conversations.length > 0 && conversations[0].messages && conversations[0].messages.length > 0) {
        selectConversation(conversations[0].id);
    } else {
        // Show welcome screen without setting currentConversationId
        // This ensures a new conversation is created when user sends first message
        renderWelcomeScreen();
    }

    // Attach new chat button handler
    document.getElementById('new-chat-btn').addEventListener('click', handleNewChat);

    // Placeholder handlers for future features
    document.getElementById('search-chats-btn').addEventListener('click', () => {
        alert('Search chats feature coming soon!');
    });

    document.getElementById('video-recording-btn').addEventListener('click', async () => {
        const videos = await fetchVideos();
        renderVideoGallery(videos);
    });
}

// Start app
init();
