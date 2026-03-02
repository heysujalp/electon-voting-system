/**
 * dashboard/posts.js — Positions tab logic.
 * Handles multi-row add (dynamic row injection like voters tab),
 * delete, and drag-and-drop reorder.
 */
import { getUrl, post, showErr, notify, confirm, getCSRFToken, escapeHtml, refreshStats } from './helpers.js';

/* ─── URL helper for per-entity endpoints (posts & candidates) ─── */
function entityUrl(key, id) {
    return getUrl(key).replace('/0/', `/${id}/`);
}

/* ══════════════════════════════════════════════════════════════
   ENTRY ROW FACTORY — reusable multi-row add pattern
══════════════════════════════════════════════════════════════ */

/**
 * Creates a set of entry-row management functions for a given container.
 *
 * @param {Object} cfg
 * @param {string} cfg.containerId     – DOM id of the entries container
 * @param {string} cfg.rowSel          – CSS class selector for a row (e.g. '.ed-pf-entry')
 * @param {string} cfg.snSel           – CSS selector for serial-number element within a row
 * @param {string} cfg.nameInputSel    – CSS class for the primary name input
 * @param {string} cfg.removeBtnSel    – CSS class for the remove button
 * @param {Function} cfg.createRow     – (sn: number) => HTMLElement
 * @param {Function} cfg.collectRow    – (row: HTMLElement) => object|null  (null = skip)
 * @param {Function} cfg.clearRow      – (row: HTMLElement) => void
 * @param {string} cfg.btnTextId       – DOM id for the add-button text element
 * @param {string} cfg.singular        – e.g. 'Add Position'
 * @param {string} cfg.plural          – e.g. 'Add Positions'
 * @param {Function} [cfg.onNewRow]    – optional callback after a new row is auto-added
 * @param {Function} [cfg.onReset]     – optional extra callback after reset
 */
function createEntryRowManager(cfg) {
    const getContainer = () => document.getElementById(cfg.containerId);

    function renumber() {
        const c = getContainer();
        if (!c) return;
        c.querySelectorAll(cfg.rowSel).forEach((row, i) => {
            const sn = row.querySelector(cfg.snSel);
            if (sn) sn.textContent = i + 1;
        });
    }

    function countFilled() {
        const c = getContainer();
        if (!c) return 0;
        let n = 0;
        c.querySelectorAll(cfg.nameInputSel).forEach(inp => { if (inp.value.trim()) n++; });
        return n;
    }

    function updateBtnText() {
        const el = document.getElementById(cfg.btnTextId);
        if (!el) return;
        el.textContent = countFilled() > 1 ? cfg.plural : cfg.singular;
    }

    function collect() {
        const c = getContainer();
        if (!c) return [];
        const out = [];
        c.querySelectorAll(cfg.rowSel).forEach(row => {
            const item = cfg.collectRow(row);
            if (item) out.push(item);
        });
        return out;
    }

    function reset() {
        const c = getContainer();
        if (!c) return;
        c.innerHTML = '';
        c.appendChild(cfg.createRow(1));
        cfg.onNewRow?.();
        const inp = c.querySelector(cfg.nameInputSel);
        if (inp) inp.focus();
        updateBtnText();
        cfg.onReset?.();
    }

    function init() {
        const c = getContainer();
        if (!c) return;

        c.addEventListener('input', (e) => {
            if (!e.target.matches(cfg.nameInputSel)) return;
            const rows = c.querySelectorAll(cfg.rowSel);
            const lastRow = rows[rows.length - 1];
            if (e.target.closest(cfg.rowSel) === lastRow && e.target.value.trim()) {
                c.appendChild(cfg.createRow(rows.length + 1));
                cfg.onNewRow?.();
            }
            updateBtnText();
        });

        c.addEventListener('click', (e) => {
            const removeBtn = e.target.closest(cfg.removeBtnSel);
            if (!removeBtn) return;
            const row = removeBtn.closest(cfg.rowSel);
            if (!row) return;
            const allRows = c.querySelectorAll(cfg.rowSel);
            if (allRows.length <= 1) {
                cfg.clearRow(row);
            } else {
                row.remove();
                renumber();
            }
            updateBtnText();
        });
    }

    return { renumber, countFilled, updateBtnText, collect, reset, init };
}

/* ── Position entry rows ── */

function _createPositionRow(sn) {
    const div = document.createElement('div');
    div.className = 'ed-pf-entry';
    div.innerHTML = `
        <span class="ed-pf-entry-sn">${sn}</span>
        <input type="text" class="ed-input ed-pf-entry-name"
               placeholder="e.g. President, Secretary…"
               maxlength="255" autocomplete="off">
        <button type="button" class="ed-pf-entry-remove" title="Remove row">
            <i class="fas fa-times"></i>
        </button>`;
    return div;
}

const _posEntries = createEntryRowManager({
    containerId:  'positionEntries',
    rowSel:       '.ed-pf-entry',
    snSel:        '.ed-pf-entry-sn',
    nameInputSel: '.ed-pf-entry-name',
    removeBtnSel: '.ed-pf-entry-remove',
    createRow:    _createPositionRow,
    collectRow(row) {
        const name = row.querySelector('.ed-pf-entry-name')?.value?.trim();
        return name ? { name } : null;
    },
    clearRow(row) {
        const nameInp = row.querySelector('.ed-pf-entry-name');
        if (nameInp) nameInp.value = '';
    },
    btnTextId: 'addPostBtnText',
    singular:  'Add Position',
    plural:    'Add Positions',
});

// Public aliases used by the rest of the file
const renumberEntries    = _posEntries.renumber;
const updateAddBtnText   = _posEntries.updateBtnText;
const collectEntries     = _posEntries.collect;
const resetEntries       = _posEntries.reset;
const initEntryRows      = _posEntries.init;

/* ══════════════════════════════════════════════════════════════
   ADD POSITIONS — bulk submit (sends JSON to add-posts-bulk)
══════════════════════════════════════════════════════════════ */

function buildCard(id, name, order) {
    const deleteUrl = entityUrl('delete-post-base', id);
    const renameUrl = entityUrl('rename-post-base', id);
    // FE-13: Sanitize URL for safe HTML attribute embedding
    const safeRenameUrl = renameUrl.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const canEdit = !!window.electionData?.canEdit;

    const el = document.createElement('div');
    el.className = 'ed-pc ed-pc-enter';
    el.dataset.postId = id;
    el.draggable = true;
    el.innerHTML = `
        <span class="ed-pc-drag" title="Drag to reorder"><i class="fas fa-grip-vertical"></i></span>
        <div class="ed-pc-order">${order}</div>
        <div class="ed-pc-info">
            <span class="ed-pc-name">${escapeHtml(name)}</span>
            <span class="ed-pc-cands"><i class="fas fa-user-tie"></i> 0 candidates</span>
        </div>
        <div class="ed-pc-actions">
            ${canEdit ? `<button class="ed-pc-rename-btn" title="Rename position" data-url="${safeRenameUrl}">
                <i class="fas fa-pencil-alt"></i>
            </button>` : ''}
            <button class="ed-pc-expand-btn" title="Show candidates" data-post-id="${id}">
                <i class="fas fa-chevron-down"></i>
            </button>
            <button class="ed-pc-delete ed-delete-post-btn"
                    data-url="${deleteUrl}"
                    title="Delete position">
                <i class="fas fa-trash"></i>
            </button>
        </div>`;

    el.querySelector('.ed-pc-delete').addEventListener('click', () => deletePost(el.querySelector('.ed-pc-delete')));
    el.querySelector('.ed-pc-expand-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleCandPanel(id);
    });
    if (canEdit) el.querySelector('.ed-pc-rename-btn').addEventListener('click', () => renamePost(el));

    return el;
}

