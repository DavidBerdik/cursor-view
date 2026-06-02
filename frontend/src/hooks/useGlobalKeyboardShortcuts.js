import { useEffect, useRef } from 'react';

import { eventMatchesCombo } from '../utils/keyboardShortcuts';

// Registers a single global `keydown` listener that dispatches to the
// caller-supplied shortcut bindings.
//
// One concern only (per `frontend-hooks.mdc`): combo matching + dispatch. The
// consumer composes its own `shortcuts` map (`{ 'mod+t': () => ... }`), so the
// hook stays agnostic about which actions exist and which mode they apply to
// -- `App.js` populates the map only in desktop mode, where the native menu's
// (display-only) accelerators need a real binding because pywebview cannot
// bind them itself.
//
// The map is read through a ref so the single listener is installed once and
// always sees the latest bindings, rather than re-subscribing whenever the
// consumer passes a fresh object/closure. `event.preventDefault()` fires only
// when a binding actually matches, so unrelated keystrokes (and native webview
// edit shortcuts like Cmd/Ctrl+C) pass through untouched.
export function useGlobalKeyboardShortcuts(shortcuts) {
  const shortcutsRef = useRef(shortcuts);

  useEffect(() => {
    shortcutsRef.current = shortcuts;
  }, [shortcuts]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      const map = shortcutsRef.current;
      if (!map) {
        return;
      }
      for (const combo of Object.keys(map)) {
        if (eventMatchesCombo(event, combo)) {
          const handler = map[combo];
          if (typeof handler === 'function') {
            event.preventDefault();
            handler();
          }
          return;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);
}
