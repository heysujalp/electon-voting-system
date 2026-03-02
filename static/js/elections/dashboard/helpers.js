/**
 * dashboard/helpers.js — Shared utility functions for the dashboard.
 */
import {
    getCSRFToken,
    showNotification,
    showConfirmDialog,
} from '../../modules/index.js';

export { getCSRFToken };

/* ─── URL resolver ─── */

/** Resolve URL from the `<script type="application/json" id="electionUrlData">` element. */
export function getUrl(key) {
    const el = document.getElementById('electionUrlData');
    if (!el) return '';
    try {
        const urls = JSON.parse(el.textContent || '{}');
        return urls[key] || '';
    } catch { return ''; }
}

/* ─── CSRF-protected POST ─── */

/** Quick CSRF-protected POST with JSON response. Supports FormData, plain objects (URL-encoded), and JSON body. */
export async function post(url, body = {}, { json: sendJson = false } = {}) {
    let headers = {
        'X-CSRFToken': getCSRFToken(),
        'X-Requested-With': 'XMLHttpRequest',
    };
    let finalBody;

    if (body instanceof FormData) {
        finalBody = body;
    } else if (sendJson) {
        headers['Content-Type'] = 'application/json';
        finalBody = JSON.stringify(body);
    } else {
        headers['Content-Type'] = 'application/x-www-form-urlencoded';
        finalBody = new URLSearchParams(body);
    }

    const res = await fetch(url, { method: 'POST', headers, body: finalBody });
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
        const data = await res.json();
        if (!res.ok && !data.error) data.error = `Server error (${res.status})`;
        return data;
    }
    if (res.redirected || res.ok) return { success: true };
    throw new Error(`Server error (${res.status})`);
}

/* ─── UI helpers ─── */

/** Show inline error text. */
export function showErr(el, msg) {
    if (!el) return;
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
}

/** Notify wrapper — uses window.ElectON if available, else falls back. */
export function notify(msg, type = 'success', duration) {
    if (window.ElectON?.showNotification) {
        window.ElectON.showNotification(msg, type, duration);
    } else if (typeof showNotification === 'function') {
        showNotification(msg, type, duration);
    } else {
        alert(msg);
    }
}

/** Confirm wrapper — uses window.ElectON if available. */
export async function confirm(msg, { confirmText = 'Confirm', danger = false } = {}) {
    const opts = { message: msg, confirmText, confirmType: danger ? 'danger' : 'primary' };
    if (window.ElectON?.showConfirmDialog) {
        return window.ElectON.showConfirmDialog(opts);
    }
    if (typeof showConfirmDialog === 'function') {
        return showConfirmDialog(opts);
    }
    return window.confirm(msg);
}

/** Escape HTML entities for safe insertion. */
export function escapeHtml(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str || ''));
    return d.innerHTML;
}

/**
 * applyStatsData(data) — Update dashboard stat cards with the provided data object.
 * Used by both refreshStats() (HTTP fetch) and SSE event handlers (push data).
 * Dispatches a 'statsRefreshed' event for other tabs (e.g. overview progress ring).
 */
export function applyStatsData(data) {
    if (!data) return;

    // ── Status transition detection ──────────────────────────────────
    if (
        data.status &&
        window.electionData &&
        data.status !== window.electionData.status
    ) {
        location.reload();
        return;
    }

    // ── Header stat cards ([data-stat="posts|candidates|voters|votes"]) ──
    const map = { posts: data.posts, candidates: data.candidates, voters: data.voters, votes: data.votes };
    for (const [stat, value] of Object.entries(map)) {
        const el = document.querySelector(`.ed-stat-value[data-stat="${stat}"]`);
        if (!el) continue;
        const cur = parseInt(el.dataset.count || '0', 10);
        el.dataset.count = value;
        el.textContent   = value;
        if (cur !== value) {
            el.classList.remove('ed-stat-bump');
            void el.offsetWidth;
            el.classList.add('ed-stat-bump');
        }
    }

    // ── Voters tab stat cards ([data-voter-stat="total|email_invited|pdf_generated|voted"]) ──
    const voterMap = {
        total:          data.voters,
        email_invited:  data.voter_email_invited,
        pdf_generated:  data.voter_pdf_generated,
        voted:          data.votes,
    };
    for (const [stat, value] of Object.entries(voterMap)) {
        if (value === undefined) continue;
        const el = document.querySelector(`[data-voter-stat="${stat}"]`);
        if (!el) continue;
        const cur = parseInt(el.textContent || '0', 10);
        el.textContent = value;
        if (cur !== value) {
            el.classList.remove('ed-stat-bump');
            void el.offsetWidth;
            el.classList.add('ed-stat-bump');
        }
    }

    // Notify overview tab to refresh progress ring
    document.dispatchEvent(new CustomEvent('statsRefreshed', { detail: data }));
}

/**
 * refreshStats() — Fetch live stats from the backend and apply them.
 * Kept as the HTTP-polling fallback when SSE is unavailable.
 */
export async function refreshStats() {
    const url = getUrl('dashboard-stats');
    if (!url) return;
    try {
        const res = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;
        applyStatsData(data);
    } catch (_) { /* silently ignore — stats are non-critical */ }
}

/* ─── Focus trap (UX-02) ─── */

/**
 * Trap keyboard focus within a container element.
 * Returns a cleanup function to remove the trap.
 */
export function trapFocus(container) {
    const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function handleKeydown(e) {
        if (e.key !== 'Tab') return;
        const focusable = [...container.querySelectorAll(FOCUSABLE)].filter(el => el.offsetParent !== null);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
            if (document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }

    container.addEventListener('keydown', handleKeydown);
    return () => container.removeEventListener('keydown', handleKeydown);
}
