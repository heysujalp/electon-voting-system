/**
 * ElectON V2 — Voter Login Page
 */

import {
    apiPost, validateForm, showNotification, showLoading,
    StateStore, onDOMReady
} from '../modules/index.js';

const CONFIG = {
    selectors: {
        form: '#voterLoginForm',
        username: '[name="username"]',
        password: '#password',
        submitBtn: '.btn-auth-primary'
    },
    validation: {
        username: { required: true, message: 'Username is required' },
        password: { required: true, message: 'Password is required' }
    },
    errorMessages: {
        revoked: 'Your voting access has been revoked. Please contact your election administrator.',
        already_voted: 'You have already submitted your vote for this election. Redirecting to results...',
        election_not_active: 'This election is not currently accepting votes.',
        election_pre_launch: 'This election has not started yet. Please check back later.',
        election_inactive: 'This election has been launched but voting has not started yet. Please check back later.',
        election_concluded: 'This election has ended. Voting is no longer available.',
    }
};

class VoterLoginManager {
    constructor() {
        this.state = new StateStore();
        this.form = document.querySelector(CONFIG.selectors.form);
        this.submitBtn = document.querySelector(CONFIG.selectors.submitBtn);
        this.isSubmitting = false;
        this._countdownTimer = null;

        if (!this.form || !this.submitBtn) return;
        this.setup();
    }

    setup() {
        this.form.addEventListener('submit', e => { e.preventDefault(); if (!this.isSubmitting) this.handleLogin(); });

        // Password toggle (data-target pattern)
        this.form.querySelectorAll('.password-toggle[data-target]').forEach(btn => {
            btn.addEventListener('click', () => {
                const input = this.form.querySelector(`[name="${btn.dataset.target}"]`);
                if (!input) return;
                const icon = btn.querySelector('i');
                if (input.type === 'password') {
                    input.type = 'text';
                    icon.classList.replace('fa-eye', 'fa-eye-slash');
                    btn.setAttribute('aria-label', 'Hide password');
                } else {
                    input.type = 'password';
                    icon.classList.replace('fa-eye-slash', 'fa-eye');
                    btn.setAttribute('aria-label', 'Show password');
                }
            });
        });

        // Auto-focus
        const user = document.querySelector(CONFIG.selectors.username);
        if (user && !user.value) user.focus();

        // Enhanced input feedback
        [user, document.querySelector(CONFIG.selectors.password)].forEach(f => {
            if (!f) return;
            f.addEventListener('focus', () => { f.style.borderColor = 'var(--apple-blue)'; f.style.boxShadow = '0 0 0 3px rgba(0,122,255,0.1)'; });
            f.addEventListener('blur', () => { f.style.borderColor = ''; f.style.boxShadow = ''; });
            f.addEventListener('input', () => f.classList.remove('error-field', 'is-invalid'));
        });

        // Check redirect messages
        ['registration_success', 'voter_login_success'].forEach(key => {
            const msg = sessionStorage.getItem(key);
            if (msg) { showNotification(msg, 'success', 4000); sessionStorage.removeItem(key); }
        });
    }

    async handleLogin() {
        this.isSubmitting = true;
        showLoading(this.submitBtn, true, 'Signing In...');

        try {
            if (!validateForm(this.form, CONFIG.validation)) {
                showNotification('Please correct the errors', 'error');
                return;
            }

            const fd = new FormData(this.form);
            const data = { username: fd.get('username'), password: fd.get('password') };
            const endpoint = this.form.dataset.loginUrl || '/voting/voter-login/';
            const response = await apiPost(endpoint, data);

            if (response.success) {
                showNotification(response.data?.message || 'Login successful', 'success');
                if (response.data?.redirect_url) {
                    setTimeout(() => { window.location.href = response.data.redirect_url; }, 500);
                }
            } else {
                // Handle rate limiting with countdown
                const retryAfter = response.data?.retry_after || response.retry_after;
                if (response.status === 429 && retryAfter) {
                    this._startCountdown(Math.ceil(retryAfter));
                    return;
                }

                // Map error_code to user-friendly message
                const errorCode = response.data?.error_code;
                const friendlyMsg = errorCode && CONFIG.errorMessages[errorCode];

                if (friendlyMsg) {
                    showNotification(friendlyMsg, 'error', 6000);
                } else {
                    // Fallback to server message or generic
                    const msg = response.data?.message || 'Login failed. Please check your credentials.';
                    showNotification(msg, 'error');
                }

                // Handle redirect (e.g. already_voted → results, election_not_active → denied)
                const redirectUrl = response.data?.redirect_url;
                if (redirectUrl) {
                    setTimeout(() => { window.location.href = redirectUrl; }, 2000);
                }
            }
        } catch (error) {
            showNotification('An unexpected error occurred', 'error');
        } finally {
            this.isSubmitting = false;
            showLoading(this.submitBtn, false);
        }
    }

    /**
     * FE-04: Show a countdown timer and disable the form when rate-limited.
     */
    _startCountdown(seconds) {
        if (this._countdownTimer) clearInterval(this._countdownTimer);

        const originalText = this.submitBtn.innerHTML;
        this.submitBtn.disabled = true;
        this.form.querySelectorAll('input').forEach(f => f.disabled = true);

        let remaining = seconds;

        const updateBtn = () => {
            this.submitBtn.innerHTML = `<i class="fas fa-clock me-1"></i>Try again in ${remaining}s`;
            this.submitBtn.classList.remove('btn-primary');
            this.submitBtn.classList.add('btn-secondary');
        };
        updateBtn();

        showNotification(`Too many login attempts. Please wait ${remaining} seconds.`, 'warning', (seconds + 1) * 1000);

        this._countdownTimer = setInterval(() => {
            remaining--;
            if (remaining <= 0) {
                clearInterval(this._countdownTimer);
                this._countdownTimer = null;
                this.submitBtn.disabled = false;
                this.submitBtn.innerHTML = originalText;
                this.submitBtn.classList.remove('btn-secondary');
                this.submitBtn.classList.add('btn-primary');
                this.form.querySelectorAll('input').forEach(f => f.disabled = false);
                showNotification('You can try again now.', 'info', 3000);
            } else {
                updateBtn();
            }
        }, 1000);
    }
}

onDOMReady(() => new VoterLoginManager());
