// dashboard.js — User dashboard logic

requireAuth();
initTheme();  // Apply saved theme before render

// ======================== //
// State                    //
// ======================== //

let currentUser = null;
let deleteKeyId = null;
let jobsPage    = 1;
let jobsFilter  = '';
let jobsTotal   = 0;
let jobsAutoRefreshTimer = null;

// ======================== //
// Init                     //
// ======================== //

async function init() {
    try {
        currentUser = await apiJSON('/auth/me');
        setCachedUser(currentUser);
    } catch (_) {
        logout();
        return;
    }
    renderHeader();
    renderOverview();
    loadApiKeys();
    loadBilling();
    setupModals();
    setupNav();
    setupThemeToggle();
    handleHashNav();

    // Show email verification banner if not verified
    if (!currentUser.email_verified) {
        document.getElementById('verifyBanner').style.display = 'flex';
    }
}

// ======================== //
// Navigation               //
// ======================== //

function switchTab(name) {
    document.querySelectorAll('.dash-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.dash-nav-item').forEach(n => n.classList.remove('active'));
    const tab = document.getElementById('tab-' + name);
    if (tab) tab.classList.add('active');
    const navItem = document.querySelector(`[data-tab="${name}"]`);
    if (navItem) navItem.classList.add('active');
    window.location.hash = name;
    document.getElementById('dashSidebar').classList.remove('open');
    if (name === 'jobs') loadJobs();
}

function handleHashNav() {
    const hash = window.location.hash.replace('#', '');
    const valid = ['overview', 'jobs', 'apikeys', 'billing'];
    if (valid.includes(hash)) switchTab(hash);
}

function setupNav() {
    document.querySelectorAll('.dash-nav-item[data-tab]').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            const tab = item.dataset.tab;
            if (tab === 'admin-link') {
                window.location.href = '/static/admin.html';
            } else {
                switchTab(tab);
            }
        });
    });

    document.getElementById('logoutBtn').addEventListener('click', logout);

    document.getElementById('sidebarToggle').addEventListener('click', () => {
        document.getElementById('dashSidebar').classList.toggle('open');
    });
}

// ======================== //
// Header                   //
// ======================== //

function renderHeader() {
    document.getElementById('topUserEmail').textContent = currentUser.email;
    const badge = document.getElementById('topPlanBadge');
    badge.textContent = planLabel(currentUser.plan_tier);
    badge.style.background = planColor(currentUser.plan_tier);

    if (currentUser.is_admin) {
        document.getElementById('adminNavLink').style.display = '';
    }
}

// ======================== //
// Overview Tab             //
// ======================== //

function renderOverview() {
    const name = currentUser.full_name || currentUser.email.split('@')[0];
    document.getElementById('welcomeMsg').textContent = `Welcome back, ${name}!`;

    // Usage bar
    const used = currentUser.monthly_minutes_used;
    const limit = currentUser.monthly_minutes_limit;
    const pct = Math.min(100, (used / limit) * 100);
    const fill = document.getElementById('usageBarFill');
    fill.style.width = pct + '%';
    fill.style.background = pct > 80 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#10b981';

    document.getElementById('usageNumbers').textContent = `${used.toFixed(1)} / ${limit} minutes`;
    document.getElementById('usagePct').textContent = `${pct.toFixed(1)}% used`;

    const overviewBadge = document.getElementById('overviewPlanBadge');
    overviewBadge.textContent = planLabel(currentUser.plan_tier);
    overviewBadge.style.background = planColor(currentUser.plan_tier);

    if (pct > 80) {
        document.getElementById('overviewUpgradeLink').style.display = '';
        document.getElementById('overviewUpgradeLink').addEventListener('click', e => { e.preventDefault(); switchTab('billing'); });
    }

    // Stats
    document.getElementById('statLastLogin').textContent = currentUser.last_login ? formatDateTime(currentUser.last_login) : 'Now';
}

// ======================== //
// API Keys Tab             //
// ======================== //

async function loadApiKeys() {
    try {
        const keys = await apiJSON('/api-keys');
        renderApiKeys(keys);
        document.getElementById('statKeyCount').textContent = keys.length;
    } catch (_) {
        document.getElementById('apiKeysList').innerHTML = '<div class="empty-state">Failed to load API keys</div>';
    }
}

