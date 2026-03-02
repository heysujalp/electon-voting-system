/**
 * ElectON V2 — UI Module
 * Notifications, modals, loading states, theme management
 */

import { UI_CONFIG } from './config.js';

/**
 * Escape HTML special characters to prevent XSS when inserting user content.
 */
function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

/**
 * UIManager — notifications and loading states
 */
export class UIManager {
    constructor() {
        this.notificationContainer = null;
        this.activeNotifications = new Map();
        this._ensureContainer();
    }

    _ensureContainer() {
        if (!document.getElementById('notificationContainer')) {
            const c = document.createElement('div');
            c.id = 'notificationContainer';
            c.className = 'notification-container position-fixed top-0 end-0 p-3';
            c.style.zIndex = '9999';
            document.body.appendChild(c);
        }
        this.notificationContainer = document.getElementById('notificationContainer');
    }

    showNotification(message, type = 'info', duration = 5000) {
        this._ensureContainer();
        this._removeDuplicates(message, type);

        const icons = { success: 'fas fa-check', error: 'fas fa-times', warning: 'fas fa-exclamation', info: 'fas fa-info' };
        const id = `notif-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        const el = document.createElement('div');
        el.id = id;
        el.className = `notification notification-${type}`;

        // Build notification DOM safely (no innerHTML with unsanitized input)
        const iconDiv = document.createElement('div');
        iconDiv.className = 'notification-icon';
        const iconEl = document.createElement('i');
        iconEl.className = icons[type] || icons.info;
        iconEl.setAttribute('aria-hidden', 'true');
        iconDiv.appendChild(iconEl);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'notification-content';
        const msgDiv = document.createElement('div');
        msgDiv.className = 'notification-message';
        // Allow trusted HTML (like spinner) only from internal callers
        if (message && message.includes && message.includes('<span class="spinner-apple')) {
            msgDiv.innerHTML = message; // trusted internal loading indicator
        } else {
            msgDiv.textContent = message;
        }
        contentDiv.appendChild(msgDiv);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn-close';
        closeBtn.setAttribute('aria-label', 'Close');
        closeBtn.addEventListener('click', () => this.removeNotification(id));

        el.appendChild(iconDiv);
        el.appendChild(contentDiv);
        el.appendChild(closeBtn);

        this.notificationContainer.appendChild(el);
        this.activeNotifications.set(id, el);
        requestAnimationFrame(() => el.classList.add('show'));
        if (duration > 0) setTimeout(() => this.removeNotification(id), duration);
        return id;
    }

    _removeDuplicates(msg, type) {
        this.notificationContainer.querySelectorAll(`.notification-${type}`).forEach(n => {
            const txt = n.querySelector('.notification-message')?.textContent?.trim();
            const clean = msg.replace(/<[^>]*>/g, '').trim();
            if (txt === clean || txt?.includes(clean) || clean.includes(txt)) this.removeNotification(n.id);
        });
    }

    removeNotification(id) {
        const el = this.activeNotifications.get(id) || document.getElementById(id);
        if (!el) return;
        el.classList.remove('show');
        setTimeout(() => { el.parentNode?.removeChild(el); this.activeNotifications.delete(id); }, 300);
    }

    showLoading(show, message = 'Loading...') {
        if (show) return this.showNotification(`<span class="spinner-apple me-2"></span>${message}`, 'info', 0);
        this.activeNotifications.forEach((n, id) => { if (n.querySelector('.spinner-apple')) this.removeNotification(id); });
        return null;
    }

    togglePasswordVisibility(fieldId) {
        const field = document.getElementById(fieldId);
        if (!field) return;
        const btn = field.parentElement?.querySelector('.password-toggle i');
        if (field.type === 'password') { field.type = 'text'; if (btn) btn.className = 'fas fa-eye-slash'; }
        else { field.type = 'password'; if (btn) btn.className = 'fas fa-eye'; }
    }
}

/**
 * ThemeManager — light/dark toggle with persistence
 */
export class ThemeManager {
    constructor() {
        this.theme = localStorage.getItem('electon-theme') || (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        this.apply();
    }

    apply() {
        document.documentElement.setAttribute('data-theme', this.theme);
        const icon = document.querySelector('.nav-theme-toggle i');
        if (icon) icon.className = this.theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
    }

    toggle() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('electon-theme', this.theme);
        this.apply();
    }
}

/**
 * Create and show a Bootstrap modal
 */
export function createModal(options = {}) {
    const { title = '', content = '', buttons = [], size = 'md', closable = true, onClose = null, backdrop = true, keyboard = true } = options;
    const id = `modal-${Date.now()}`;

    const safeTitle = escapeHtml(title);
    const html = `
    <div class="modal fade" id="${id}" tabindex="-1" ${backdrop ? '' : 'data-bs-backdrop="false"'} ${keyboard ? '' : 'data-bs-keyboard="false"'}>
        <div class="modal-dialog modal-${escapeHtml(size)}">
            <div class="modal-content glass-card">
                <div class="modal-header">
                    <h5 class="modal-title">${safeTitle}</h5>
                    ${closable ? '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>' : ''}
                </div>
                <div class="modal-body">${content}</div>
                <div class="modal-footer">${buttons.map((b, i) => `<button type="button" class="btn btn-${escapeHtml(b.type || 'secondary')}" id="${id}-btn-${i}">${escapeHtml(b.text)}</button>`).join('')}</div>
            </div>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    // FE-21: Guard against missing Bootstrap JS
    if (typeof bootstrap === 'undefined' || !bootstrap.Modal) {
        console.error('[ElectON] Bootstrap JS not loaded — cannot create modal');
        el?.remove();
        return null;
    }
    const modal = new bootstrap.Modal(el, { backdrop, keyboard });

    buttons.forEach((b, i) => {
        document.getElementById(`${id}-btn-${i}`)?.addEventListener('click', e => b.onClick?.(e, modal));
    });

    if (onClose) el.addEventListener('hidden.bs.modal', () => onClose(modal));
    el.addEventListener('hidden.bs.modal', () => el.remove());

    modal.show();
    return { modal, element: el, hide: () => modal.hide(), show: () => modal.show(), dispose: () => { modal.dispose(); el.remove(); } };
}

/**
 * Confirm dialog returning a Promise<boolean>
 */
export function showConfirmDialog({ title = 'Confirm', message = 'Are you sure?', confirmText = 'Confirm', cancelText = 'Cancel', confirmType = 'primary' } = {}) {
    return new Promise(resolve => {
        createModal({
            title,
            content: `<p>${escapeHtml(message)}</p>`,
            buttons: [
                { text: cancelText, type: 'secondary', onClick: (_, m) => { resolve(false); m.hide(); } },
                { text: confirmText, type: confirmType, onClick: (_, m) => { resolve(true); m.hide(); } }
            ]
        });
    });
}

export function showAlertDialog({ title = 'Alert', message = '', buttonText = 'OK' } = {}) {
    return new Promise(resolve => {
        createModal({ title, content: `<p>${escapeHtml(message)}</p>`, buttons: [{ text: buttonText, type: 'primary', onClick: (_, m) => { resolve(); m.hide(); } }] });
    });
}

/** Standalone helpers for backward compat */
const _ui = new UIManager();
export function showNotification(msg, type, dur) { return _ui.showNotification(msg, type, dur); }
export function showLoading(btnOrFlag, isLoading, text) {
    // FE-07: Handle string argument — showLoading('Loading...') → show loading overlay, return cleanup fn
    if (typeof btnOrFlag === 'string') {
        const id = _ui.showLoading(true, btnOrFlag);
        return () => _ui.showLoading(false);
    }
    if (typeof btnOrFlag === 'boolean') {
        const id = _ui.showLoading(btnOrFlag, text);
        return btnOrFlag ? () => _ui.showLoading(false) : null;
    }
    if (btnOrFlag instanceof HTMLElement) {
        if (isLoading) { btnOrFlag.dataset.originalHtml = btnOrFlag.innerHTML; btnOrFlag.disabled = true; btnOrFlag.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${text || 'Processing...'}`; }
        else { btnOrFlag.disabled = false; if (btnOrFlag.dataset.originalHtml) { btnOrFlag.innerHTML = btnOrFlag.dataset.originalHtml; delete btnOrFlag.dataset.originalHtml; } }
    }
}

export function debounce(fn, delay = 300) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn.apply(null, args), delay); };
}

export function smoothScrollTo(el) { el?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
