/**
 * ElectON V2 — State Management Module
 */

/**
 * Simple key-value state store backed by localStorage
 */
export class StateStore {
    constructor(namespace = 'electon') {
        this.namespace = namespace;
    }

    _key(k) { return `${this.namespace}_${k}`; }

    get(key, fallback = null) {
        try {
            const v = localStorage.getItem(this._key(key));
            return v !== null ? JSON.parse(v) : fallback;
        } catch { return fallback; }
    }

    set(key, value) {
        try { localStorage.setItem(this._key(key), JSON.stringify(value)); } catch { /* quota exceeded */ }
    }

    remove(key) { localStorage.removeItem(this._key(key)); }

    clear() {
        const prefix = `${this.namespace}_`;
        Object.keys(localStorage).filter(k => k.startsWith(prefix)).forEach(k => localStorage.removeItem(k));
    }
}

/**
 * FormStateManager — track form dirty state
 */
export class FormStateManager {
    constructor(form) {
        this.form = form;
        this.initialData = this._snapshot();
    }

    _snapshot() {
        return Object.fromEntries(new FormData(this.form).entries());
    }

    isDirty() {
        const current = this._snapshot();
        return JSON.stringify(current) !== JSON.stringify(this.initialData);
    }

    reset() { this.initialData = this._snapshot(); }
}

/**
 * Simple reactive store (pub/sub)
 */
export function createStore(initialState = {}) {
    let state = { ...initialState };
    const listeners = new Set();

    return {
        getState: () => ({ ...state }),
        setState: (patch) => {
            state = { ...state, ...patch };
            listeners.forEach(fn => fn(state));
        },
        subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); }
    };
}