function renderApiKeys(keys) {
    const container = document.getElementById('apiKeysList');
    if (!keys.length) {
        container.innerHTML = '<div class="empty-state">No API keys yet. Create one above to get started.</div>';
        return;
    }
    container.innerHTML = keys.map(k => `
        <div class="api-key-row" id="key-row-${k.id}">
            <div class="api-key-info">
                <div class="api-key-name">${escHtml(k.name)}</div>
                <div class="api-key-meta">Created ${formatDate(k.created_at)} · Last used: ${k.last_used ? formatDateTime(k.last_used) : 'Never'}</div>
            </div>
            <button class="key-delete-btn" onclick="confirmDeleteKey(${k.id}, '${escHtml(k.name)}')">Delete</button>
        </div>`).join('');
}

document.getElementById('createKeyBtn').addEventListener('click', async () => {
    const nameInput = document.getElementById('newKeyName');
    const name = nameInput.value.trim();
    if (!name) { showToast('Please enter a key name', 'warning'); return; }
    const btn = document.getElementById('createKeyBtn');
    btn.disabled = true; btn.textContent = 'Creating…';
    try {
        const data = await apiJSON('/api-keys', { method: 'POST', body: JSON.stringify({ name }) });
        nameInput.value = '';
        showNewKeyModal(data.key);
        loadApiKeys();
    } catch (err) {
        showToast(err.detail || 'Failed to create key', 'error');
    } finally {
        btn.disabled = false; btn.textContent = 'Create Key';
    }
});

function showNewKeyModal(key) {
    document.getElementById('newKeyDisplay').textContent = key;
    document.getElementById('keyCreatedModal').classList.add('show');
}

function confirmDeleteKey(id, name) {
    deleteKeyId = id;
    document.getElementById('deleteKeyModal').classList.add('show');
}

document.getElementById('confirmDeleteBtn').addEventListener('click', async () => {
    if (!deleteKeyId) return;
    try {
        await apiFetch(`/api-keys/${deleteKeyId}`, { method: 'DELETE' });
        showToast('API key deleted', 'success');
        loadApiKeys();
    } catch (_) {
        showToast('Failed to delete key', 'error');
    } finally {
        document.getElementById('deleteKeyModal').classList.remove('show');
        deleteKeyId = null;
    }
});

document.getElementById('cancelDeleteBtn').addEventListener('click', () => {
    document.getElementById('deleteKeyModal').classList.remove('show');
    deleteKeyId = null;
});

// ======================== //
// Billing Tab              //
// ======================== //

const PLAN_DETAILS = {
    free:       { label: 'FREE',     price: '$0',  tagline: 'Hobbyist',     mins: '60',     splits: '5/min',   features: ['Web upload only', '1 video at a time', 'Community support'] },
    starter:    { label: 'STARTER',  price: '$9',  tagline: 'Creator',      mins: '600',    splits: '30/min',  features: ['API access', '3 concurrent uploads', 'Email support (24–48h)'] },
    pro:        { label: 'PRO',      price: '$19', tagline: 'Professional', mins: '3,000',  splits: '100/min', features: ['Full API access', '10 concurrent uploads', 'Cropping + aspect ratio', 'Email support (12–24h)'] },
    enterprise: { label: 'BUSINESS', price: '$49', tagline: 'Team',         mins: '15,000', splits: '500/min', features: ['Everything in Pro', 'Unlimited uploads', 'White-label option', 'Priority support (2–6h)', 'Dedicated account manager'] },
};

async function loadBilling() {
    try {
        const status = await apiJSON('/billing/status');
        renderCurrentPlan(status);
        renderPlanGrid(status.plan_tier);
    } catch (_) {
        document.getElementById('currentPlanCard').innerHTML = '<p style="color:#6b7280">Failed to load billing info</p>';
    }
}

