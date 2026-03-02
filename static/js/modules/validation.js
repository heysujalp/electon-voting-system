/**
 * ElectON V2 — Validation Module
 */

import { ELECTON_CONFIG } from './config.js';

/**
 * Validate a single field
 */
export function validateField(field, rules = {}) {
    const value = field.value?.trim() ?? '';
    const errors = [];

    if (rules.required && !value) errors.push(rules.message || 'This field is required');
    if (rules.minLength && value.length < rules.minLength) errors.push(`Minimum ${rules.minLength} characters required`);
    if (rules.maxLength && value.length > rules.maxLength) errors.push(`Maximum ${rules.maxLength} characters allowed`);
    if (rules.pattern && !rules.pattern.test(value)) errors.push(rules.patternMessage || 'Invalid format');
    if (rules.email && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) errors.push('Invalid email address');

    return { valid: errors.length === 0, errors };
}

/**
 * Validate an entire form
 */
export function validateForm(form, validationRules = {}) {
    let isValid = true;

    for (const [fieldName, rules] of Object.entries(validationRules)) {
        const field = form.querySelector(`[name="${fieldName}"]`);
        if (!field) continue;

        const result = validateField(field, rules);
        updateFieldValidationState(field, result);
        if (!result.valid) isValid = false;
    }

    return isValid;
}

/**
 * Update visual state of a field based on validation result
 */
export function updateFieldValidationState(field, result) {
    // Remove previous state
    field.classList.remove('is-valid', 'is-invalid');
    const existing = field.parentElement?.querySelector('.invalid-feedback');
    if (existing) existing.remove();

    if (result.valid) {
        field.classList.add('is-valid');
    } else {
        field.classList.add('is-invalid');
        const feedback = document.createElement('div');
        feedback.className = 'invalid-feedback';
        feedback.textContent = result.errors[0] || 'Invalid';
        feedback.style.display = 'block';
        field.parentElement?.appendChild(feedback);
    }
}

/**
 * Setup real-time validation on blur
 */
export function setupRealTimeValidation(form, rules = {}) {
    for (const [fieldName, fieldRules] of Object.entries(rules)) {
        const field = form.querySelector(`[name="${fieldName}"]`);
        if (!field) continue;

        field.addEventListener('blur', () => {
            const result = validateField(field, fieldRules);
            updateFieldValidationState(field, result);
        });

        field.addEventListener('input', () => {
            field.classList.remove('is-invalid');
            field.parentElement?.querySelector('.invalid-feedback')?.remove();
        });
    }
}