/** Build empty candidate panel for a newly created position */
function buildCandPanel(postId) {
    const panel = document.createElement('div');
    panel.className = 'ed-pc-cand-panel';
    panel.id = `candPanel-${postId}`;
    panel.dataset.postId = postId;
    panel.style.display = 'none';
    panel.innerHTML = `<div class="ed-cl-empty" id="candEmpty-${postId}"><p class="ed-cl-empty-hint" style="margin:0;">No candidates yet</p></div>`;
    return panel;
}

async function addPosts(errEl) {
    const entries = collectEntries();
    if (entries.length === 0) {
        showErr(errEl, 'Enter at least one position name.');
        const firstInput = document.querySelector('#positionEntries .ed-pf-entry-name');
        if (firstInput) firstInput.focus();
        return;
    }
    showErr(errEl, '');

    const addBtn = document.getElementById('addPostBtn');
    const textEl = document.getElementById('addPostBtnText');
    if (addBtn) addBtn.disabled = true;
    const origText = textEl?.textContent || 'Add Position';
    if (textEl) textEl.textContent = 'Adding…';

    try {
        const url = getUrl('add-posts-bulk');
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ posts: entries }),
        });
        const data = await res.json();

        if (data.success !== false) {
            // Insert all new cards into the list
            const listEl = document.getElementById('postsList');
            if (listEl) {
                const emptyEl = listEl.querySelector('.ed-pl-empty');
                if (emptyEl) emptyEl.remove();

                const existingCount = listEl.querySelectorAll('.ed-pc').length;
                data.posts.forEach((p, i) => {
                    const card = buildCard(p.post_id, p.post_name, existingCount + i + 1);
                    listEl.appendChild(card);
                    listEl.appendChild(buildCandPanel(p.post_id));
                    // Also add to position selector if it exists
                    addPositionOption(p.post_id, p.post_name, 0);
                });
                updateListHeaderCount();
            }

            // Reset form to single empty row
            resetEntries();

            const count = data.posts.length;
            notify(`${count} position${count !== 1 ? 's' : ''} added!`, 'success');
            refreshStats();
        } else {
            showErr(errEl, data.error || 'Failed to add positions.');
        }
    } catch (e) {
        showErr(errEl, e.message || 'Network error.');
    } finally {
        if (addBtn) addBtn.disabled = false;
        if (textEl) textEl.textContent = origText;
        updateAddBtnText();
    }
}

/* ══════════════════════════════════════════════════════════════
   DELETE POSITION
══════════════════════════════════════════════════════════════ */

async function deletePost(btn) {
    const url = btn.dataset.url;
    const card = btn.closest('.ed-pc');
    const postId = card?.dataset.postId;
    const name = card?.querySelector('.ed-pc-name')?.textContent || 'this position';

    const ok = await confirm(`Delete "${name}"? All candidates under it will also be removed.`, { confirmText: 'Delete', danger: true });
    if (!ok) return;

    try {
        const res = await post(url);
        if (res.success !== false) {
            // Remove the candidate panel for this position
            if (postId) {
                const panel = document.getElementById(`candPanel-${postId}`);
                if (panel) panel.remove();
            }
            card?.classList.add('ed-pc-exit');
            card?.addEventListener('animationend', () => {
                card.remove();
                renumberCards();
                updateListHeaderCount();
                showEmptyIfNeeded();
            }, { once: true });
            // Remove from position selector
            removePositionOption(postId);
            notify('Position deleted.', 'success');
            refreshStats();
        } else {
            notify(res.error || 'Failed to delete.', 'error');
        }
    } catch (e) {
        notify(e.message || 'Network error.', 'error');
    }
}

/* ══════════════════════════════════════════════════════════════
   RENAME POSITION (FEAT-01)
══════════════════════════════════════════════════════════════ */

/**
 * Activate inline rename for a position card.
 * Replaces the name span with an <input>, saves on blur/Enter, reverts on Escape.
 */
async function renamePost(cardEl) {
    const nameEl = cardEl.querySelector('.ed-pc-name');
    const renameBtn = cardEl.querySelector('.ed-pc-rename-btn');
    const url = renameBtn?.dataset.url;
    if (!nameEl || !url) return;

    const oldName = nameEl.textContent.trim();

    // Build an input in-place
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = oldName;
    inp.className = 'ed-pc-name-input';
    inp.maxLength = 200;
    nameEl.replaceWith(inp);
    inp.select();

    const revert = () => {
        if (!inp.isConnected) return;
        const span = document.createElement('span');
        span.className = 'ed-pc-name';
        span.textContent = oldName;
        inp.replaceWith(span);
    };

    const save = async () => {
        if (!inp.isConnected) return;  // FE-12: guard against blur firing after Escape revert
        const newName = inp.value.trim();
        if (!newName || newName === oldName) { revert(); return; }
        try {
            const res = await post(url, { name: newName }, { json: true });
            if (res.success) {
                const span = document.createElement('span');
                span.className = 'ed-pc-name';
                span.textContent = res.name || newName;
                inp.replaceWith(span);
                // Sync position selector option
                const select = document.getElementById('candPositionSelect');
                const opt = select?.querySelector(`option[value="${cardEl.dataset.postId}"]`);
                if (opt) opt.textContent = `${res.name} (${opt.dataset.count || 0} candidate${opt.dataset.count !== '1' ? 's' : ''})`;
                notify('Position renamed.', 'success');
            } else {
                notify(res.error || 'Rename failed.', 'error');
                revert();
            }
        } catch (e) {
            notify(e.message || 'Network error.', 'error');
            revert();
        }
    };

    inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
        if (e.key === 'Escape') { revert(); }
    });
    inp.addEventListener('blur', save, { once: true });
}

/* ══════════════════════════════════════════════════════════════
   DRAG-AND-DROP REORDER
   Uses JSON body to fix the URL-encoded array serialisation bug.
══════════════════════════════════════════════════════════════ */

/**
 * Generic reorder helper — sends a JSON body with { [idsKey]: ids } to the given URL.
 * On failure, shows a notification; if `reloadOnFail` is true, also reloads the page.
 */
async function sendReorderRequest(url, idsKey, ids, { reloadOnFail = false, label = 'order' } = {}) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ [idsKey]: ids }),
        });
        const data = await res.json();
        if (data.success === false) {
            notify(data.error || `Failed to save ${label}.`, 'error');
            if (reloadOnFail) location.reload();
        }
    } catch {
        notify(`Failed to save ${label}.`, 'error');
        if (reloadOnFail) location.reload();
    }
}

async function sendReorder(newOrder) {
    await sendReorderRequest(getUrl('reorder-posts'), 'post_ids', newOrder, { reloadOnFail: true });
}

async function sendCandReorder(postId, candidateIds) {
    await sendReorderRequest(entityUrl('reorder-candidates-base', postId), 'candidate_ids', candidateIds, { label: 'candidate order' });
}

