/**
 * election_dashboard.js — ElectON v2 Dashboard
 * Orchestrator: manages tab switching and
 * lazy-initializes per-module functions for the active tab.
 */
import { onDOMReady } from '../modules/index.js';
import { updateChartsTheme } from '../modules/chart_manager.js';

import { initOverviewTab }                    from './dashboard/overview.js';
import { initPostsTab }                       from './dashboard/posts.js';
import { initVotersTab }                      from './dashboard/voters.js';
import { initResultsTab }                     from './dashboard/results.js';
import { notify, refreshStats, applyStatsData, getUrl } from './dashboard/helpers.js';
import { connectSSE, onSSE, disconnectSSE }  from './dashboard/sse_client.js';

/* ═══════════════════════════════════════════════════════════════
   ELECTION DASHBOARD CLASS
   ═══════════════════════════════════════════════════════════════ */

class ElectionDashboard {
    constructor() {
        /* DOM refs */
        this.tabs       = document.querySelectorAll('.ed-tab');
        this.panels     = document.querySelectorAll('.ed-panel');
        this.activeTab  = 'overview';
        this._tabInited = {};

        /* Init everything */
        this.initTabs();
        this.initTabFromHash();
        this.initCopyables();
        // BUG-04: initResultBars moved into initResultsTab() so the animation
        // runs only when the Results panel is visible (CSS transitions fire).
        this.initCurrentTab();
        this.initThemeObserver();
        this.initScrollAnimations();
        this.initDurationTimer();
        this.initSSE();
    }

    /* ─── TAB MANAGEMENT ─── */

