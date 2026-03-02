/**
 * dashboard/voters.js — Voters tab logic (redesigned).
 * Email invite entry, collapsible sections, search/sort,
 * send invitations, duplicate-resolution modal, offline PDF,
 * revoke, regeneration, bulk actions, batch management.
 */
import { getUrl, post, showErr, notify, confirm, escapeHtml, trapFocus, getCSRFToken } from './helpers.js';

/* ═══════════════════════════════════════════════════════════════
   Module-level state
   ═══════════════════════════════════════════════════════════════ */
let _pendingManualVoters = null;
let _dupAbort = null;
let _emailActiveFilter = 'all';  // active status filter for email voter table

/* ═══════════════════════════════════════════════════════════════
   INVITE TAB TOGGLE  (Email ↔ In-Person/PDF)
   ═══════════════════════════════════════════════════════════════ */

function initInviteToggle() {
    const tabs = document.querySelectorAll('.ed-voters-invite-tab');
    if (!tabs.length) return;

    const storageKey = `voterSubTab_${window.electionUuid || ''}`;

    const applyActiveTab = () => {
        const activeTab = document.querySelector('.ed-voters-invite-tab.active');
        const activePanelId = activeTab?.dataset.panel;
        const activeSectionId = activeTab?.dataset.section;
        document.querySelectorAll('.ed-voters-invite-panel').forEach(panel => {
            panel.style.display = panel.id === activePanelId ? '' : 'none';
        });
        const emailSection = document.getElementById('emailVotersSection');
        const batchSection = document.getElementById('batchVotersSection');
        const accessSection = document.getElementById('accessRequestsSection');
        if (emailSection) emailSection.style.display = activeSectionId === 'batchVotersSection' ? 'none' : '';
        if (batchSection) batchSection.style.display = activeSectionId === 'batchVotersSection' ? '' : 'none';
        if (accessSection) accessSection.style.display = activeSectionId === 'batchVotersSection' ? 'none' : '';
    };

    // Restore sub-tab from sessionStorage before initial apply
    const savedPanel = sessionStorage.getItem(storageKey);
    if (savedPanel) {
        tabs.forEach(t => {
            const isMatch = t.dataset.panel === savedPanel;
            t.classList.toggle('active', isMatch);
            t.setAttribute('aria-selected', isMatch ? 'true' : 'false');
        });
    }

    applyActiveTab();

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => {
                t.classList.remove('active');
                t.setAttribute('aria-selected', 'false');
            });
            tab.classList.add('active');
            tab.setAttribute('aria-selected', 'true');
            applyActiveTab();
            // Persist selection across refreshes
            sessionStorage.setItem(storageKey, tab.dataset.panel);
        });
    });

    window.addEventListener('pageshow', (e) => { if (e.persisted) applyActiveTab(); });
}

/* ═══════════════════════════════════════════════════════════════
   VOTER IMPORT PANEL TOGGLE  (within Email tab)
   ═══════════════════════════════════════════════════════════════ */

function initVoterImportToggle() {
    const toggleBtn   = document.getElementById('toggleVoterImport');
    const importPanel = document.getElementById('voterImportSection');
    const closeBtn    = document.getElementById('closeVoterImport');
    if (!toggleBtn || !importPanel) return;

    // Use CSS class toggle (not inline style) so the base CSS display:none is
    // not accidentally re-applied when the inline style is removed.
    toggleBtn.addEventListener('click', () => {
        const open = importPanel.classList.contains('ed-pf-import--open');
        importPanel.classList.toggle('ed-pf-import--open', !open);
        toggleBtn.classList.toggle('active', !open);
    });
    closeBtn?.addEventListener('click', () => {
        importPanel.classList.remove('ed-pf-import--open');
        toggleBtn.classList.remove('active');
    });
}

/* ═══════════════════════════════════════════════════════════════
   MANUAL VOTER ENTRY TABLE
   ═══════════════════════════════════════════════════════════════ */

function initManualVoterEntry() {
    const clearBtn  = document.getElementById('voterClearRowsBtn');
    const container = document.getElementById('voterEntryBody');
    if (!container) return;

    const createEntry = (sn) => {
        const div = document.createElement('div');
        div.className = 'ed-voter-entry';
        div.innerHTML = `
            <span class="ed-pf-entry-sn">${sn}</span>
            <input type="email" class="ed-input ed-entry-email" placeholder="voter@example.com" autocomplete="off">
            <input type="text"  class="ed-input ed-entry-name"  placeholder="Full name" autocomplete="off">
            <button type="button" class="ed-pf-entry-remove ed-entry-remove" title="Remove row">
                <i class="fas fa-times"></i>
            </button>`;
        return div;
    };

    const renumber = () => {
        container.querySelectorAll('.ed-voter-entry').forEach((entry, i) => {
            const sn = entry.querySelector('.ed-pf-entry-sn');
            if (sn) sn.textContent = i + 1;
        });
    };

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            container.innerHTML = '';
            container.appendChild(createEntry(1));
            container.querySelector('.ed-entry-email')?.focus();
        });
    }

    // Delegate: remove button
    container.addEventListener('click', (e) => {
        const rmBtn = e.target.closest('.ed-entry-remove');
        if (!rmBtn) return;
        const entries = container.querySelectorAll('.ed-voter-entry');
        if (entries.length <= 1) {
            entries[0].querySelector('.ed-entry-email').value = '';
            const nameInput = entries[0].querySelector('.ed-entry-name');
            if (nameInput) nameInput.value = '';
            return;
        }
        rmBtn.closest('.ed-voter-entry').remove();
        renumber();
    });

    // Delegate: auto-add row when typing in last entry's email field
    container.addEventListener('input', (e) => {
        if (!e.target.classList.contains('ed-entry-email')) return;
        const entries = container.querySelectorAll('.ed-voter-entry');
        const lastEntry = entries[entries.length - 1];
        if (e.target.closest('.ed-voter-entry') === lastEntry && e.target.value.trim()) {
            container.appendChild(createEntry(entries.length + 1));
        }
    });
}

/** Collect non-empty manual voter entries from the entry rows. */
function collectManualEntries() {
    const container = document.getElementById('voterEntryBody');
    if (!container) return [];
    const entries = [];
    container.querySelectorAll('.ed-voter-entry').forEach(entry => {
        const email = entry.querySelector('.ed-entry-email')?.value?.trim();
        const name  = entry.querySelector('.ed-entry-name')?.value?.trim() || '';
        if (email) entries.push({ email, name });
    });
    return entries;
}

/* ═══════════════════════════════════════════════════════════════
   OFFLINE CREDENTIALS  (PDF generation)
   ═══════════════════════════════════════════════════════════════ */

