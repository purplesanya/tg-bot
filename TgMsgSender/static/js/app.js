// Telegram Scheduler - Main JavaScript

// --- Globals ---
let selectedFiles = [];
let editFilesUnified = [];
let pollingInterval = null;
let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
let selectedChatIds = [];
let editSelectedChatIds = [];
let allChats = [];
let showingArchived = false;
let currentUser = {};
let isLoggingOut = false; // Flag to prevent multiple logout triggers

// --- Utility Functions ---
const showAlert = (msg, type = 'info') => {
    const alertBox = document.getElementById('alertBox');
    if (alertBox) {
        alertBox.innerHTML = `<div class="alert alert-${type}"><i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>${msg}</div>`;
        setTimeout(() => { if (alertBox) alertBox.innerHTML = ''; }, 5000);
    }
};

// In app.js

const fetchApi = async (endpoint, options = {}) => {
    try {
        const r = await fetch(endpoint, options);

        if (r.status === 401) {
            // If we get a 401, the session is dead. Don't try to manage UI state.
            // Just reload the page immediately. The server will now serve the login page
            // because the session is invalid.
            if (!isLoggingOut) { // Use the flag to prevent reload loops
                isLoggingOut = true;
                // Use replace() so the user can't use the back button to get to a broken state.
                window.location.replace('/');
            }
            // Throw an error to stop the execution of the current code block.
            throw new Error('Session expired');
        }

        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'API error');
        return d;
    } catch (e) {
        // We only want to show alerts for errors that are NOT session related,
        // because the page reload is the feedback for a session error.
        if (e.message !== 'Session expired' && !isLoggingOut) {
            showAlert(e.message, 'error');
        }
        throw e; // Propagate the error so calling functions know something went wrong.
    }
};

const formatTimeAgo = (isoString) => {
    if (!isoString) return 'Never';
    const date = new Date(isoString);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
};

