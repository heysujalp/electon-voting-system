/**
 * ElectON V2 — Lazy Module Loader
 * @deprecated This module has no consumers. Consider removing in next cleanup.
 */

const loadedModules = new Map();

/**
 * Dynamically import a module by path
 * @deprecated No consumers — unused export.
 */
export async function loadModule(path) {
    if (loadedModules.has(path)) return loadedModules.get(path);

    try {
        const mod = await import(path);
        loadedModules.set(path, mod);
        return mod;
    } catch (error) {
        console.error(`[ElectON] Failed to load module: ${path}`, error);
        throw error;
    }
}

/**
 * Preload multiple modules
 */
export async function preloadModules(paths) {
    return Promise.all(paths.map(p => loadModule(p)));
}

/**
 * Check if a module is already loaded
 */
export function isModuleLoaded(path) {
    return loadedModules.has(path);
}

/**
 * Get loading stats
 */
export function getModuleStats() {
    return { loaded: loadedModules.size, modules: Array.from(loadedModules.keys()) };
}