function initCandDragAndDrop(grid) {
    if (!grid) return;
    // Drag handles (.ed-cc-drag) are only rendered by the server when can_edit
    // is True. If none exist, there is nothing to drag — return early.
    if (!grid.querySelector('.ed-cc-drag')) return;

    const candCards = () => [...grid.querySelectorAll('.ed-cc[draggable="true"]')];
    // Closure-scoped so each grid tracks its own drag independently.
    let _candDragEl = null;
    let _lastDragOverTarget = null;

    // Track whether the pointer started on the grip handle.
    // HTML5 DnD sets dragstart's e.target to the *draggable* element (the card),
    // NOT the child the user clicked—so e.target.closest('.ed-cc-drag') always
    // fails.  We record the real click target via pointerdown instead.
    let _startedOnHandle = false;
    grid.addEventListener('pointerdown', (e) => {
        _startedOnHandle = !!e.target.closest('.ed-cc-drag');
    }, true);

    // Make existing cards draggable
    grid.querySelectorAll('.ed-cc').forEach(c => { c.draggable = true; });

    grid.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.ed-cc');
        if (!card) return;
        // Only initiate drag from the grip handle so edit/delete buttons remain clickable
        if (!_startedOnHandle) { e.preventDefault(); return; }
        // Stop propagation so the parent position-list dragstart handler
        // doesn't interfere with this candidate drag.
        e.stopPropagation();
        _candDragEl = card;
        card.classList.add('ed-cc-dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', card.dataset.candidateId);
    });

    grid.addEventListener('dragend', () => {
        if (_candDragEl) { _candDragEl.classList.remove('ed-cc-dragging'); _candDragEl = null; }
        _lastDragOverTarget = null;
        candCards().forEach(c => c.classList.remove('ed-cc-drag-over'));
    });

    grid.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const target = e.target.closest('.ed-cc');
        if (!target || target === _candDragEl) return;
        _lastDragOverTarget = target;
        candCards().forEach(c => c.classList.remove('ed-cc-drag-over'));
        target.classList.add('ed-cc-drag-over');
    });

    grid.addEventListener('dragleave', (e) => {
        const target = e.target.closest('.ed-cc');
        if (!target) return;
        // Only remove highlight when truly leaving the card, not when moving
        // between its child elements (toolbar, avatar, name span, etc.).
        if (!target.contains(e.relatedTarget)) {
            target.classList.remove('ed-cc-drag-over');
        }
    });

    grid.addEventListener('drop', async (e) => {
        e.preventDefault();
        e.stopPropagation(); // Prevent position card drop handler
        // Use last hovered card as fallback if cursor lands on grid gap/background
        const target = e.target.closest('.ed-cc') || _lastDragOverTarget;
        _lastDragOverTarget = null;
        if (!target || !_candDragEl || target === _candDragEl) return;

        const all = candCards();
        const fromIdx = all.indexOf(_candDragEl);
        const toIdx = all.indexOf(target);
        if (fromIdx < toIdx) target.after(_candDragEl); else target.before(_candDragEl);
        target.classList.remove('ed-cc-drag-over');

        const panel = grid.closest('.ed-pc-cand-panel');
        const postId = panel?.dataset.postId;
        if (postId) {
            const newOrder = [...grid.querySelectorAll('.ed-cc[data-candidate-id]')]
                .map(el => el.dataset.candidateId);
            await sendCandReorder(postId, newOrder);
        }
    });
}

/**
 * Generic card drag-and-drop setup. Attaches dragstart/dragend/dragover/
 * dragleave/drop listeners to `listEl`. The `onDrop(draggedCard, listEl, newOrder)`
 * callback receives the dragged card, the list element, and the ordered IDs
 * after the move. Returns a ref object with `.current` holding the dragged card.
 */
function setupCardDrag(listEl, onDrop) {
    const ref = { current: null };
    let _lastPcDragTarget = null;
    const cards = () => [...listEl.querySelectorAll('.ed-pc[draggable="true"]')];

    // Track whether the pointer started on the grip handle.
    // HTML5 DnD sets dragstart's e.target to the *draggable* element (the card),
    // NOT the child the user clicked—so e.target.closest('.ed-pc-drag') always
    // fails.  We record the real click target via pointerdown instead.
    let _startedOnHandle = false;
    listEl.addEventListener('pointerdown', (e) => {
        _startedOnHandle = !!e.target.closest('.ed-pc-drag');
    }, true);

    listEl.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.ed-pc');
        if (!card || !card.draggable) return;
        // If this drag starts from inside a candidate card, let the candidate
        // drag handler manage it — don't interfere or call preventDefault here.
        if (e.target.closest('.ed-cc')) return;
        // Only start drag from the position grip handle; other buttons stay clickable
        if (!_startedOnHandle) { e.preventDefault(); return; }
        ref.current = card;
        card.classList.add('ed-pc-dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', card.dataset.postId);
    });
    listEl.addEventListener('dragend', () => {
        if (ref.current) { ref.current.classList.remove('ed-pc-dragging'); ref.current = null; }
        _lastPcDragTarget = null;
        cards().forEach(c => c.classList.remove('ed-pc-drag-over'));
    });
    listEl.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const target = e.target.closest('.ed-pc');
        if (!target || target === ref.current) return;
        _lastPcDragTarget = target;
        cards().forEach(c => c.classList.remove('ed-pc-drag-over'));
        target.classList.add('ed-pc-drag-over');
    });
    listEl.addEventListener('dragleave', (e) => {
        const target = e.target.closest('.ed-pc');
        if (!target) return;
        // Only remove highlight when truly leaving the card boundary,
        // not when moving between its child elements.
        if (!target.contains(e.relatedTarget)) {
            target.classList.remove('ed-pc-drag-over');
        }
    });
    listEl.addEventListener('drop', async (e) => {
        e.preventDefault();
        const target = e.target.closest('.ed-pc') || _lastPcDragTarget;
        _lastPcDragTarget = null;
        if (!target || !ref.current || target === ref.current) return;
        const all = cards();
        const fromIdx = all.indexOf(ref.current);
        const toIdx = all.indexOf(target);
        if (fromIdx < toIdx) target.after(ref.current); else target.before(ref.current);
        target.classList.remove('ed-pc-drag-over');
        const newOrder = [...listEl.querySelectorAll('.ed-pc[data-post-id]')].map(el => el.dataset.postId);
        await onDrop(ref.current, listEl, newOrder);
    });
    return ref;
}

function initDragAndDrop() {
    const list = document.getElementById('postsList');
    if (!list) return;
    const ref = setupCardDrag(list, async (_card, listEl, newOrder) => {
        // Re-attach each candidate panel immediately after its position card
        listEl.querySelectorAll('.ed-pc').forEach(card => {
            const pid = card.dataset.postId;
            const panel = document.getElementById(`candPanel-${pid}`);
            if (panel) card.after(panel);
        });
        renumberCards();
        await sendReorder(newOrder);
    });
}

/* ─── Helpers ─── */

/** Renumber .ed-pc-order badges inside the given container element ID */
function renumberCardsIn(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.querySelectorAll('.ed-pc').forEach((card, i) => {
        const badge = card.querySelector('.ed-pc-order');
        if (badge) badge.textContent = i + 1;
    });
}

function renumberCards() { renumberCardsIn('postsList'); }

function updateListHeaderCount() {
    const list = document.getElementById('postsList');
    const descEl = document.querySelector('.ed-pl-desc');
    if (!descEl || !list) return;
    const posCount = list.querySelectorAll('.ed-pc').length;
    // Sum candidate counts from all position cards
    let candCount = 0;
    list.querySelectorAll('.ed-pc .ed-pc-cands').forEach(el => {
        const m = el.textContent.match(/\d+/);
        if (m) candCount += parseInt(m[0], 10);
    });
    if (posCount === 0) {
        descEl.textContent = 'No positions added yet';
    } else {
        const canEdit = !!window.electionData?.canEdit;
        descEl.textContent = `${posCount} position${posCount !== 1 ? 's' : ''} · ${candCount} candidate${candCount !== 1 ? 's' : ''}${canEdit ? ' · drag to reorder' : ''}`;
    }
}

function showEmptyIfNeeded() {
    const list = document.getElementById('postsList');
    if (!list) return;
    const hasCards = list.querySelectorAll('.ed-pc').length > 0;
    const existing = list.querySelector('.ed-pl-empty');
    if (!hasCards && !existing) {
        list.innerHTML = `
            <div class="ed-pl-empty" id="postsEmpty">
                <div class="ed-pl-empty-icon"><i class="fas fa-layer-group"></i></div>
                <p class="ed-pl-empty-title">No positions yet</p>
                <p class="ed-pl-empty-hint">Use the form on the left to add your first position.</p>
            </div>`;
    }
}

