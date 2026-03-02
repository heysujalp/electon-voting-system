/**
 * ElectON V2 — Configuration Module
 */

export const ELECTON_CONFIG = {
    // Animation durations
    THEME_TRANSITION_DURATION: 200,
    NOTIFICATION_FADE_DURATION: 300,
    BUTTON_ANIMATION_DURATION: 100,
    STAGGER_ANIMATION_DELAY: 100,

    // Timeouts
    THEME_DEBOUNCE_DELAY: 300,
    ALERT_AUTO_DISMISS_DELAY: 8000,
    FORM_SUBMIT_TIMEOUT: 10000,

    // Notification durations
    DEFAULT_NOTIFICATION_DURATION: 5000,
    THEME_NOTIFICATION_DURATION: 2000,
    CONNECTION_NOTIFICATION_DURATION: 3000,

    // Password requirements — must match backend constants
    PASSWORD_REQUIREMENTS: {
        'has_lower': /[a-z]/,
        'has_upper': /[A-Z]/,
        'has_digit': /\d/,
        'has_special': /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/
    },

    // API
    API_TIMEOUT: 10000,
    API_RETRIES: 3,

    // Validation limits
    VALIDATION: {
        MIN_PASSWORD_LENGTH: 8,
        MAX_PASSWORD_LENGTH: 128,
        MAX_NAME_LENGTH: 255,
        MAX_EMAIL_LENGTH: 254,
        MAX_MESSAGE_LENGTH: 500
    },

    // UI
    UI: {
        MODAL_SIZES: ['sm', 'md', 'lg', 'xl'],
        NOTIFICATION_TYPES: ['info', 'success', 'warning', 'error'],
        FORM_STATES: ['idle', 'validating', 'submitting', 'success', 'error']
    }
};

export const PASSWORD_REQUIREMENTS = ELECTON_CONFIG.PASSWORD_REQUIREMENTS;
export const VALIDATION_RULES = ELECTON_CONFIG.VALIDATION;
export const UI_CONFIG = ELECTON_CONFIG.UI;
