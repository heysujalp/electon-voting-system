/**
 * ElectON V2 — Create Election Page
 * Duration bar auto-calculation, client-side validation,
 * native date-picker opening, scroll-in animations, input focus styling.
 */

import { onDOMReady } from '../modules/index.js';

const MS_PER_MIN  = 60_000;
const MS_PER_HOUR = 3_600_000;
const MS_PER_DAY  = 86_400_000;

/* ===================================================================
   DURATION BAR
   =================================================================== */

function humanDuration(ms) {
    if (ms <= 0) return '0 minutes';
    const d = Math.floor(ms / MS_PER_DAY);
    const h = Math.floor((ms % MS_PER_DAY) / MS_PER_HOUR);
    const m = Math.floor((ms % MS_PER_HOUR) / MS_PER_MIN);
    const parts = [];
    if (d > 0) parts.push(d + (d === 1 ? ' day' : ' days'));
    if (h > 0) parts.push(h + (h === 1 ? ' hour' : ' hours'));
    if (m > 0) parts.push(m + (m === 1 ? ' min' : ' mins'));
    return parts.join(', ') || '0 minutes';
}

function initDurationBar(startEl, endEl, durBar, durText) {
    if (!startEl || !endEl || !durBar || !durText) return;

    function update() {
        const sv = startEl.value;
        const ev = endEl.value;
        if (!sv || !ev) { durBar.classList.remove('visible'); return; }

        const s = new Date(sv);
        const e = new Date(ev);
        if (isNaN(s) || isNaN(e) || e <= s) {
            durBar.classList.remove('visible');
            return;
        }

        durText.textContent = humanDuration(e - s);
        durBar.classList.add('visible');
    }

    // Listen on both 'input' (typing) and 'change' (picker selection)
    for (const evt of ['input', 'change']) {
        startEl.addEventListener(evt, update);
        endEl.addEventListener(evt, update);
    }

    // Show bar immediately if values are pre-filled (e.g. form re-render)
    if (startEl.value && endEl.value) update();
}

/* ===================================================================
   CLIENT-SIDE VALIDATION
   =================================================================== */

function initValidation(startEl, endEl, startErrEl, endErrEl) {
    if (!startEl || !endEl) return;

    function clearErr(el) {
        if (el) el.textContent = '';
        el?.closest('.ce-field')?.querySelector('.ce-input-group')?.classList.remove('ce-error');
    }

    function setErr(el, msg) {
        if (!el) return;
        // FE-18: Use textContent to prevent XSS instead of innerHTML
        el.textContent = '';
        const icon = document.createElement('i');
        icon.className = 'fas fa-circle-exclamation';
        el.appendChild(icon);
        el.appendChild(document.createTextNode(' ' + msg));
        el.closest('.ce-field')?.querySelector('.ce-input-group')?.classList.add('ce-error');
    }

    function validate() {
        clearErr(startErrEl);
        clearErr(endErrEl);

        const now = new Date();
        const sv = startEl.value;
        const ev = endEl.value;

        if (sv) {
            const s = new Date(sv);
            if (!isNaN(s) && s < now) {
                setErr(startErrEl, 'Start time cannot be in the past.');
            }
        }

        if (sv && ev) {
            const s = new Date(sv);
            const e = new Date(ev);
            if (!isNaN(s) && !isNaN(e) && e <= s) {
                setErr(endErrEl, 'End time must be after start time.');
            }
        }
    }

    for (const evt of ['input', 'change']) {
        startEl.addEventListener(evt, validate);
        endEl.addEventListener(evt, validate);
    }
}

/* ===================================================================
   NATIVE DATE-PICKER ON CLICK
   =================================================================== */

function initDatePicker(startEl, endEl) {
    function openPicker(el) {
        if (el && typeof el.showPicker === 'function') {
            try { el.showPicker(); } catch { /* some browsers restrict */ }
        }
    }

    if (startEl) startEl.addEventListener('click', () => openPicker(startEl));
    if (endEl)   endEl.addEventListener('click', () => openPicker(endEl));
}

/* ===================================================================
   ADMIN MESSAGE TOGGLE
   =================================================================== */

function initAdminMessageToggle() {
    const toggle = document.getElementById('adminMsgToggle');
    const area   = document.getElementById('adminMsgArea');
    if (!toggle || !area) return;

    function sync() {
        area.style.display = toggle.checked ? 'block' : 'none';
    }

    toggle.addEventListener('change', sync);
    // Sync on load (if textarea has content, auto-check)
    const textarea = area.querySelector('textarea');
    if (textarea && textarea.value.trim()) {
        toggle.checked = true;
    }
    sync();
}

/* ===================================================================
   SCROLL-IN ANIMATIONS
   =================================================================== */

function initAnimations() {
    const targets = document.querySelectorAll('.ce-hero, .ce-card');
    targets.forEach(el => el.classList.add('anim'));

    if (!('IntersectionObserver' in window)) {
        targets.forEach(el => el.classList.add('in'));
        return;
    }

    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('in');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.08 });

    targets.forEach(el => observer.observe(el));
}

/* ===================================================================
   INPUT FOCUS STYLING
   =================================================================== */

function initFocusStyling() {
    document.querySelectorAll('.ce-input-group').forEach(wrap => {
        const input = wrap.querySelector('input, select, textarea');
        if (!input) return;
        input.addEventListener('focus', () => wrap.classList.add('focused'));
        input.addEventListener('blur',  () => wrap.classList.remove('focused'));
    });
}

/* ===================================================================
   INIT
   =================================================================== */

onDOMReady(() => {
    if (!document.querySelector('.ce')) return;

    // Query inputs directly by name
    const startEl   = document.querySelector('.ce input[name="start_time"]');
    const endEl     = document.querySelector('.ce input[name="end_time"]');
    const durBar    = document.getElementById('durationBar');
    const durText   = document.getElementById('durationText');
    const startErr  = document.getElementById('startTimeErr');
    const endErr    = document.getElementById('endTimeErr');

    initDurationBar(startEl, endEl, durBar, durText);
    initValidation(startEl, endEl, startErr, endErr);
    initDatePicker(startEl, endEl);
    initAdminMessageToggle();
    initAnimations();
    initFocusStyling();
});
