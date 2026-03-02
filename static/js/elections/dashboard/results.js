/**
 * dashboard/results.js — Results tab: winner cards, candidate tables,
 * summary stats, timeline stats, per-card view toggles, live SSE updates.
 *
 * Exports: initResultsTab (called by dashboard.js on tab activation)
 */
import {
    renderTurnoutGauge,
    renderPostDonut,
    renderPostBar,
    renderTimeline,
} from '../../modules/chart_manager.js';
import { getUrl } from './helpers.js';

// ─── Module state ────────────────────────────────────────────────────────────
let _lastUpdated  = null;   // Date of last successful fetch
let _tickInterval = null;   // "X ago" updater
let _refreshTimer = null;   // SSE debounce timer
const _viewMode = {};       // postId → 'donut' | 'bar'
const DEBOUNCE_MS = 2500;

// ─── Entry ───────────────────────────────────────────────────────────────────
export function initResultsTab() {
    loadCharts();
    initLiveIndicator();
    initBcCopyBtns();
    initResultSSEListeners();
    initRefreshBtn();
    initIntegrityCheck();
}

// ─── Data fetch ──────────────────────────────────────────────────────────────
async function loadCharts() {
    const url = getUrl('charts');
    if (!url) return;
    try {
        const res = await fetch(`${url}?type=all`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!res.ok) return;
        const json = await res.json();
        if (!json.success) return;

        _lastUpdated = new Date();

        const pie      = json.pie      || [];
        const turnout  = json.turnout  || {};
        const timeline = json.timeline || {};

        renderSummaryStats(turnout, pie);
        populateWinnerCards(pie);
        renderCandidateTables(pie);
        renderAllCharts(pie, turnout, timeline);
        renderTimelineStats(timeline);
    } catch (e) {
        console.warn('[results] loadCharts error:', e);
    }
}

// ─── Summary stat bar ────────────────────────────────────────────────────────
function renderSummaryStats(turnout, pie) {
    const pct    = turnout.turnout_pct ?? 0;
    const voted  = turnout.voted       ?? 0;
    const nPosts = pie.length;

    _setText('rsTurnout',  pct.toFixed(1) + '%');
    _setText('rsVotesCast', voted.toLocaleString());
    _setText('rsPositions', nPosts);
    _setText('rsLastUpdated', 'Just now');
}

// ─── Winner cards ─────────────────────────────────────────────────────────────
function populateWinnerCards(pieData) {
    const section = document.getElementById('edWinnerSection');
    if (!section) return;

    let anyWinner = false;
    pieData.forEach(post => {
        const nameEl  = document.getElementById(`winnerName${post.post_id}`);
        const pctEl   = document.getElementById(`winnerPct${post.post_id}`);
        const avatarEl = document.getElementById(`winnerAvatar${post.post_id}`);
        const card    = avatarEl && avatarEl.closest('.ed-winner-card');

        if (!nameEl) return;

        if (post.winner_name) {
            anyWinner = true;
            nameEl.textContent = post.winner_name;

            if (pctEl) {
                if (post.is_tied) {
                    pctEl.textContent = 'Tied';
                    pctEl.classList.add('ed-winner-tied');
                } else {
                    pctEl.textContent = (post.winner_pct || 0).toFixed(1) + '%';
                    pctEl.classList.remove('ed-winner-tied');
                }
            }
            if (avatarEl) {
                if (post.winner_image) {
                    avatarEl.innerHTML = `<img src="${post.winner_image}" alt="${post.winner_name}" loading="lazy">`;
                } else {
                    avatarEl.innerHTML = '<i class="fa-solid fa-user"></i>';
                }
            }
            if (card && post.is_tied) card.classList.add('ed-winner-card--tied');
        } else {
            if (nameEl)  nameEl.textContent = '—';
            if (pctEl)   pctEl.textContent  = 'No votes';
        }
    });

    section.style.display = anyWinner ? '' : 'none';
}

