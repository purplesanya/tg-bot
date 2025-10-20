// --- Globals ---
let currentLang = 'en';
let selectedFiles = [];
let editFilesUnified = [];
let pollingInterval = null;
let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
let selectedChatIds = [];
let editSelectedChatIds = [];
let allChats = [];
let showingArchived = false;
let currentUser = {};
let isLoggingOut = false;

// --- Account Management ---
const accountManager = {
    getAccounts: () => {
        try {
            const data = JSON.parse(localStorage.getItem('userAccounts'));
            return data && Array.isArray(data.accounts) ? data : { activeAccountId: null, accounts: [] };
        } catch (e) {
            return { activeAccountId: null, accounts: [] };
        }
    },
    saveAccounts: (data) => {
        localStorage.setItem('userAccounts', JSON.stringify(data));
    },
    addOrUpdateAccount: (user) => {
        const data = accountManager.getAccounts();
        const existingIndex = data.accounts.findIndex(a => a.id === user.id);
        if (existingIndex > -1) {
            data.accounts[existingIndex] = user;
        } else {
            data.accounts.push(user);
        }
        data.activeAccountId = user.id;
        accountManager.saveAccounts(data);
    },
    removeAccount: (telegramId) => {
        const data = accountManager.getAccounts();
        data.accounts = data.accounts.filter(a => a.id !== telegramId);
        if (data.activeAccountId === telegramId) {
            data.activeAccountId = data.accounts.length > 0 ? data.accounts[0].id : null;
        }
        accountManager.saveAccounts(data);
        return data;
    }
};

// --- Internationalization (i18n) ---
const getText = (key) => {
    return translations[currentLang]?.[key] || translations['en']?.[key] || key;
};

const setLanguage = (lang) => {
    if (!translations[lang]) return;
    currentLang = lang;
    localStorage.setItem('preferredLanguage', lang);

    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = getText(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        el.placeholder = getText(key);
    });

    document.getElementById('lang-en').classList.toggle('active', lang === 'en');
    document.getElementById('lang-ru').classList.toggle('active', lang === 'ru');

    const activeTab = document.querySelector('.tab-content.active');
    if (activeTab && window.appSection && !window.appSection.classList.contains('hidden')) {
        switch(activeTab.id) {
            case 'tasksTab': if (window.tasksList) loadTasks(true); break;
            case 'dashboardTab': if(window.statsGrid) loadStats(true); break;
            case 'adminTab': if (window.adminStatsGrid) loadAdminData(true); break;
        }
    }
};


// --- Utility Functions ---
const showAlert = (msg, type = 'info') => {
    const alertBox = document.getElementById('alertBox');
    if (alertBox) {
        alertBox.innerHTML = `<div class="alert alert-${type}"><i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>${msg}</div>`;
        setTimeout(() => { if (alertBox) alertBox.innerHTML = ''; }, 5000);
    }
};

const fetchApi = async (endpoint, options = {}) => {
    try {
        const r = await fetch(endpoint, options);
        if (r.status === 401) {
            if (!isLoggingOut) {
                isLoggingOut = true;
                const { activeAccountId } = accountManager.getAccounts();
                const remaining = accountManager.removeAccount(activeAccountId);
                if (remaining.activeAccountId) {
                    window.location.reload();
                } else {
                    window.location.replace('/');
                }
            }
            throw new Error('Session expired');
        }
        const d = await r.json();
        if (!r.ok) {
            const error = new Error(d.error || 'API error');
            error.data = d; // Attach full JSON response
            throw error;
        }
        return d;
    } catch (e) {
        if (e.message !== 'Session expired' && !isLoggingOut) {
            showAlert(e.message, 'error');
        }
        throw e;
    }
};

