/**
 * chart_manager.js — ElectON v2 Chart.js wrapper (Phase 6)
 *
 * Renders interactive, dark-mode-aware charts on the Results tab.
 * Uses the Chart.js global (loaded via CDN in the dashboard template).
 */

/* ═══════════════════════════════════════════════════════════════
   PALETTE (matches Apple HIG tokens)
   ═══════════════════════════════════════════════════════════════ */
const COLORS = [
    '#007AFF', '#34C759', '#FF9500', '#FF3B30',
    '#AF52DE', '#5856D6', '#FF2D55', '#00C7BE',
    '#FFD60A', '#8E8E93',
];

const COLORS_50 = COLORS.map(c => c + '80'); // 50% opacity variants

/** Detect dark mode from <html data-theme="dark"> */
function isDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark';
}

/** Get text color matching current theme */
function textColor() {
    return isDark() ? '#f5f5f7' : '#1d1d1f';
}

/** Get subtle grid / border color */
function gridColor() {
    return isDark() ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.06)';
}

/* ═══════════════════════════════════════════════════════════════
   CHART REGISTRY (for theme-switching & cleanup)
   ═══════════════════════════════════════════════════════════════ */
const _charts = {};

/** Destroy a previous chart instance by key before recreating. */
function destroy(key) {
    if (_charts[key]) {
        _charts[key].destroy();
        delete _charts[key];
    }
}

/* ═══════════════════════════════════════════════════════════════
   TURNOUT GAUGE (Doughnut — single-metric)
   ═══════════════════════════════════════════════════════════════ */
export function renderTurnoutGauge(canvasId, data) {
    if (typeof Chart === 'undefined') return null;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    destroy(canvasId);

    const voted = data.voted || 0;
    const notVoted = data.not_voted || 0;

    const chart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Voted', 'Not Voted'],
            datasets: [{
                data: [voted, notVoted],
                backgroundColor: ['#34C759', isDark() ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.06)'],
                borderWidth: 0,
                borderRadius: 6,
                spacing: 2,
            }],
        },
        options: {
            cutout: '75%',
            responsive: false,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: isDark() ? '#2c2c2e' : '#fff',
                    titleColor: textColor(),
                    bodyColor: textColor(),
                    borderColor: gridColor(),
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 10,
                    callbacks: {
                        label: ctx => `${ctx.label}: ${ctx.raw}`,
                    },
                },
            },
            animation: {
                animateRotate: true,
                duration: 1200,
                easing: 'easeOutQuart',
            },
        },
    });
    _charts[canvasId] = chart;
    return chart;
}

/* ═══════════════════════════════════════════════════════════════
   PER-POST DONUT CHART
   ═══════════════════════════════════════════════════════════════ */
export function renderPostDonut(canvasId, postData) {
    if (typeof Chart === 'undefined') return null;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    destroy(canvasId);

    const colors = postData.colors || COLORS.slice(0, postData.labels.length);

    const chart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: postData.labels,
            datasets: [{
                data: postData.values,
                backgroundColor: colors,
                borderWidth: 0,
                borderRadius: 4,
                spacing: 2,
            }],
        },
        options: {
            cutout: '60%',
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: textColor(),
                        font: { size: 11, family: 'Inter, -apple-system, sans-serif', weight: '500' },
                        padding: 12,
                        usePointStyle: true,
                        pointStyleWidth: 8,
                    },
                },
                tooltip: {
                    backgroundColor: isDark() ? '#2c2c2e' : '#fff',
                    titleColor: textColor(),
                    bodyColor: textColor(),
                    borderColor: gridColor(),
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 10,
                    callbacks: {
                        label: ctx => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = total > 0 ? ((ctx.raw / total) * 100).toFixed(1) : 0;
                            return `${ctx.label}: ${ctx.raw} votes (${pct}%)`;
                        },
                    },
                },
            },
            animation: {
                animateRotate: true,
                duration: 1000,
                easing: 'easeOutQuart',
            },
        },
    });
    _charts[canvasId] = chart;
    return chart;
}

/* ═══════════════════════════════════════════════════════════════
   PER-POST HORIZONTAL BAR CHART
   ═══════════════════════════════════════════════════════════════ */
