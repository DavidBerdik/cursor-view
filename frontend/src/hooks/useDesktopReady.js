import { useEffect, useState } from 'react';

import { isDesktopMode } from '../utils/mode';

// Reactive desktop-runtime readiness signal.
//
// `isDesktopMode()` (in `utils/mode.js`) checks `!!window.pywebview`, which is
// the right primitive for *call-time* gates (event handlers, action callbacks)
// but is racy at *render/mount time*: pywebview's Windows/WebView2 backend
// injects `window.pywebview` from its `NavigationCompleted` callback, which
// runs after the React bundle has executed and `App` has already mounted. A
// render-time `isDesktopMode()` therefore returns `false` on first render and
// pywebview's later injection triggers no React re-render -- so any memo or
// effect gated on the synchronous check stays stuck in its initial state
// forever (the symptom that broke the keyboard shortcut map in `App.js`).
//
// This hook closes the gap: it seeds from the synchronous check (so callers
// that mount *after* pywebview is ready still see `true` on first render),
// then subscribes to the `pywebviewready` event that pywebview's `finish.js`
// dispatches once `window.pywebview._createApi` has populated the bridge.
// Returns a boolean -- one concern only, per
// `.cursor/rules/frontend-hooks.mdc`.
export function useDesktopReady() {
  const [ready, setReady] = useState(() => isDesktopMode());

  useEffect(() => {
    if (isDesktopMode()) {
      // Covers the case where pywebview injected between render and
      // effect commit (the synchronous check missed it at render but
      // catches it here). Also handles the "pywebviewready already
      // fired before this effect attached" case: the event is one-shot
      // and not replayed, but `window.pywebview` is present so the
      // check is sufficient.
      setReady(true);
      return undefined;
    }
    const onReady = () => setReady(true);
    window.addEventListener('pywebviewready', onReady);
    return () => {
      window.removeEventListener('pywebviewready', onReady);
    };
  }, []);

  return ready;
}
