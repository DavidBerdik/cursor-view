// Custom-event names dispatched from the native desktop menu (and, in
// Improvement 06, the global keyboard shortcuts) into the React app.
//
// These are the contract between the Python bridge and the React UI: the
// desktop menu lives in `cursor_view/desktop/menu.py` and cannot touch React
// state directly, so cross-mode menu actions are delivered as
// `window.dispatchEvent(new CustomEvent(<name>))` calls issued by
// `cursor_view/desktop/api.py`'s bridge methods. The listeners that translate
// them back into React callbacks live in `useDesktopMenuEvents`.
//
// The string values MUST stay byte-for-byte in sync with the matching
// constants in `cursor_view/desktop/api.py` (e.g. `EVENT_TOGGLE_THEME`).
export const DESKTOP_EVENT_TOGGLE_THEME = 'cursor-view:toggle-theme';
