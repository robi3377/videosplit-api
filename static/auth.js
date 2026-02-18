// auth.js — Login / Register page logic

// If already logged in, redirect to dashboard
if (isLoggedIn()) {
    window.location.href = '/static/dashboard.html';
}

// Auto-switch to register tab if ?mode=register
if (new URLSearchParams(window.location.search).get('mode') === 'register') {
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('registerTab')?.click();
    });
}

// Handle Google OAuth callback (?access_token=...&refresh_token=...)
(function handleOAuthCallback() {
    const params = new URLSearchParams(window.location.search);
    const at = params.get('access_token');
    const rt = params.get('refresh_token');
    if (at && rt) {
        setTokens(at, rt);
        fetchAndCacheUser().then(() => {
            window.location.href = '/static/dashboard.html';
        });
    }
})();

async function fetchAndCacheUser() {
    try {
        const user = await apiJSON('/auth/me');
        setCachedUser(user);
        return user;
    } catch (_) {
        return null;
    }
}

// ======================== //
// Tab Switching            //
// ======================== //

const loginTab      = document.getElementById('loginTab');
const registerTab   = document.getElementById('registerTab');
const loginForm     = document.getElementById('loginForm');
const registerForm  = document.getElementById('registerForm');
const authError     = document.getElementById('authError');
const verifySection = document.getElementById('verifySection');
const oauthDivider  = document.getElementById('oauthDivider');
const googleBtnEl   = document.getElementById('googleBtn');

// Email awaiting verification
let pendingVerifyEmail = '';

function showVerifyStep(email) {
    pendingVerifyEmail = email;
    document.getElementById('verifyEmailDisplay').textContent = email;
    // Hide normal auth UI
    document.querySelector('.tab-row').style.display = 'none';
    loginForm.style.display = 'none';
    registerForm.style.display = 'none';
    oauthDivider.style.display = 'none';
    googleBtnEl.style.display = 'none';
    authError.style.display = 'none';
    // Show verification UI
    verifySection.style.display = '';
    document.getElementById('verifyCodeInput').focus();
}

loginTab.addEventListener('click', () => {
    loginTab.classList.add('active');
    registerTab.classList.remove('active');
    loginForm.style.display = '';
    registerForm.style.display = 'none';
    clearError();
});

registerTab.addEventListener('click', () => {
    registerTab.classList.add('active');
    loginTab.classList.remove('active');
    registerForm.style.display = '';
    loginForm.style.display = 'none';
    clearError();
});

function showError(msg) {
    authError.textContent = msg;
    authError.style.display = 'block';
}

function clearError() {
    authError.style.display = 'none';
    authError.textContent = '';
}

function setLoading(btn, loading) {
    btn.disabled = loading;
    btn.textContent = loading ? 'Please wait…' : btn.dataset.label;
}

// Save original labels
document.getElementById('loginBtn').dataset.label    = 'Sign In';
document.getElementById('registerBtn').dataset.label = 'Create Account';

// ======================== //
// Login Form               //
// ======================== //

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const btn = document.getElementById('loginBtn');
    const email    = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;

    setLoading(btn, true);
    try {
        const data = await apiJSON('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password }),
        });
        setTokens(data.access_token, data.refresh_token);
        await fetchAndCacheUser();
        const next = new URLSearchParams(window.location.search).get('next');
        window.location.href = next || '/static/dashboard.html';
    } catch (err) {
        showError(err.detail || 'Invalid email or password');
        setLoading(btn, false);
    }
});

// ======================== //
// Register Form            //
// ======================== //

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const btn      = document.getElementById('registerBtn');
    const name     = document.getElementById('regName').value.trim();
    const email    = document.getElementById('regEmail').value.trim();
    const password = document.getElementById('regPassword').value;
    const confirm  = document.getElementById('regConfirm').value;
    const confirmError = document.getElementById('confirmError');

    // Client-side validation
    if (!document.getElementById('tosCheck').checked) {
        showError('Please agree to the Terms of Service and Privacy Policy to continue');
        return;
    }

    if (password !== confirm) {
        confirmError.style.display = 'block';
        document.getElementById('regConfirm').classList.add('error');
        return;
    }
    confirmError.style.display = 'none';
    document.getElementById('regConfirm').classList.remove('error');

    if (password.length < 8) {
        showError('Password must be at least 8 characters');
        return;
    }

    setLoading(btn, true);
    try {
        const body = { email, password };
        if (name) body.full_name = name;
        const data = await apiJSON('/auth/register', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        // Show verification step — account is pending email confirmation
        if (data.status === 'verify_required') {
            showVerifyStep(data.email);
        }
    } catch (err) {
        showError(err.detail || 'Registration failed. Please try again.');
        setLoading(btn, false);
    }
});

// ======================== //
// Email Verification Step  //
// ======================== //

document.getElementById('verifySubmitBtn').addEventListener('click', async () => {
    const code = document.getElementById('verifyCodeInput').value.trim();
    const verifyError = document.getElementById('verifyError');
    verifyError.style.display = 'none';

    if (code.length !== 6) {
        verifyError.textContent = 'Please enter the 6-digit code from your email';
        verifyError.style.display = 'block';
        return;
    }

    const btn = document.getElementById('verifySubmitBtn');
    btn.disabled = true;
    btn.textContent = 'Verifying…';

    try {
        const data = await apiJSON('/auth/complete-registration', {
            method: 'POST',
            body: JSON.stringify({ email: pendingVerifyEmail, code }),
        });
        setTokens(data.access_token, data.refresh_token);
        await fetchAndCacheUser();
        window.location.href = '/static/dashboard.html';
    } catch (err) {
        verifyError.textContent = err.detail || 'Invalid or expired code. Please try again.';
        verifyError.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Verify & Sign In';
    }
});

// Allow pressing Enter in the code input
document.getElementById('verifyCodeInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('verifySubmitBtn').click();
});

// Resend code with 60-second cooldown
document.getElementById('resendVerifyBtn').addEventListener('click', async () => {
    const resendBtn = document.getElementById('resendVerifyBtn');
    const cooldownEl = document.getElementById('resendCooldown');
    resendBtn.style.display = 'none';
    cooldownEl.style.display = '';

    try {
        await apiJSON('/auth/resend-registration-code', {
            method: 'POST',
            body: JSON.stringify({ email: pendingVerifyEmail }),
        });
    } catch (_) { /* ignore — always show cooldown */ }

    let secs = 60;
    cooldownEl.textContent = `Resend in ${secs}s`;
    const interval = setInterval(() => {
        secs--;
        cooldownEl.textContent = `Resend in ${secs}s`;
        if (secs <= 0) {
            clearInterval(interval);
            cooldownEl.style.display = 'none';
            resendBtn.style.display = '';
        }
    }, 1000);
});

// ======================== //
// Google OAuth             //
// ======================== //

document.getElementById('googleBtn').addEventListener('click', () => {
    window.location.href = '/auth/google/login';
});