/* ══════════════════════════════════════════════════════════════
   IMPORT FROM FILE
══════════════════════════════════════════════════════════════ */

let _selectedFile = null;

function initImportSection() {
    const toggle   = document.getElementById('toggleImportSection');
    const section  = document.getElementById('importSection');
    const closeBtn = document.getElementById('closeImportSection');
    const tplBtnCSV = document.getElementById('downloadPosTemplateCSV');
    const tplBtnXLS = document.getElementById('downloadPosTemplateExcel');
    const dropzone = document.getElementById('importDropzone');
    const fileInp  = document.getElementById('importFileInput');
    const nameEl   = document.getElementById('importFileName');
    const importBtn = document.getElementById('importBtn');
    const errEl    = document.getElementById('importError');

    if (!toggle || !section) return;

    toggle.addEventListener('click', () => {
        section.classList.toggle('ed-pf-import--open');
    });
    if (closeBtn) closeBtn.addEventListener('click', () => {
        section.classList.remove('ed-pf-import--open');
        _selectedFile = null;
        if (nameEl) nameEl.style.display = 'none';
        if (importBtn) importBtn.disabled = true;
        showErr(errEl, '');
    });

    // Template downloads
    if (tplBtnCSV) tplBtnCSV.addEventListener('click', (e) => {
        e.preventDefault();
        window.location.href = getUrl('export-template-positions');
    });
    if (tplBtnXLS) tplBtnXLS.addEventListener('click', (e) => {
        e.preventDefault();
        window.location.href = getUrl('export-template-positions') + '?format=xlsx';
    });

    // File input
    if (fileInp) fileInp.addEventListener('change', () => {
        setImportFile(fileInp.files[0], nameEl, importBtn, errEl);
    });

    // Drag-and-drop
    if (dropzone) {
        ['dragenter', 'dragover'].forEach(ev =>
            dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add('ed-pf-dropzone--over'); })
        );
        ['dragleave', 'drop'].forEach(ev =>
            dropzone.addEventListener(ev, () => dropzone.classList.remove('ed-pf-dropzone--over'))
        );
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            const file = e.dataTransfer?.files?.[0];
            if (file) setImportFile(file, nameEl, importBtn, errEl);
        });
    }

    // Import button
    if (importBtn) importBtn.addEventListener('click', () => doImport(errEl));
}

function setImportFile(file, nameEl, importBtn, errEl) {
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['csv', 'xlsx', 'xls'].includes(ext)) {
        showErr(errEl, 'Only CSV or Excel files accepted.');
        return;
    }
    _selectedFile = file;
    showErr(errEl, '');
    if (nameEl) {
        nameEl.textContent = `📄 ${file.name}`;
        nameEl.style.display = 'block';
    }
    if (importBtn) importBtn.disabled = false;
}

async function doImport(errEl) {
    if (!_selectedFile) return;
    const btn = document.getElementById('importBtn');
    const textEl = document.getElementById('importBtnText');
    if (btn) btn.disabled = true;
    if (textEl) textEl.textContent = 'Importing…';
    showErr(errEl, '');

    try {
        const fd = new FormData();
        fd.append('election_file', _selectedFile);
        const url = getUrl('bulk-import');
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: fd,
        });
        if (!res.ok) {
            const ct = res.headers.get('content-type') || '';
            if (ct.includes('application/json')) {
                const data = await res.json();
                showErr(errEl, data.error || `Server error (${res.status})`);
            } else {
                showErr(errEl, `Server error (${res.status})`);
            }
            return;
        }
        const data = await res.json();
        if (data.success) {
            notify(data.message || 'Import complete!', 'success');
            location.reload();
        } else {
            showErr(errEl, data.error || 'Import failed.');
        }
    } catch (e) {
        showErr(errEl, e.message || 'Network error.');
    } finally {
        if (btn) btn.disabled = false;
        if (textEl) textEl.textContent = 'Import';
    }
}

/* ══════════════════════════════════════════════════════════════
   DELETE ALL POSITIONS
══════════════════════════════════════════════════════════════ */

async function deleteAllPosts() {
    const list = document.getElementById('postsList');
    const count = list ? list.querySelectorAll('.ed-pc').length : 0;
    if (count === 0) {
        notify('No positions to delete.', 'info');
        return;
    }
    const ok = await confirm(
        `Delete all ${count} position(s)? This will also remove all candidates under them. This cannot be undone.`,
        { confirmText: 'Delete All', danger: true },
    );
    if (!ok) return;

    try {
        const res = await post(getUrl('delete-all-posts'));
        if (res.success !== false) {
            if (list) list.innerHTML = '';
            showEmptyIfNeeded();
            updateListHeaderCount();
            resetCandidatesSection();
            notify(res.message || 'All positions deleted.', 'success');
            refreshStats();
        } else {
            notify(res.error || 'Failed to delete.', 'error');
        }
    } catch (e) {
        notify(e.message || 'Network error.', 'error');
    }
}

/* ══════════════════════════════════════════════════════════════
   DOWNLOAD POSITIONS PDF
══════════════════════════════════════════════════════════════ */

function downloadPositionsPdf() {
    const url = getUrl('export-positions-pdf');
    if (url) window.location.href = url;
}

/* ══════════════════════════════════════════════════════════════
   CANDIDATE ENTRY ROWS — via factory (merged from candidates tab)
══════════════════════════════════════════════════════════════ */

function _createCandRow(sn) {
    const div = document.createElement('div');
    div.className = 'ed-cf-entry';
    div.innerHTML = `
        <span class="ed-cf-entry-sn">${sn}</span>
        <input type="text" class="ed-input ed-cf-entry-name"
               placeholder="e.g. John Doe, Jane Smith…"
               maxlength="255" autocomplete="off">
        <input type="text" class="ed-input ed-cf-entry-bio"
               placeholder="Short bio…"
               maxlength="500" autocomplete="off">
        <button type="button" class="ed-cf-entry-remove" title="Remove row">
            <i class="fas fa-times"></i>
        </button>`;
    return div;
}

const _candEntries = createEntryRowManager({
    containerId:  'candidateEntries',
    rowSel:       '.ed-cf-entry',
    snSel:        '.ed-cf-entry-sn',
    nameInputSel: '.ed-cf-entry-name',
    removeBtnSel: '.ed-cf-entry-remove',
    createRow:    _createCandRow,
    collectRow(row) {
        const name = row.querySelector('.ed-cf-entry-name')?.value?.trim();
        const bio  = row.querySelector('.ed-cf-entry-bio')?.value?.trim() || '';
        return name ? { name, bio } : null;
    },
    clearRow(row) {
        const nameInp = row.querySelector('.ed-cf-entry-name');
        const bioInp  = row.querySelector('.ed-cf-entry-bio');
        if (nameInp) nameInp.value = '';
        if (bioInp)  bioInp.value = '';
    },
    btnTextId: 'candAddBtnText',
    singular:  'Add Candidate',
    plural:    'Add Candidates',
});

const collectCandEntries    = _candEntries.collect;
const resetCandEntries      = _candEntries.reset;
const updateCandAddBtnText  = _candEntries.updateBtnText;
const initCandEntryRows     = _candEntries.init;

/* ── Unlock candidates form (replace "No Positions Yet" with real form) ── */