const formatTimeAgo = (isoString) => {
    if (!isoString) return getText('not_executed_yet');
    const date = new Date(isoString);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);

    if (currentLang === 'ru') {
        if (diff < 60) return "Только что";
        if (diff < 3600) return `${Math.floor(diff / 60)} м. назад`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} ч. назад`;
        return `${Math.floor(diff / 86400)} д. назад`;
    } else {
        if (diff < 60) return "Just now";
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    }
};

const formatNextRun = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diff = Math.floor((date - now) / 1000);
    const langPrefix = getText('in_time');

    if (diff < 0) {
        if (diff < -86400) return `${getText('overdue_by')} ${Math.floor(-diff / 86400)}d`;
        if (diff < -3600) return `${getText('overdue_by')} ${Math.floor(-diff / 3600)}h`;
        return getText('overdue');
    }
    if (diff < 60) return getText('very_soon');
    if (diff < 3600) return `${langPrefix} ${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${langPrefix} ${Math.floor(diff / 3600)}h`;
    return `${langPrefix} ${Math.floor(diff / 86400)}d`;
};

const formatLocaleDateTime = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleString(currentLang, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: false });
};

const switchTab = (tab) => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector(`.nav-tab[onclick="switchTab('${tab}')"]`).classList.add('active');
    document.getElementById(tab + 'Tab').classList.add('active');

    if (tab === 'tasks') { showingArchived = false; loadTasks(true); }
    if (tab === 'dashboard') loadStats(true);
    if (tab === 'admin') loadAdminData(true);
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
    if (simplifiedLoginSection.classList.contains('hidden')) {
        payload = { phone: phoneInputFull.value, api_id: apiIdInput.value, api_hash: apiHashInput.value };
    } else {
        payload = { phone: phoneInputSimple.value };
    }
    try {
        await fetchApi('/api/auth/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        showAlert(getText('code_sent'), 'success');
        simplifiedLoginSection.classList.add('hidden');
        fullLoginSection.classList.add('hidden');
        codeSection.classList.remove('hidden');
    } catch (e) {
        if (e.data && e.data.action === 'require_full_login') {
            toggleLoginForm(true);
            localStorage.removeItem('prefersSimplifiedLogin');
            localStorage.removeItem('savedPhoneNumber');
        }
    }
};

const verifyCode = async () => {
    try {
        const d = await fetchApi('/api/auth/verify_code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: codeInput.value }) });
        if (d.needs_2fa) {
            showAlert(getText('login_2fa'), 'info');
            document.getElementById('2faSection').classList.remove('hidden');
            codeSection.classList.add('hidden');
        } else if (d.success) {
            showAlert(getText('login_success'), 'success');
            accountManager.addOrUpdateAccount(d.user);
            setTimeout(() => window.location.reload(), 500);
        }
    } catch (e) { console.error('Verify error:', e); }
};

const verify2FA = async () => {
    try {
        const d = await fetchApi('/api/auth/verify_2fa', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: passwordInput.value }) });
        if (d.success) {
            showAlert(getText('login_success'), 'success');
            accountManager.addOrUpdateAccount(d.user);
            setTimeout(() => window.location.reload(), 500);
        }
    } catch (e) { console.error('2FA error:', e); }
};

const switchAccount = async (telegramId) => {
    const data = accountManager.getAccounts();
    if (data.activeAccountId === telegramId) return;
    data.activeAccountId = telegramId;
    accountManager.saveAccounts(data);
    try {
        await fetchApi('/api/auth/switch_account', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ telegram_id: telegramId })
        });
        window.location.reload();
    } catch(e) {
        showAlert(getText('session_expired_relogin'), 'error');
        const remaining = accountManager.removeAccount(telegramId);
        setTimeout(() => {
            if (remaining.activeAccountId) {
                window.location.reload();
            } else {
                window.location.replace('/');
            }
        }, 2000);
    }
};

const logout = async () => {
    if (confirm(getText('logout_confirm'))) {
        if (pollingInterval) clearInterval(pollingInterval);
        isLoggingOut = true;
        const { activeAccountId } = accountManager.getAccounts();

        await fetchApi('/api/logout', { method: 'POST' });

        const remainingData = accountManager.removeAccount(activeAccountId);

        if (remainingData.activeAccountId) {
            await switchAccount(remainingData.activeAccountId);
        } else {
            window.location.replace('/');
        }
    }
};

// --- App Functions ---
const showApp = (user) => {
    if (isLoggingOut) return;
    currentUser = user;
    userName.textContent = user.first_name + (user.username ? ` (@${user.username})` : '');
    userAvatar.innerHTML = user.photo ? `<img src="data:image/jpeg;base64,${user.photo}" alt="Profile">` : user.first_name[0].toUpperCase();
    document.getElementById('userTimezone').textContent = userTimezone;
    authSection.classList.add('hidden');
    appSection.classList.remove('hidden');

    if(user.is_admin) {
        document.getElementById('adminNavTab').classList.remove('hidden');
    }

    populateAccountDropdown();

    const userBadgeClickable = document.getElementById('userBadgeClickable');
    const dropdown = document.getElementById('accountDropdown');
    userBadgeClickable.addEventListener('click', (e) => {
        if (!e.target.closest('.lang-switcher')) {
            dropdown.classList.toggle('active');
            userBadgeClickable.classList.toggle('active');
        }
    });

    document.addEventListener('click', (event) => {
        if (!userBadgeClickable.contains(event.target)) {
            dropdown.classList.remove('active');
            userBadgeClickable.classList.remove('active');
        }
    });

    loadInitialData();
    pollingInterval = setInterval(() => {
        if (isLoggingOut) {
            clearInterval(pollingInterval);
            return;
        }
        if (document.getElementById('tasksTab').classList.contains('active')) loadTasks(false);
        if (document.getElementById('dashboardTab').classList.contains('active')) loadStats(false);
        if (document.getElementById('adminTab').classList.contains('active')) loadAdminData(false);
        fetchApi('/api/auth/status').catch(() => {});
    }, 15000);
};

const populateAccountDropdown = () => {
    const { activeAccountId, accounts } = accountManager.getAccounts();
    const dropdown = document.getElementById('accountDropdown');

    let accountsHtml = accounts.map(acc => `
        <div class="account-item ${acc.id === activeAccountId ? 'current' : ''}" onclick="switchAccount(${acc.id})">
            <div class="user-avatar">${acc.photo ? `<img src="data:image/jpeg;base64,${acc.photo}" alt="">` : acc.first_name[0].toUpperCase()}</div>
            <div class="account-item-info">
                <strong>${acc.first_name}</strong>
                <span>@${acc.username || acc.id}</span>
            </div>
            <div class="active-indicator"><i class="fas fa-check-circle"></i></div>
        </div>
    `).join('');

    dropdown.innerHTML = `
        ${accountsHtml}
        <div class="dropdown-divider"></div>
        <button class="dropdown-btn add-account" onclick="triggerAddAccount()"><i class="fas fa-plus-circle fa-fw"></i> <span data-i18n="add_account_btn">Add Account</span></button>
        <button class="dropdown-btn logout" onclick="logout()"><i class="fas fa-sign-out-alt fa-fw"></i> <span data-i18n="logout_btn">Logout</span></button>
    `;
    setLanguage(currentLang);
};

const triggerAddAccount = () => {
    appSection.classList.add('hidden');
    authSection.classList.remove('hidden');
    accountDropdown.classList.remove('active');
    userBadgeClickable.classList.remove('active');
    cancelAddAccountBtn.classList.remove('hidden');

    toggleLoginForm(true);
};

const cancelAddAccount = () => {
    authSection.classList.add('hidden');
    cancelAddAccountBtn.classList.add('hidden');
    appSection.classList.remove('hidden');

    // Clear any half-finished login forms
    codeInput.value = '';
    passwordInput.value = '';
    codeSection.classList.add('hidden');
    if (window.twoFaSection) {
        twoFaSection.classList.add('hidden');
    }
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
    showAlert(getText('chats_refreshing'), 'info');
    try {
        await fetchApi('/api/chats/refresh', { method: 'POST' });
        await loadChats();
        showAlert(getText('chats_refreshed'), 'success');
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
            const btnText = showingArchived ? getText('show_active_btn') : getText('show_archived_btn');
            toggleBtn.innerHTML = `<i class="fas ${showingArchived ? 'fa-list' : 'fa-archive'}"></i> <span>${btnText}</span>`;
        }
        if (!d.tasks || d.tasks.length === 0) {
            const emptyMsg = showingArchived
            ? `<h3>${getText('no_archived_tasks_header')}</h3><p>${getText('no_archived_tasks_desc')}</p>`
            : `<h3>${getText('no_tasks_header')}</h3><p>${getText('no_tasks_desc')}</p>`;
            tasksList.innerHTML = `<div class="empty-state"><i class="fas fa-inbox"></i>${emptyMsg}</div>`;
            return;
        }
        tasksList.innerHTML = d.tasks.map(t => {
            let actions = '';
            if (showingArchived) {
                actions = `<button class="btn btn-success btn-sm" onclick="unarchiveTask('${t.id}')"><i class="fas fa-undo"></i> ${getText('unarchive_btn')}</button><button class="btn btn-danger btn-sm" onclick="deleteTask('${t.id}')"><i class="fas fa-trash"></i> ${getText('delete_btn')}</button>`;
            } else {
                actions = `<button class="btn btn-secondary btn-sm" onclick="openEditModal('${t.id}')"><i class="fas fa-edit"></i> ${getText('edit_btn')}</button>`;
                if (t.status === 'active') actions += `<button class="btn btn-secondary btn-sm" onclick="pauseTask('${t.id}')"><i class="fas fa-pause"></i> ${getText('pause_btn')}</button>`;
                if (t.status === 'paused') actions += `<button class="btn btn-success btn-sm" onclick="resumeTask('${t.id}')"><i class="fas fa-play"></i> ${getText('resume_btn')}</button>`;
                actions += `<button class="btn btn-warning btn-sm" onclick="archiveTask('${t.id}')"><i class="fas fa-archive"></i> ${getText('archive_btn')}</button><button class="btn btn-danger btn-sm" onclick="deleteTask('${t.id}')"><i class="fas fa-trash"></i> ${getText('delete_btn')}</button>`;
            }
            const lastRunText = t.last_run ? `${getText('last_run')} ${formatTimeAgo(t.last_run)}` : getText('not_executed_yet');
            const nextRunText = t.next_run && t.status === 'active' ? ` | ${getText('next_run')} ${formatNextRun(t.next_run)}` : '';
            const intervalUnitText = getText(t.interval_unit) || t.interval_unit;
            return `<div class="task-card"><div class="task-header"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">${t.name ? `<div class="task-name-badge">${t.name}</div>` : ''}<span class="task-status status-${t.status}">${t.status}</span></div><div class="task-actions">${actions}</div></div><div class="task-body"><div class="task-message">${t.message.substring(0, 120)}${t.message.length > 120 ? '...' : ''}</div><div class="task-meta"><div class="task-meta-item"><i class="far fa-clock"></i><span>${getText('every')} ${t.interval_value} ${intervalUnitText}</span></div><div class="task-meta-item"><i class="fas fa-users"></i><span>${t.chat_ids.length} ${getText('chats')}</span></div>${t.files > 0 ? `<div class="task-meta-item"><i class="fas fa-paperclip"></i><span>${t.files} ${getText('files')}</span></div>` : ''}<div class="task-meta-item"><i class="fas fa-repeat"></i><span>${t.execution_count}${getText('executed')}</span></div><div class="task-meta-item"><i class="fas fa-history"></i><span>${lastRunText}${nextRunText}</span></div></div></div></div>`;
        }).join('');
    } catch (e) {}
};

