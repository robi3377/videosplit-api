// admin.js — Admin dashboard logic

requireAuth();

let adminUser = null;
let editingUserId = null;
let currentPage = 1;
const perPage = 20;

async function init() {
    try {
        adminUser = await apiJSON('/auth/me');
        setCachedUser(adminUser);
    } catch (_) { logout(); return; }

    if (!adminUser.is_admin) {
        showToast('Access denied', 'error');
        window.location.href = '/static/dashboard.html';
        return;
    }

    document.getElementById('topUserEmail').textContent = adminUser.email;

    setupNav();
    loadMetrics();
    loadUsers();
}

// ======================== //
// Navigation               //
// ======================== //

function setupNav() {
    document.querySelectorAll('.dash-nav-item[data-tab]').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            switchTab(item.dataset.tab);
        });
    });
    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('sidebarToggle').addEventListener('click', () => {
        document.getElementById('dashSidebar').classList.toggle('open');
    });
}

function switchTab(name) {
    document.querySelectorAll('.dash-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.dash-nav-item').forEach(n => n.classList.remove('active'));
    const tab = document.getElementById('tab-' + name);
    if (tab) tab.classList.add('active');
    const nav = document.querySelector(`[data-tab="${name}"]`);
    if (nav) nav.classList.add('active');
}

// ======================== //
// Metrics                  //
// ======================== //

async function loadMetrics() {
    try {
        const m = await apiJSON('/admin/metrics');

        document.getElementById('mTotalUsers').textContent  = m.total_users.toLocaleString();
        document.getElementById('mActiveSubs').textContent  = m.active_subscriptions.toLocaleString();
        document.getElementById('mJobsToday').textContent   = m.jobs_today.toLocaleString();
        document.getElementById('mJobsMonth').textContent   = m.jobs_this_month.toLocaleString();
        document.getElementById('mMinutesMonth').textContent = m.minutes_processed_this_month.toLocaleString();

        // Plan breakdown
        const breakdown = document.getElementById('planBreakdown');
        const total = m.total_users || 1;
        breakdown.innerHTML = Object.entries(m.users_by_plan).map(([plan, count]) => {
            const pct = Math.round((count / total) * 100);
            return `
            <div class="plan-breakdown-row">
                <span class="plan-badge" style="background:${planColor(plan)};min-width:90px;text-align:center">${planLabel(plan)}</span>
                <div class="plan-bar-track">
                    <div class="plan-bar-fill" style="width:${pct}%;background:${planColor(plan)}"></div>
                </div>
                <span style="color:#374151;font-weight:600;min-width:60px;text-align:right">${count} (${pct}%)</span>
            </div>`;
        }).join('') || '<div class="empty-state">No users yet</div>';
    } catch (err) {
        showToast('Failed to load metrics', 'error');
    }
}

// ======================== //
// Users                    //
// ======================== //

async function loadUsers(page = 1, search = '', planFilter = '') {
    currentPage = page;
    const tbody = document.getElementById('usersTableBody');
    tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Loading…</td></tr>';

    try {
        const params = new URLSearchParams({ page, per_page: perPage });
        if (search)     params.set('search', search);
        if (planFilter) params.set('plan_tier', planFilter);

        const data = await apiJSON('/admin/users?' + params.toString());
        renderUsersTable(data.users);
        renderPagination(data.total, data.page, data.per_page);
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Failed to load users</td></tr>';
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById('usersTableBody');
    if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No users found</td></tr>';
        return;
    }
    tbody.innerHTML = users.map(u => `
        <tr>
            <td style="color:#9ca3af">#${u.id}</td>
            <td><strong>${escHtml(u.email)}</strong>${u.is_admin ? ' <span class="plan-badge" style="background:#ef4444;font-size:.7em;padding:2px 6px">ADMIN</span>' : ''}</td>
            <td style="color:#6b7280">${escHtml(u.full_name || '—')}</td>
            <td><span class="plan-badge" style="background:${planColor(u.plan_tier)}">${planLabel(u.plan_tier)}</span></td>
            <td>${u.monthly_minutes_used.toFixed(1)} / ${['pro','enterprise'].includes(u.plan_tier) ? '∞' : u.monthly_minutes_limit}</td>
            <td><span class="status-dot ${u.is_active ? 'active' : 'inactive'}">${u.is_active ? 'Active' : 'Inactive'}</span></td>
            <td style="color:#6b7280">${formatDate(u.created_at)}</td>
            <td>
                <button class="table-action-btn" onclick="openUserModal(${u.id},'${escHtml(u.email)}','${u.plan_tier}',${u.is_admin})">Edit</button>
            </td>
        </tr>`).join('');
}