function unlockCandidatesForm(postId, name, count) {
    const locked = document.querySelector('#panel-posts .ed-cf-locked');
    if (!locked) return;

    // Build selector HTML
    const selectorHtml = `
        <div class="ed-cf-selector">
            <label class="ed-cf-selector-label" for="candPositionSelect">Position</label>
            <select id="candPositionSelect" class="ed-input ed-cf-select">
                <option value="${postId}" data-name="${escapeHtml(name)}" data-count="${count}" selected>
                    ${escapeHtml(name)} (${count} candidate${count !== 1 ? 's' : ''})
                </option>
            </select>
        </div>`;

    // Build form body HTML
    const bodyHtml = `
        <div class="ed-cf-body">
            <div class="ed-cf-inner">
                <div class="ed-cf-cols-header">
                    <span class="ed-cf-col-hdr ed-cf-col-sn">#</span>
                    <span class="ed-cf-col-hdr ed-cf-col-name">Candidate Name</span>
                    <span class="ed-cf-col-hdr ed-cf-col-bio">Bio (optional)</span>
                    <span class="ed-cf-col-hdr ed-cf-col-remove">
                        <button type="button" class="ed-cf-clear-all" id="clearAllCandEntries" title="Clear all">
                            <i class="fas fa-times"></i>
                        </button>
                    </span>
                </div>
                <div class="ed-cf-entries" id="candidateEntries">
                    <div class="ed-cf-entry">
                        <span class="ed-cf-entry-sn">1</span>
                        <input type="text" class="ed-input ed-cf-entry-name"
                               placeholder="e.g. John Doe, Jane Smith…"
                               maxlength="255" autocomplete="off">
                        <input type="text" class="ed-input ed-cf-entry-bio"
                               placeholder="Short bio…"
                               maxlength="500" autocomplete="off">
                        <button type="button" class="ed-cf-entry-remove" title="Remove row">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
                <p class="ed-cf-error" id="candFormError" style="display:none;"></p>
            </div>
        </div>
        <div class="ed-cf-footer">
            <span class="ed-pf-footer-spacer"></span>
            <button class="ed-cf-add-btn" id="candAddBtn">
                <i class="fas fa-plus"></i>
                <span id="candAddBtnText">Add Candidates</span>
            </button>
        </div>`;

    // Replace the locked section with actual form elements
    const parent = locked.parentNode;
    locked.remove();

    // Find the divider before the import section to insert before it
    const dividers = parent.querySelectorAll('.ed-pf-divider');
    const lastDivider = dividers[dividers.length - 1];

    // Create temp container
    const tmp = document.createElement('div');
    tmp.innerHTML = selectorHtml + bodyHtml;

    // Insert all child nodes before the last divider
    while (tmp.firstChild) {
        parent.insertBefore(tmp.firstChild, lastDivider);
    }

    // Re-wire event listeners for the new form
    initCandEntryRows();

    const clearCandBtn = document.getElementById('clearAllCandEntries');
    if (clearCandBtn) clearCandBtn.addEventListener('click', resetCandEntries);

    const candAddBtn = document.getElementById('candAddBtn');
    const candErrEl  = document.getElementById('candFormError');
    if (candAddBtn) candAddBtn.addEventListener('click', () => addCandidates(candErrEl));

    const candContainer = document.getElementById('candidateEntries');
    if (candContainer) {
        candContainer.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.classList.contains('ed-cf-entry-name')) {
                e.preventDefault();
                addCandidates(candErrEl);
            }
        });
    }
}

/* ── Position selector ── */

function getActivePostId() {
    const sel = document.getElementById('candPositionSelect');
    return sel ? sel.value : null;
}

function addPositionOption(postId, name, count) {
    const sel = document.getElementById('candPositionSelect');
    if (sel) {
        const opt = document.createElement('option');
        opt.value = postId;
        opt.dataset.name = name;
        opt.dataset.count = count;
        opt.textContent = `${name} (${count} candidate${count !== 1 ? 's' : ''})`;
        sel.appendChild(opt);
        return;
    }
    // If selector doesn't exist yet, the candidates form is in locked state — inject full form
    unlockCandidatesForm(postId, name, count);
}

/** Remove a position option from the candidates selector, and re-lock if empty */
function removePositionOption(postId) {
    const sel = document.getElementById('candPositionSelect');
    if (!sel) return;
    const opt = sel.querySelector(`option[value="${postId}"]`);
    if (opt) opt.remove();
    // If no options remain, re-lock the candidates form
    if (sel.options.length === 0) {
        resetCandidatesSection();
    }
}

/** Reset the candidates section back to locked "No Positions Yet" state */
function resetCandidatesSection() {
    const cfSelector = document.querySelector('#panel-posts .ed-cf-selector');
    const cfBody     = document.querySelector('#panel-posts .ed-cf-body');
    const cfFooter   = document.querySelector('#panel-posts .ed-cf-footer');
    const targets = [cfSelector, cfBody, cfFooter].filter(Boolean);
    if (!targets.length) return;

    const parent = targets[0].parentNode;
    targets.forEach(el => el.remove());

    // Find the import divider to insert before
    const dividers = parent.querySelectorAll('.ed-pf-divider');
    const lastDivider = dividers[dividers.length - 1];

    const locked = document.createElement('div');
    locked.className = 'ed-cf-locked';
    locked.innerHTML = `
        <div class="ed-cf-locked-icon"><i class="fas fa-columns"></i></div>
        <p class="ed-cf-locked-title">No Positions Yet</p>
        <p class="ed-cf-locked-desc">Add positions above first, then add candidates here.</p>`;

    if (lastDivider) {
        parent.insertBefore(locked, lastDivider);
    } else {
        parent.appendChild(locked);
    }
}

/* ── Build candidate card for DOM injection ── */

function buildCandCard(candId, name, bio, imageUrl, canEdit) {
    const el = document.createElement('div');
    el.className = 'ed-cc ed-cc-enter';
    el.dataset.candidateId = candId;
    if (canEdit) el.draggable = true;

    const avatarInner = imageUrl
        ? `<img src="${imageUrl}" alt="${escapeHtml(name)}" loading="lazy" width="64" height="64">` 
        : `<i class="fas fa-user"></i>`;

    const bioHtml = bio ? `<p class="ed-cc-bio">${escapeHtml(bio)}</p>` : '';

    const toolbarHtml = canEdit
        ? `<div class="ed-cc-toolbar">
               <span class="ed-cc-drag" title="Drag to reorder"><i class="fas fa-grip-vertical"></i></span>
               <div class="ed-cc-tb-actions">
                   <button class="ed-cc-edit-btn"
                           data-url="${entityUrl('update-candidate-base', candId)}"
                           title="Edit candidate">
                       <i class="fas fa-pencil-alt"></i>
                   </button>
                   <button class="ed-cc-delete ed-delete-cand-btn"
                           data-url="${entityUrl('delete-candidate-base', candId)}"
                           data-candidate-id="${candId}"
                           title="Remove candidate">
                       <i class="fas fa-trash-alt"></i>
                   </button>
               </div>
           </div>`
        : '';

    const uploadOverlay = canEdit
        ? '<span class="ed-cc-avatar-overlay"><i class="fas fa-camera"></i></span>'
        : '';

    el.innerHTML = `
        ${toolbarHtml}
        <div class="ed-cc-avatar${canEdit ? ' ed-cc-avatar--editable' : ''}" data-candidate-id="${candId}">${avatarInner}${uploadOverlay}</div>
        <span class="ed-cc-name">${escapeHtml(name)}</span>
        ${bioHtml}`;

    const delBtn = el.querySelector('.ed-delete-cand-btn');
    if (delBtn) delBtn.addEventListener('click', () => deleteCandidate(delBtn));

    if (canEdit) {
        const avatar = el.querySelector('.ed-cc-avatar');
        if (avatar) avatar.addEventListener('click', () => triggerAvatarUpload(avatar, candId));
        const editBtn = el.querySelector('.ed-cc-edit-btn');
        if (editBtn) editBtn.addEventListener('click', () => editCandidate(el));
    }

    return el;
}

/* ── Avatar click-to-upload ── */