function initOfflineCredentials() {
    const btn = document.getElementById('generateOfflineBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        const input = document.getElementById('offlineCount');
        const errEl = document.getElementById('offlineError');
        const count = parseInt(input?.value);

        if (!count || count < 1 || count > 500) {
            showErr(errEl, 'Enter a number between 1 and 500.');
            return;
        }
        showErr(errEl, '');

        const ok = await confirm(
            `Generate printable PDF credentials for ${count} offline voter${count !== 1 ? 's' : ''}?`
        );
        if (!ok) return;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';

        try {
            const url = getUrl('generate-offline-creds');
            const res = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: new URLSearchParams({ num_voters: count }),
            });

            if (res.ok) {
                const ct = res.headers.get('content-type') || '';
                if (ct.includes('application/pdf')) {
                    const pdfPassword = res.headers.get('X-PDF-Password') || '';
                    const blob = await res.blob();
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    const batchNum = res.headers.get('X-Batch-Number') || '';
                    const electionName = (window.electionData?.name || 'election').replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_');
                    const safeBatch = batchNum.replace(/\s+/g, '_') || `creds_${count}`;
                    a.download = `${electionName}_${safeBatch}.pdf`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(a.href);

                    if (pdfPassword) {
                        showPdfPasswordModal(pdfPassword);
                    } else {
                        notify(`PDF with ${count} offline credentials generated!`, 'success');
                        setTimeout(() => location.reload(), 1500);
                    }
                } else {
                    const data = await res.json();
                    showErr(errEl, data.error || 'Failed to generate PDF.');
                }
            } else {
                const data = await res.json().catch(() => ({}));
                showErr(errEl, data.error || `Server error (${res.status})`);
            }
        } catch (e) {
            showErr(errEl, e.message || 'Network error.');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-file-pdf"></i> Generate PDF';
        }
    });
}

/* ═══════════════════════════════════════════════════════════════
   PDF PASSWORD MODAL  (60 s countdown)
   ═══════════════════════════════════════════════════════════════ */

function showPdfPasswordModal(password) {
    const modal = document.getElementById('pdfPasswordModal');
    if (!modal) {
        // Fallback if modal not present
        notify(`PDF Password: ${password} — save it now, it won't be shown again.`, 'success', 15000);
        setTimeout(() => location.reload(), 15500);
        return;
    }

    const pwDisplay = modal.querySelector('#pdfPwDisplay');
    const copyBtn   = modal.querySelector('#pdfPwCopyBtn');
    const countdown = modal.querySelector('#pdfPwCountdown');
    const doneBtn   = modal.querySelector('#pdfPwDoneBtn');

    if (pwDisplay) pwDisplay.textContent = password;

    let seconds = 60;
    const formatTime = s => `${s}s`;
    if (countdown) countdown.textContent = formatTime(seconds);

    // BUG-08: initialise as no-op; assigned to real trapFocus after modal is shown
    let removeTrap = () => {};

    const timer = setInterval(() => {
        seconds--;
        if (countdown) countdown.textContent = formatTime(seconds);
        if (seconds <= 0) {
            clearInterval(timer);
            closePasswordModal();
        }
    }, 1000);

    const closePasswordModal = () => {
        clearInterval(timer);
        // BUG-08: release focus trap before hiding the modal
        removeTrap();
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        setTimeout(() => location.reload(), 400);
    };

    copyBtn?.addEventListener('click', () => {
        navigator.clipboard.writeText(password).then(() => {
            copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
            copyBtn.classList.add('ed-pdfpw-copied');
            setTimeout(() => {
                copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy Password';
                copyBtn.classList.remove('ed-pdfpw-copied');
            }, 2000);
        }).catch(() => {
            // Manual selection fallback
            if (pwDisplay) {
                const range = document.createRange();
                range.selectNodeContents(pwDisplay);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            }
        });
    }, { once: false });

    doneBtn?.addEventListener('click', closePasswordModal, { once: true });

    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    // BUG-08: trap keyboard focus within the modal while it is visible
    removeTrap = trapFocus(modal);
}

/* ═══════════════════════════════════════════════════════════════
   VOTER REVOKE  (single)
   ═══════════════════════════════════════════════════════════════ */

/** Format a Date object as "Mon DD, HH:MM" matching Django's date:"M d, H:i" */
function _fmtTimeline(date) {
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const h = String(date.getHours()).padStart(2, '0');
    const m = String(date.getMinutes()).padStart(2, '0');
    return `${months[date.getMonth()]} ${date.getDate()}, ${h}:${m}`;
}

/** Append a timeline event <div> to the row's .ed-timeline-cell. */
function _appendTimelineEvent(row, cssClass, label, dateStr) {
    const cell = row.querySelector('.ed-timeline-cell');
    if (!cell) return;
    // Remove the "no events" dash if present
    const nil = cell.querySelector('.ed-ts-nil');
    if (nil) nil.remove();
    const div = document.createElement('div');
    div.className = `ed-tl-event ${cssClass}`;
    div.innerHTML = `<span class="ed-tl-dot"></span><span class="ed-tl-label">${label}</span><span class="ed-tl-time">${dateStr}</span>`;
    cell.appendChild(div);
}

function initVoterRevoke() {
    const container = document.getElementById('emailVotersSection') || document.body;
    container.addEventListener('click', async (e) => {
        const btn = e.target.closest('.ed-revoke-btn');
        if (!btn) return;
        const email = btn.dataset.email || 'this voter';
        const ok = await confirm(
            `Revoke access for ${email}? You can reinstate the voter later by clicking Resend.`,
            { confirmText: 'Revoke', danger: true }
        );
        if (!ok) return;

        btn.disabled = true;
        try {
            const res = await post(btn.dataset.url);
            if (res.success !== false) {
                notify(res.message || 'Voter revoked.', 'success');
                const row = btn.closest('tr');
                if (row) {
                    // Update badge
                    const badge = row.querySelector('.ed-badge');
                    if (badge) {
                        badge.className = 'ed-badge ed-badge-orange';
                        badge.innerHTML = '<i class="fas fa-ban"></i> Revoked';
                    }
                    // Update data-status so filter works correctly
                    row.dataset.status = 'revoked';
                    // Remove only the revoke button — resend button stays so admin can reinstate
                    btn.remove();
                    // Append timeline event
                    _appendTimelineEvent(row, 'ed-tl-revoked', 'Revoked', _fmtTimeline(new Date()));
                }
            } else {
                notify(res.error || 'Failed to revoke.', 'error');
                btn.disabled = false;
            }
        } catch (err) {
            notify(err.message || 'Network error.', 'error');
            btn.disabled = false;
        }
    });
}

/* ═══════════════════════════════════════════════════════════════
   BULK ACTIONS — Revoke All, Resend All, Batch Revoke
   ═══════════════════════════════════════════════════════════════ */