function renderCurrentPlan(status) {
    const tier = status.plan_tier?.toLowerCase();
    const details = PLAN_DETAILS[tier] || PLAN_DETAILS.free;
    const isActive = status.subscription_status === 'active';
    const isPaid = tier !== 'free';

    document.getElementById('currentPlanInfo').innerHTML = `
        <div class="current-plan-row">
            <div>
                <span class="plan-badge" style="background:${planColor(tier)};font-size:1em">${details.label}</span>
                <span class="sub-status ${isActive ? 'status-active' : ''}">${status.subscription_status || 'Active'}</span>
            </div>
            <div style="color:#6b7280;font-size:.9em">
                ${status.monthly_minutes_used.toFixed(1)} / ${status.monthly_minutes_limit} minutes used
                ${status.subscription_ends_at ? `<br>Renews ${formatDate(status.subscription_ends_at)}` : ''}
            </div>
        </div>
        ${isPaid ? `<button class="secondary-btn" style="margin:16px 0 0" onclick="openPortal()">Manage Subscription →</button>` : ''}
    `;
}

const TIER_ORDER = { free: 0, starter: 1, pro: 2, enterprise: 3 };

function renderPlanGrid(currentTier) {
    const tiers = ['free', 'starter', 'pro', 'enterprise'];
    const currentOrder = TIER_ORDER[currentTier?.toLowerCase()] ?? 0;
    const grid = document.getElementById('planGrid');
    // Map tier key → plan name sent to checkout API
    const checkoutPlan = { starter: 'starter', pro: 'pro', enterprise: 'business' };
    grid.innerHTML = tiers.map(tier => {
        const d = PLAN_DETAILS[tier];
        const isCurrent = tier === currentTier?.toLowerCase();
        const isFree = tier === 'free';
        const targetOrder = TIER_ORDER[tier] ?? 0;
        const isUpgrade = targetOrder > currentOrder;
        const btnLabel = isUpgrade ? `Upgrade to ${d.label}` : `Downgrade to ${d.label}`;
        return `
        <div class="plan-card ${isCurrent ? 'plan-current' : ''} ${tier === 'pro' ? 'plan-featured' : ''}">
            ${tier === 'pro' ? '<div class="plan-popular">Most Popular</div>' : ''}
            <div class="plan-card-header">
                <div class="plan-name">${d.label}</div>
                <div class="plan-tagline" style="font-size:.75em;color:#9ca3af;margin-bottom:4px">${d.tagline}</div>
                <div class="plan-price">${d.price}<span>${tier !== 'free' ? '/mo' : ''}</span></div>
            </div>
            <ul class="plan-features">
                <li>✓ ${d.mins} minutes/month</li>
                <li>✓ ${d.splits} rate limit</li>
                ${d.features.map(f => `<li>✓ ${f}</li>`).join('')}
            </ul>
            ${isCurrent
                ? `<button class="plan-btn plan-btn-current" disabled>Current Plan</button>`
                : isFree
                ? `<button class="plan-btn secondary-btn" style="margin:0;width:100%;opacity:.7" onclick="openPortal()">Cancel Subscription →</button>`
                : `<button class="plan-btn primary-btn" style="margin:0;width:100%" onclick="upgradePlan('${checkoutPlan[tier]}')">${btnLabel}</button>`
            }
        </div>`;
    }).join('');
}

async function upgradePlan(plan) {
    try {
        const data = await apiJSON('/billing/checkout', { method: 'POST', body: JSON.stringify({ plan }) });
        if (data.plan_changed) {
            showToast('Plan updated! Changes will take effect shortly.', 'success');
            setTimeout(loadBilling, 2500);
        } else {
            window.location.href = data.checkout_url;
        }
    } catch (err) {
        showToast(err.detail || 'Billing not configured yet', 'warning');
    }
}

async function openPortal() {
    try {
        const data = await apiJSON('/billing/portal', { method: 'POST' });
        window.location.href = data.portal_url;
    } catch (err) {
        showToast(err.detail || 'Could not open billing portal', 'error');
    }
}

// ======================== //
// Modals                   //
// ======================== //

function setupModals() {
    document.getElementById('closeKeyModal').addEventListener('click', () => {
        document.getElementById('keyCreatedModal').classList.remove('show');
    });
    document.getElementById('copyKeyBtn').addEventListener('click', () => {
        const key = document.getElementById('newKeyDisplay').textContent;
        navigator.clipboard.writeText(key).then(() => showToast('Copied to clipboard!', 'success'));
    });
    document.getElementById('closeJobModal').addEventListener('click', () => {
        document.getElementById('jobDetailModal').classList.remove('show');
    });
    window.addEventListener('click', e => {
        if (e.target.id === 'keyCreatedModal') document.getElementById('keyCreatedModal').classList.remove('show');
        if (e.target.id === 'deleteKeyModal') { document.getElementById('deleteKeyModal').classList.remove('show'); deleteKeyId = null; }
        if (e.target.id === 'jobDetailModal') document.getElementById('jobDetailModal').classList.remove('show');
    });
}

