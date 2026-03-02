/**
 * ElectON V2 — Module Index (barrel export)
 */

// Core modules
export * from './config.js';
export * from './security.js';
export * from './api.js';
export * from './validation.js';
export * from './ui.js';
export * from './state.js';
export * from './error_handler.js';
export * from './utils.js';
// LOW-47: lazy_loader.js removed — deprecated module with no consumers

// FE-26: Removed redundant named re-exports (already covered by export * above)

// Legacy compatibility — expose on window for non-module scripts
import { getCSRFToken, sanitizeHtml } from './security.js';
import { apiRequest, submitForm } from './api.js';
import { validateField, updateFieldValidationState } from './validation.js';
import { onDOMReady, initializePage } from './utils.js';
import { UIManager, ThemeManager } from './ui.js';

window.ElectON = {
    getCSRFToken,
    sanitizeHtml,
    apiRequest,
    submitForm,
    validateField,
    updateFieldValidationState,
    onDOMReady,
    initializePage,
    UIManager,
    ThemeManager,
    togglePassword(fieldId) { new UIManager().togglePasswordVisibility(fieldId); }
};

// Backward compat globals
window.getCSRFToken = getCSRFToken;
window.sanitizeHtml = sanitizeHtml;
window.apiRequest = apiRequest;
window.submitForm = submitForm;
window.validateField = validateField;
window.updateFieldValidationState = updateFieldValidationState;
window.onDOMReady = onDOMReady;
window.initializePage = initializePage;
window.UIManager = UIManager;
window.ThemeManager = ThemeManager;
window.togglePassword = window.ElectON.togglePassword;

// Initialize theme on load
const themeManager = new ThemeManager();
window._themeManager = themeManager;