function triggerAvatarUpload(avatarEl, candId) {
    const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
    const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB (raw input — before crop)
    const OUTPUT_SIZE = 400;               // px — final crop dimensions
    const OUTPUT_QUALITY = 0.78;           // WebP quality (0.75-0.80 range)

    const inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = ALLOWED_TYPES.join(',');
    inp.style.cssText = 'position:fixed;left:-9999px;opacity:0;';
    document.body.appendChild(inp);

    const cleanup = () => { if (inp.parentNode) inp.remove(); };

    inp.addEventListener('change', () => {
        const file = inp.files?.[0];
        cleanup();
        if (!file) return;
        if (!ALLOWED_TYPES.includes(file.type)) {
            notify('Allowed formats: JPEG, PNG, WebP.', 'error');
            return;
        }
        if (file.size > MAX_FILE_SIZE) {
            notify('Image must be under 5 MB.', 'error');
            return;
        }
        openCropModal(file, avatarEl, candId, OUTPUT_SIZE, OUTPUT_QUALITY);
    }, { once: true });

    inp.addEventListener('cancel', cleanup, { once: true });
    inp.click();
}

/**
 * Opens the crop modal with Cropper.js. On confirm, exports a
 * 400×400 WebP blob and uploads it (pre-signed or server-mediated).
 */
function openCropModal(file, avatarEl, candId, outputSize, quality) {
    const modal = document.getElementById('cropModal');
    const imgEl = document.getElementById('cropImage');
    if (!modal || !imgEl) {
        // Fallback: no crop modal in DOM — upload raw (legacy path)
        uploadImageDirect(file, avatarEl, candId);
        return;
    }

    const objectUrl = URL.createObjectURL(file);
    imgEl.src = objectUrl;
    modal.classList.add('is-open');

    // Small delay so the image element has dimensions for Cropper.js
    requestAnimationFrame(() => {
        if (typeof Cropper === 'undefined') {
            notify('Image cropper failed to load. Please refresh and try again.', 'error');
            URL.revokeObjectURL(objectUrl);
            imgEl.src = '';
            modal.classList.remove('is-open');
            return;
        }
        const cropper = new Cropper(imgEl, {
            aspectRatio: 1,          // Force square crop
            viewMode: 1,             // Restrict crop box to canvas
            dragMode: 'move',
            autoCropArea: 0.9,
            cropBoxResizable: true,
            background: false,
            modal: true,
            guides: true,
            center: true,
            responsive: true,
        });

        const closeModal = () => {
            cropper.destroy();
            URL.revokeObjectURL(objectUrl);
            imgEl.src = '';
            modal.classList.remove('is-open');
            // Remove cloned listeners by replacing buttons
            ['cropConfirm', 'cropCancel'].forEach(id => {
                const el = document.getElementById(id);
                if (el) { const c = el.cloneNode(true); el.replaceWith(c); }
            });
            const closeBtn = modal.querySelector('.ed-crop-modal-close');
            if (closeBtn) { const c = closeBtn.cloneNode(true); closeBtn.replaceWith(c); }
        };

        const onConfirm = async () => {
            const canvas = cropper.getCroppedCanvas({
                width: outputSize,
                height: outputSize,
                imageSmoothingEnabled: true,
                imageSmoothingQuality: 'high',
            });

            closeModal();

            // Convert canvas to WebP blob (JPEG fallback for older Safari)
            const blob = await new Promise((resolve) => {
                canvas.toBlob((b) => {
                    if (b && b.type === 'image/webp') {
                        resolve(b);
                    } else {
                        // Fallback: Safari versions that don't support WebP canvas export
                        canvas.toBlob((fb) => resolve(fb), 'image/jpeg', quality);
                    }
                }, 'image/webp', quality);
            });

            if (!blob) { notify('Failed to process image.', 'error'); return; }

            await uploadCroppedImage(blob, avatarEl, candId);
        };

        document.getElementById('cropConfirm')?.addEventListener('click', onConfirm);
        document.getElementById('cropCancel')?.addEventListener('click', closeModal);
        modal.querySelector('.ed-crop-modal-close')?.addEventListener('click', closeModal);
        modal.querySelector('.ed-crop-modal-backdrop')?.addEventListener('click', closeModal);
    });
}

/**
 * Upload a cropped blob — tries pre-signed URL first, falls back to
 * server-mediated FormData upload if R2 is not configured.
 */
async function uploadCroppedImage(blob, avatarEl, candId) {
    const origHTML = avatarEl.innerHTML;
    avatarEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    try {
        // Step 1: Request pre-signed URL from Django
        const presignUrl = entityUrl('presign-upload-base', candId);
        const presignRes = await post(presignUrl, {}, { json: true });

        if (presignRes.presign && presignRes.upload_url) {
            // Step 2a: Direct upload to R2 via pre-signed PUT
            const putRes = await fetch(presignRes.upload_url, {
                method: 'PUT',
                headers: { 'Content-Type': 'image/webp' },
                body: blob,
            });

            if (!putRes.ok) throw new Error('R2 upload failed.');

            // Step 3: Confirm with Django to update the model
            const confirmUrl = entityUrl('confirm-upload-base', candId);
            const confirmRes = await post(confirmUrl, {
                object_key: presignRes.object_key,
            }, { json: true });

            if (confirmRes.success && confirmRes.image_url) {
                updateAvatarUI(avatarEl, confirmRes.image_url);
                notify('Photo updated!', 'success');
            } else {
                throw new Error(confirmRes.error || 'Confirm failed.');
            }
        } else {
            // Step 2b: Fallback — server-mediated upload (no R2 / dev mode)
            await uploadImageDirect(blob, avatarEl, candId, origHTML);
            return; // uploadImageDirect handles its own UI
        }
    } catch (e) {
        avatarEl.innerHTML = origHTML;
        notify(e.message || 'Upload failed.', 'error');
    }
}

/**
 * Upload an image file/blob to Django via FormData (server-mediated path).
 * Used as fallback when R2 is not configured.
 */
async function uploadImageDirect(fileOrBlob, avatarEl, candId, origHTML) {
    if (!origHTML) origHTML = avatarEl.innerHTML;
    avatarEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    try {
        const url = entityUrl('update-candidate-image-base', candId);
        const fd = new FormData();
        // Blob has no .name; supply an explicit filename so Django picks up the
        // correct Content-Type and storage path.
        const ext = (fileOrBlob.type === 'image/webp') ? 'webp'
                  : (fileOrBlob.type === 'image/png')  ? 'png' : 'jpg';
        const filename = fileOrBlob.name || `candidate-${candId}.${ext}`;
        fd.append('image', fileOrBlob, filename);
        // Use the post() helper — it checks Content-Type before calling .json(),
        // preventing "unexpected token" when the server returns an error page.
        const data = await post(url, fd);
        if (data.success && data.image_url) {
            updateAvatarUI(avatarEl, data.image_url);
            notify('Photo updated!', 'success');
        } else {
            avatarEl.innerHTML = origHTML;
            notify(data.error || 'Upload failed.', 'error');
        }
    } catch (e) {
        avatarEl.innerHTML = origHTML;
        notify(e.message || 'Network error.', 'error');
    }
}

/** Swap avatar element innerHTML with new image + overlay */
function updateAvatarUI(avatarEl, imageUrl) {
    avatarEl.innerHTML = `<img src="${imageUrl}" alt="">` +
        (avatarEl.classList.contains('ed-cc-avatar--editable')
            ? '<span class="ed-cc-avatar-overlay"><i class="fas fa-camera"></i></span>'
            : '');
}

/* ══════════════════════════════════════════════════════════════
   ADD CANDIDATES — bulk submit
══════════════════════════════════════════════════════════════ */