const formatNextRun = (isoString) => {
    if (!isoString) return 'Not scheduled';
    const date = new Date(isoString);
    const now = new Date();
    const diff = Math.floor((date - now) / 1000);
    if (diff < -86400) return `Overdue by ${Math.floor(-diff / 86400)}d`;
    if (diff < -3600) return `Overdue by ${Math.floor(-diff / 3600)}h`;
    if (diff < 0) return 'Overdue';
    if (diff < 60) return 'Very soon';
    if (diff < 3600) return `in ${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `in ${Math.floor(diff / 3600)}h`;
    return `in ${Math.floor(diff / 86400)}d`;
};

const formatLocaleDateTime = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
};

const switchTab = (tab) => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(tab + 'Tab').classList.add('active');
    if (tab === 'tasks') { showingArchived = false; loadTasks(true); }
    if (tab === 'dashboard') loadStats(true);
};

// --- Auth Functions ---
const toggleLoginForm = (showFull) => {
    if (showFull) {
        simplifiedLoginSection.classList.add('hidden');
        fullLoginSection.classList.remove('hidden');
    } else {
        simplifiedLoginSection.classList.remove('hidden');
        fullLoginSection.classList.add('hidden');
    }
    alertBox.innerHTML = '';
};

const startAuth = async () => {
    let payload;
    if (simplifiedLoginSection.classList.contains('hidden')) { // Full form is visible
        payload = {
            phone: phoneInputFull.value,
            api_id: apiIdInput.value,
            api_hash: apiHashInput.value
        };
    } else { // Simplified form is visible
        payload = { phone: phoneInputSimple.value };
    }
    try {
        await fetchApi('/api/auth/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        showAlert('Code sent to Telegram!', 'success');
        simplifiedLoginSection.classList.add('hidden');
        fullLoginSection.classList.add('hidden');
        codeSection.classList.remove('hidden');
    } catch (e) { /* Handled */ }
};

const verifyCode = async () => {
    try {
        const d = await fetchApi('/api/auth/verify_code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: codeInput.value }) });
        if (d.needs_2fa) {
            showAlert('2FA required', 'info');
            document.getElementById('2faSection').classList.remove('hidden');
            codeSection.classList.add('hidden');
        } else if (d.success) {
            showAlert('Login successful!', 'success');
            setTimeout(() => showApp(d.user), 500);
        }
    } catch (e) { console.error('Verify error:', e); }
};

const verify2FA = async () => {
    try {
        const d = await fetchApi('/api/auth/verify_2fa', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: passwordInput.value }) });
        if (d.success) {
            showAlert('Login successful!', 'success');
            setTimeout(() => showApp(d.user), 500);
        }
    } catch (e) { console.error('2FA error:', e); }
};

const logout = async () => {
    if (confirm('Are you sure you want to logout? This will require you to re-authenticate with Telegram on your next login.')) {
        if (pollingInterval) clearInterval(pollingInterval);
        await fetchApi('/api/logout', { method: 'POST' });
        localStorage.removeItem('prefersSimplifiedLogin');
        localStorage.removeItem('savedPhoneNumber');
        window.location.reload();
    }
};

// --- App Functions ---
const showApp = (user) => {
    if (isLoggingOut) return; // Prevent showing the app if a logout is in progress
    currentUser = user;
    userName.textContent = user.first_name + (user.username ? ` (@${user.username})` : '');
    userAvatar.innerHTML = user.photo ? `<img src="data:image/jpeg;base64,${user.photo}" alt="Profile">` : user.first_name[0].toUpperCase();
    document.getElementById('userTimezone').textContent = userTimezone;
    authSection.classList.add('hidden');
    appSection.classList.remove('hidden');
    loadInitialData();
    pollingInterval = setInterval(() => {
        if (isLoggingOut) {
            clearInterval(pollingInterval);
            return;
        }
        if (document.getElementById('tasksTab').classList.contains('active')) loadTasks(false);
        if (document.getElementById('dashboardTab').classList.contains('active')) loadStats(false);
        // Heartbeat check. Add a catch to prevent Uncaught Promise Rejection errors.
        // The actual 401 handling is inside fetchApi itself.
        fetchApi('/api/auth/status').catch(() => {
            // This catch block is primarily to prevent console noise.
            // fetchApi handles the UI changes and reload for 401s.
        });
    }, 15000);
};

const loadInitialData = () => {
    loadChats();
    loadTasks(true);
    loadStats(true);
    loadNotificationSettings();
    loadSimplifiedLoginSetting();
};

const loadChats = async (selectIds = []) => {
    try {
        const d = await fetchApi('/api/chats');
        allChats = d.chats;
        renderChatSelector(chatSelector, selectedChatIds, false);
    } catch (e) {}
};

const renderChatSelector = (container, selected, isEdit) => {
    container.innerHTML = allChats.map(c => `<div class="chat-item ${selected.includes(c.id) ? 'selected' : ''}" onclick="toggleChat(${c.id}, ${isEdit})"><div class="chat-checkbox"><i class="fas fa-check"></i></div><div class="chat-info"><div class="chat-name">${c.name}</div><div class="chat-type">${c.type}</div></div></div>`).join('');
};

const toggleChat = (chatId, isEdit) => {
    const list = isEdit ? editSelectedChatIds : selectedChatIds;
    const container = isEdit ? editChatSelector : chatSelector;
    const idx = list.indexOf(chatId);
    if (idx > -1) list.splice(idx, 1);
    else list.push(chatId);
    renderChatSelector(container, list, isEdit);
};

const refreshChats = async () => {
    showAlert('Refreshing chats...', 'info');
    try {
        await fetchApi('/api/chats/refresh', { method: 'POST' });
        await loadChats();
        showAlert('Chats refreshed!', 'success');
    } catch (e) {}
};

const toggleArchivedView = () => {
    showingArchived = !showingArchived;
    loadTasks(true);
};

const loadTasks = async (showLoader = false) => {
    if (showLoader) tasksList.innerHTML = '<div class="loader"></div>';
    const endpoint = showingArchived ? '/api/tasks/archived' : '/api/tasks';
    try {
        const d = await fetchApi(`${endpoint}?timezone=${encodeURIComponent(userTimezone)}`);
        const toggleBtn = document.getElementById('toggleArchivedBtn');
        if (toggleBtn) {
            toggleBtn.innerHTML = showingArchived ? '<i class="fas fa-list"></i> Show Active Tasks' : '<i class="fas fa-archive"></i> Show Archived';
        }
        if (!d.tasks || d.tasks.length === 0) {
            const emptyMsg = showingArchived ? '<h3>No archived tasks</h3><p>Archived tasks will appear here</p>' : '<h3>No tasks yet</h3><p>Create your first repeating task to get started</p>';
            tasksList.innerHTML = `<div class="empty-state"><i class="fas fa-inbox"></i>${emptyMsg}</div>`;
            return;
        }
        tasksList.innerHTML = d.tasks.map(t => {
            let actions = '';
            if (showingArchived) {
                actions = `<button class="btn btn-success btn-sm" onclick="unarchiveTask('${t.id}')"><i class="fas fa-undo"></i> Unarchive</button><button class="btn btn-danger btn-sm" onclick="deleteTask('${t.id}')"><i class="fas fa-trash"></i> Delete</button>`;
            } else {
                actions = `<button class="btn btn-secondary btn-sm" onclick="openEditModal('${t.id}')"><i class="fas fa-edit"></i> Edit</button>`;
                if (t.status === 'active') actions += `<button class="btn btn-secondary btn-sm" onclick="pauseTask('${t.id}')"><i class="fas fa-pause"></i> Pause</button>`;
                if (t.status === 'paused') actions += `<button class="btn btn-success btn-sm" onclick="resumeTask('${t.id}')"><i class="fas fa-play"></i> Resume</button>`;
                actions += `<button class="btn btn-warning btn-sm" onclick="archiveTask('${t.id}')"><i class="fas fa-archive"></i> Archive</button><button class="btn btn-danger btn-sm" onclick="deleteTask('${t.id}')"><i class="fas fa-trash"></i> Delete</button>`;
            }
            const lastRunText = t.last_run ? `Last: ${formatTimeAgo(t.last_run)} (${formatLocaleDateTime(t.last_run)})` : 'Not executed yet';
            const nextRunText = t.next_run && t.status === 'active' ? ` | Next: ${formatNextRun(t.next_run)} (${formatLocaleDateTime(t.next_run)})` : '';
            return `<div class="task-card"><div class="task-header"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">${t.name ? `<div class="task-name-badge">${t.name}</div>` : ''}<span class="task-status status-${t.status}">${t.status}</span></div><div class="task-actions">${actions}</div></div><div class="task-body"><div class="task-message">${t.message.substring(0, 120)}${t.message.length > 120 ? '...' : ''}</div><div class="task-meta"><div class="task-meta-item"><i class="far fa-clock"></i><span>Every ${t.interval_value} ${t.interval_unit}</span></div><div class="task-meta-item"><i class="fas fa-users"></i><span>${t.chat_ids.length} chats</span></div>${t.files > 0 ? `<div class="task-meta-item"><i class="fas fa-paperclip"></i><span>${t.files} files</span></div>` : ''}<div class="task-meta-item"><i class="fas fa-repeat"></i><span>${t.execution_count}x executed</span></div><div class="task-meta-item"><i class="fas fa-history"></i><span>${lastRunText}${nextRunText}</span></div></div></div></div>`;
        }).join('');
    } catch (e) {
        // Error is handled by fetchApi
    }
};

