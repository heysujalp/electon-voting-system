/**
 * ElectON V2 — API Module
 * Standardized fetch wrapper with CSRF, retry, and timeout
 */

import { ELECTON_CONFIG } from './config.js';
import { getCSRFToken } from './security.js';

function createApiResponse(success = false, data = null, message = null, status = 200) {
    return { success, data, message, error: success ? null : message, status, errors: null };
}

/**
 * Unified API request with retry + exponential backoff
 */
export async function apiRequest(url, options = {}, retryCount = 0) {
    const { headers: extraHeaders, ...restOptions } = options;
    const defaults = {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken(),
            'X-Requested-With': 'XMLHttpRequest',
            ...extraHeaders,
        },
        timeout: ELECTON_CONFIG.API_TIMEOUT,
        ...restOptions,
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), defaults.timeout);

    try {
        const response = await fetch(url, { ...defaults, signal: controller.signal });
        clearTimeout(timeoutId);

        const contentType = response.headers.get('content-type');
        const data = contentType?.includes('application/json') ? await response.json() : await response.text();

        if (response.ok) {
            return createApiResponse(true, data, data?.message || 'Success', response.status);
        }

        let msg = 'An error occurred';
        if (typeof data === 'object' && data?.message) msg = data.message;
        else if (typeof data === 'string') msg = data;
        else if (response.status === 404) msg = 'Resource not found';
        else if (response.status === 403) msg = 'Access denied';
        else if (response.status === 500) msg = 'Server error. Please try again later.';

        // FE-06: Retry on 5xx server errors (moved from catch block where error.status was always undefined)
        if (response.status >= 500 && retryCount < ELECTON_CONFIG.API_RETRIES) {
            await new Promise(r => setTimeout(r, 1000 * (retryCount + 1)));
            return apiRequest(url, options, retryCount + 1);
        }

        return createApiResponse(false, null, msg, response.status);
    } catch (error) {
        clearTimeout(timeoutId);

        if (error.name === 'AbortError') return createApiResponse(false, null, 'Request timeout', 408);

        // FE-06: Retry on network errors (TypeError) only
        if (retryCount < ELECTON_CONFIG.API_RETRIES && error.name === 'TypeError') {
            await new Promise(r => setTimeout(r, 1000 * (retryCount + 1)));
            return apiRequest(url, options, retryCount + 1);
        }

        return createApiResponse(false, null, error.message || 'Unknown error', 0);
    }
}

/**
 * Submit a form via JSON POST
 */
export async function submitForm(formElement, endpoint, options = {}) {
    if (!(formElement instanceof HTMLFormElement)) throw new Error('Invalid form element');

    const { successCallback, errorCallback, showLoading = true, loadingText = 'Processing...', resetOnSuccess = false, redirectOnSuccess = null } = options;

    const submitBtn = formElement.querySelector('button[type="submit"], input[type="submit"]');
    let originalHtml = '';

    if (submitBtn && showLoading) {
        originalHtml = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${loadingText}`;
    }

    const inputs = Array.from(formElement.querySelectorAll('input, textarea, select, button')).slice(0, 100);
    const wasDisabled = inputs.map(i => i.disabled);
    inputs.forEach(i => { i.disabled = true; });

    try {
        const data = Object.fromEntries(new FormData(formElement).entries());
        const result = await apiRequest(endpoint, { method: 'POST', body: JSON.stringify(data) });

        if (result.success) {
            successCallback?.(result);
            if (resetOnSuccess) formElement.reset();
            if (redirectOnSuccess) window.location.href = redirectOnSuccess;
        } else {
            errorCallback?.(result);
        }
        return result;
    } finally {
        if (submitBtn && showLoading && originalHtml) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHtml;
        }
        inputs.forEach((inp, i) => { inp.disabled = wasDisabled[i]; });
    }
}

/** Convenience helpers */
export function apiGet(url, opts = {}) { return apiRequest(url, { method: 'GET', ...opts }); }
export function apiPost(url, data, opts = {}) { return apiRequest(url, { method: 'POST', body: JSON.stringify(data), ...opts }); }
export function apiPut(url, data, opts = {}) { return apiRequest(url, { method: 'PUT', body: JSON.stringify(data), ...opts }); }
export function apiDelete(url, opts = {}) { return apiRequest(url, { method: 'DELETE', ...opts }); }