// ─── Candidate tables ─────────────────────────────────────────────────────────
function renderCandidateTables(pieData) {
    pieData.forEach(post => {
        const totalEl = document.getElementById(`posTotal${post.post_id}`);
        if (totalEl) totalEl.textContent = `${post.total} vote${post.total !== 1 ? 's' : ''}`;

        const tbody = document.getElementById(`posTableBody${post.post_id}`);
        if (!tbody) return;

        const rows = post.labels.map((label, i) => {
            const votes  = post.values[i] || 0;
            const pct    = post.total > 0 ? (votes / post.total * 100) : 0;
            const rank   = (post.ranks && post.ranks[i] != null) ? post.ranks[i] : i + 1;
            const candId = post.candidate_ids  && post.candidate_ids[i];
            const img    = post.candidate_images && post.candidate_images[i];
            const isNota    = !candId;
            const isWinner  = !post.is_tied && rank === 1 && votes > 0;
            const isTied    = post.is_tied  && rank === 1 && votes > 0;
            const rankClass = rank <= 3 ? `rank-${rank}` : '';

            const avatarHtml = img
                ? `<img src="${img}" alt="${label}" loading="lazy">`
                : '<i class="fa-solid fa-user"></i>';

            const badgeHtml = isWinner
                ? '<span class="ed-pos-winner-badge"><i class="fa-solid fa-check"></i> Winner</span>'
                : isTied
                ? '<span class="ed-pos-tied-badge"><i class="fa-solid fa-equals"></i> Tied</span>'
                : '';

            const idAttrs = candId
                ? `id="candRank${candId}"`
                : '';
            const avatarId = candId ? `id="candAvatar${candId}"` : '';
            const barId    = candId ? `id="candBar${candId}"`    : '';
            const countId  = candId ? `id="candCount${candId}"`  : '';
            const pctId    = candId ? `id="candPct${candId}"`    : '';

            return `
<tr class="${isNota ? 'ed-pos-tr--nota' : ''}" ${idAttrs}>
  <td class="ed-pos-td-rank">
    <span class="ed-pos-rank-circle ${rankClass}">${rank}</span>
  </td>
  <td class="ed-pos-td-cand">
    <div class="ed-pos-cand-info">
      <span class="ed-pos-cand-avatar" ${avatarId}>${avatarHtml}</span>
      <span class="ed-pos-cand-name">${label}${badgeHtml}</span>
    </div>
  </td>
  <td class="ed-pos-td-bar">
    <div class="ed-pos-bar-track">
      <div class="ed-pos-bar-fill ${rankClass}" ${barId}
           style="width:0%" data-pct="${pct.toFixed(2)}"></div>
    </div>
  </td>
  <td class="ed-pos-td-count" ${countId}>${votes.toLocaleString()}</td>
  <td class="ed-pos-td-pct"   ${pctId}>${pct.toFixed(1)}%</td>
</tr>`;
        });

        tbody.innerHTML = rows.join('');

        // Animate bars after paint
        requestAnimationFrame(() => {
            tbody.querySelectorAll('.ed-pos-bar-fill[data-pct]').forEach(el => {
                setTimeout(() => { el.style.width = el.dataset.pct + '%'; }, 80);
            });
        });
    });
}

// ─── Chart.js renders ─────────────────────────────────────────────────────────
function renderAllCharts(pie, turnout, timeline) {
    // Turnout gauge (canvas id established in template)
    if (Object.keys(turnout).length) {
        renderTurnoutGauge('chartTurnout', turnout);
    }

    // Per-position charts
    pie.forEach((post, idx) => {
        const canvasId = `chartPost${idx + 1}`;   // 1-based forloop.counter
        const view = _viewMode[post.post_id] || 'donut';
        _renderPostChart(canvasId, post, view);
    });

    // Timeline
    if (timeline.labels && timeline.labels.length) {
        renderTimeline('chartTimeline', timeline);
        const empty = document.getElementById('timelineEmpty');
        if (empty) empty.style.display = 'none';
    }

    // Wire per-card toggles the first time data arrives
    if (!Object.keys(_viewMode).length) {
        _initPerCardToggles(pie);
    }
}

function _renderPostChart(canvasId, post, view) {
    if (view === 'bar') {
        renderPostBar(canvasId, post);
    } else {
        renderPostDonut(canvasId, post);
    }
}

function _initPerCardToggles(pie) {
    document.querySelectorAll('[data-pos-card-id]').forEach(card => {
        const postId = parseInt(card.dataset.posCardId, 10);
        const idx    = pie.findIndex(p => p.post_id === postId);
        if (idx < 0) return;
        const post     = pie[idx];
        const canvasId = `chartPost${idx + 1}`;

        // Mark default active
        _viewMode[postId] = 'donut';
        const defaultBtn = card.querySelector('.ed-chart-toggle[data-view="donut"]');
        if (defaultBtn) defaultBtn.classList.add('active');

        card.querySelectorAll('.ed-chart-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const view = btn.dataset.view || 'donut';
                if (_viewMode[postId] === view) return;
                _viewMode[postId] = view;
                card.querySelectorAll('.ed-chart-toggle').forEach(b => b.classList.toggle('active', b === btn));
                _renderPostChart(canvasId, post, view);
            });
        });
    });
}

// ─── Timeline stats row ───────────────────────────────────────────────────────
function renderTimelineStats(timeline) {
    _setText('tlFirstVote', timeline.first_vote ? _fmtDate(timeline.first_vote) : '—');
    _setText('tlLastVote',  timeline.last_vote  ? _fmtDate(timeline.last_vote)  : '—');
    _setText('tlPeakHour',  timeline.peak_hour  || '—');
    _setText('tlPeakCount', timeline.peak_count ? `${timeline.peak_count} votes` : '—');
}

function _fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric',
            hour: 'numeric', minute: '2-digit',
        }).format(new Date(iso));
    } catch { return iso; }
}

// ─── Refresh button ───────────────────────────────────────────────────────────
function initRefreshBtn() {
    const btn = document.getElementById('rsRefreshBtn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        btn.classList.add('ed-refresh-btn--spinning');
        btn.disabled = true;
        try {
            await loadCharts();
        } finally {
            btn.classList.remove('ed-refresh-btn--spinning');
            btn.disabled = false;
        }
    });
}