const loadStats = async (showLoader = false) => {
    if (showLoader) statsGrid.innerHTML = '<div class="loader"></div>';
    try {
        const s = await fetchApi('/api/stats');
        statsGrid.innerHTML = `<div class="stat-card"><div class="stat-value">${s.total_tasks}</div><div class="stat-label">Total Tasks</div></div><div class="stat-card"><div class="stat-value">${s.active_tasks}</div><div class="stat-label">Active Tasks</div></div><div class="stat-card"><div class="stat-value">${s.archived_tasks}</div><div class="stat-label">Archived</div></div><div class="stat-card"><div class="stat-value">${s.total_executions}</div><div class="stat-label">Executions</div></div>`;
    } catch (e) {}
};

const loadNotificationSettings = async () => { try { const s = await fetchApi('/api/settings/notifications'); notificationsToggle.checked = s.enabled; } catch(e) {} };
const loadSimplifiedLoginSetting = async () => { try { const s = await fetchApi('/api/settings/simplified_login'); simplifiedLoginToggle.checked = s.enabled; } catch(e) {} };

const toggleNotifications = async () => {
    const enabled = notificationsToggle.checked;
    await fetchApi('/api/settings/notifications', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    showAlert(`Notifications ${enabled ? 'enabled' : 'disabled'}`, 'success');
};

const toggleSimplifiedLogin = async () => {
    const enabled = simplifiedLoginToggle.checked;
    await fetchApi('/api/settings/simplified_login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });

    if (enabled && currentUser.phone) {
        localStorage.setItem('prefersSimplifiedLogin', 'true');
        localStorage.setItem('savedPhoneNumber', currentUser.phone);
    } else {
        localStorage.removeItem('prefersSimplifiedLogin');
        localStorage.removeItem('savedPhoneNumber');
    }

    showAlert(`Simplified Login ${enabled ? 'enabled' : 'disabled'}`, 'success');
};

// --- Task Management ---
const submitForm = async () => {
    if (selectedChatIds.length === 0) return showAlert('Please select at least one chat', 'error');
    if (!messageInput.value.trim() && selectedFiles.length === 0) return showAlert('Please enter a message or add a file', 'error');
    if (!intervalValue.value || intervalValue.value < 1) return showAlert('Please enter a valid interval', 'error');
    const fd = new FormData();
    fd.append('chat_ids', selectedChatIds.join(','));
    fd.append('message', messageInput.value);
    fd.append('task_name', taskName.value);
    fd.append('interval_value', intervalValue.value);
    fd.append('interval_unit', intervalUnit.value);
    selectedFiles.forEach(f => fd.append('files', f));
    fd.append('final_order', JSON.stringify(selectedFiles.map(f => f.name)));
    try {
        await fetchApi('/api/schedule', { method: 'POST', body: fd });
        showAlert('Task scheduled successfully', 'success');
        resetForm();
        loadTasks(true);
        loadStats(true);
        switchTab('tasks');
    } catch (e) { /* Handled */ }
};

const resetForm = () => {
    messageInput.value = ''; taskName.value = ''; intervalValue.value = '';
    selectedChatIds = []; selectedFiles = [];
    renderChatSelector(chatSelector, [], false);
    displayFiles();
    intervalUnit.value = 'hours';
};

const openEditModal = async (id) => {
    const { task } = await fetchApi(`/api/tasks/${id}?timezone=${encodeURIComponent(userTimezone)}`);
    editTaskId.value = task.id;
    editTaskName.value = task.name || '';
    editMessageInput.value = task.message;
    editIntervalValue.value = task.interval_value;
    editIntervalUnit.value = task.interval_unit;
    editSelectedChatIds = [...task.chat_ids];
    renderChatSelector(editChatSelector, editSelectedChatIds, true);
    editFilesUnified = (task.file_urls || []).map(url => ({ type: 'existing', data: url }));
    displayEditFiles();
    editModal.classList.add('active');
};

const closeEditModal = () => {
    editModal.classList.remove('active');
    editFilesUnified = [];
};

const updateTask = async () => {
    const id = editTaskId.value;
    const fd = new FormData();
    fd.append('chat_ids', editSelectedChatIds.join(','));
    fd.append('message', editMessageInput.value);
    fd.append('task_name', editTaskName.value);
    fd.append('interval_value', editIntervalValue.value);
    fd.append('interval_unit', editIntervalUnit.value);
    fd.append('keep_existing', JSON.stringify(editFilesUnified.filter(i => i.type === 'existing').map(i => i.data)));
    editFilesUnified.filter(i => i.type === 'new').map(i => i.data).forEach(f => fd.append('files', f));
    fd.append('final_order', JSON.stringify(editFilesUnified.map(item => item.type === 'existing' ? item.data : item.data.name)));
    await fetchApi(`/api/tasks/${id}/update`, { method: 'POST', body: fd });
    showAlert('Task updated successfully', 'success');
    closeEditModal();
    loadTasks(true);
    loadStats(true);
};

const deleteTask = async (id) => { if (confirm('Are you sure you want to delete this task?')) { await fetchApi(`/api/tasks/${id}`, { method: 'DELETE' }); showAlert('Task deleted successfully', 'success'); loadTasks(true); loadStats(true); } };
const pauseTask = async (id) => { await fetchApi(`/api/tasks/${id}/pause`, { method: 'POST' }); showAlert('Task paused', 'success'); loadTasks(true); };
const resumeTask = async (id) => { await fetchApi(`/api/tasks/${id}/resume`, { method: 'POST' }); showAlert('Task resumed', 'success'); loadTasks(true); };
const archiveTask = async (id) => { if (confirm('Archive this task? It will be stopped and hidden from the task list.')) { await fetchApi(`/api/tasks/${id}/archive`, { method: 'POST' }); showAlert('Task archived', 'success'); loadTasks(true); loadStats(true); } };
const unarchiveTask = async (id) => { if (confirm('Unarchive and reactivate this task?')) { await fetchApi(`/api/tasks/${id}/unarchive`, { method: 'POST' }); showAlert('Task unarchived', 'success'); loadTasks(true); loadStats(true); } };

// --- File Handling ---
fileInput.addEventListener('change', e => { const newFiles = Array.from(e.target.files); if (selectedFiles.length + newFiles.length > 10) { showAlert(`Maximum 10 files allowed.`, 'error'); return; } selectedFiles.push(...newFiles.slice(0, 10 - selectedFiles.length)); displayFiles(); e.target.value = ''; });
editFileInput.addEventListener('change', e => { const newFiles = Array.from(e.target.files); if (editFilesUnified.length + newFiles.length > 10) { showAlert(`Maximum 10 files allowed.`, 'error'); return; } editFilesUnified.push(...newFiles.map(file => ({ type: 'new', data: file }))); displayEditFiles(); e.target.value = ''; });
const displayFiles = () => { imagePreviewGrid.innerHTML = selectedFiles.map((f, i) => { const url = URL.createObjectURL(f); return `<div class="image-preview-item" draggable="true" data-index="${i}">${f.type.startsWith('video/') ? `<video src="${url}" muted loop playsinline></video>` : `<img src="${url}" alt="Preview">`}<div class="image-preview-overlay"><div class="image-preview-number">${i + 1}</div><button class="btn-remove-image" onclick="removeFile(${i})"><i class="fas fa-times"></i></button></div></div>`; }).join(''); };
const displayEditFiles = () => { editImagePreviewGrid.innerHTML = editFilesUnified.map((item, i) => { const url = item.type === 'existing' ? item.data : URL.createObjectURL(item.data); const isVideo = (item.type === 'existing' && url.toLowerCase().match(/\.(mp4|mov|avi|webm)$/)) || (item.type === 'new' && item.data.type.startsWith('video/')); return `<div class="image-preview-item" draggable="true" data-index="${i}">${isVideo ? `<video src="${url}" muted loop playsinline></video>` : `<img src="${url}" alt="Preview">`}<div class="image-preview-overlay"><div class="image-preview-number">${i + 1}</div><button class="btn-remove-image" onclick="removeFileFromEdit(${i})"><i class="fas fa-times"></i></button></div></div>`; }).join(''); };
const removeFile = (i) => { selectedFiles.splice(i, 1); displayFiles(); };
const removeFileFromEdit = (i) => { editFilesUnified.splice(i, 1); displayEditFiles(); };
const createDragAndDropController = (grid, getFileList, redrawFunction) => {
    let draggedIndex = null;
    grid.addEventListener('dragstart', e => { const target = e.target.closest('.image-preview-item'); if (!target) return; draggedIndex = parseInt(target.dataset.index); setTimeout(() => target.classList.add('dragging'), 0); });
    grid.addEventListener('dragover', e => { e.preventDefault(); });
    grid.addEventListener('drop', e => { e.preventDefault(); const target = e.target.closest('.image-preview-item'); if (!target || draggedIndex === null) return; const dropIndex = parseInt(target.dataset.index); if (draggedIndex === dropIndex) return; const fileList = getFileList(); const [moved] = fileList.splice(draggedIndex, 1); fileList.splice(dropIndex, 0, moved); redrawFunction(); });
    grid.addEventListener('dragend', () => { const draggingElem = grid.querySelector('.dragging'); if (draggingElem) draggingElem.classList.remove('dragging'); });
};

// --- Initialization ---
window.addEventListener('DOMContentLoaded', async () => {
    if (localStorage.getItem('prefersSimplifiedLogin') === 'true') {
        const savedPhone = localStorage.getItem('savedPhoneNumber');
        if (savedPhone) {
            phoneInputSimple.value = savedPhone;
        }
        toggleLoginForm(false);
    } else {
        toggleLoginForm(true);
    }

    try {
        const d = await fetchApi('/api/user/info');
        if (d.logged_in) {
            showApp(d.user);
        }
    } catch (e) {
        // Not logged in, login form is already visible
    }

    createDragAndDropController(imagePreviewGrid, () => selectedFiles, displayFiles);
    createDragAndDropController(editImagePreviewGrid, () => editFilesUnified, displayEditFiles);
});

editModal.addEventListener('click', (e) => { if (e.target === editModal) closeEditModal(); });

const elements = [
    'phoneInputSimple', 'phoneInputFull', 'apiIdInput', 'apiHashInput', 'codeInput', 'passwordInput',
    'simplifiedLoginSection', 'fullLoginSection', 'codeSection', 'authSection', 'appSection',
    'userName', 'userAvatar', 'statsGrid', 'notificationsToggle', 'simplifiedLoginToggle',
    'chatSelector', 'editChatSelector', 'messageInput', 'intervalValue', 'intervalUnit',
    'fileInput', 'imagePreviewGrid', 'tasksList', 'alertBox', 'editModal', 'editTaskId',
    'editMessageInput', 'editIntervalValue', 'editIntervalUnit', 'editFileInput',
    'editImagePreviewGrid', 'taskName', 'editTaskName'
];
elements.forEach(id => {
    if (document.getElementById(id)) {
        window[id] = document.getElementById(id);
    }
});