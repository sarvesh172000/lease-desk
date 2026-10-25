/** Shared by the toggle (client) and the layout's inline script (server). */
export const THEME_KEY = "leasedesk-theme";

/**
 * Runs before first paint, inlined in <head> by app/layout.tsx, so a light
 * reader never sees a dark flash. Storage can throw in a private window.
 */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