function initBulkActions() {
    // Revoke All email voters
    const revokeAllBtn = document.getElementById('revokeAllBtn');
    if (revokeAllBtn) {
        revokeAllBtn.addEventListener('click', async () => {
            const ok = await confirm(
                'Revoke ALL non-voted email voters? This cannot be undone.',
                { confirmText: 'Revoke All', danger: true }
            );
            if (!ok) return;

            revokeAllBtn.disabled = true;
            revokeAllBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Revoking...';
            try {
                const res = await post(getUrl('revoke-all-voters'));
                if (res.success !== false) {
                    notify(res.message || 'All voters revoked.', 'success');
                    setTimeout(() => location.reload(), 1200);
                } else {
                    notify(res.error || 'Failed to revoke.', 'error');
                }
            } catch (err) {
                notify(err.message || 'Network error.', 'error');
            } finally {
                revokeAllBtn.disabled = false;
                revokeAllBtn.innerHTML = '<i class="fas fa-ban"></i> Revoke All';
            }
        });
    }

    // Resend All invitations
    const resendAllBtn = document.getElementById('resendAllBtn');
    if (resendAllBtn) {
        resendAllBtn.addEventListener('click', async () => {
            const ok = await confirm('Resend invitations to ALL email-invited voters? New credentials will be generated.');
            if (!ok) return;

            resendAllBtn.disabled = true;
            resendAllBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
            try {
                const res = await post(getUrl('resend-all-invitations'));
                if (res.success !== false) {
                    notify(res.message || 'All invitations resent.', 'success');
                    setTimeout(() => location.reload(), 1200);
                } else {
                    notify(res.error || 'Failed to resend.', 'error');
                }
            } catch (err) {
                notify(err.message || 'Network error.', 'error');
            } finally {
                resendAllBtn.disabled = false;
                resendAllBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Resend All';
            }
        });
    }

    // Batch revoke buttons (delegated)
    const batchSection = document.getElementById('batchVotersSection');
    if (batchSection) {
        batchSection.addEventListener('click', async (e) => {
            const btn = e.target.closest('.ed-batch-revoke-btn');
            if (!btn) return;
            const batch = btn.dataset.batch;

            const ok = await confirm(
                `Revoke all credentials in batch ${batch}? This cannot be undone.`,
                { confirmText: 'Revoke Batch', danger: true }
            );
            if (!ok) return;

            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Revoking...';
            try {
                const baseUrl = getUrl('revoke-batch-base');
                const url = baseUrl.replace('__BATCH__', encodeURIComponent(batch));
                const res = await post(url);
                if (res.success !== false) {
                    notify(res.message || `Batch ${batch} revoked.`, 'success');
                    setTimeout(() => location.reload(), 1200);
                } else {
                    notify(res.error || 'Failed to revoke batch.', 'error');
                }
            } catch (err) {
                notify(err.message || 'Network error.', 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-ban"></i> Revoke Batch';
            }
        });
    }

    // Revoke All batch credentials
    const revokeAllBatchesBtn = document.getElementById('revokeAllBatchesBtn');
    if (revokeAllBatchesBtn) {
        revokeAllBatchesBtn.addEventListener('click', async () => {
            const ok = await confirm(
                'Revoke ALL batch (PDF) credentials? This cannot be undone.',
                { confirmText: 'Revoke All Batches', danger: true }
            );
            if (!ok) return;

            revokeAllBatchesBtn.disabled = true;
            revokeAllBatchesBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Revoking...';
            try {
                const res = await post(getUrl('revoke-all-batches'));
                if (res.success !== false) {
                    notify(res.message || 'All batch credentials revoked.', 'success');
                    setTimeout(() => location.reload(), 1200);
                } else {
                    notify(res.error || 'Failed to revoke batch credentials.', 'error');
                }
            } catch (err) {
                notify(err.message || 'Network error.', 'error');
            } finally {
                revokeAllBatchesBtn.disabled = false;
                revokeAllBatchesBtn.innerHTML = '<i class="fas fa-ban"></i> Revoke All';
            }
        });
    }
}

/* ═══════════════════════════════════════════════════════════════
   EMAIL VOTER SEARCH + SORT
   ═══════════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════
   TOOLBAR — admin-home-style search + sort dropdown
   ═══════════════════════════════════════════════════════════════ */

/**
 * Admin-home-style collapsible search: icon button + expanding input.
 * Clicking the icon opens the input; Escape or clicking-away-when-empty closes it.
 */
function initVtSearch(wrapperId, inputId, filterFn) {
    const wrap  = document.getElementById(wrapperId);
    const input = document.getElementById(inputId);
    if (!wrap || !input) return;
    const toggle = wrap.querySelector('.ed-vt-search-toggle');
    if (!toggle) return;

    let debounceTimer;

    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        if (wrap.classList.contains('open')) {
            wrap.classList.remove('open');
            input.value = '';
            filterFn?.();
        } else {
            wrap.classList.add('open');
            input.focus();
        }
    });

    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => filterFn?.(), 250);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            wrap.classList.remove('open');
            input.value = '';
            filterFn?.();
        }
    });

    // Close (clearing input) when clicking outside and bar is empty
    document.addEventListener('click', (e) => {
        if (!wrap.contains(e.target) && !input.value.trim()) {
            wrap.classList.remove('open');
        }
    });
}

/**
 * Admin-home-style sort dropdown.
 * @param {string}   wrapperId  — id of .ed-vt-sort wrapper
 * @param {string}   dropdownId — id of .ed-vt-sort-dropdown
 * @param {Function} onSelect   — called with the clicked button's data-sort value
 */
function initVtSort(wrapperId, dropdownId, onSelect) {
    const wrap     = document.getElementById(wrapperId);
    const dropdown = document.getElementById(dropdownId);
    if (!wrap || !dropdown) return;
    const toggle = wrap.querySelector('.ed-vt-sort-toggle');
    if (!toggle) return;

    const open  = () => dropdown.classList.add('open');
    const close = () => dropdown.classList.remove('open');

    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.contains('open') ? close() : open();
    });

    dropdown.querySelectorAll('.ed-vt-sort-option').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.querySelectorAll('.ed-vt-sort-option').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            close();
            onSelect(btn.dataset.sort);
        });
    });

    document.addEventListener('click', (e) => {
        if (!wrap.contains(e.target)) close();
    });
}

function applyEmailVoterFilter() {
    const search = document.getElementById('emailVoterSearch');
    const q = (search?.value || '').toLowerCase().trim();
    const tbody = document.getElementById('emailVoterTableBody');
    const emptyEl = document.getElementById('emailTableEmpty');
    if (!tbody) return;

    let visibleCount = 0;
    tbody.querySelectorAll('tr').forEach(row => {
        // BUG-14: scope search to name/email only — not button labels or badge text
        const name  = (row.dataset.name  || '').toLowerCase();
        const email = (row.dataset.email || '').toLowerCase();
        const rowStatus = row.dataset.status || '';
        const textMatch = !q || name.includes(q) || email.includes(q);
        const statusMatch = _emailActiveFilter === 'all' || rowStatus === _emailActiveFilter;
        const show = textMatch && statusMatch;
        row.style.display = show ? '' : 'none';
        if (show) visibleCount++;
    });

    // Only show the "no match" message when search or filter is actually active
    const filterActive = _emailActiveFilter !== 'all' || q.length > 0;
    if (emptyEl) emptyEl.style.display = (visibleCount === 0 && filterActive) ? '' : 'none';
}

