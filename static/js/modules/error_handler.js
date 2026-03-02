/**
 * ElectON V2 — Error Handler Module
 */

import { showNotification } from './ui.js';

/**
 * Handle generic errors with optional notification
 */
export function handleError(error, context = '') {
    console.error(`[ElectON] ${context}:`, error);
    const msg = error?.message || 'An unexpected error occurred';
    showNotification(msg, 'error');
}

/**
 * Handle API response errors
 */
export function handleApiError(result, fallbackMsg = 'Request failed') {
    const msg = result?.message || result?.error || fallbackMsg;
    showNotification(msg, 'error');

    if (result?.errors) {
        for (const [field, errs] of Object.entries(result.errors)) {
            const el = document.querySelector(`[name="${field}"]`);
            if (el) {
                el.classList.add('is-invalid');
                // FE-11: Remove previous feedback to prevent accumulation
                el.parentElement?.querySelector('.invalid-feedback')?.remove();
                const fb = document.createElement('div');
                fb.className = 'invalid-feedback';
                fb.textContent = Array.isArray(errs) ? errs[0] : errs;
                fb.style.display = 'block';
                el.parentElement?.appendChild(fb);
            }
        }
    }
}

/**
 * Handle validation errors
 */
export function handleValidationError(errors) {
    if (Array.isArray(errors)) {
        errors.forEach(e => showNotification(e, 'warning'));
    } else if (typeof errors === 'object') {
        Object.values(errors).flat().forEach(e => showNotification(e, 'warning'));
    } else {
        showNotification(String(errors), 'warning');
    }
}
