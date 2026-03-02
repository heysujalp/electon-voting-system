/**
 * ElectON V2 — Account Settings
 * Modal-based confirmations, view/edit toggle, email verification,
 * username availability, password update, delete flow.
 */
document.addEventListener('DOMContentLoaded', () => {
    'use strict';

    const settingsPath = '/accounts/settings/';
    const settingsData = JSON.parse(document.getElementById('settingsData')?.textContent || '{}');

    // Lazily resolve UIManager — module scripts (which define it) execute after
    // classic scripts, so we defer resolution until first use.
    let _ui = null;
    function getUI() {
        if (_ui) return _ui;
        if (typeof window.UIManager === 'function') {
            _ui = new window.UIManager();
        } else if (window.ElectON?.UIManager) {
            _ui = new window.ElectON.UIManager();
        }
        return _ui;
    }

    const notify = (msg, type = 'success') => {
        try {
            const ui = getUI();
            if (ui) {
                ui.showNotification(msg, type);
            } else {
                alert(msg);
            }
        } catch {
            alert(msg);
        }
    };

    // Show any pending notification from a previous reload
    const _pending = sessionStorage.getItem('_settingsNotify');
    if (_pending) {
        sessionStorage.removeItem('_settingsNotify');
        try { const p = JSON.parse(_pending); notify(p.msg, p.type); } catch {}
    }

    function getCSRF() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : settingsData.csrfToken || '';
    }

    /** Store notification message and reload immediately */
    function reloadWithNotify(msg, type = 'success') {
        sessionStorage.setItem('_settingsNotify', JSON.stringify({ msg, type }));
        location.reload();
    }

    /** Extract a readable error message from API response data */
    function extractMsg(data) {
        return data.error || (data.errors ? Object.values(data.errors).flat().join(', ') : 'An error occurred.');
    }

    /** Escape HTML to prevent XSS in dynamically injected markup */
    function esc(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    // ═══════════════════════════════════════════════════
    // 1. Modal Manager
    // ═══════════════════════════════════════════════════
    const Modal = {
        overlay: document.getElementById('settingsModal'),
        box: document.getElementById('settingsModalBox'),
        content: document.getElementById('settingsModalContent'),
        closeBtn: document.getElementById('settingsModalClose'),

        open(html) {
            this.content.innerHTML = html;
            this.overlay.classList.add('active');
            document.body.style.overflow = 'hidden';
            setTimeout(() => {
                const input = this.content.querySelector('input:not([type="hidden"])');
                if (input) input.focus();
            }, 150);
        },

        close() {
            this.overlay.classList.remove('active');
            document.body.style.overflow = '';
            setTimeout(() => { this.content.innerHTML = ''; }, 300);
        },

        isOpen() {
            return this.overlay.classList.contains('active');
        }
    };

    if (Modal.closeBtn) Modal.closeBtn.addEventListener('click', () => Modal.close());
    if (Modal.overlay) Modal.overlay.addEventListener('click', (e) => {
        if (e.target === Modal.overlay) Modal.close();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && Modal.isOpen()) Modal.close();
    });

    // ═══════════════════════════════════════════════════
    // 2. Sidebar Navigation (auto-cancel edits on switch)
    // ═══════════════════════════════════════════════════
    const navItems = document.querySelectorAll('.settings-nav-item[data-panel]');
    const panels = document.querySelectorAll('.settings-panel');
    const editableFields = ['email', 'fullname', 'username', 'password', 'securityq'];

    function switchPanel(panelId) {
        editableFields.forEach(f => hideEdit(f));
        navItems.forEach(btn => {
            const isActive = btn.dataset.panel === panelId;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-selected', isActive);
        });
        panels.forEach(p => p.classList.toggle('active', p.id === 'panel-' + panelId));
        history.replaceState(null, '', '#' + panelId);
    }

    navItems.forEach(btn => btn.addEventListener('click', () => switchPanel(btn.dataset.panel)));

    const hash = location.hash.replace('#', '');
    if (hash && document.getElementById('panel-' + hash)) switchPanel(hash);

    // ═══════════════════════════════════════════════════
    // 3. View / Edit Toggle
    // ═══════════════════════════════════════════════════
    function showEdit(field) {
        // Cancel any other open edits first
        editableFields.forEach(f => { if (f !== field) hideEdit(f); });
        const viewEl = document.getElementById(field + 'View');
        const editEl = document.getElementById(field + 'Edit');
        const editBtn = document.querySelector(`.settings-edit-btn[data-edit="${field}"]`);
        if (viewEl) viewEl.style.display = 'none';
        if (editEl) { editEl.style.display = 'block'; editEl.style.animation = 'settingsEditIn 0.3s ease forwards'; }
        if (editBtn) editBtn.style.display = 'none';
        // Email: always start at step 1 (enter email), hide step 2 (enter code)
        if (field === 'email') {
            const ef = document.getElementById('emailSendForm');
            const vs = document.getElementById('emailVerifyStep');
            if (ef) ef.style.display = '';
            if (vs) vs.style.display = 'none';
        }
    }

    function hideEdit(field) {
        const viewEl = document.getElementById(field + 'View');
        const editEl = document.getElementById(field + 'Edit');
        const editBtn = document.querySelector(`.settings-edit-btn[data-edit="${field}"]`);
        if (viewEl) viewEl.style.display = '';
        if (editEl) editEl.style.display = 'none';
        if (editBtn) editBtn.style.display = '';
        const form = editEl?.querySelector('form');
        if (form) form.reset();
        if (field === 'username') {
            const s = document.getElementById('usernameStatus');
            if (s) { s.textContent = ''; s.className = 'settings-username-status'; }
        }
        if (field === 'email') {
            const vs = document.getElementById('emailVerifyStep');
            const ef = document.getElementById('emailSendForm');
            if (vs) vs.style.display = 'none';
            if (ef) ef.style.display = '';
        }
    }

    document.querySelectorAll('.settings-edit-btn[data-edit]').forEach(btn => {
        btn.addEventListener('click', () => showEdit(btn.dataset.edit));
    });
    document.querySelectorAll('.settings-cancel-btn[data-cancel]').forEach(btn => {
        btn.addEventListener('click', () => hideEdit(btn.dataset.cancel));
    });

    // ═══════════════════════════════════════════════════
    // 4. AJAX + Spinner Utilities
    // ═══════════════════════════════════════════════════
    async function ajaxPost(url, formData) {
        let resp;
        try {
            resp = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': formData.get('csrfmiddlewaretoken') || getCSRF() },
                body: formData,
                credentials: 'same-origin',
            });
        } catch {
            return { success: false, error: 'Network error. Please check your connection.' };
        }
        try {
            return await resp.json();
        } catch {
            return { success: false, error: `Server error (${resp.status}). Please try again.` };
        }
    }

    function withSpinner(btn, callback) {
        const origHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        return callback().finally(() => {
            btn.disabled = false;
            btn.innerHTML = origHTML;
        });
    }

    // ═══════════════════════════════════════════════════
    // 5. Eye Toggle Utility
    // ═══════════════════════════════════════════════════
    function initEyeToggles(container) {
        (container || document).querySelectorAll('.settings-password-toggle').forEach(btn => {
            if (btn.dataset.bound) return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', () => {
                const input = document.getElementById(btn.dataset.targetId);
                if (!input) return;
                const isPw = input.type === 'password';
                input.type = isPw ? 'text' : 'password';
                btn.querySelector('i').className = isPw ? 'fas fa-eye-slash' : 'fas fa-eye';
            });
        });
    }
    initEyeToggles();

    // ═══════════════════════════════════════════════════
    // 6. Password Confirmation Modal (reusable)
    // ═══════════════════════════════════════════════════
    function showPasswordModal(title, subtitle, onConfirm, opts = {}) {
        const theme = opts.theme || 'blue'; // 'blue' or 'red'
        const iconClass = theme === 'red' ? 'modal-icon-red' : '';
        const iconName = theme === 'red' ? 'fa-exclamation-triangle' : 'fa-shield-halved';
        const confirmClass = theme === 'red' ? 'settings-btn-danger' : 'settings-btn-primary';
        const confirmText = opts.confirmText || 'Confirm';
        Modal.open(`
            <div class="modal-icon ${iconClass}"><i class="fas ${iconName}"></i></div>
            <h3 class="modal-title">${esc(title)}</h3>
            <p class="modal-subtitle">${esc(subtitle)}</p>
            <form id="modalPwForm" autocomplete="off">
                <div class="settings-field-group">
                    <label class="settings-field-label">Password</label>
                    <div class="settings-password-wrapper">
                        <input type="password" id="modalPwInput" class="form-control" placeholder="Enter your password" required autocomplete="current-password">
                        <button type="button" class="settings-password-toggle" data-target-id="modalPwInput"><i class="fas fa-eye"></i></button>
                    </div>
                    <div class="modal-error" id="modalPwError"></div>
                </div>
                <div class="modal-actions">
                    <button type="submit" class="settings-btn ${confirmClass} settings-btn-sm modal-confirm-btn">
                        <i class="fas fa-check"></i> ${confirmText}
                    </button>
                    <button type="button" class="settings-btn settings-btn-ghost settings-btn-sm modal-cancel-btn">Cancel</button>
                </div>
            </form>
        `);
        initEyeToggles(Modal.content);
        Modal.content.querySelector('.modal-cancel-btn').addEventListener('click', () => Modal.close());
        document.getElementById('modalPwForm').addEventListener('submit', (e) => {
            e.preventDefault();
            const password = document.getElementById('modalPwInput').value;
            if (!password) return;
            const btn = Modal.content.querySelector('.modal-confirm-btn');
            withSpinner(btn, () => onConfirm(password));
        });
    }

    // ═══════════════════════════════════════════════════
    // 7. Full Name Update
    // ═══════════════════════════════════════════════════
    const fullNameForm = document.getElementById('fullNameForm');
    if (fullNameForm) {
        fullNameForm.addEventListener('submit', (e) => {
            e.preventDefault();
            showPasswordModal('Confirm Changes', 'Enter your password to update your full name.', async (password) => {
                const fd = new FormData(fullNameForm);
                fd.append('password', password);
                const data = await ajaxPost(settingsPath + 'update-name/', fd);
                if (data.success) {
                    Modal.close();
                    reloadWithNotify(data.message || 'Full name updated.');
                } else {
                    const msg = extractMsg(data);
                    const err = document.getElementById('modalPwError');
                    if (err) err.textContent = msg;
                    notify(msg, 'error');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // 8. Username Update + Availability Check
    // ═══════════════════════════════════════════════════
    const usernameForm = document.getElementById('usernameForm');
    const usernameInput = document.getElementById('id_username');
    const usernameStatus = document.getElementById('usernameStatus');
    let usernameCheckTimer = null;

    if (usernameInput && usernameStatus) {
        usernameInput.addEventListener('input', () => {
            clearTimeout(usernameCheckTimer);
            const val = usernameInput.value.trim();
            if (!val || val.length < 3) {
                usernameStatus.textContent = '';
                usernameStatus.className = 'settings-username-status';
                return;
            }
            usernameStatus.textContent = 'Checking\u2026';
            usernameStatus.className = 'settings-username-status status-checking';
            usernameCheckTimer = setTimeout(async () => {
                try {
                    const resp = await fetch(settingsPath + 'check-username/?username=' + encodeURIComponent(val), { credentials: 'same-origin' });
                    const data = await resp.json();
                    if (data.current) {
                        usernameStatus.textContent = 'This is your current username';
                        usernameStatus.className = 'settings-username-status status-checking';
                    } else if (data.available) {
                        usernameStatus.textContent = '\u2713 Username is available';
                        usernameStatus.className = 'settings-username-status status-available';
                    } else {
                        usernameStatus.textContent = '\u2717 Username is already taken';
                        usernameStatus.className = 'settings-username-status status-taken';
                    }
                } catch { usernameStatus.textContent = ''; }
            }, 400);
        });
    }

    if (usernameForm) {
        usernameForm.addEventListener('submit', (e) => {
            e.preventDefault();
            showPasswordModal('Confirm Changes', 'Enter your password to update your username.', async (password) => {
                const fd = new FormData(usernameForm);
                fd.append('password', password);
                const data = await ajaxPost(settingsPath + 'update-username/', fd);
                if (data.success) {
                    Modal.close();
                    reloadWithNotify(data.message || 'Username updated.');
                } else {
                    const msg = extractMsg(data);
                    const err = document.getElementById('modalPwError');
                    if (err) err.textContent = msg;
                    notify(msg, 'error');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // 9. Email Update (inline 2-step + password modal)
    //    Step 1: Enter email → Send Verification Code (inline)
    //    Step 2: Enter code → press Update Email → password modal
    // ═══════════════════════════════════════════════════
    const emailSendForm = document.getElementById('emailSendForm');
    const emailVerifyForm = document.getElementById('emailVerifyForm');
    const emailVerifyStep = document.getElementById('emailVerifyStep');

    // Step 1: Send verification code (no password yet)
    if (emailSendForm) {
        emailSendForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const emailVal = document.getElementById('id_email')?.value.trim();
            if (!emailVal) return;
            const btn = emailSendForm.querySelector('button[type="submit"]');
            withSpinner(btn, async () => {
                const fd = new FormData(emailSendForm);
                const data = await ajaxPost(settingsPath + 'send-email-code/', fd);
                if (data.success) {
                    // Show verify step FIRST, then notify
                    emailSendForm.style.display = 'none';
                    emailVerifyStep.style.display = 'block';
                    notify(data.message, 'success');
                } else {
                    notify(data.error || 'Failed to send verification code.', 'error');
                }
            });
        });
    }

    // Step 2: Enter code, then password modal
    if (emailVerifyForm) {
        emailVerifyForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const code = document.getElementById('email_verify_code')?.value.trim();
            if (!code) return;
            // Show password popup to confirm email change
            showPasswordModal('Confirm Email Change', 'Enter your password to complete the email update.', async (password) => {
                const fd = new FormData();
                fd.append('csrfmiddlewaretoken', getCSRF());
                fd.append('code', code);
                fd.append('password', password);
                const data = await ajaxPost(settingsPath + 'verify-email-change/', fd);
                if (data.success) {
                    Modal.close();
                    reloadWithNotify(data.message || 'Email updated.');
                } else {
                    const msg = extractMsg(data);
                    const err = document.getElementById('modalPwError');
                    if (err) err.textContent = msg;
                    notify(msg, 'error');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // 10. Password Update (inline form with strength meter)
    // ═══════════════════════════════════════════════════
    const passwordForm = document.getElementById('passwordForm');
    if (passwordForm) {
        passwordForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const btn = passwordForm.querySelector('button[type="submit"]');
            withSpinner(btn, async () => {
                const data = await ajaxPost(settingsPath + 'update-password/', new FormData(passwordForm));
                if (data.success) {
                    reloadWithNotify(data.message || 'Password updated.');
                } else {
                    notify(extractMsg(data), 'error');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // 11. Password Strength + Match (inline form)
    //     Uses shared utilities from window.ElectON if available,
    //     otherwise falls back to inline implementation.
    // ═══════════════════════════════════════════════════
    const STRENGTH = window.ElectON?.STRENGTH || [
        { label: 'Too short', color: '#ff3b30', pct: 10 },
        { label: 'Weak',      color: '#ff3b30', pct: 25 },
        { label: 'Fair',      color: '#ff9500', pct: 50 },
        { label: 'Good',      color: '#34c759', pct: 75 },
        { label: 'Strong',    color: '#30d158', pct: 100 },
    ];

    function evaluateStrength(pw) {
        if (window.ElectON?.evaluateStrength) {
            const rules = JSON.parse(document.getElementById('settingsData')?.textContent || '{}');
            return window.ElectON.evaluateStrength(pw, rules.min_password_length);
        }
        // Fallback when password.js module hasn't loaded
        if (!pw) return -1;
        const rules = JSON.parse(document.getElementById('settingsData')?.textContent || '{}');
        const minLen = rules.min_password_length || 8;
        if (pw.length < minLen) return 0;
        let score = 1;
        if (/[A-Z]/.test(pw)) score++;
        if (/[a-z]/.test(pw)) score++;
        if (/\d/.test(pw)) score++;
        if (/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(pw)) score++;
        if (pw.length >= 12) score++;
        if (pw.length >= 16) score++;
        if (score <= 2) return 1;
        if (score <= 4) return 2;
        if (score <= 5) return 3;
        return 4;
    }

    const newPw     = document.getElementById('id_new_password');
    const confirmPw = document.getElementById('id_confirm_password');
    const fill      = document.getElementById('strengthFill');
    const label     = document.getElementById('strengthLabel');
    const meter     = document.getElementById('strengthMeter');
    const matchEl   = document.getElementById('passwordMatch');

    function updateMatch() {
        if (!confirmPw || !matchEl) return;
        const val = confirmPw.value;
        if (!val) { matchEl.textContent = ''; return; }
        if (newPw && newPw.value === val) {
            matchEl.textContent = 'Passwords match';
            matchEl.className = 'settings-password-match match-ok';
        } else {
            matchEl.textContent = 'Passwords don\u2019t match';
            matchEl.className = 'settings-password-match match-fail';
        }
    }

    if (newPw && fill && label && meter) {
        newPw.addEventListener('input', () => {
            const idx = evaluateStrength(newPw.value);
            if (idx < 0) {
                fill.style.width = '0';
                label.textContent = '';
                meter.classList.remove('visible');
                return;
            }
            meter.classList.add('visible');
            const lvl = STRENGTH[idx];
            fill.style.width = lvl.pct + '%';
            fill.style.background = lvl.color;
            label.textContent = lvl.label;
            label.style.color = lvl.color;
            updateMatch();
        });
    }

    if (confirmPw) confirmPw.addEventListener('input', updateMatch);

    // ═══════════════════════════════════════════════════
    // 12. Security Questions
    // ═══════════════════════════════════════════════════
    const sqForm = document.getElementById('securityQuestionsForm');
    if (sqForm) {
        sqForm.addEventListener('submit', (e) => {
            e.preventDefault();
            showPasswordModal('Confirm Changes', 'Enter your password to update your security questions.', async (password) => {
                const fd = new FormData(sqForm);
                fd.append('current_password', password);
                const data = await ajaxPost(settingsPath + 'update-security-questions/', fd);
                if (data.success) {
                    Modal.close();
                    reloadWithNotify(data.message || 'Security questions updated.');
                } else {
                    const msg = extractMsg(data);
                    const err = document.getElementById('modalPwError');
                    if (err) err.textContent = msg;
                    notify(msg, 'error');
                }
            });
        });

        // Prevent duplicate question selection
        const sqSelects = sqForm.querySelectorAll('select[name^="question_"]');
        sqSelects.forEach(select => {
            select.addEventListener('change', () => {
                const chosen = Array.from(sqSelects).map(s => s.value).filter(Boolean);
                sqSelects.forEach(s => {
                    Array.from(s.options).forEach(opt => {
                        if (opt.value && opt.value !== s.value) {
                            opt.disabled = chosen.includes(opt.value);
                        }
                    });
                });
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // 13. Delete Account (2-step modal flow — red themed)
    // ═══════════════════════════════════════════════════
    const deleteBtn = document.getElementById('deleteAccountBtn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', () => {
            // Step 1: Password modal (RED theme)
            showPasswordModal(
                'Delete Account',
                'Enter your password to proceed with account deletion.',
                async (password) => {
                    const fd = new FormData();
                    fd.append('csrfmiddlewaretoken', getCSRF());
                    fd.append('password', password);
                    const data = await ajaxPost(settingsPath + 'verify-password/', fd);
                    if (data.success) {
                        Modal.close();
                        setTimeout(() => showDeleteUsernameModal(password), 350);
                    } else {
                        const err = document.getElementById('modalPwError');
                        if (err) err.textContent = data.error || 'Incorrect password.';
                        notify(data.error || 'Incorrect password.', 'error');
                    }
                },
                { theme: 'red', confirmText: 'Continue' }
            );
        });
    }

    function showDeleteUsernameModal(password) {
        Modal.open(`
            <div class="modal-icon modal-icon-red"><i class="fas fa-exclamation-triangle"></i></div>
            <h3 class="modal-title">Final Confirmation</h3>
            <p class="modal-subtitle">This action is permanent and cannot be undone. Type your username to confirm account deletion.</p>
            <form id="modalDeleteForm" autocomplete="off">
                <div class="settings-field-group">
                    <label class="settings-field-label">Your Username</label>
                    <input type="text" id="modalDeleteUsername" class="form-control" placeholder="Type your username" required autocomplete="off">
                    <div class="settings-username-confirm-status" id="modalDeleteStatus"></div>
                </div>
                <div class="modal-actions">
                    <button type="submit" class="settings-btn settings-btn-danger settings-btn-sm modal-confirm-btn" id="modalDeleteConfirmBtn" disabled>
                        <i class="fas fa-trash-can"></i> Permanently Delete
                    </button>
                    <button type="button" class="settings-btn settings-btn-ghost settings-btn-sm modal-cancel-btn">Cancel</button>
                </div>
            </form>
        `);

        const usrInput = document.getElementById('modalDeleteUsername');
        const cfmBtn = document.getElementById('modalDeleteConfirmBtn');
        const statusEl = document.getElementById('modalDeleteStatus');

        Modal.content.querySelector('.modal-cancel-btn').addEventListener('click', () => Modal.close());

        usrInput.addEventListener('input', () => {
            const matches = usrInput.value.trim() === settingsData.username;
            cfmBtn.disabled = !matches;
            if (!usrInput.value.trim()) {
                statusEl.textContent = '';
                statusEl.className = 'settings-username-confirm-status';
            } else if (matches) {
                statusEl.textContent = '\u2713 Username matches';
                statusEl.className = 'settings-username-confirm-status status-match';
            } else {
                statusEl.textContent = '\u2717 Username does not match';
                statusEl.className = 'settings-username-confirm-status status-nomatch';
            }
        });

        document.getElementById('modalDeleteForm').addEventListener('submit', (e) => {
            e.preventDefault();
            if (cfmBtn.disabled) return;
            withSpinner(cfmBtn, async () => {
                const fd = new FormData();
                fd.append('csrfmiddlewaretoken', getCSRF());
                fd.append('password', password);
                fd.append('username_confirm', usrInput.value.trim());
                const data = await ajaxPost(settingsPath + 'delete-account/', fd);
                if (data.success) {
                    Modal.close();
                    notify('Account deleted. Redirecting\u2026', 'success');
                    setTimeout(() => { window.location.href = data.redirect || '/'; }, 1000);
                } else {
                    notify(data.error || 'Could not delete account.', 'error');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════
    // 14. Usage Bar Animation
    // ═══════════════════════════════════════════════════
    document.querySelectorAll('.settings-usage').forEach(usageEl => {
        const fill = usageEl.querySelector('.settings-usage-fill');
        if (!fill) return;
        const used = parseInt(usageEl.dataset.used, 10) || 0;
        const max  = parseInt(usageEl.dataset.max, 10) || 1;
        const pct  = Math.min(100, Math.round((used / max) * 100));
        requestAnimationFrame(() => { fill.style.width = pct + '%'; });
    });
});