    initTabs() {
        this.tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const id = tab.dataset.tab;
                if (id === this.activeTab) return;
                this.switchTab(id);
            });
        });
    }

    /** If URL contains #tab-name, open that tab on load. */
    initTabFromHash() {
        const hash = window.location.hash.replace('#', '');
        if (hash && document.getElementById(`panel-${hash}`)) {
            this.switchTab(hash, false);
        }
    }

    switchTab(id, pushHash = true) {
        this.tabs.forEach(t => {
            const isActive = t.dataset.tab === id;
            t.classList.toggle('active', isActive);
            t.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        this.panels.forEach(p => {
            p.classList.toggle('active', p.id === `panel-${id}`);
        });
        this.activeTab = id;
        if (pushHash) {
            history.replaceState(null, '', `#${id}`);
        }
        this.initCurrentTab();
    }

    /** Dispatch to per-tab init (called once per tab). */
    initCurrentTab() {
        const id = this.activeTab;
        if (this._tabInited[id]) return;
        this._tabInited[id] = true;

        const initMap = {
            overview:   initOverviewTab,
            posts:      initPostsTab,
            voters:     initVotersTab,
            results:    initResultsTab,
        };
        initMap[id]?.();
    }

    /* ─── COPYABLES ─── */

    /** Copy-to-clipboard for access code, UUID, blockchain addresses. */
    initCopyables() {
        const copyText = (text) => {
            if (navigator.clipboard?.writeText) {
                navigator.clipboard.writeText(text)
                    .then(() => notify('Copied!', 'success'))
                    .catch(() => fallbackCopy(text));
            } else {
                fallbackCopy(text);
            }
        };

        const fallbackCopy = (text) => {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); notify('Copied!', 'success'); }
            catch { notify('Copy failed — please copy manually.', 'error'); }
            ta.remove();
        };

        document.querySelectorAll('.ed-access-code').forEach(el => {
            el.addEventListener('click', () => {
                const code = el.dataset.code;
                if (code) copyText(code);
            });
        });
        // BUG-13: removed dead .ed-copyable listener — that class is never used
        // in any template; blockchain copies are handled in overview.js.
    }

    /* ─── REAL-TIME SSE (with polling fallback) ─── */

    initSSE() {
        const streamUrl = getUrl('election-stream');

        // Register SSE event handlers BEFORE connecting
        onSSE('stats_update', (data) => applyStatsData(data));
        onSSE('vote_cast',    (data) => {
            applyStatsData(data);
            document.dispatchEvent(new CustomEvent('sse:vote_cast', { detail: data }));
        });
        onSSE('election_update', (data) => {
            // For status or structural changes, reload the page
            if (data.field === 'status') {
                location.reload();
                return;
            }
            // For name changes, update the header
            if (data.field === 'name' && data.value) {
                const nameEl = document.querySelector('.ed-election-name');
                if (nameEl) nameEl.textContent = data.value;
            }
        });
        onSSE('access_request', (data) => {
            // Refresh stats + notify voters tab
            refreshStats();
            document.dispatchEvent(new CustomEvent('sse:access_request', { detail: data }));
        });
        onSSE('voter_update', (data) => {
            // Refresh stats + notify voters tab
            refreshStats();
            document.dispatchEvent(new CustomEvent('sse:voter_update', { detail: data }));
        });
        onSSE('blockchain_update', (data) => {
            // Dispatch for results tab to handle
            document.dispatchEvent(new CustomEvent('blockchainUpdate', { detail: data }));
        });

        if (streamUrl) {
            connectSSE(streamUrl);
        }

        // Fallback: if SSE fails 5 times, revert to polling
        document.addEventListener('sse:fallback', () => {
            this._startPolling();
        });

        // Also do an initial fetch to have fresh data immediately
        setTimeout(() => refreshStats(), 3000);
    }

    /** Legacy polling — activated only when SSE is unavailable. */
    _startPolling() {
        if (this._pollingActive) return;
        this._pollingActive = true;

        setInterval(() => {
            if (document.visibilityState === 'visible') refreshStats();
        }, 30000);

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') refreshStats();
        });
    }

    /* ─── STATUS COUNTDOWN (segmented header timer) ─── */

    initDurationTimer() {
        const pill = document.querySelector('.ed-header-countdown');
        if (!pill) return;

        const startStr = pill.dataset.start;
        const endStr   = pill.dataset.end;
        const status   = pill.dataset.status;

        const elDays  = document.getElementById('edCdDays');
        const elHours = document.getElementById('edCdHours');
        const elMins  = document.getElementById('edCdMins');
        const elSecs  = document.getElementById('edCdSecs');
        const labelEl = document.getElementById('edCountdownLabelText');
        if (!startStr || !endStr || !elDays) return;

        const pad = (n) => String(n).padStart(2, '0');

        const setDigits = (ms) => {
            if (ms <= 0) {
                elDays.textContent = '00'; elHours.textContent = '00';
                elMins.textContent = '00'; elSecs.textContent = '00';
                return;
            }
            const totalSec = Math.floor(ms / 1000);
            const d = Math.floor(totalSec / 86400);
            const h = Math.floor((totalSec % 86400) / 3600);
            const m = Math.floor((totalSec % 3600) / 60);
            const s = totalSec % 60;
            elDays.textContent  = pad(d);
            elHours.textContent = pad(h);
            elMins.textContent  = pad(m);
            elSecs.textContent  = pad(s);
        };

        if (status === 'active') {
            if (labelEl) labelEl.textContent = 'Ends in';
            const end = new Date(endStr);
            let timer;
            const tick = () => {
                const remaining = end.getTime() - Date.now();
                if (remaining <= 0) {
                    clearInterval(timer);
                    setDigits(0);
                    if (labelEl) labelEl.textContent = 'Ending…';
                    setTimeout(() => location.reload(), 2000);
                    return;
                }
                setDigits(remaining);
            };
            tick();
            timer = setInterval(tick, 1000);

        } else if (status === 'inactive') {
            if (labelEl) labelEl.textContent = 'Starts in';
            const start = new Date(startStr);
            let timer;
            const tick = () => {
                const remaining = start.getTime() - Date.now();
                if (remaining <= 0) {
                    clearInterval(timer);
                    setDigits(0);
                    if (labelEl) labelEl.textContent = 'Starting…';
                    setTimeout(() => location.reload(), 2000);
                    return;
                }
                setDigits(remaining);
            };
            tick();
            timer = setInterval(tick, 1000);
        }
    }


    /* ─── THEME OBSERVER (dark ↔ light) ─── */

    initThemeObserver() {
        const root = document.documentElement;
        this._themeObserver = new MutationObserver((mutations) => {
            for (const m of mutations) {
                if (m.type === 'attributes' && m.attributeName === 'data-theme') {
                    updateChartsTheme();
                    break;
                }
            }
        });
        this._themeObserver.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    }

    /* ─── SCROLL-IN ANIMATIONS ─── */

    initScrollAnimations() {
        const targets = document.querySelectorAll(
            '.ed-header, .ed-stat, .ed-tabs, .ed-section'
        );
        targets.forEach(el => el.classList.add('ed-anim'));

        if (!('IntersectionObserver' in window)) {
            targets.forEach(el => el.classList.add('ed-in'));
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('ed-in');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.06 });

        targets.forEach(el => observer.observe(el));
    }
}

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */
onDOMReady(() => {
    if (document.querySelector('.ed')) {
        new ElectionDashboard();
    }
});
