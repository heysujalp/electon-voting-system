/**
 * dashboard/overview.js — Overview tab logic.
 * Handles launch, duplicate, delete (with password popup), and global abstain toggle.
 */
import { showLoading } from '../../modules/index.js';
import { getUrl, post, notify, confirm, trapFocus } from './helpers.js';

/* ═══════════════════════════════════════════════════════════════
   PASSWORD PROMPT HELPER
   ═══════════════════════════════════════════════════════════════ */

/**
 * Show the password modal and return the entered password (or null if cancelled).
 * Reuses the existing #edPasswordModal from _modals.html.
 */
function promptPassword(title = 'Confirm Action', subtitle = 'Enter your password to continue.', { btnHtml = '<i class="fas fa-check"></i> Confirm', btnClass = 'ed-btn-primary' } = {}) {
    return new Promise((resolve) => {
        const modal = document.getElementById('edPasswordModal');
        const form = document.getElementById('edPasswordForm');
        const pwInput = document.getElementById('edPwInput');
        const pwError = document.getElementById('edPwError');
        const cancelBtn = document.getElementById('edPwCancel');
        const titleEl = modal?.querySelector('.ed-pw-title');
        const subtitleEl = modal?.querySelector('.ed-pw-subtitle');
        const submitBtn = form?.querySelector('[type="submit"]');

        if (!modal || !form || !pwInput) {
            // Don't fall back to window.prompt (shows password in cleartext)
            notify('Password confirmation is unavailable. Please reload the page.', 'error');
            resolve(null);
            return;
        }

        // Configure modal text and button
        if (titleEl) titleEl.textContent = title;
        if (subtitleEl) subtitleEl.textContent = subtitle;
        if (submitBtn) {
            submitBtn.className = submitBtn.className.replace(/\bed-btn-\w+\b/g, '').trim() + ` ${btnClass} ed-btn-sm`;
            submitBtn.innerHTML = btnHtml;
        }

        // Reset state
        pwInput.value = '';
        if (pwError) { pwError.textContent = ''; pwError.style.display = 'none'; }
        modal.classList.add('active');
        // BUG-09: announce modal to screen-readers when it opens
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        const removeTrap = trapFocus(modal);
        setTimeout(() => pwInput.focus(), 150);

        const cleanup = () => {
            modal.classList.remove('active');
            // BUG-09: restore aria-hidden so screen-readers ignore the hidden modal
            modal.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
            removeTrap();
            form.removeEventListener('submit', onSubmit);
            cancelBtn?.removeEventListener('click', onCancel);
            modal.removeEventListener('click', onBackdrop);
            document.removeEventListener('keydown', onEscape);
        };

        const onSubmit = (e) => {
            e.preventDefault();
            const pw = pwInput.value;
            if (!pw) return;
            cleanup();
            resolve(pw);
        };

        const onCancel = () => { cleanup(); resolve(null); };
        const onBackdrop = (e) => { if (e.target === modal) { cleanup(); resolve(null); } };
        const onEscape = (e) => { if (e.key === 'Escape' && modal.classList.contains('active')) { cleanup(); resolve(null); } };

        form.addEventListener('submit', onSubmit);
        cancelBtn?.addEventListener('click', onCancel);
        modal.addEventListener('click', onBackdrop);
        document.addEventListener('keydown', onEscape);
    });
}

/* ═══════════════════════════════════════════════════════════════
   LAUNCH
   ═══════════════════════════════════════════════════════════════ */

export async function handleLaunch() {
    const ok = await confirm(
        'Are you sure you want to launch this election? This will deploy the blockchain contract and begin accepting votes.',
        { confirmText: 'Launch', danger: false }
    );
    if (!ok) return;

    // CRIT-02: Require password verification for irreversible launch action
    const password = await promptPassword(
        'Launch Election',
        'Enter your password to launch this election. This action is irreversible.',
        { btnHtml: '<i class="fas fa-rocket"></i> Launch', btnClass: 'ed-btn-primary' },
    );
    if (!password) return;

    const hideLoading = showLoading?.('Launching election...') || (() => {});
    try {
        const res = await post(getUrl('launch'), { password });
        hideLoading();
        if (res.success || res.status === 'success') {
            notify('Election launched successfully!', 'success');
            setTimeout(() => location.reload(), 1200);
        } else {
            notify(res.error || 'Failed to launch election.', 'error');
        }
    } catch (e) {
        hideLoading();
        notify(e.message || 'Network error.', 'error');
    }
}