// ======================== //
// Helpers                  //
// ======================== //

function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ======================== //
// Recent Jobs Tab          //
// ======================== //

async function loadJobs() {
    clearTimeout(jobsAutoRefreshTimer);
    const container = document.getElementById('jobsTableContainer');
    if (!container) return;
    container.innerHTML = '<div class="empty-state" style="padding:40px">Loading…</div>';

    try {
        const params = new URLSearchParams({ page: jobsPage, per_page: 10 });
        if (jobsFilter) params.set('status', jobsFilter);
        const data = await apiJSON(`/api/v1/jobs/recent?${params}`);
        jobsTotal = data.total;
        renderJobsTable(data.jobs);
        renderJobsPagination(data.total, data.page, data.per_page);

        // Auto-refresh if any jobs are still processing
        const hasProcessing = data.jobs.some(j => j.status === 'processing');
        if (hasProcessing) {
            jobsAutoRefreshTimer = setTimeout(loadJobs, 30000);
        }
    } catch (_) {
        container.innerHTML = '<div class="empty-state" style="padding:40px">Failed to load jobs</div>';
    }
}

function renderJobsTable(jobs) {
    const container = document.getElementById('jobsTableContainer');
    if (!jobs.length) {
        container.innerHTML = `<div class="empty-state" style="padding:40px">
            No jobs yet. <a href="/static/index.html" style="color:#667eea">Upload a video →</a>
        </div>`;
        return;
    }

    const rows = jobs.map(j => {
        const statusIcon = { completed: '✅', failed: '❌', processing: '⏳', expired: '⏰' }[j.status] || '?';
        const statusLabel = j.status.charAt(0).toUpperCase() + j.status.slice(1);
        const filenameTrunc = j.original_filename.length > 30
            ? j.original_filename.substring(0, 27) + '…'
            : j.original_filename;
        const expiryLabel = j.minutes_until_expiry != null && j.status === 'completed'
            ? `<span class="expiry-badge ${j.minutes_until_expiry <= 3 ? 'expiry-soon' : ''}">⏰ ${j.minutes_until_expiry}m left</span>`
            : '';

        return `
        <tr class="job-row" onclick="showJobDetail(${JSON.stringify(j).replace(/"/g, '&quot;')})">
            <td class="job-filename" title="${escHtml(j.original_filename)}">${escHtml(filenameTrunc)}</td>
            <td><span class="job-status-badge status-${j.status}">${statusIcon} ${statusLabel}</span></td>
            <td>${j.total_duration_minutes} min</td>
            <td>${j.segments_count}</td>
            <td>${j.aspect_ratio || 'Original'}</td>
            <td><span title="${j.created_at}">${relativeTime(j.created_at)}</span>${expiryLabel}</td>
            <td onclick="event.stopPropagation()" style="white-space:nowrap">
                ${j.status === 'completed'
                    ? `<a href="${j.download_all_url}" class="job-action-btn" download>⬇ All</a>
                       <button class="job-action-btn danger" onclick="deleteJob('${j.job_id}')">🗑</button>`
                    : '—'
                }
            </td>
        </tr>`;
    }).join('');

    container.innerHTML = `
        <table class="jobs-table">
            <thead>
                <tr>
                    <th>Filename</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Segments</th>
                    <th>Aspect</th>
                    <th>Created</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function renderJobsPagination(total, page, perPage) {
    const pagination = document.getElementById('jobsPagination');
    if (total <= perPage) { pagination.style.display = 'none'; return; }
    pagination.style.display = 'flex';
    const totalPages = Math.ceil(total / perPage);
    document.getElementById('jobsPageInfo').textContent = `Page ${page} of ${totalPages}`;
    document.getElementById('jobsPrevBtn').disabled = page <= 1;
    document.getElementById('jobsNextBtn').disabled = page >= totalPages;
}

function showJobDetail(job) {
    document.getElementById('jobDetailTitle').textContent = job.original_filename;
    const expiresLine = job.expires_at
        ? `<p><strong>Expires:</strong> ${new Date(job.expires_at).toLocaleString()} (${job.minutes_until_expiry ?? 0}m left)</p>`
        : '';
    const segmentLinks = job.status === 'completed'
        ? `<div style="margin-top:12px">
             <strong>Downloads:</strong>
             <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
               <a href="/api/v1/download-all/${job.job_id}" class="primary-btn" style="margin:0;padding:8px 16px;font-size:.85em;text-decoration:none" download>⬇ Download All (.zip)</a>
             </div>
           </div>`
        : '';
    const errorLine = job.error_message
        ? `<div style="background:#fef2f2;border-radius:8px;padding:12px;margin-top:12px;color:#dc2626;font-size:.85em">${escHtml(job.error_message)}</div>`
        : '';

    document.getElementById('jobDetailBody').innerHTML = `
        <div class="job-detail-grid">
            <p><strong>Job ID:</strong> <code style="font-size:.8em">${job.job_id}</code></p>
            <p><strong>Status:</strong> ${job.status}</p>
            <p><strong>Duration:</strong> ${job.total_duration_minutes} minutes</p>
            <p><strong>Segments:</strong> ${job.segments_count} × ${job.segment_duration}s</p>
            <p><strong>Aspect ratio:</strong> ${job.aspect_ratio || 'Original'}</p>
            <p><strong>Crop position:</strong> ${job.crop_position || '—'}</p>
            <p><strong>Created:</strong> ${new Date(job.created_at).toLocaleString()}</p>
            ${expiresLine}
        </div>
        ${errorLine}
        ${segmentLinks}`;

    document.getElementById('jobDetailModal').classList.add('show');
}

async function deleteJob(jobId) {
    if (!confirm('Delete this job and all its segments?')) return;
    try {
        await apiFetch(`/api/v1/job/${jobId}`, { method: 'DELETE' });
        showToast('Job deleted', 'success');
        loadJobs();
    } catch (_) {
        showToast('Failed to delete job', 'error');
    }
}

function relativeTime(dateStr) {
    if (!dateStr) return '—';
    const diff = Date.now() - new Date(dateStr).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
}

// Filter buttons
document.addEventListener('click', e => {
    if (e.target.classList.contains('filter-btn')) {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        jobsFilter = e.target.dataset.filter;
        jobsPage = 1;
        loadJobs();
    }
});

document.addEventListener('click', e => {
    if (e.target.id === 'refreshJobsBtn') loadJobs();
    if (e.target.id === 'jobsPrevBtn') { jobsPage--; loadJobs(); }
    if (e.target.id === 'jobsNextBtn') { jobsPage++; loadJobs(); }
});


// ======================== //
// Dark Mode                //
// ======================== //

function initTheme() {
    const saved = localStorage.getItem('vs_theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
}

function setupThemeToggle() {
    const btn = document.getElementById('themeToggle');
    if (!btn) return;
    const update = () => {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        btn.textContent = isDark ? '☀️' : '🌙';
    };
    update();
    btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('vs_theme', next);
        update();
    });
    // Sync across tabs
    window.addEventListener('storage', e => {
        if (e.key === 'vs_theme' && e.newValue) {
            document.documentElement.setAttribute('data-theme', e.newValue);
            update();
        }
    });
}


// ======================== //
// Delete Account           //
// ======================== //

document.getElementById('deleteAccountBtn').addEventListener('click', async () => {
    if (!confirm('This will permanently delete your account, all API keys, and all usage history.\n\nThis cannot be undone. Are you sure?')) return;
    if (!confirm('Final confirmation: delete account for ' + (currentUser?.email || 'this account') + '?')) return;

    const btn = document.getElementById('deleteAccountBtn');
    btn.disabled = true;
    btn.textContent = 'Deleting…';

    try {
        await apiFetch('/auth/me', { method: 'DELETE' });
        clearTokens();
        window.location.href = '/static/auth.html';
    } catch (_) {
        showToast('Failed to delete account. Please try again.', 'error');
        btn.disabled = false;
        btn.textContent = 'Delete My Account';
    }
});


// ======================== //
// Modals (extended)        //
// ======================== //

// Boot
init();
