import { useEffect, useRef } from 'react';

import {
  DESKTOP_EVENT_TOGGLE_THEME,
  DESKTOP_EVENT_OPEN_ABOUT,
} from '../utils/desktopEvents';

// Bridges native desktop-menu actions into React state.
//
// The desktop menu (`cursor_view/desktop/menu.py`) lives in Python and cannot
// call React directly, so cross-mode actions are dispatched as window
// `CustomEvent`s (see `desktopEvents.js`) that this hook translates into the
// handlers the consumer passes in. Pure side-effect hook: it returns nothing,
// installs one listener per supported event, and removes every listener on
// cleanup.
//
// Safe to call unconditionally regardless of mode -- in terminal mode no menu
// ever dispatches these events, so the listeners simply never fire; there is
// no need to gate on `isDesktopMode()`.
//
// The handlers are read through a ref so the window listener is installed once
// and always invokes the latest callback, rather than re-subscribing whenever
// the consumer passes a fresh closure (`App.js::ThemeModeBridge` recreates
// `toggleDarkMode` every render). This mirrors the stable-callback discipline
// in `frontend-hooks.mdc`.
export function useDesktopMenuEvents({ onToggleTheme, onOpenAbout } = {}) {
  const handlersRef = useRef({ onToggleTheme, onOpenAbout });

  useEffect(() => {
    handlersRef.current.onToggleTheme = onToggleTheme;
    handlersRef.current.onOpenAbout = onOpenAbout;
  }, [onToggleTheme, onOpenAbout]);

  useEffect(() => {
    const handleToggleTheme = () => {
      const fn = handlersRef.current.onToggleTheme;
      if (typeof fn === 'function') {
        fn();
      }
    };
    const handleOpenAbout = () => {
      const fn = handlersRef.current.onOpenAbout;
      if (typeof fn === 'function') {
        fn();
      }
    };

    window.addEventListener(DESKTOP_EVENT_TOGGLE_THEME, handleToggleTheme);
    window.addEventListener(DESKTOP_EVENT_OPEN_ABOUT, handleOpenAbout);
    return () => {
      window.removeEventListener(DESKTOP_EVENT_TOGGLE_THEME, handleToggleTheme);
      window.removeEventListener(DESKTOP_EVENT_OPEN_ABOUT, handleOpenAbout);
    };
  }, []);
}
