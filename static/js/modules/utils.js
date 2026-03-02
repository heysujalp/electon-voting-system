/**
 * ElectON V2 — Utility Functions
 */

/**
 * Execute callback when DOM is ready
 */
export function onDOMReady(callback) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', callback);
    } else {
        callback();
    }
}

/**
 * Initialize a page with standard setup
 */
export function initializePage(pageName, initFn) {
    onDOMReady(() => {
        try {
            initFn();
        } catch (error) {
            console.error(`[ElectON] Failed to initialize ${pageName}:`, error);
        }
    });
}

/**
 * Date utilities
 */
export const dateUtils = {
    format(date, locale = 'en-US') {
        return new Date(date).toLocaleDateString(locale, {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    },

    timeAgo(date) {
        const now = Date.now();
        const diff = now - new Date(date).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        const days = Math.floor(hrs / 24);
        return `${days}d ago`;
    },

    isExpired(date) { return new Date(date).getTime() < Date.now(); }
};

/**
 * URL utilities
 */
export const urlUtils = {
    getParam(name) { return new URLSearchParams(window.location.search).get(name); },
    setParam(name, value) {
        const url = new URL(window.location);
        url.searchParams.set(name, value);
        window.history.replaceState({}, '', url);
    },
    removeParam(name) {
        const url = new URL(window.location);
        url.searchParams.delete(name);
        window.history.replaceState({}, '', url);
    }
};

/**
 * Storage utilities
 */
export const storageUtils = {
    get(key, fallback = null) {
        try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
        catch { return fallback; }
    },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* */ } },
    remove(key) { localStorage.removeItem(key); }
};

/**
 * Memory utilities for performance monitoring
 */
export const memoryUtils = {
    getUsage() {
        if (performance?.memory) {
            return {
                usedJSHeapSize: performance.memory.usedJSHeapSize,
                totalJSHeapSize: performance.memory.totalJSHeapSize,
                jsHeapSizeLimit: performance.memory.jsHeapSizeLimit
            };
        }
        return null;
    }
};
