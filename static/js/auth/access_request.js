/**
 * ElectON V2 — Access Request Page
 *
 * Single-step: voter enters access code + name + email, submits.
 * Supports ?code=XXX query param to prefill access code from shared link.
 */

import {
    apiPost, showNotification, showLoading, onDOMReady
} from '../modules/index.js';

class AccessRequestManager {
    constructor() {
        this.form = document.getElementById('accessRequestForm');
        this.submitBtn = document.getElementById('submitRequestBtn');
        this.codeInput = document.getElementById('accessCode');
        this.nameInput = document.getElementById('voterName');
        this.emailInput = document.getElementById('voterEmail');

        this.stepForm = document.getElementById('stepForm');
        this.stepSuccess = document.getElementById('stepSuccess');

        this.apiUrl = this.form?.dataset.url || '/voting/request-access/';

        if (!this.form) return;
        this.setup();
    }

    setup() {
        this.form.addEventListener('submit', e => {
            e.preventDefault();
            this.handleSubmit();
        });

        // Reset visibility on every page show (covers bfcache restores and normal
        // back-navigation when bfcache is bypassed).  Safe to run unconditionally
        // because pageshow never fires during the page-internal AJAX flow that
        // transitions the form into the success state.
        window.addEventListener('pageshow', () => {
            this.stepForm.style.display = '';
            this.stepSuccess.style.display = 'none';
            showLoading(this.submitBtn, false);
        });

        // Prefill access code from ?code= query param
        const params = new URLSearchParams(window.location.search);
        const prefillCode = (params.get('code') || '').trim().toUpperCase();
        if (prefillCode && this.codeInput) {
            this.codeInput.value = prefillCode;
            // Focus name field instead since code is already filled
            if (this.nameInput) this.nameInput.focus();
        } else if (this.codeInput) {
            this.codeInput.focus();
        }

        // Force uppercase as user types
        if (this.codeInput) {
            this.codeInput.addEventListener('input', () => {
                this.codeInput.value = this.codeInput.value.toUpperCase();
            });
        }
    }

    async handleSubmit() {
        const code = (this.codeInput?.value || '').trim().toUpperCase();
        const name = (this.nameInput?.value || '').trim();
        const email = (this.emailInput?.value || '').trim();

        if (!code) {
            showNotification('Please enter an election access code.', 'error');
            this.codeInput?.focus();
            return;
        }
        if (!name) {
            showNotification('Please enter your full name.', 'error');
            this.nameInput?.focus();
            return;
        }
        if (!email) {
            showNotification('Please enter your email address.', 'error');
            this.emailInput?.focus();
            return;
        }

        showLoading(this.submitBtn, true, 'Submitting...');

        try {
            const response = await apiPost(this.apiUrl, {
                access_code: code,
                name,
                email,
            });

            if (response.success) {
                const successMsg = document.getElementById('successMessage');
                if (successMsg) {
                    successMsg.textContent = response.data?.message
                        || 'Your access request has been submitted successfully.';
                }
                this.stepForm.style.display = 'none';
                this.stepSuccess.style.display = '';
            } else {
                showNotification(
                    response.message || 'Request failed.', 'error', 6000
                );
            }
        } catch {
            showNotification('An unexpected error occurred.', 'error');
        } finally {
            showLoading(this.submitBtn, false);
        }
    }
}

onDOMReady(() => new AccessRequestManager());