export function renderPostBar(canvasId, postData) {
    if (typeof Chart === 'undefined') return null;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Dynamic canvas height: give each bar ~48px so long names aren't clipped
    const nLabels = (postData.labels || []).length;
    const minH = 180;
    const calcH = Math.max(minH, nLabels * 48 + 40);
    canvas.style.height = calcH + 'px';
    canvas.parentElement.style.height = calcH + 'px';

    destroy(canvasId);

    const colors = postData.colors || COLORS.slice(0, postData.labels.length);

    const chart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: postData.labels,
            datasets: [{
                data: postData.values,
                backgroundColor: colors.map(c => c + 'CC'),
                borderColor: colors,
                borderWidth: 1,
                borderRadius: 6,
                barPercentage: 0.7,
            }],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: isDark() ? '#2c2c2e' : '#fff',
                    titleColor: textColor(),
                    bodyColor: textColor(),
                    borderColor: gridColor(),
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 10,
                    callbacks: {
                        label: ctx => `${ctx.raw} votes`,
                    },
                },
            },
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: { color: textColor(), font: { size: 11 }, precision: 0 },
                    grid: { color: gridColor() },
                },
                y: {
                    ticks: {
                        color: textColor(),
                        font: { size: 12, weight: '500' },
                        // Truncate very long names with ellipsis at 28 chars
                        callback: function(value) {
                            const label = this.getLabelForValue(value);
                            return label.length > 28 ? label.slice(0, 26) + '…' : label;
                        },
                    },
                    grid: { display: false },
                    afterFit: (axis) => { axis.width = Math.max(axis.width, 140); },
                },
            },
            animation: { duration: 800, easing: 'easeOutQuart' },
        },
    });
    _charts[canvasId] = chart;
    return chart;
}

/* ═══════════════════════════════════════════════════════════════
   VOTING TIMELINE (Line + Cumulative)
   ═══════════════════════════════════════════════════════════════ */
export function renderTimeline(canvasId, timelineData) {
    if (typeof Chart === 'undefined') return null;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    destroy(canvasId);

    if (!timelineData.labels || timelineData.labels.length === 0) {
        return null; // caller handles "no data" message
    }

    // Abbreviate labels for display
    const labels = timelineData.labels.map(l => {
        const d = new Date(l);
        return isNaN(d) ? l : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    });

    const chart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Votes / Hour',
                    data: timelineData.hourly,
                    borderColor: '#007AFF',
                    backgroundColor: 'rgba(0,122,255,.08)',
                    fill: true,
                    tension: 0.35,
                    pointRadius: 4,
                    pointBackgroundColor: '#007AFF',
                    pointBorderWidth: 0,
                    borderWidth: 2,
                    yAxisID: 'y',
                },
                {
                    label: 'Cumulative',
                    data: timelineData.cumulative,
                    borderColor: '#FF9500',
                    backgroundColor: 'transparent',
                    borderDash: [6, 3],
                    tension: 0.35,
                    pointRadius: 3,
                    pointBackgroundColor: '#FF9500',
                    pointBorderWidth: 0,
                    borderWidth: 2,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    labels: {
                        color: textColor(),
                        font: { size: 11, family: 'Inter, -apple-system, sans-serif' },
                        usePointStyle: true,
                        pointStyleWidth: 8,
                        padding: 14,
                    },
                },
                tooltip: {
                    backgroundColor: isDark() ? '#2c2c2e' : '#fff',
                    titleColor: textColor(),
                    bodyColor: textColor(),
                    borderColor: gridColor(),
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 10,
                },
            },
            scales: {
                x: {
                    ticks: { color: textColor(), font: { size: 10 }, maxRotation: 45 },
                    grid: { color: gridColor() },
                },
                y: {
                    position: 'left',
                    beginAtZero: true,
                    title: { display: true, text: 'Votes / Hour', color: '#007AFF', font: { size: 11 } },
                    ticks: { color: textColor(), font: { size: 10 }, precision: 0 },
                    grid: { color: gridColor() },
                },
                y1: {
                    position: 'right',
                    beginAtZero: true,
                    title: { display: true, text: 'Cumulative', color: '#FF9500', font: { size: 11 } },
                    ticks: { color: textColor(), font: { size: 10 }, precision: 0 },
                    grid: { drawOnChartArea: false },
                },
            },
            animation: { duration: 1000, easing: 'easeOutQuart' },
        },
    });
    _charts[canvasId] = chart;
    return chart;
}

/* ═══════════════════════════════════════════════════════════════
   THEME UPDATE (re-render all active charts with new colors)
   ═══════════════════════════════════════════════════════════════ */
export function updateChartsTheme() {
    Object.values(_charts).forEach(chart => {
        if (!chart) return;
        // Update tooltip and scale colors
        const opts = chart.options;
        if (opts.plugins?.tooltip) {
            opts.plugins.tooltip.backgroundColor = isDark() ? '#2c2c2e' : '#fff';
            opts.plugins.tooltip.titleColor = textColor();
            opts.plugins.tooltip.bodyColor = textColor();
            opts.plugins.tooltip.borderColor = gridColor();
        }
        if (opts.plugins?.legend?.labels) {
            opts.plugins.legend.labels.color = textColor();
        }
        ['x', 'y', 'y1'].forEach(axis => {
            if (opts.scales?.[axis]) {
                if (opts.scales[axis].ticks) opts.scales[axis].ticks.color = textColor();
                if (opts.scales[axis].grid) opts.scales[axis].grid.color = gridColor();
            }
        });
        chart.update('none');
    });
}

/** Destroy all tracked chart instances. */
export function destroyAll() {
    Object.keys(_charts).forEach(destroy);
}