// ─── "Last updated" ticker ────────────────────────────────────────────────────
function initLiveIndicator() {
    if (_tickInterval) clearInterval(_tickInterval);
    _tickInterval = setInterval(() => {
        const el = document.getElementById('rsLastUpdated');
        if (!el || !_lastUpdated) return;
        const s = Math.round((Date.now() - _lastUpdated.getTime()) / 1000);
        if      (s < 10)  el.textContent = 'Just now';
        else if (s < 60)  el.textContent = `${s}s ago`;
        else if (s < 3600) el.textContent = `${Math.round(s / 60)}m ago`;
        else              el.textContent = `${Math.round(s / 3600)}h ago`;
    }, 15_000);
}

// ─── SSE live refresh ─────────────────────────────────────────────────────────
function initResultSSEListeners() {
    document.addEventListener('sse:vote_cast', () => {
        clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(() => loadCharts(), DEBOUNCE_MS);
    });

    document.addEventListener('sse:election_concluded', () => {
        setTimeout(() => location.reload(), 1500);
    });

    // Legacy blockchain confirm event
    document.addEventListener('blockchainUpdate', e => {
        const detail = e.detail || {};
        if (detail.status === 'confirmed') {
            const el = document.getElementById('blockchainStatus');
            if (el) { el.textContent = 'Confirmed'; el.classList.add('ed-bc-confirmed'); }
        }
    });
}

// ─── Blockchain integrity check ───────────────────────────────────────────────
function initIntegrityCheck() {
    const btn    = document.getElementById('bcIntegrityBtn');
    const result = document.getElementById('bcIntegrityResult');
    if (!btn || !result) return;

    btn.addEventListener('click', async () => {
        const url = getUrl('integrity');
        if (!url) return;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking…';
        result.style.display = 'none';

        try {
            const res = await fetch(url, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            if (data.error) {
                result.innerHTML = `<div class="ed-bc-int-error"><i class="fas fa-exclamation-triangle"></i> ${_esc(data.error)}</div>`;
            } else {
                result.innerHTML = _buildIntegrityHtml(data);
            }
            result.style.display = '';
        } catch (e) {
            result.innerHTML = `<div class="ed-bc-int-error"><i class="fas fa-exclamation-triangle"></i> Integrity check failed: ${_esc(e.message)}</div>`;
            result.style.display = '';
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-balance-scale"></i> Verify';
        }
    });
}

function _buildIntegrityHtml(data) {
    const overall = data.match;
    const icon = overall
        ? '<i class="fas fa-check-circle"></i>'
        : '<i class="fas fa-times-circle"></i>';
    const cls  = overall ? 'ed-bc-int-match' : 'ed-bc-int-mismatch';
    const label = overall ? 'All Results Match' : 'Mismatch Detected';

    let html = `<div class="ed-bc-int-summary ${cls}">${icon} <strong>${label}</strong>`;
    html += `<span class="ed-bc-int-totals">DB: ${data.total_votes_db ?? '—'} &bull; Chain: ${data.total_votes_chain ?? '—'}</span>`;
    html += `</div>`;

    if (data.posts && data.posts.length) {
        html += '<div class="ed-bc-int-posts">';
        data.posts.forEach(post => {
            html += `<div class="ed-bc-int-post">`;
            html += `<div class="ed-bc-int-post-name">${_esc(post.post_name)}</div>`;
            html += '<div class="ed-bc-int-cands">';
            (post.candidates || []).forEach(c => {
                const m = c.match;
                const candCls = m ? 'ed-bc-int-cand--ok' : 'ed-bc-int-cand--fail';
                const candIcon = m ? '✓' : '✗';
                html += `<div class="ed-bc-int-cand ${candCls}">`;
                html += `<span class="ed-bc-int-cand-icon">${candIcon}</span>`;
                html += `<span class="ed-bc-int-cand-name">${_esc(c.candidate_name)}</span>`;
                html += `<span class="ed-bc-int-cand-counts">DB: ${c.db_count} / Chain: ${c.chain_count}</span>`;
                html += `</div>`;
            });
            html += '</div></div>';
        });
        html += '</div>';
    }

    return html;
}

function _esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

// ─── Clipboard helper (blockchain copy buttons) ───────────────────────────────
export function initBcCopyBtns() {
    document.querySelectorAll('[data-copy-target]').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = document.getElementById(btn.dataset.copyTarget);
            if (!target) return;
            navigator.clipboard.writeText(target.textContent.trim())
                .then(() => {
                    const orig = btn.innerHTML;
                    btn.innerHTML = '<i class="fa-solid fa-check"></i>';
                    setTimeout(() => { btn.innerHTML = orig; }, 1500);
                }).catch(() => {});
        });
    });
}

// ─── Internal util ────────────────────────────────────────────────────────────
function _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val != null ? val : '—';
}
