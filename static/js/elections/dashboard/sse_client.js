/**
 * dashboard/sse_client.js — SSE EventSource manager for the election dashboard.
 *
 * Manages a single EventSource connection to the per-election SSE stream.
 * Auto-reconnects with exponential backoff on failure and falls back to
 * legacy 30-second polling if SSE is unsupported or fails repeatedly.
 *
 * Usage:
 *     import { onSSE, connectSSE, disconnectSSE } from './sse_client.js';
 *     onSSE('stats_update', (data) => { ... });
 *     connectSSE('/elections/<uuid>/stream/');
 */

const MAX_RETRIES = 5;
const BASE_DELAY  = 2000; // 2 s initial retry delay

let _es = null;
let _retries = 0;
let _listeners = {};
let _fallbackActive = false;
let _streamUrl = null;

/* ─── Public API ─── */

/**
 * Register a handler for a specific SSE event type.
 * Must be called BEFORE connectSSE() so all listeners are attached on connect.
 */
export function onSSE(eventType, handler) {
    if (!_listeners[eventType]) _listeners[eventType] = [];
    _listeners[eventType].push(handler);
}

/**
 * Open the EventSource connection to *streamUrl*.
 * If EventSource is not supported, dispatches the fallback event immediately.
 */
export function connectSSE(streamUrl) {
    _streamUrl = streamUrl;

    if (!window.EventSource) {
        console.warn('[SSE] EventSource not supported — using fallback polling.');
        _activateFallback();
        return;
    }

    _open();
}

/** Close the EventSource connection gracefully. */
export function disconnectSSE() {
    if (_es) {
        _es.close();
        _es = null;
    }
}

/** True when the SSE connection is open and receiving events. */
export function isSSEActive() {
    return _es !== null && _es.readyState !== EventSource.CLOSED;
}

/* ─── Internal helpers ─── */

function _open() {
    if (!_streamUrl) return;

    _es = new EventSource(_streamUrl);

    _es.onopen = () => {
        _retries = 0; // reset on successful connection
    };

    _es.onerror = () => {
        _es.close();
        _es = null;
        _retries++;

        if (_retries >= MAX_RETRIES) {
            console.warn(`[SSE] Failed ${_retries} times — switching to fallback polling.`);
            _activateFallback();
            return;
        }

        // Exponential backoff: 2s → 4s → 8s → 16s → 32s
        const delay = BASE_DELAY * Math.pow(2, _retries - 1);
        setTimeout(() => _open(), delay);
    };

    // Attach all registered listeners
    for (const [eventType, handlers] of Object.entries(_listeners)) {
        _es.addEventListener(eventType, (e) => {
            let data;
            try { data = JSON.parse(e.data); } catch { return; }
            for (const h of handlers) {
                try { h(data); } catch (err) { console.error('[SSE] handler error:', err); }
            }
        });
    }
}

/**
 * Notify dashboard.js to re-enable the legacy 30-second polling.
 * Only fires once per page load.
 */
function _activateFallback() {
    if (_fallbackActive) return;
    _fallbackActive = true;
    document.dispatchEvent(new CustomEvent('sse:fallback'));
}