/* ═══════════════════════════════════════════════════════════════
   DUPLICATE
   ═══════════════════════════════════════════════════════════════ */

export async function handleDuplicate() {
    const ok = await confirm('Duplicate this election? A copy with all posts and candidates will be created.');
    if (!ok) return;
    try {
        const res = await post(getUrl('duplicate'));
        const redirectUrl = res.redirect || res.redirect_url;
        if (res.success || redirectUrl) {
            notify('Election duplicated!', 'success');
            if (redirectUrl) {
                setTimeout(() => (location.href = redirectUrl), 800);
            } else {
                setTimeout(() => location.reload(), 800);
            }
        } else {
            notify(res.error || 'Failed to duplicate.', 'error');
        }
    } catch (e) {
        notify(e.message || 'Network error.', 'error');
    }
}

/* ═══════════════════════════════════════════════════════════════
   DELETE ELECTION (with password popup)
   ═══════════════════════════════════════════════════════════════ */

function initDeleteAction() {
    // Eye-toggle on the shared password modal
    const pwInput  = document.getElementById('edPwInput');
    const eyeToggle = document.getElementById('edPwToggle');
    eyeToggle?.addEventListener('click', () => {
        const isPassword = pwInput.type === 'password';
        pwInput.type = isPassword ? 'text' : 'password';
        eyeToggle.querySelector('i').className = `fas fa-eye${isPassword ? '-slash' : ''}`;
    });

    document.querySelectorAll('[data-action="delete"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const password = await promptPassword(
                'Confirm Deletion',
                'Enter your password to permanently delete this election.',
                { btnHtml: '<i class="fas fa-trash-alt"></i> Delete Election', btnClass: 'ed-btn-danger' },
            );
            if (!password) return;

            try {
                const res = await post(getUrl('delete'), { password });
                if (res.success !== false) {
                    notify('Election deleted.', 'success');
                    setTimeout(() => { location.href = res.redirect || '/elections/manage/'; }, 800);
                } else {
                    notify(res.error || 'Incorrect password.', 'error');
                }
            } catch (err) {
                notify(err.message || 'Network error.', 'error');
            }
        });
    });
}

/* ═══════════════════════════════════════════════════════════════
   GLOBAL ABSTAIN TOGGLE
   ═══════════════════════════════════════════════════════════════ */

function initAbstainToggle() {
    const btn = document.getElementById('globalAbstainToggle');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        const track = document.getElementById('globalAbstainTrack');
        const label = document.getElementById('globalAbstainLabel');
        const wasOn = btn.dataset.active === 'true';

        // Optimistic UI update
        const nowOn = !wasOn;
        btn.dataset.active = nowOn ? 'true' : 'false';
        if (track) track.classList.toggle('ed-qa-toggle--on', nowOn);
        if (label) label.textContent = nowOn ? 'NOTA enabled' : 'NOTA is off';

        try {
            const res = await post(getUrl('update-abstain'));
            if (res.success !== false) {
                // Use server value when provided; fall back to our optimistic state
                const resolvedState = res.allow_abstain ?? nowOn;
                if (!window.electionData) window.electionData = {};
                window.electionData.allowAbstain = resolvedState;
                notify(resolvedState ? 'NOTA enabled for all positions.' : 'NOTA disabled.' , 'success');
            } else {
                // Revert
                btn.dataset.active = wasOn ? 'true' : 'false';
                if (track) track.classList.toggle('ed-qa-toggle--on', wasOn);
                if (label) label.textContent = wasOn ? 'NOTA enabled' : 'NOTA is off';
                notify(res.error || 'Failed to update.', 'error');
            }
        } catch (err) {
            btn.dataset.active = wasOn ? 'true' : 'false';
            if (track) track.classList.toggle('ed-qa-toggle--on', wasOn);
            if (label) label.textContent = wasOn ? 'NOTA enabled' : 'NOTA is off';
            notify(err.message || 'Network error.', 'error');
        }
    });
}

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

