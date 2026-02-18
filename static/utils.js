// ======================== //
// VideoSplit — utils.js    //
// Shared auth & API layer  //
// ======================== //

const API = window.location.origin;

// ======================== //
// Token Management         //
// ======================== //

function getToken() {
    return localStorage.getItem('vs_access_token');
}

function setTokens(accessToken, refreshToken) {
    localStorage.setItem('vs_access_token', accessToken);
    localStorage.setItem('vs_refresh_token', refreshToken);
}

function getRefreshToken() {
    return localStorage.getItem('vs_refresh_token');
}

function clearTokens() {
    localStorage.removeItem('vs_access_token');
    localStorage.removeItem('vs_refresh_token');
    localStorage.removeItem('vs_user');
}

function getCachedUser() {
    const u = localStorage.getItem('vs_user');
    return u ? JSON.parse(u) : null;
}

function setCachedUser(user) {
    localStorage.setItem('vs_user', JSON.stringify(user));
}

function isLoggedIn() {
    return !!getToken();
}

// ======================== //
// Auth Guard               //
// ======================== //

function requireAuth() {
    if (!isLoggedIn()) {
        window.location.href = '/static/auth.html?next=' + encodeURIComponent(window.location.pathname);
        return false;
    }
    return true;
}

function requireAdmin() {
    const user = getCachedUser();
    if (!user || !user.is_admin) {
        window.location.href = '/static/dashboard.html';
        return false;
    }
    return true;
}

// ======================== //
// Logout                   //
// ======================== //

function logout() {
    clearTokens();
    window.location.href = '/static/auth.html';
}

// ======================== //
// Fetch Wrapper            //
// ======================== //

let _refreshing = false;
let _refreshQueue = [];

async function apiFetch(path, options = {}) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (options.body instanceof FormData) delete headers['Content-Type'];

    let res = await fetch(API + path, { ...options, headers });

    // Attempt token refresh on 401
    if (res.status === 401 && getRefreshToken()) {
        if (!_refreshing) {
            _refreshing = true;
            try {
                const rr = await fetch(API + '/auth/refresh', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: getRefreshToken() }),
                });
                if (rr.ok) {
                    const data = await rr.json();
                    setTokens(data.access_token, data.refresh_token);
                    _refreshQueue.forEach(fn => fn(data.access_token));
                } else {
                    clearTokens();
                    window.location.href = '/static/auth.html';
                }
            } finally {
                _refreshing = false;
                _refreshQueue = [];
            }
        }
        // Retry with new token
        const newToken = getToken();
        if (newToken) {
            headers['Authorization'] = 'Bearer ' + newToken;
            res = await fetch(API + path, { ...options, headers });
        }
    }

    return res;
}

async function apiJSON(path, options = {}) {
    const res = await apiFetch(path, options);
    const data = await res.json();
    if (!res.ok) throw { status: res.status, detail: data.detail || 'Request failed' };
    return data;
}

// ======================== //
// Toast Notifications      //
// ======================== //

(function initToasts() {
    if (document.getElementById('vs-toast-container')) return;
    const container = document.createElement('div');
    container.id = 'vs-toast-container';
    document.body.appendChild(container);
    const style = document.createElement('style');
    style.textContent = `
        #vs-toast-container { position:fixed; top:20px; right:20px; z-index:9999; display:flex; flex-direction:column; gap:10px; }
        .vs-toast { padding:14px 20px; border-radius:10px; color:#fff; font-size:.9em; font-weight:500;
            box-shadow:0 4px 15px rgba(0,0,0,.2); animation:vsSlideIn .3s ease; max-width:320px; display:flex; align-items:center; gap:10px; }
        .vs-toast.success { background:#10b981; }
        .vs-toast.error   { background:#ef4444; }
        .vs-toast.info    { background:#667eea; }
        .vs-toast.warning { background:#f59e0b; }
        @keyframes vsSlideIn { from { transform:translateX(120%); opacity:0; } to { transform:translateX(0); opacity:1; } }
        @keyframes vsSlideOut { from { transform:translateX(0); opacity:1; } to { transform:translateX(120%); opacity:0; } }
    `;
    document.head.appendChild(style);
})();

function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('vs-toast-container');
    const toast = document.createElement('div');
    toast.className = `vs-toast ${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'vsSlideOut .3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ======================== //
// Formatting Utilities     //
// ======================== //

function formatDate(dateStr) {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function formatDateTime(dateStr) {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatDuration(seconds) {
    if (!seconds) return '0s';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m === 0) return `${s}s`;
    if (s === 0) return `${m}m`;
    return `${m}m ${s}s`;
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const k = 1024, sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
}

function planColor(tier) {
    return { free: '#6b7280', starter: '#667eea', pro: '#764ba2', enterprise: '#f59e0b' }[tier?.toLowerCase()] || '#6b7280';
}

function planLabel(tier) {
    return { free: 'FREE', starter: 'STARTER', pro: 'PRO', enterprise: 'ENTERPRISE' }[tier?.toLowerCase()] || tier?.toUpperCase();
}