const loadStats = async (showLoader = false) => {
    if (showLoader) statsGrid.innerHTML = '<div class="loader"></div>';
    try {
        const s = await fetchApi('/api/stats');
        statsGrid.innerHTML = `<div class="stat-card"><div class="stat-value">${s.total_tasks}</div><div class="stat-label">${getText('total_tasks')}</div></div><div class="stat-card"><div class="stat-value">${s.active_tasks}</div><div class="stat-label">${getText('active_tasks')}</div></div><div class="stat-card"><div class="stat-value">${s.archived_tasks}</div><div class="stat-label">${getText('archived_tasks')}</div></div><div class="stat-card"><div class="stat-value">${s.total_executions}</div><div class="stat-label">${getText('total_executions')}</div></div>`;
    } catch (e) {}
};

const loadNotificationSettings = async () => { try { const s = await fetchApi('/api/settings/notifications'); notificationsToggle.checked = s.enabled; } catch(e) {} };
const loadSimplifiedLoginSetting = async () => { try { const s = await fetchApi('/api/settings/simplified_login'); simplifiedLoginToggle.checked = s.enabled; } catch(e) {} };

const toggleNotifications = async () => {
    const enabled = notificationsToggle.checked;
    await fetchApi('/api/settings/notifications', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    showAlert(getText(enabled ? 'notifications_enabled' : 'notifications_disabled'), 'success');
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
    showAlert(getText(enabled ? 'simplified_login_enabled' : 'simplified_login_disabled'), 'success');
};

const submitForm = async () => {
    if (selectedChatIds.length === 0) return showAlert(getText('select_chat_error'), 'error');
    if (!messageInput.value.trim() && selectedFiles.length === 0) return showAlert(getText('message_or_file_error'), 'error');
    if (!intervalValue.value || intervalValue.value < 1) return showAlert(getText('invalid_interval_error'), 'error');

    const sendImmediately = document.getElementById('sendImmediatelyCheckbox').checked;

    const fd = new FormData();
    fd.append('chat_ids', selectedChatIds.join(','));
    fd.append('message', messageInput.value);
    fd.append('task_name', taskName.value);
    fd.append('interval_value', intervalValue.value);
    fd.append('interval_unit', intervalUnit.value);
    selectedFiles.forEach(f => fd.append('files', f));
    fd.append('final_order', JSON.stringify(selectedFiles.map(f => f.name)));
    fd.append('send_immediately', sendImmediately);

    try {
        await fetchApi('/api/schedule', { method: 'POST', body: fd });
        showAlert(getText('task_scheduled'), 'success');
        resetForm();
        loadTasks(true);
        loadStats(true);
        switchTab('tasks');
    } catch (e) { /* Handled */ }
};

const resetForm = () => {
    messageInput.value = '';
    taskName.value = '';
    intervalValue.value = '';
    document.getElementById('sendImmediatelyCheckbox').checked = false;
    selectedChatIds = [];
    selectedFiles = [];
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
    showAlert(getText('task_updated'), 'success');
    closeEditModal();
    loadTasks(true);
    loadStats(true);
};

const deleteTask = async (id) => { if (confirm(getText('delete_task_confirm'))) { await fetchApi(`/api/tasks/${id}`, { method: 'DELETE' }); showAlert(getText('task_deleted'), 'success'); loadTasks(true); loadStats(true); } };
const pauseTask = async (id) => { await fetchApi(`/api/tasks/${id}/pause`, { method: 'POST' }); showAlert(getText('task_paused'), 'success'); loadTasks(true); };
const resumeTask = async (id) => { await fetchApi(`/api/tasks/${id}/resume`, { method: 'POST' }); showAlert(getText('task_resumed'), 'success'); loadTasks(true); };
const archiveTask = async (id) => { if (confirm(getText('archive_task_confirm'))) { await fetchApi(`/api/tasks/${id}/archive`, { method: 'POST' }); showAlert(getText('task_archived'), 'success'); loadTasks(true); loadStats(true); } };
const unarchiveTask = async (id) => { if (confirm(getText('unarchive_task_confirm'))) { await fetchApi(`/api/tasks/${id}/unarchive`, { method: 'POST' }); showAlert(getText('task_unarchived'), 'success'); loadTasks(true); loadStats(true); } };

// --- File Handling ---
fileInput.addEventListener('change', e => { const newFiles = Array.from(e.target.files); if (selectedFiles.length + newFiles.length > 10) { showAlert(getText('max_files_error'), 'error'); return; } selectedFiles.push(...newFiles.slice(0, 10 - selectedFiles.length)); displayFiles(); e.target.value = ''; });
editFileInput.addEventListener('change', e => { const newFiles = Array.from(e.target.files); if (editFilesUnified.length + newFiles.length > 10) { showAlert(getText('max_files_error'), 'error'); return; } editFilesUnified.push(...newFiles.map(file => ({ type: 'new', data: file }))); displayEditFiles(); e.target.value = ''; });
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

// --- Admin Panel Functions ---
const loadAdminData = async (showLoader = false) => {
    await loadAdminStats(showLoader);
    await loadAdminUsers(showLoader);
};

const loadAdminStats = async (showLoader = false) => {
    if(showLoader) adminStatsGrid.innerHTML = '<div class="loader"></div>';
    try {
        const s = await fetchApi('/api/admin/stats');
        adminStatsGrid.innerHTML = `<div class="stat-card"><div class="stat-value">${s.total_users}</div><div class="stat-label">${getText('total_users')}</div></div><div class="stat-card"><div class="stat-value">${s.total_tasks}</div><div class="stat-label">${getText('total_active_tasks')}</div></div><div class="stat-card"><div class="stat-value">${s.total_executions}</div><div class="stat-label">${getText('total_executions')}</div></div>`;
    } catch (e) {}
};

const loadAdminUsers = async (showLoader = false) => {
    if(showLoader) adminUserList.innerHTML = '<div class="loader"></div>';
    try {
        const d = await fetchApi('/api/admin/users');
        adminUserList.innerHTML = d.users.map(u => `
            <div class="user-list-item" onclick="loadAdminUserTasks(${u.id}, '${u.first_name}')">
                <div class="user-info">
                    <strong>${u.first_name}</strong> (@${u.username || 'N/A'})
                    ${u.is_admin ? `<span class="admin-badge">${getText('admin_badge')}</span>` : ''}
                </div>
                <div class="user-meta">
                    <span>${getText('tasks_tab')}: ${u.task_count}</span>
                    <span>${getText('last_login')}: ${formatTimeAgo(u.last_login)}</span>
                </div>
            </div>
        `).join('');
    } catch(e) {}
};

const loadAdminUserTasks = async (userId, userName) => {
    adminUserTasksCard.style.display = 'block';
    adminTasksForUser.textContent = userName;
    adminUserTasksList.innerHTML = '<div class="loader"></div>';
    try {
        const d = await fetchApi(`/api/admin/tasks/${userId}?timezone=${encodeURIComponent(userTimezone)}`);
        if (!d.tasks || d.tasks.length === 0) {
            adminUserTasksList.innerHTML = `<div class="empty-state"><p>${getText('no_user_tasks')}</p></div>`;
            return;
        }
        adminUserTasksList.innerHTML = d.tasks.map(t => {
            const lastRunText = t.last_run ? `${getText('last_run')} ${formatTimeAgo(t.last_run)}` : getText('not_executed_yet');
            const nextRunText = t.next_run && t.status === 'active' ? ` | ${getText('next_run')} ${formatNextRun(t.next_run)}` : '';
            const intervalUnitText = getText(t.interval_unit) || t.interval_unit;
            return `<div class="task-card"><div class="task-header"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">${t.name ? `<div class="task-name-badge">${t.name}</div>` : ''}<span class="task-status status-${t.status}">${t.status}</span></div></div><div class="task-body"><div class="task-message">${t.message.substring(0, 120)}${t.message.length > 120 ? '...' : ''}</div><div class="task-meta"><div class="task-meta-item"><i class="far fa-clock"></i><span>${getText('every')} ${t.interval_value} ${intervalUnitText}</span></div><div class="task-meta-item"><i class="fas fa-users"></i><span>${t.chat_ids.length} ${getText('chats')}</span></div>${t.files > 0 ? `<div class="task-meta-item"><i class="fas fa-paperclip"></i><span>${t.files} ${getText('files')}</span></div>` : ''}<div class="task-meta-item"><i class="fas fa-repeat"></i><span>${t.execution_count}${getText('executed')}</span></div><div class="task-meta-item"><i class="fas fa-history"></i><span>${lastRunText}${nextRunText}</span></div></div></div></div>`;
        }).join('');
    } catch(e) {}
};

// --- Initialization ---
window.addEventListener('DOMContentLoaded', async () => {
    const savedLang = localStorage.getItem('preferredLanguage');
    setLanguage(savedLang || 'en');

    const { activeAccountId, accounts } = accountManager.getAccounts();

    if (activeAccountId && accounts.length > 0) {
        try {
            await fetchApi('/api/auth/switch_account', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: activeAccountId })
            });

            const d = await fetchApi('/api/user/info');
            if (d.logged_in) {
                accountManager.addOrUpdateAccount(d.user);
                showApp(d.user);
            } else {
                const remaining = accountManager.removeAccount(activeAccountId);
                if(remaining.activeAccountId) {
                    window.location.reload();
                } else {
                    toggleLoginForm(true);
                }
            }
        } catch (e) {
            const remaining = accountManager.removeAccount(activeAccountId);
            if(remaining.activeAccountId) {
                window.location.reload();
            } else {
                toggleLoginForm(true);
            }
        }
    } else {
        if (localStorage.getItem('prefersSimplifiedLogin') === 'true') {
            const savedPhone = localStorage.getItem('savedPhoneNumber');
            if (savedPhone) phoneInputSimple.value = savedPhone;
            toggleLoginForm(false);
        } else {
            toggleLoginForm(true);
        }
    }

    createDragAndDropController(imagePreviewGrid, () => selectedFiles, displayFiles);
    createDragAndDropController(editImagePreviewGrid, () => editFilesUnified, displayEditFiles);
});

editModal.addEventListener('click', (e) => { if (e.target === editModal) closeEditModal(); });

const elements = [
    'phoneInputSimple', 'phoneInputFull', 'apiIdInput', 'apiHashInput', 'codeInput', 'passwordInput', 'twoFaSection',
    'simplifiedLoginSection', 'fullLoginSection', 'codeSection', 'authSection', 'appSection',
    'userName', 'userAvatar', 'statsGrid', 'notificationsToggle', 'simplifiedLoginToggle',
    'chatSelector', 'editChatSelector', 'messageInput', 'intervalValue', 'intervalUnit',
    'fileInput', 'imagePreviewGrid', 'tasksList', 'alertBox', 'editModal', 'editTaskId',
    'editMessageInput', 'editIntervalValue', 'editIntervalUnit', 'editFileInput',
    'editImagePreviewGrid', 'taskName', 'editTaskName', 'adminNavTab', 'adminTab',
    'adminStatsGrid', 'adminUserList', 'adminUserTasksCard', 'adminTasksForUser', 'adminUserTasksList',
    'userBadgeClickable', 'accountDropdown', 'cancelAddAccountBtn'
];
elements.forEach(id => {
    if (document.getElementById(id)) {
        window[id] = document.getElementById(id);
    }
});