function applyEmailVoterSort(sortBy) {
    const tbody = document.getElementById('emailVoterTableBody');
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {
        switch (sortBy) {
            case 'name-asc':  return (a.cells[1]?.textContent || '').localeCompare(b.cells[1]?.textContent || '');
            case 'name-desc': return (b.cells[1]?.textContent || '').localeCompare(a.cells[1]?.textContent || '');
            case 'oldest':    return parseInt(a.dataset.invited || '0') - parseInt(b.dataset.invited || '0');
            case 'newest':
            default:          return parseInt(b.dataset.invited || '0') - parseInt(a.dataset.invited || '0');
        }
    });
    rows.forEach((row, i) => {
        tbody.appendChild(row);
        const sn = row.querySelector('.ed-entry-sn');
        if (sn) sn.textContent = i + 1;
    });
}

function handleEmailSortOption(val) {
    if (val.startsWith('filter:')) {
        _emailActiveFilter = val.slice(7);
        applyEmailVoterFilter();
    } else {
        _emailActiveFilter = 'all';
        applyEmailVoterSort(val);
        applyEmailVoterFilter();
    }
}

function handleBatchSortOption(val) {
    const tbody = document.getElementById('batchTableBody');
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {
        const aIdx = parseInt(a.querySelector('.ed-entry-sn')?.textContent || '0');
        const bIdx = parseInt(b.querySelector('.ed-entry-sn')?.textContent || '0');
        return val === 'oldest' ? aIdx - bIdx : bIdx - aIdx;
    });
    rows.forEach(row => tbody.appendChild(row));
}

/* ═══════════════════════════════════════════════════════════════
   VOTER FILE UPLOAD
   ═══════════════════════════════════════════════════════════════ */

function initVoterUpload() {
    const dropzone = document.getElementById('voterDropzone');
    const fileInput = document.getElementById('voterFileInput');
    const progressWrap = document.getElementById('voterUploadProgress');
    const progressFill = document.getElementById('voterProgressFill');
    const progressText = document.getElementById('voterProgressText');
    const errEl = document.getElementById('voterUploadError');

    if (!dropzone || !fileInput) return;

    // Click anywhere on the dropzone (except the label which natively triggers the input) to open file picker
    dropzone.addEventListener('click', (e) => {
        if (!e.target.closest('label')) fileInput.click();
    });

    ['dragenter', 'dragover'].forEach(evt => {
        dropzone.addEventListener(evt, e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
    });
    ['dragleave', 'drop'].forEach(evt => {
        dropzone.addEventListener(evt, e => { e.preventDefault(); dropzone.classList.remove('drag-over'); });
    });
    dropzone.addEventListener('drop', e => {
        const file = e.dataTransfer?.files?.[0];
        if (file) uploadVoterFile(file, progressWrap, progressFill, progressText, errEl);
    });

    fileInput.addEventListener('change', () => {
        const file = fileInput.files?.[0];
        if (file) uploadVoterFile(file, progressWrap, progressFill, progressText, errEl);
    });
}

async function uploadVoterFile(file, progressWrap, progressFill, progressText, errEl) {
    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) { showErr(errEl, 'File exceeds 5 MB limit.'); return; }

    const allowed = ['.csv', '.xlsx', '.xls'];
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (!allowed.includes(ext)) { showErr(errEl, 'Only CSV and Excel files are accepted.'); return; }

    showErr(errEl, '');
    if (progressWrap) progressWrap.style.display = 'block';
    if (progressFill) progressFill.style.width = '30%';
    if (progressText) progressText.textContent = 'Uploading...';

    const fd = new FormData();
    fd.append('voter_file', file);

    try {
        if (progressFill) progressFill.style.width = '60%';
        // Use parse-only endpoint: validates file but does NOT create credentials.
        // Returns the voter list so the frontend can populate the manual entry form.
        const res = await post(getUrl('parse-voter-file'), fd);
        if (progressFill) progressFill.style.width = '100%';

        if (res.success !== false) {
            const voters = res.voters || [];
            const count = res.count || voters.length;
            if (progressText) progressText.textContent = `Parsed ${count} voter(s)`;

            // Populate manual entry form with imported voters
            populateVoterEntries(voters);

            // Close the import panel
            const importSection = document.getElementById('voterImportSection');
            const toggleBtn = document.getElementById('toggleVoterImport');
            if (importSection) importSection.classList.remove('ed-pf-import--open');
            if (toggleBtn) toggleBtn.classList.remove('active');

            // Reset progress after a short delay
            setTimeout(() => {
                if (progressWrap) progressWrap.style.display = 'none';
                if (progressFill) progressFill.style.width = '0%';
            }, 1500);

            if (res.errors && res.errors.length > 0) {
                notify(`${count} voter(s) ready. ${res.errors.length} row(s) had errors and were skipped. Review entries and click Send Invitations.`, 'warning', 6000);
            } else {
                notify(`${count} voter(s) ready. Review the entries below and click Send Invitations.`, 'success', 5000);
            }
        } else {
            showErr(errEl, res.error || res.message || 'Import failed.');
            if (progressWrap) progressWrap.style.display = 'none';
        }
    } catch (e) {
        showErr(errEl, e.message || 'Upload failed.');
        if (progressWrap) progressWrap.style.display = 'none';
    }
}

/**
 * Populate the manual voter entry form with a list of {email, name} objects.
 * Clears existing entries, creates one row per voter, and adds a blank row at end.
 */
function populateVoterEntries(voters) {
    const container = document.getElementById('voterEntryBody');
    if (!container) return;

    // Clear existing entries
    container.innerHTML = '';

    const createRow = (sn, email, name) => {
        const div = document.createElement('div');
        div.className = 'ed-voter-entry';
        div.innerHTML = `
            <span class="ed-pf-entry-sn">${sn}</span>
            <input type="email" class="ed-input ed-entry-email" placeholder="voter@example.com" autocomplete="off" value="${escapeHtml(email || '')}">
            <input type="text"  class="ed-input ed-entry-name"  placeholder="Full name" autocomplete="off" value="${escapeHtml(name || '')}">
            <button type="button" class="ed-pf-entry-remove ed-entry-remove" title="Remove row">
                <i class="fas fa-times"></i>
            </button>`;
        return div;
    };

    // Add one row per imported voter
    voters.forEach((voter, i) => {
        container.appendChild(createRow(i + 1, voter.email || '', voter.name || ''));
    });

    // Always append one blank row at the end so the user can add more
    container.appendChild(createRow(voters.length + 1, '', ''));

    // Scroll the entry form into view
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ═══════════════════════════════════════════════════════════════
   SEND INVITATIONS  +  DUPLICATE RESOLUTION
   ═══════════════════════════════════════════════════════════════ */

function initSendInvitations() {
    const btn = document.getElementById('sendInvitationsBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        const manualVoters = collectManualEntries();
        const errEl = document.getElementById('voterEntryError');

        if (manualVoters.length > 0) {
            const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            const invalid = manualVoters.filter(v => !emailRe.test(v.email));
            if (invalid.length > 0) {
                showErr(errEl, `Invalid email${invalid.length > 1 ? 's' : ''}: ${invalid.map(v => v.email).join(', ')}`);
                return;
            }
            showErr(errEl, '');
        }

        const analysis = analyzeVoterTable();

        if (manualVoters.length === 0 && analysis.pending === 0 &&
            analysis.sentVoters.length === 0) {
            notify('No voters to send invitations to.', 'info');
            return;
        }

        if (analysis.sentVoters.length > 0) {
            _pendingManualVoters = manualVoters;
            showDuplicateModal(analysis);
            return;
        }

        const parts = [];
        if (manualVoters.length > 0) parts.push(`${manualVoters.length} new`);
        if (analysis.pending > 0) parts.push(`${analysis.pending} pending`);
        const summary = parts.join(' + ') + ` voter${(manualVoters.length + analysis.pending) !== 1 ? 's' : ''}`;

        const ok = await confirm(`Send email invitations to ${summary}?`);
        if (!ok) return;

        if (manualVoters.length > 0) {
            await executeDuplicateResolve(analysis, [], manualVoters);
        } else {
            await executeSendInvitations(btn);
        }
    });
}

