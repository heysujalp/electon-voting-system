/**
 * ElectON V2 — Security Module
 * CSRF tokens, HTML sanitization, security utilities
 */

/**
 * Get CSRF token from the page
 */
export function getCSRFToken() {
    // Hidden input (standard Django form)
    let el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el?.value) return el.value;

    // Meta tag
    el = document.querySelector('meta[name="csrf-token"]');
    if (el?.content) return el.content;

    // Fallback
    const inputs = document.querySelectorAll('input[name*="csrf"]');
    for (const input of inputs) {
        if (input.value) return input.value;
    }

    console.warn('CSRF token not found');
    return null;
}

/**
 * Sanitize HTML to prevent XSS
 */
export function sanitizeHtml(html) {
    if (!html || typeof html !== 'string') return '';

    const ALLOWED_TAGS = ['i', 'b', 'strong', 'em', 'span', 'br', 'p', 'div', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'];
    const ALLOWED_ATTRS = ['class', 'href', 'target', 'rel'];

    const template = document.createElement('template');
    template.innerHTML = html;

    function clean(el) {
        const tag = el.tagName?.toLowerCase() ?? '';

        if (el.nodeType === Node.ELEMENT_NODE && !ALLOWED_TAGS.includes(tag)) {
            el.parentNode?.replaceChild(document.createTextNode(el.textContent || ''), el);
            return;
        }

        if (el.nodeType === Node.ELEMENT_NODE) {
            const toRemove = [];
            const DANGEROUS_SCHEMES = ['javascript:', 'data:', 'vbscript:', 'blob:'];  // FE-10
            for (const attr of el.attributes) {
                if (!ALLOWED_ATTRS.includes(attr.name.toLowerCase())) toRemove.push(attr.name);
                if (attr.name.toLowerCase() === 'href') {
                    const val = attr.value.replace(/\s/g, '').toLowerCase();
                    if (DANGEROUS_SCHEMES.some(s => val.startsWith(s))) toRemove.push(attr.name);
                }
            }
            toRemove.forEach(a => el.removeAttribute(a));
        }

        Array.from(el.childNodes).forEach(child => {
            if (child.nodeType === Node.ELEMENT_NODE) clean(child);
        });
    }

    Array.from(template.content.childNodes).forEach(child => {
        if (child.nodeType === Node.ELEMENT_NODE) clean(child);
    });

    return template.content.innerHTML || '';
}

/**
 * Validate email format
 */
export function validateEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// FE-25: generateSecureToken removed — was dead code, never imported anywhere

/**
 * Ensure all forms have CSRF tokens
 */
export function initializeCSRFProtection() {
    const token = getCSRFToken();
    if (!token) return;

    document.querySelectorAll('form').forEach(form => {
        if (!form.querySelector('[name=csrfmiddlewaretoken]')) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'csrfmiddlewaretoken';
            input.value = token;
            form.appendChild(input);
        }
    });
}
