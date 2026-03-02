/**
 * ElectON V2 — Auth Password Utilities
 * Shared eye-toggle, password strength meter, and match check.
 * Used by: admin_login.html, reset_password.html
 * (Registration uses registration.js which has its own implementation.)
 */

import { PASSWORD_REQUIREMENTS, VALIDATION_RULES, onDOMReady } from '../modules/index.js';

export const STRENGTH = [
    { label: 'Too short', color: '#ff3b30', pct: 10 },
    { label: 'Weak',      color: '#ff3b30', pct: 25 },
    { label: 'Fair',      color: '#ff9500', pct: 50 },
    { label: 'Good',      color: '#34c759', pct: 75 },
    { label: 'Strong',    color: '#30d158', pct: 100 },
];

export function evaluateStrength(pw, minLen) {
    if (!pw) return -1;
    const min = minLen || VALIDATION_RULES.MIN_PASSWORD_LENGTH;
    if (pw.length < min) return 0;

    let score = 1; // passes length
    for (const regex of Object.values(PASSWORD_REQUIREMENTS)) {
        if (regex.test(pw)) score++;
    }
    if (pw.length >= 12) score++;
    if (pw.length >= 16) score++;

    // Map score (1-7) → index (1-4)
    if (score <= 2) return 1;
    if (score <= 4) return 2;
    if (score <= 5) return 3;
    return 4;
}

// Expose for non-module scripts (e.g., settings.js)
if (typeof window !== 'undefined') {
    window.ElectON = window.ElectON || {};
    window.ElectON.evaluateStrength = evaluateStrength;
    window.ElectON.STRENGTH = STRENGTH;
}

onDOMReady(() => {
    // --- Eye Toggle (works on any page with .password-toggle buttons) ---
    document.querySelectorAll('.password-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetName = btn.dataset.target;
            const input = document.querySelector(`input[name="${targetName}"]`);
            if (!input) return;
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            const icon = btn.querySelector('i');
            icon.className = isPassword ? 'fas fa-eye-slash' : 'fas fa-eye';
        });
    });

    // --- Password Strength Meter (only if meter elements exist) ---
    const pwField = document.querySelector('input[name="password"]');
    const fill = document.getElementById('passwordFill');
    const label = document.getElementById('passwordLabel');
    const meter = document.getElementById('passwordMeter');

    if (pwField && fill && label && meter) {
        pwField.addEventListener('input', () => {
            const idx = evaluateStrength(pwField.value);
            if (idx < 0) {
                fill.style.width = '0';
                label.textContent = '';
                meter.classList.remove('visible');
                return;
            }
            meter.classList.add('visible');
            const level = STRENGTH[idx];
            fill.style.width = level.pct + '%';
            fill.style.background = level.color;
            label.textContent = level.label;
            label.style.color = level.color;
            updateMatch();
        });
    }

    // --- Password Match Indicator ---
    const confirmField = document.querySelector('input[name="confirm_password"]');
    const matchEl = document.getElementById('passwordMatch');

    function updateMatch() {
        if (!confirmField || !matchEl) return;
        const confirm = confirmField.value;
        if (!confirm) { matchEl.textContent = ''; return; }
        if (pwField && pwField.value === confirm) {
            matchEl.textContent = 'Passwords match';
            matchEl.className = 'password-match match-ok';
        } else {
            matchEl.textContent = 'Passwords don\u2019t match';
            matchEl.className = 'password-match match-fail';
        }
    }

    if (confirmField) {
        confirmField.addEventListener('input', updateMatch);
    }
});