/** Analyse the email voter table to categorise voters by status. */
function analyzeVoterTable() {
    const table = document.getElementById('emailVoterTable');
    const result = {
        pending: 0, sent: 0, voted: 0, revoked: 0,
        sentVoters: [], nameDuplicates: [],
    };
    if (!table) return result;

    const rows = table.querySelectorAll('tbody tr');
    const nameMap = {};

    rows.forEach(row => {
        const email = row.querySelector('.ed-voter-email')?.textContent?.trim() || '';
        const nameCell = row.cells?.[1]?.textContent?.trim() || '';
        const rowStatus = (row.dataset.status || '').toLowerCase();
        const voterId = row.dataset.voterId;

        if (rowStatus === 'revoked') { result.revoked++; }
        else if (rowStatus === 'voted') { result.voted++; }
        else if (rowStatus === 'invited') {
            result.sent++;
            result.sentVoters.push({ id: voterId, email, name: nameCell });
        } else {
            // 'failed', 'pending', or empty — treat as unsent (will receive invitation)
            result.pending++;
        }

        const nameLower = nameCell.toLowerCase();
        if (nameLower && nameLower !== '—' && nameLower !== '-') {
            nameMap[nameLower] = nameMap[nameLower] || [];
            nameMap[nameLower].push({ id: voterId, email, name: nameCell });
        }
    });

    result.nameDuplicates = Object.entries(nameMap)
        .filter(([, entries]) => entries.length > 1)
        .map(([, entries]) => ({ name: entries[0].name, entries }));

    return result;
}

/* ─── Duplicate resolution modal ─── */

function showDuplicateModal(analysis) {
    const modal = document.getElementById('dupModal');
    const body = document.getElementById('dupModalBody');
    if (!modal || !body) return;

    if (_dupAbort) _dupAbort.abort();
    _dupAbort = new AbortController();
    const signal = _dupAbort.signal;

    let html = '';

    // Name duplicates (informational)
    if (analysis.nameDuplicates.length > 0) {
        html += `
        <div class="ed-dup-section ed-dup-section-info">
            <div class="ed-dup-section-header">
                <i class="fas fa-users"></i>
                <div>
                    <h3>Duplicate Names</h3>
                    <p>${analysis.nameDuplicates.length} name${analysis.nameDuplicates.length !== 1 ? 's' : ''} appear${analysis.nameDuplicates.length === 1 ? 's' : ''} more than once</p>
                </div>
            </div>
            <div class="ed-dup-note">
                <i class="fas fa-info-circle"></i>
                These voters share the same name but have different email addresses. Review if needed.
            </div>
            <div class="ed-dup-items">
                ${analysis.nameDuplicates.map(d => `
                    <div class="ed-dup-group">
                        <div class="ed-dup-group-label">${escapeHtml(d.name)}</div>
                        ${d.entries.map(e => `
                            <div class="ed-dup-group-entry">
                                <i class="fas fa-user"></i> ${escapeHtml(e.email)}
                            </div>
                        `).join('')}
                    </div>
                `).join('')}
            </div>
        </div>`;
    }

    // Already-invited voters
    if (analysis.sentVoters.length > 0) {
        html += `
        <div class="ed-dup-section ed-dup-section-warn">
            <div class="ed-dup-section-header">
                <i class="fas fa-envelope"></i>
                <div>
                    <h3>Already Invited</h3>
                    <p>${analysis.sentVoters.length} voter${analysis.sentVoters.length !== 1 ? 's have' : ' has'} already received invitations</p>
                </div>
            </div>
            <div class="ed-dup-bulk-actions">
                <button class="ed-dup-bulk-btn" data-action="reinvite" data-group="sent">
                    <i class="fas fa-redo"></i> Reinvite All
                </button>
                <button class="ed-dup-bulk-btn active" data-action="skip" data-group="sent">
                    <i class="fas fa-forward"></i> Skip All
                </button>
            </div>
            <div class="ed-dup-items" id="dupSentList">
                ${analysis.sentVoters.map((v, i) => `
                    <div class="ed-dup-item" data-credential-id="${v.id}">
                        <div class="ed-dup-item-info">
                            <span class="ed-dup-item-email">${escapeHtml(v.email)}</span>
                            ${v.name && v.name !== '—' ? `<span class="ed-dup-item-name">${escapeHtml(v.name)}</span>` : ''}
                        </div>
                        <div class="ed-dup-toggle">
                            <label class="ed-dup-toggle-opt">
                                <input type="radio" name="sent-${i}" value="reinvite"> Reinvite
                            </label>
                            <label class="ed-dup-toggle-opt">
                                <input type="radio" name="sent-${i}" value="skip" checked> Skip
                            </label>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }

    // Summary
    html += `
    <div class="ed-dup-summary">
        <div class="ed-dup-summary-item">
            <i class="fas fa-paper-plane"></i>
            <span><strong>${analysis.pending}</strong> pending voter${analysis.pending !== 1 ? 's' : ''} will receive new invitations</span>
        </div>
        ${analysis.voted > 0 ? `
        <div class="ed-dup-summary-item ed-dup-summary-muted">
            <i class="fas fa-check-circle"></i>
            <span><strong>${analysis.voted}</strong> voter${analysis.voted !== 1 ? 's have' : ' has'} already voted (not affected)</span>
        </div>` : ''}
    </div>`;

    body.innerHTML = html;

    // Wire bulk-action buttons
    body.querySelectorAll('.ed-dup-bulk-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const value = btn.dataset.action;
            const group = btn.dataset.group;
            const listId = group === 'sent' ? 'dupSentList' : null;
            const list = listId ? document.getElementById(listId) : null;
            if (list) list.querySelectorAll(`input[value="${value}"]`).forEach(r => { r.checked = true; });
            btn.parentElement.querySelectorAll('.ed-dup-bulk-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        }, { signal });
    });

    let _removeTrap = null;

    const closeModal = () => {
        _dupAbort?.abort();
        if (_removeTrap) { _removeTrap(); _removeTrap = null; }
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    };

    document.getElementById('dupCancelBtn')?.addEventListener('click', closeModal, { signal });
    document.getElementById('dupModalClose')?.addEventListener('click', closeModal, { signal });
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(); }, { signal });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); }, { signal });

    document.getElementById('dupConfirmBtn')?.addEventListener('click', async () => {
        const reinviteIds = collectReinviteIds(analysis);
        const manualVoters = _pendingManualVoters || [];
        closeModal();
        await executeDuplicateResolve(analysis, reinviteIds, manualVoters);
        _pendingManualVoters = null;
    }, { signal });

    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    _removeTrap = trapFocus(modal);
}