async function addCandidates(errEl) {
    const entries = collectCandEntries();
    if (entries.length === 0) {
        showErr(errEl, 'Enter at least one candidate name.');
        const firstInp = document.querySelector('#candidateEntries .ed-cf-entry-name');
        if (firstInp) firstInp.focus();
        return;
    }
    showErr(errEl, '');

    const postId = getActivePostId();
    if (!postId) { showErr(errEl, 'Please select a position first.'); return; }

    const addBtn = document.getElementById('candAddBtn');
    const textEl = document.getElementById('candAddBtnText');
    if (addBtn) addBtn.disabled = true;
    const origText = textEl?.textContent || 'Add Candidates';
    if (textEl) textEl.textContent = 'Adding…';

    try {
        const url = entityUrl('add-candidates-bulk-base', postId);
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ candidates: entries }),
        });
        const data = await res.json();

        if (data.success !== false) {
            // Inject into the inline candidate panel
            const panel = document.getElementById(`candPanel-${postId}`);
            if (panel) {
                const emptyEl = panel.querySelector('.ed-cl-empty');
                if (emptyEl) emptyEl.remove();
                let grid = panel.querySelector('.ed-cand-grid');
                if (!grid) {
                    grid = document.createElement('div');
                    grid.className = 'ed-cand-grid';
                    grid.id = `candGrid-${postId}`;
                    panel.appendChild(grid);
                    initCandDragAndDrop(grid);
                }
                const canEdit = !!window.electionData?.canEdit;
                data.candidates.forEach(c => {
                    const card = buildCandCard(c.candidate_id, c.name, c.bio, c.image_url, canEdit);
                    if (canEdit) card.draggable = true;
                    grid.appendChild(card);
                });
            }

            updateCandCount(postId, data.new_count);
            updateListHeaderCount();
            resetCandEntries();
            const n = data.candidates.length;
            notify(`${n} candidate${n !== 1 ? 's' : ''} added!`, 'success');
            refreshStats();
            setTimeout(() => location.reload(), 800);
        } else {
            showErr(errEl, data.error || 'Failed to add candidates.');
        }
    } catch (e) {
        showErr(errEl, e.message || 'Network error.');
    } finally {
        if (addBtn) addBtn.disabled = false;
        if (textEl) textEl.textContent = origText;
    }
}

/* ══════════════════════════════════════════════════════════════
   DELETE CANDIDATE
══════════════════════════════════════════════════════════════ */

async function deleteCandidate(btn) {
    const url  = btn.dataset.url;
    const card = btn.closest('.ed-cc');
    const name = card?.querySelector('.ed-cc-name')?.textContent || 'this candidate';

    const ok = await confirm(`Remove "${name}"?`, { confirmText: 'Remove', danger: true });
    if (!ok) return;

    try {
        const res = await post(url);
        if (res.success !== false) {
            // Find which panel this card belongs to
            const panel = card.closest('.ed-pc-cand-panel');
            const postId = panel?.dataset.postId || getActivePostId();
            card?.classList.add('ed-cc-exit');
            card?.addEventListener('animationend', () => {
                card.remove();
                if (panel) {
                    const grid = panel.querySelector('.ed-cand-grid');
                    if (grid && !grid.children.length) {
                        grid.remove();
                        const empty = document.createElement('div');
                        empty.className = 'ed-cl-empty';
                        empty.id = `candEmpty-${postId}`;
                        empty.innerHTML = '<p class="ed-cl-empty-hint" style="margin:0;">No candidates yet</p>';
                        panel.appendChild(empty);
                    }
                }
                const curCount = getCandCount(postId);
                updateCandCount(postId, Math.max(0, curCount - 1));
                updateListHeaderCount();
                refreshStats();
            }, { once: true });
            notify('Candidate removed.', 'success');
        } else {
            notify(res.error || 'Failed to remove.', 'error');
        }
    } catch (e) {
        notify(e.message || 'Network error.', 'error');
    }
}

/* ══════════════════════════════════════════════════════════════
   EDIT CANDIDATE NAME / BIO (FEAT-02)
══════════════════════════════════════════════════════════════ */

/**
 * Open a tiny inline form on a candidate card to edit name and bio.
 * Saves on Submit, reverts on Escape or Cancel.
 */
async function editCandidate(cardEl) {
    const nameEl  = cardEl.querySelector('.ed-cc-name');
    const bioEl   = cardEl.querySelector('.ed-cc-bio');
    const editBtn = cardEl.querySelector('.ed-cc-edit-btn');
    const url     = editBtn?.dataset.url;
    if (!nameEl || !url) return;

    const oldName = nameEl.textContent.trim();
    const oldBio  = bioEl?.textContent.trim() ?? '';

    // ── In-place inputs (same pattern as renamePost) ──────────────────────────
    const nameInp = document.createElement('input');
    nameInp.type        = 'text';
    nameInp.value       = oldName;
    nameInp.className   = 'ed-cc-edit-name';
    nameInp.maxLength   = 255;
    nameInp.placeholder = 'Name';

    const bioInp = document.createElement('input');
    bioInp.type        = 'text';
    bioInp.value       = oldBio;
    bioInp.className   = 'ed-cc-edit-bio';
    bioInp.maxLength   = 500;
    bioInp.placeholder = 'Bio (optional)';

    nameEl.replaceWith(nameInp);
    if (bioEl) {
        bioEl.replaceWith(bioInp);
    } else {
        nameInp.insertAdjacentElement('afterend', bioInp);
    }
    nameInp.select();

    // ── Restore original spans without saving ─────────────────────────────────
    const revert = () => {
        if (!nameInp.isConnected) return;
        const ns = document.createElement('span');
        ns.className   = 'ed-cc-name';
        ns.textContent = oldName;
        nameInp.replaceWith(ns);
        if (bioInp.isConnected) {
            if (oldBio) {
                const nb = document.createElement('p');
                nb.className   = 'ed-cc-bio';
                nb.textContent = oldBio;
                bioInp.replaceWith(nb);
            } else {
                bioInp.remove();
            }
        }
    };

    // ── Detach inputs then call API ───────────────────────────────────────────
    const save = async () => {
        if (!nameInp.isConnected) return;   // guard: already saved or reverted
        const newName = nameInp.value.trim();
        const newBio  = bioInp.value.trim();
        if (!newName) { notify('Name cannot be empty.', 'error'); nameInp.focus(); return; }
        if (newName === oldName && newBio === oldBio) { revert(); return; }

        // Detach inputs immediately to prevent re-entrant blur saves
        const ns = document.createElement('span');
        ns.className   = 'ed-cc-name';
        ns.textContent = newName;           // optimistic; overwritten on success
        nameInp.replaceWith(ns);
        if (bioInp.isConnected) bioInp.remove();

        try {
            const res = await post(url, { name: newName, bio: newBio }, { json: true });
            if (res.success) {
                ns.textContent = res.name || newName;
                if (res.bio || newBio) {
                    const nb = document.createElement('p');
                    nb.className   = 'ed-cc-bio';
                    nb.textContent = res.bio || newBio;
                    ns.insertAdjacentElement('afterend', nb);
                }
                notify('Candidate updated.', 'success');
            } else {
                notify(res.error || 'Update failed.', 'error');
                _restoreOriginal(ns, oldName, oldBio);
            }
        } catch (err) {
            notify(err.message || 'Network error.', 'error');
            _restoreOriginal(ns, oldName, oldBio);
        }
    };

    // ── Keyboard: Enter = save-via-blur, Escape = revert ──────────────────────
    nameInp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter')  { e.preventDefault(); nameInp.blur(); }
        if (e.key === 'Escape') { revert(); }
    });
    bioInp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter')  { e.preventDefault(); bioInp.blur(); }
        if (e.key === 'Escape') { revert(); }
    });

    // ── Blur: save unless tabbing between the two sibling inputs ──────────────
    nameInp.addEventListener('blur', (e) => {
        if (e.relatedTarget === bioInp) return;
        save();
    });
    bioInp.addEventListener('blur', (e) => {
        if (e.relatedTarget === nameInp) return;
        save();
    });
}