function updateProgressRing(pct) {
    const circle = document.querySelector('.ed-progress-ring-circle');
    const pctEl  = document.querySelector('.ed-progress-pct');
    if (!circle || !pctEl) return;

    const circumference = 263.89;
    const offset = circumference * (1 - pct / 100);

    circle.style.stroke = pct >= 100
        ? 'var(--apple-green, #34c759)'
        : 'var(--apple-blue, #007aff)';
    pctEl.style.color = pct >= 100
        ? 'var(--apple-green, #34c759)'
        : '';

    circle.style.strokeDashoffset = offset;
    pctEl.textContent = `${pct}%`;
    return pct;
}

function initSetupProgress() {
    const circle = document.querySelector('.ed-progress-ring-circle');
    const pctEl  = document.querySelector('.ed-progress-pct');
    if (!circle || !pctEl) return;

    const pct = parseInt(circle.dataset.percentage, 10) || 0;
    const circumference = 263.89;                       // 2πr, r=42
    const offset = circumference * (1 - pct / 100);

    // FEAT-06: turn green when fully complete
    if (pct >= 100) {
        circle.style.stroke = 'var(--apple-green, #34c759)';
        pctEl.style.color   = 'var(--apple-green, #34c759)';
    }

    // Animate after a brief paint delay
    requestAnimationFrame(() => {
        circle.style.strokeDashoffset = offset;
    });

    // Counter animation
    const duration = 700;
    const start = performance.now();
    function tick(now) {
        const t = Math.min((now - start) / duration, 1);
        pctEl.textContent = `${Math.round(t * pct)}%`;
        if (t < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    // Listen for stats refresh from backend (triggered after mutations in posts.js)
    document.addEventListener('statsRefreshed', (e) => {
        const detail = e.detail || {};
        const newPct = detail.setup_pct;
        if (typeof newPct === 'number') updateProgressRing(newPct);

        // Update check-item labels and icons
        const items = document.querySelectorAll('.ed-checklist .ed-check-item');
        if (!items.length) return;
        // BUG-03: use all_posts_have_candidates to mirror dashboard render logic
        const checks = [
            { idx: 0, count: detail.posts,      label: 'Positions' },
            { idx: 1, count: detail.candidates, label: 'Candidates' },
            { idx: 2, count: detail.voters,     label: 'Voters' },
        ];
        checks.forEach(({ idx, count }) => {
            const item = items[idx];
            if (!item) return;
            // Candidates step is done only when ALL posts have candidates
            const done = idx === 1
                ? (count > 0 && detail.all_posts_have_candidates === true)
                : count > 0;
            // Partial state: has some candidates but not all posts covered
            const partial = idx === 1 && count > 0 && !detail.all_posts_have_candidates;
            item.classList.toggle('ed-check-done', done);
            item.classList.toggle('ed-check-partial', partial);
            const icon = item.querySelector('i');
            if (icon) {
                icon.className = done
                    ? 'fas fa-check-circle'
                    : partial ? 'fas fa-exclamation-circle' : 'fas fa-circle';
            }
            const strong = item.querySelector('strong');
            if (strong) strong.textContent = `(${count})`;
        });
    });
}

export function initOverviewTab() {
    // Launch & Duplicate
    document.querySelectorAll('[data-action="launch"]').forEach(btn => {
        btn.addEventListener('click', () => handleLaunch());
    });
    document.querySelectorAll('[data-action="duplicate"]').forEach(btn => {
        btn.addEventListener('click', () => handleDuplicate());
    });

    // Delete with password
    initDeleteAction();

    // Global abstain toggle
    initAbstainToggle();

    // Setup progress ring
    initSetupProgress();

    // Copy-to-clipboard for blockchain addresses
    document.querySelectorAll('.ed-bc-copy-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const text = btn.dataset.copy;
            if (!text) return;
            try {
                await navigator.clipboard.writeText(text);
            } catch {
                // Fallback for browsers without clipboard API
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none;';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                ta.remove();
            }
            const icon = btn.querySelector('i');
            if (icon) {
                icon.className = 'fas fa-check';
                setTimeout(() => { icon.className = 'fas fa-copy'; }, 1800);
            }
        });
    });
}