function collectReinviteIds(analysis) {
    const ids = [];
    analysis.sentVoters.forEach((v, i) => {
        if (document.querySelector(`input[name="sent-${i}"]:checked`)?.value === 'reinvite') {
            ids.push(parseInt(v.id));
        }
    });
    return ids;
}

async function executeDuplicateResolve(analysis, reinviteIds, manualVoters = []) {
    const btn = document.getElementById('sendInvitationsBtn');
    const resetBtn = () => {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-paper-plane"></i><span>Send Invitations</span>'; }
    };
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...'; }

    try {
        let totalSent = 0, totalFailed = 0;

        if (analysis.pending > 0 && manualVoters.length === 0 && reinviteIds.length === 0) {
            const res = await post(getUrl('send-invitations'));
            // Invitations are queued via Celery — response gives success/message only.
            if (res.success !== false) { totalSent += analysis.pending; }
        }

        if (manualVoters.length > 0 || reinviteIds.length > 0) {
            // BUG-05: use two-step fetch so server errors surface rather than
            // silently becoming "No invitations were sent."
            const raw = await fetch(getUrl('resolve-and-send'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({
                    voters: manualVoters,
                    reinvite: reinviteIds,
                    skip: [],
                }),
            });
            const res = await raw.json().catch(() => ({
                success: false,
                error: `Server error (${raw.status})`,
            }));
            if (res.success === false) {
                notify(res.error || 'Failed to send invitations.', 'error');
                resetBtn();
                return;
            }
            totalSent  += res.sent  || 0;
            totalFailed += res.failed || 0;
        }

        if (totalFailed > 0) {
            notify(`Sent: ${totalSent}, Failed: ${totalFailed}`, totalSent > 0 ? 'warning' : 'error');
        } else if (totalSent > 0) {
            notify(`${totalSent} invitation${totalSent !== 1 ? 's' : ''} sent successfully!`, 'success');
        } else {
            notify('No invitations were sent.', 'info');
        }
        setTimeout(() => location.reload(), 1200);
    } catch (e) {
        notify(e.message || 'Network error.', 'error');
        resetBtn();
    }
}

async function executeSendInvitations(btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
    try {
        const res = await post(getUrl('send-invitations'));
        if (res.success !== false) {
            notify(res.message || 'Invitations sent!', 'success');
            setTimeout(() => location.reload(), 1200);
        } else {
            notify(res.error || 'Failed to send.', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-paper-plane"></i><span>Send Invitations</span>';
        }
    } catch (e) {
        notify(e.message || 'Network error.', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-paper-plane"></i><span>Send Invitations</span>';
    }
}

/* ═══════════════════════════════════════════════════════════════
   REGENERATE BUTTONS
   ═══════════════════════════════════════════════════════════════ */

function initRegenButtons() {
    // Use event delegation for dynamically rendered rows
    const container = document.getElementById('emailVotersSection');
    if (!container) return;
    container.addEventListener('click', async (e) => {
        const btn = e.target.closest('.ed-regen-btn');
        if (!btn) return;

        const row = btn.closest('tr');
        const wasRevoked = row?.dataset.status === 'revoked';
        const confirmMsg = wasRevoked
            ? 'Reinstate this voter? Their access will be restored and new credentials will be sent.'
            : 'Resend credentials for this voter? Their old credentials will be invalidated and new ones will be sent.';

        const ok = await confirm(confirmMsg);
        if (!ok) return;

        btn.disabled = true;
        try {
            const res = await post(btn.dataset.url);
            if (res.success !== false) {
                notify('Credentials resent.', 'success');
                if (row) {
                    // Append timeline "Resent" event
                    _appendTimelineEvent(row, 'ed-tl-resent', 'Resent', _fmtTimeline(new Date()));

                    // If the voter was revoked, update their status back to "Invited"
                    if (res.was_revoked) {
                        const badge = row.querySelector('.ed-badge');
                        if (badge) {
                            badge.className = 'ed-badge ed-badge-blue';
                            badge.innerHTML = '<i class="fas fa-envelope"></i> Invited';
                        }
                        row.dataset.status = 'invited';

                        // Add the revoke button back next to the resend button
                        const actCell = row.querySelector('.ed-voter-actions');
                        if (actCell && row.dataset.revokeUrl) {
                            const revokeBtn = document.createElement('button');
                            revokeBtn.className = 'ed-btn-icon ed-revoke-btn';
                            revokeBtn.dataset.email = row.dataset.email || '';
                            revokeBtn.dataset.url = row.dataset.revokeUrl;
                            revokeBtn.title = 'Revoke access';
                            revokeBtn.innerHTML = '<i class="fas fa-ban"></i>';
                            actCell.appendChild(revokeBtn);
                        }
                    }
                }
            } else {
                notify(res.error || 'Failed to resend.', 'error');
            }
        } catch (err) {
            notify(err.message || 'Network error.', 'error');
        } finally {
            btn.disabled = false;
        }
    });
}

/* ═══════════════════════════════════════════════════════════════
   INVITATION FAILURE POPUP
   ═══════════════════════════════════════════════════════════════ */

async function fetchAndShowFailures() {
    const btn  = document.getElementById('viewFailuresBtn');
    const url  = btn?.dataset.failedUrl || getUrl('failed-invitations');
    if (!url) { notify('Failure details URL not available.', 'error'); return; }

    const origHtml = btn?.innerHTML;
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }

    try {
        const res = await fetch(url, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!res.ok) throw new Error(`Server error (${res.status})`);
        const data = await res.json();
        if (data.total > 0) {
            showFailureModal(data.failures || []);
        } else {
            notify('No invitation failures found — all deliveries succeeded.', 'success');
        }
    } catch (e) {
        notify(e.message || 'Could not load failure details.', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
    }
}

function showFailureModal(failures) {
    // Remove stale modal if present
    document.getElementById('inviteFailureModal')?.remove();

    const ERROR_LABELS = {
        INVALID_FORMAT:  'Invalid Email Format',
        SMTP_REJECTED:   'Email Rejected',
        SMTP_ERROR:      'SMTP Error',
        RATE_LIMITED:    'Rate Limited',
        PROVIDER_ERROR:  'Provider Error',
        UNKNOWN:         'Unknown Error',
    };

    const rows = failures.map((f, i) => {
        const label = f.error_label || ERROR_LABELS[f.error_code] || f.error_code || 'Unknown Error';
        return `
        <tr>
            <td class="ed-entry-sn">${i + 1}</td>
            <td class="ed-voter-email">${escapeHtml(f.voter_email || '')}</td>
            <td>${escapeHtml(f.voter_name || '—')}</td>
            <td><span class="ed-badge ed-badge-yellow" style="white-space:nowrap"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(label)}</span></td>
            <td style="max-width:260px;word-break:break-word;font-size:.82rem;color:var(--text-secondary)">${escapeHtml(f.error_message || '—')}</td>
        </tr>`;
    }).join('');

    const modal = document.createElement('div');
    modal.id = 'inviteFailureModal';
    modal.className = 'ed-modal active';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'inviteFailureTitle');
    modal.setAttribute('aria-hidden', 'false');
    modal.innerHTML = `
        <div class="ed-modal-box" style="max-width:820px">
            <div class="ed-modal-header">
                <h3 class="ed-modal-title" id="inviteFailureTitle">
                    <i class="fas fa-exclamation-triangle" style="color:var(--apple-yellow,#ffcc00)"></i>
                    Invitation Delivery Failures (${failures.length})
                </h3>
                <button type="button" class="ed-modal-close" id="inviteFailureClose" aria-label="Close">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="ed-modal-body" style="padding:0;overflow-x:auto;max-height:60vh;overflow-y:auto">
                <table class="ed-table" style="font-size:.88rem">
                    <thead>
                        <tr>
                            <th class="ed-th-sn">#</th>
                            <th>Email</th>
                            <th>Name</th>
                            <th>Error Type</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <div class="ed-modal-footer">
                <p style="font-size:.8rem;color:var(--text-tertiary);margin:0 auto 0 0">
                    Use <strong>Resend</strong> on individual voters or <strong>Resend All</strong> to retry failures.
                </p>
                <button type="button" class="ed-btn ed-btn-secondary" id="inviteFailureDismiss">Dismiss</button>
            </div>
        </div>`;

    document.body.style.overflow = 'hidden';
    document.body.appendChild(modal);

    // BUG-15: store cleanup so keyboard focus is released when the modal closes
    const removeTrap = trapFocus(modal);
    const close = () => {
        removeTrap();
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        setTimeout(() => modal.remove(), 300);
    };

    modal.querySelector('#inviteFailureClose')?.addEventListener('click', close);
    modal.querySelector('#inviteFailureDismiss')?.addEventListener('click', close);
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    const onEsc = e => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onEsc); } };
    document.addEventListener('keydown', onEsc);
}