function renderPagination(total, page, perPage) {
    const pages = Math.ceil(total / perPage);
    const pag = document.getElementById('pagination');
    if (pages <= 1) { pag.innerHTML = ''; return; }

    let html = `<span style="color:#6b7280;font-size:.9em">${total} users</span>`;
    if (page > 1)    html += `<button class="page-btn" onclick="changePage(${page - 1})">← Prev</button>`;
    html += `<span class="page-info">Page ${page} of ${pages}</span>`;
    if (page < pages) html += `<button class="page-btn" onclick="changePage(${page + 1})">Next →</button>`;
    pag.innerHTML = html;
}

function changePage(page) {
    const search = document.getElementById('userSearch').value.trim();
    const plan   = document.getElementById('planFilter').value;
    loadUsers(page, search, plan);
}

document.getElementById('searchBtn').addEventListener('click', () => {
    const search = document.getElementById('userSearch').value.trim();
    const plan   = document.getElementById('planFilter').value;
    loadUsers(1, search, plan);
});

document.getElementById('userSearch').addEventListener('keypress', e => {
    if (e.key === 'Enter') document.getElementById('searchBtn').click();
});

// ======================== //
// User Edit Modal          //
// ======================== //

function openUserModal(id, email, planTier, isAdmin) {
    editingUserId = id;
    document.getElementById('modalUserEmail').textContent = email;
    document.getElementById('modalPlanSelect').value = planTier?.toLowerCase() || 'free';
    document.getElementById('modalAdminCheck').checked = isAdmin;
    document.getElementById('userModal').classList.add('show');
}

document.getElementById('closeUserModal').addEventListener('click',  closeUserModal);
document.getElementById('cancelUserModal').addEventListener('click', closeUserModal);
window.addEventListener('click', e => { if (e.target.id === 'userModal') closeUserModal(); });

function closeUserModal() {
    document.getElementById('userModal').classList.remove('show');
    editingUserId = null;
}

document.getElementById('saveUserBtn').addEventListener('click', async () => {
    if (!editingUserId) return;
    const plan    = document.getElementById('modalPlanSelect').value;
    const isAdmin = document.getElementById('modalAdminCheck').checked;
    const btn = document.getElementById('saveUserBtn');
    btn.disabled = true; btn.textContent = 'Saving…';

    try {
        await Promise.all([
            apiJSON(`/admin/users/${editingUserId}/plan`, { method: 'PUT', body: JSON.stringify({ plan_tier: plan }) }),
            apiJSON(`/admin/users/${editingUserId}/admin`, { method: 'PUT', body: JSON.stringify({ is_admin: isAdmin }) }),
        ]);
        showToast('User updated successfully', 'success');
        closeUserModal();
        const search = document.getElementById('userSearch').value.trim();
        const planFilter = document.getElementById('planFilter').value;
        loadUsers(currentPage, search, planFilter);
    } catch (err) {
        showToast(err.detail || 'Failed to update user', 'error');
    } finally {
        btn.disabled = false; btn.textContent = 'Save Changes';
    }
});

// ======================== //
// Helpers                  //
// ======================== //

function escHtml(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ======================== //
// Boot                     //
// ======================== //

init();
