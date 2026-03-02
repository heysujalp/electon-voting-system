/**
 * ElectON V2 — Base JS
 * Theme toggle, Django message → notification bridge, CSRF protection.
 * Loaded as ES module on every page via base.html.
 */

import { ThemeManager, UIManager, onDOMReady, initializeCSRFProtection } from './modules/index.js';

onDOMReady(() => {
    // Theme manager (handles persistence + icon updates)
    const theme = new ThemeManager();

    // Bind all theme toggle buttons (authenticated and guest)
    document.querySelectorAll('#themeToggle, #themeToggleGuest').forEach(btn => {
        btn.addEventListener('click', () => theme.toggle());
        btn.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); theme.toggle(); } });
    });

    // Expose toggleTheme globally for any inline calls
    window.toggleTheme = () => theme.toggle();

    // Notification system: convert Django message data attributes to glass notifications
    const ui = new UIManager();
    document.querySelectorAll('[data-django-message]').forEach(el => {
        const msg = el.dataset.djangoMessage;
        const type = el.dataset.djangoMessageType || 'info';
        // Map Django message tags to notification types
        const typeMap = { 'success': 'success', 'error': 'error', 'danger': 'error', 'warning': 'warning', 'info': 'info' };
        if (msg) ui.showNotification(msg, typeMap[type] || 'info');
        el.remove();
    });

    // CSRF protection for dynamic fetch/XHR requests
    initializeCSRFProtection();

    // Navbar active link highlighting
    const path = window.location.pathname;
    document.querySelectorAll('.navbar-nav .btn').forEach(link => {
        if (link.getAttribute('href') === path) {
            link.classList.add('active');
        }
    });
});