/* ═══════════════════════════════════════════════════════════════
   ACCESS REQUESTS
   ═══════════════════════════════════════════════════════════════ */

function initAccessRequests() {
    const section = document.getElementById('accessRequestsSection');
    if (!section) return;

    const listUrl = section.dataset.url;
    const approveUrlTemplate = section.dataset.approveUrlTemplate || '';
    const rejectUrlTemplate = section.dataset.rejectUrlTemplate || '';
    const toggleBtn = document.getElementById('arToggleBtn');
    const panel = document.getElementById('arPanel');
    const tbody = document.getElementById('arTableBody');
    const emptyState = document.getElementById('arEmptyState');
    const tableWrap = section.querySelector('.ed-table-wrap');
    const toolbar = section.querySelector('.ed-ar-toolbar');
    const badge = document.getElementById('accessRequestCount');
    const searchInput = document.getElementById('arSearchInput');
    const approveAllBtn = document.getElementById('arApproveAllBtn');
    const rejectAllBtn = document.getElementById('arRejectAllBtn');

    let allRequests = [];
    let arSort = 'newest';
    let arSearchQuery = '';

    // Copy access link button
    const copyLinkBtn = document.getElementById('arCopyLinkBtn');
    const accessLinkEl = document.getElementById('electionAccessLink');
    if (copyLinkBtn && accessLinkEl) {
        copyLinkBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(accessLinkEl.textContent.trim());
            copyLinkBtn.innerHTML = '<i class="fas fa-check"></i>';
            setTimeout(() => { copyLinkBtn.innerHTML = '<i class="fas fa-copy"></i>'; }, 2000);
        });
    }

    // Always start collapsed — force it regardless of any cached DOM state
    if (panel) panel.style.display = 'none';
    if (toggleBtn) toggleBtn.classList.remove('open');

    // Toggle panel
    toggleBtn?.addEventListener('click', () => {
        const open = panel.style.display !== 'none';
        panel.style.display = open ? 'none' : '';
        toggleBtn.classList.toggle('open', !open);
    });

    // Eagerly load data so the badge count stays accurate
    loadRequests();

    // Search
    initVtSearch('arVtSearch', 'arSearchInput', () => {
        arSearchQuery = (searchInput?.value || '').toLowerCase().trim();
        renderTable();
    });
    // Sort dropdown (no filter — table only shows pending)
    initVtSort('arVtSort', 'arSortDropdown', option => {
        arSort = option;
        renderTable();
    });

    async function loadRequests() {
        try {
            const res = await fetch(listUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!res.ok) { showEmpty('Failed to load requests.'); return; }
            const data = await res.json();
            if (!data.success) { showEmpty('Failed to load requests.'); return; }
            // Only keep pending requests (approved move to email voters, rejected are deleted)
            allRequests = (data.requests || []).filter(r => r.status === 'pending');
            renderTable();
        } catch {
            showEmpty('Failed to load requests.');
        }
    }

    function showEmpty(msg) {
        if (tableWrap) tableWrap.style.display = 'none';
        if (toolbar) toolbar.style.display = 'none';
        if (emptyState) {
            emptyState.style.display = '';
            emptyState.querySelector('p').textContent = msg || 'No pending access requests.';
        }
        if (badge) badge.textContent = '0';
    }

    function getFilteredRequests() {
        let list = [...allRequests];
        // Search
        if (arSearchQuery) {
            list = list.filter(r =>
                (r.name || '').toLowerCase().includes(arSearchQuery) ||
                (r.email || '').toLowerCase().includes(arSearchQuery)
            );
        }
        // Sort
        list.sort((a, b) => {
            switch (arSort) {
                case 'oldest': return new Date(a.created_at) - new Date(b.created_at);
                case 'name-asc': return (a.name || '').localeCompare(b.name || '');
                case 'name-desc': return (b.name || '').localeCompare(a.name || '');
                default: return new Date(b.created_at) - new Date(a.created_at); // newest
            }
        });
        return list;
    }

    function renderTable() {
        if (badge) badge.textContent = String(allRequests.length);

        if (allRequests.length === 0) { showEmpty(); return; }
        if (tableWrap) tableWrap.style.display = '';
        if (toolbar) toolbar.style.display = '';
        if (emptyState) emptyState.style.display = 'none';

        const filtered = getFilteredRequests();

        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No requests match the current search.</td></tr>';
            return;
        }

        tbody.innerHTML = filtered.map((r, i) => {
            const requestedAt = r.created_at
                ? new Date(r.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                : '\u2014';

            return `<tr data-request-id="${r.id}">
                <td class="ed-entry-sn">${i + 1}</td>
                <td>${escapeHtml(r.name)}</td>
                <td class="ed-voter-email">${escapeHtml(r.email)}</td>
                <td class="ed-timeline-cell">
                    <div class="ed-tl-event ed-tl-invited">
                        <span class="ed-tl-dot"></span>
                        <span class="ed-tl-time">${requestedAt}</span>
                    </div>
                </td>
                <td class="ed-voter-actions">
                    <button class="ed-btn-icon ed-btn-icon--green ar-approve-btn" data-id="${r.id}" title="Approve">
                        <i class="fas fa-check"></i>
                    </button>
                    <button class="ed-btn-icon ed-btn-icon--danger ar-reject-btn" data-id="${r.id}" title="Reject">
                        <i class="fas fa-times"></i>
                    </button>
                </td>
            </tr>`;
        }).join('');

        // Bind action handlers
        tbody.querySelectorAll('.ar-approve-btn').forEach(btn =>
            btn.addEventListener('click', () => handleAccessAction(btn.dataset.id, 'approve'))
        );
        tbody.querySelectorAll('.ar-reject-btn').forEach(btn =>
            btn.addEventListener('click', () => handleAccessAction(btn.dataset.id, 'reject'))
        );
    }

    async function handleAccessAction(requestId, action, { reloadAfterApprove = true } = {}) {
        const urlTemplate = action === 'approve' ? approveUrlTemplate : rejectUrlTemplate;
        const url = urlTemplate.replace('/0/', `/${requestId}/`);
        try {
            const result = await post(url, {});
            if (result.success) {
                notify(result.message || `Request ${action}d.`, 'success');
                // Remove from local array (approved → email voters table; rejected → deleted)
                allRequests = allRequests.filter(r => r.id !== Number(requestId));
                renderTable();
                // If approved, reload page after a short delay so the email voters table refreshes
                if (action === 'approve' && reloadAfterApprove) {
                    setTimeout(() => window.location.reload(), 1500);
                }
            } else {
                notify(result.message || `Failed to ${action} request.`, 'error');
            }
        } catch {
            notify(`Failed to ${action} request.`, 'error');
        }
    }

    // Bulk approve all pending
    approveAllBtn?.addEventListener('click', async () => {
        if (!allRequests.length) { notify('No pending requests to approve.', 'info'); return; }
        const ok = await confirm(`Approve all ${allRequests.length} pending request(s)?`, { confirmText: 'Approve All' });
        if (!ok) return;
        const ids = allRequests.map(r => r.id);
        for (const id of ids) {
            await handleAccessAction(id, 'approve', { reloadAfterApprove: false });
        }
        // Single reload after all approvals complete — prevents multiple reload timers
        // racing against in-flight API calls when N > 1
        setTimeout(() => window.location.reload(), 1500);
    });

    // Bulk reject all pending
    rejectAllBtn?.addEventListener('click', async () => {
        if (!allRequests.length) { notify('No pending requests to reject.', 'info'); return; }
        const ok = await confirm(`Reject all ${allRequests.length} pending request(s)?`, { confirmText: 'Reject All', danger: true });
        if (!ok) return;
        const ids = allRequests.map(r => r.id);
        for (const id of ids) {
            await handleAccessAction(id, 'reject');
        }
    });
}

