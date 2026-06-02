// Pure helpers for the global keyboard-shortcut system.
//
// Shortcut combos are written as lowercase '+'-separated strings, e.g.
// 'mod+t', 'mod+shift+i'. The 'mod' token resolves to the platform's primary
// accelerator modifier -- Cmd (metaKey) on macOS, Ctrl (ctrlKey) elsewhere --
// so a single binding works cross-platform. Recognized modifier tokens:
// 'mod', 'ctrl', 'meta', 'shift', 'alt'. The remaining token is the key,
// matched case-insensitively against `event.key` (never the deprecated
// `event.keyCode`).
//
// These are consumed by `useGlobalKeyboardShortcuts` (matching) and by
// `Header.js` (display, via `formatShortcut`). The display format here MUST
// match the accelerator hints `cursor_view/desktop/menu.py` appends to the
// native menu titles (Cmd glyph on macOS, `Ctrl+` prefix elsewhere).

export function isMac() {
  if (typeof navigator === 'undefined') {
    return false;
  }
  // `navigator.platform` is deprecated but still the most reliable signal in
  // embedded webviews; fall back to the UA string when it is unavailable.
  const platform = navigator.platform || navigator.userAgent || '';
  return /Mac|iPhone|iPad|iPod/i.test(platform);
}

// Render a key (e.g. 'T') as a human-readable shortcut hint: '⌘T' on macOS,
// 'Ctrl+T' elsewhere.
export function formatShortcut(keyLabel) {
  return isMac() ? `\u2318${keyLabel}` : `Ctrl+${keyLabel}`;
}

const MODIFIER_TOKENS = new Set(['mod', 'ctrl', 'meta', 'shift', 'alt']);

// Return true iff `event` matches the parsed `combo`. Modifier state must
// match exactly: a combo without 'shift' will not fire when Shift is held, so
// 'mod+t' cannot swallow 'mod+shift+t'.
export function eventMatchesCombo(event, combo) {
  const tokens = String(combo)
    .toLowerCase()
    .split('+')
    .map((t) => t.trim())
    .filter(Boolean);
  if (tokens.length === 0) {
    return false;
  }

  const mac = isMac();
  let wantCtrl = false;
  let wantMeta = false;
  let wantShift = false;
  let wantAlt = false;
  let keyToken = null;

  for (const token of tokens) {
    if (token === 'mod') {
      if (mac) {
        wantMeta = true;
      } else {
        wantCtrl = true;
      }
    } else if (token === 'ctrl') {
      wantCtrl = true;
    } else if (token === 'meta') {
      wantMeta = true;
    } else if (token === 'shift') {
      wantShift = true;
    } else if (token === 'alt') {
      wantAlt = true;
    } else if (!MODIFIER_TOKENS.has(token)) {
      keyToken = token;
    }
  }

  if (keyToken === null) {
    return false;
  }

  return (
    event.ctrlKey === wantCtrl &&
    event.metaKey === wantMeta &&
    event.shiftKey === wantShift &&
    event.altKey === wantAlt &&
    typeof event.key === 'string' &&
    event.key.toLowerCase() === keyToken
  );
}
