import { useEffect } from 'react';
import axios from 'axios';

import { useDesktopReady } from './useDesktopReady';

const TOKEN_HEADER = 'X-Cursor-View-Token';

// Configures axios to send the desktop-mode loopback-auth token on every
// request, so the React app passes the `/api/*` gate installed by
// `cursor_view/desktop/auth.py`.
//
// The token is read once from the Python bridge (`pywebview.api.get_token()`)
// and set as a global default header on the shared axios instance every
// component already uses. Non-axios same-origin requests (notably
// `<img src="/api/chat/.../image/...">`) do not need this -- they inherit the
// `cursor-view-token` cookie the server set on the SPA HTML shell.
//
// Gated on `useDesktopReady` rather than a mount-time `isDesktopMode()` so the
// fetch runs once the bridge has actually been injected (pywebview injects
// `window.pywebview` after React mounts on Windows/WebView2 -- see
// `useDesktopReady`). A brief window before the header is set is harmless: the
// bootstrapped cookie is sent automatically with same-origin axios requests
// too, so early `/api/*` calls still authenticate. Terminal mode never
// becomes ready, so this is a no-op there and browser-mode requests are
// unauthenticated exactly as before.
export function useDesktopAuth() {
  const desktopReady = useDesktopReady();

  useEffect(() => {
    if (!desktopReady) {
      return undefined;
    }
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.get_token !== 'function') {
      return undefined;
    }

    let cancelled = false;
    Promise.resolve(api.get_token())
      .then((token) => {
        if (cancelled || typeof token !== 'string' || !token) {
          return;
        }
        axios.defaults.headers.common[TOKEN_HEADER] = token;
      })
      .catch(() => {
        // Bridge error reading the token: the bootstrapped cookie still
        // authenticates same-origin requests, so there is nothing to
        // surface to the user here.
      });

    return () => {
      cancelled = true;
    };
  }, [desktopReady]);
}