/* ═══════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════ */

/** Initialise the entire Voters tab. */
export function initVotersTab() {
    initInviteToggle();
    initVoterImportToggle();
    initManualVoterEntry();
    // Admin-home-style toolbar for email voters table
    initVtSearch('emailVtSearch', 'emailVoterSearch', applyEmailVoterFilter);
    initVtSort('emailVtSort', 'emailSortDropdown', handleEmailSortOption);
    // Admin-home-style toolbar for PDF credentials table
    initVtSearch('batchVtSearch', 'batchSearch', () => {
        const q = document.getElementById('batchSearch')?.value.toLowerCase().trim() || '';
        const tbody = document.getElementById('batchTableBody');
        if (!tbody) return;
        tbody.querySelectorAll('tr').forEach(row => {
            row.style.display = (!q || row.textContent.toLowerCase().includes(q)) ? '' : 'none';
        });
    });
    initVtSort('batchVtSort', 'batchSortDropdown', handleBatchSortOption);
    initVoterUpload();
    initSendInvitations();
    initOfflineCredentials();
    initRegenButtons();
    initVoterRevoke();
    initBulkActions();

    // Wire invitation-failure details button (shown only when voter_stats.failed > 0)
    const viewFailuresBtn = document.getElementById('viewFailuresBtn');
    if (viewFailuresBtn) {
        viewFailuresBtn.addEventListener('click', fetchAndShowFailures);
    }

    // Ensure empty-state message is correctly hidden on initial load
    // (guards against any stale display state before user interaction)
    applyEmailVoterFilter();

    // Load access requests if section exists
    initAccessRequests();

    // ── SSE live update listeners ──
    initVoterSSEListeners();
}

/* ═══════════════════════════════════════════════════════════════
   SSE: Real-time voter tab updates
   ═══════════════════════════════════════════════════════════════ */

function initVoterSSEListeners() {
    let _staleShown = false;

    function showStaleBar() {
        if (_staleShown) return;
        _staleShown = true;
        const bar = document.createElement('div');
        bar.className = 'ed-sse-stale-bar';
        bar.innerHTML = '<span>Voter data has been updated.</span> '
            + '<button class="ed-sse-stale-refresh" onclick="location.reload()">Refresh now</button>';
        bar.style.cssText = 'background:var(--accent,#3b82f6);color:#fff;'
            + 'text-align:center;padding:0.5rem 1rem;border-radius:8px;'
            + 'margin:0.5rem 0;font-size:0.92rem;display:flex;align-items:center;'
            + 'justify-content:center;gap:0.5rem;animation:fadeIn 0.3s ease;';
        const refreshBtn = bar.querySelector('button');
        refreshBtn.style.cssText = 'background:rgba(255,255,255,0.2);'
            + 'border:1px solid rgba(255,255,255,0.4);color:#fff;'
            + 'border-radius:6px;padding:0.25rem 0.75rem;cursor:pointer;font-size:0.85rem;';
        // Insert at top of voters panel
        const panel = document.getElementById('panel-voters');
        if (panel) panel.insertBefore(bar, panel.firstChild);
    }

    // When another admin session modifies voters, show refresh bar
    document.addEventListener('sse:voter_update', (e) => {
        const detail = e.detail || {};
        const action = detail.action || '';
        // Show stale bar for server-side mutations not initiated by this tab
        if (['revoked', 'bulk_revoked', 'regenerated', 'bulk_invited',
             'batch_revoked', 'all_batches_revoked'].includes(action)) {
            showStaleBar();
        }
    });

    // When an access request is approved/rejected/new, refresh the access section
    document.addEventListener('sse:access_request', (e) => {
        const detail = e.detail || {};
        if (detail.action === 'new') {
            // Show notification for new access request
            const { notify } = window.ElectON || {};
            if (typeof notify === 'function') {
                notify('New voter access request received!', 'info');
            }
        }
        // Reload access-requests section from server
        const section = document.getElementById('accessRequestsSection');
        if (section) showStaleBar();
    });
}