/** Replace a temporary optimistic span with the original name/bio after an API error. */
function _restoreOriginal(ns, oldName, oldBio) {
    const rs = document.createElement('span');
    rs.className   = 'ed-cc-name';
    rs.textContent = oldName;
    ns.replaceWith(rs);
    if (oldBio) {
        const rb = document.createElement('p');
        rb.className   = 'ed-cc-bio';
        rb.textContent = oldBio;
        rs.insertAdjacentElement('afterend', rb);
    }
}

/* ── Candidate count helpers ── */

function getCandCount(postId) {
    const sel = document.getElementById('candPositionSelect');
    if (!sel) return 0;
    const opt = sel.querySelector(`option[value="${postId}"]`);
    return parseInt(opt?.dataset.count || '0', 10);
}

function updateCandCount(postId, newCount) {
    // Update position selector dropdown
    const sel = document.getElementById('candPositionSelect');
    if (sel) {
        const opt = sel.querySelector(`option[value="${postId}"]`);
        if (opt) {
            opt.dataset.count = newCount;
            const postName = opt.dataset.name || opt.textContent.split('(')[0].trim();
            opt.textContent = `${postName} (${newCount} candidate${newCount !== 1 ? 's' : ''})`;
        }
    }
    // Update inline card candidate count
    const posCard = document.querySelector(`#postsList .ed-pc[data-post-id="${postId}"]`);
    if (posCard) {
        const candsEl = posCard.querySelector('.ed-pc-cands');
        if (candsEl) candsEl.innerHTML = `<i class="fas fa-user-tie"></i> ${newCount} candidate${newCount !== 1 ? 's' : ''}`;
    }
}

/* ══════════════════════════════════════════════════════════════
   INLINE EXPAND/COLLAPSE — candidate panels under position cards
══════════════════════════════════════════════════════════════ */

function toggleCandPanel(postId) {
    const panel = document.getElementById(`candPanel-${postId}`);
    const btn = document.querySelector(`.ed-pc-expand-btn[data-post-id="${postId}"]`);
    if (!panel) return;

    const isOpen = panel.style.display !== 'none';
    panel.style.display = isOpen ? 'none' : '';
    if (btn) {
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = isOpen ? 'fas fa-chevron-down' : 'fas fa-chevron-up';
        }
        btn.title = isOpen ? 'Show candidates' : 'Hide candidates';
    }
}

function initExpandPanels() {
    document.querySelectorAll('.ed-pc-expand-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleCandPanel(btn.dataset.postId);
        });
    });
}

/* ══════════════════════════════════════════════════════════════
   CARD CLICK — toggle candidate panel on card click
══════════════════════════════════════════════════════════════ */
function initCardClick() {
    const list = document.getElementById('postsList');
    if (!list) return;
    list.addEventListener('click', (e) => {
        if (e.target.closest('.ed-pc-actions, .ed-pc-drag, .ed-pc-delete, .ed-pc-expand-btn, .ed-pc-cand-panel')) return;
        const card = e.target.closest('.ed-pc');
        if (!card) return;
        toggleCandPanel(card.dataset.postId);
    });
}

/* ══════════════════════════════════════════════════════════════
   EXPAND / IN-TAB TOGGLE — split ↔ stacked layout
══════════════════════════════════════════════════════════════ */

function initExpandToggle() {
    const btn   = document.getElementById('expandPostsBtn');
    const split = document.querySelector('#panel-posts .ed-posts-split');
    if (!btn || !split) return;

    const uuid       = window.electionUuid || '';
    const PREF_KEY   = `ed_posts_layout_${uuid}`;
    const isLaunched = !window.electionData?.isDraft;

    function apply(expanded) {
        split.classList.toggle('ed-posts-split--expanded', expanded);
        const icon = btn.querySelector('i');
        if (icon) icon.className = expanded ? 'fas fa-compress-alt' : 'fas fa-expand-alt';
        btn.title = expanded ? 'Switch to split view' : 'Expand to full view';
        try { localStorage.setItem(PREF_KEY, expanded ? 'expanded' : 'split'); } catch {}
    }

    let saved;
    try { saved = localStorage.getItem(PREF_KEY); } catch {}
    const initExpanded = saved !== null ? (saved === 'expanded') : isLaunched;
    apply(initExpanded);

    btn.addEventListener('click', () => {
        apply(!split.classList.contains('ed-posts-split--expanded'));
    });
}

/* ══════════════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════════════ */

export function initPostsTab() {
    /* ── Position entry rows ── */
    const addBtn = document.getElementById('addPostBtn');
    const errEl  = document.getElementById('postError');

    initEntryRows();

    const clearAllBtn = document.getElementById('clearAllEntries');
    if (clearAllBtn) clearAllBtn.addEventListener('click', resetEntries);

    if (addBtn) addBtn.addEventListener('click', () => addPosts(errEl));

    const container = document.getElementById('positionEntries');
    if (container) {
        container.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.classList.contains('ed-pf-entry-name')) {
                e.preventDefault();
                addPosts(errEl);
            }
        });
    }

    // Delete buttons (server-rendered cards)
    document.querySelectorAll('#panel-posts .ed-delete-post-btn').forEach(btn => {
        btn.addEventListener('click', () => deletePost(btn));
    });

    // FEAT-01: Rename buttons on server-rendered position cards
    document.querySelectorAll('#panel-posts .ed-pc-rename-btn').forEach(btn => {
        const card = btn.closest('.ed-pc');
        if (card) btn.addEventListener('click', () => renamePost(card));
    });

    initDragAndDrop();
    initImportSection();

    const deleteAllBtn = document.getElementById('deleteAllPostsBtn');
    if (deleteAllBtn) deleteAllBtn.addEventListener('click', deleteAllPosts);

    const pdfBtn = document.getElementById('downloadPositionsPdf');
    if (pdfBtn) pdfBtn.addEventListener('click', (e) => { e.preventDefault(); downloadPositionsPdf(); });

    initExpandToggle();

    /* ── Candidate entry rows ── */
    initCandEntryRows();

    const clearCandBtn = document.getElementById('clearAllCandEntries');
    if (clearCandBtn) clearCandBtn.addEventListener('click', resetCandEntries);

    const candAddBtn = document.getElementById('candAddBtn');
    const candErrEl  = document.getElementById('candFormError');
    if (candAddBtn) candAddBtn.addEventListener('click', () => addCandidates(candErrEl));

    const candContainer = document.getElementById('candidateEntries');
    if (candContainer) {
        candContainer.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.classList.contains('ed-cf-entry-name')) {
                e.preventDefault();
                addCandidates(candErrEl);
            }
        });
    }

    // Delete candidate buttons (server-rendered)
    document.querySelectorAll('#panel-posts .ed-delete-cand-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteCandidate(btn));
    });

    // Avatar click-to-upload (server-rendered)
    // NOTE: the server template only renders .ed-cc-avatar--editable when
    // election.can_edit is True — we rely on DOM presence, not the JS config
    // flag, so that a JSON-parse failure can never silently disable these.
    document.querySelectorAll('#panel-posts .ed-cc-avatar--editable').forEach(avatar => {
        const candId = avatar.dataset.candidateId;
        if (candId) avatar.addEventListener('click', () => triggerAvatarUpload(avatar, candId));
    });

    // FEAT-02: edit candidate name/bio (server-rendered cards)
    document.querySelectorAll('#panel-posts .ed-cc-edit-btn').forEach(btn => {
        const card = btn.closest('.ed-cc');
        if (card) btn.addEventListener('click', () => editCandidate(card));
    });

    // Candidate drag-to-reorder (server-rendered grids)
    document.querySelectorAll('#panel-posts .ed-cand-grid').forEach(grid => {
        initCandDragAndDrop(grid);
    });

    /* ── Inline expand panels ── */
    initExpandPanels();
    initCardClick();
}
