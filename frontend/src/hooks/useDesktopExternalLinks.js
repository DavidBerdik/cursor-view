import { useEffect } from 'react';

import { isDesktopMode } from '../utils/mode';

// Routes external (non-same-origin) link clicks to the OS default browser
// through the pywebview bridge when running in the desktop shell.
//
// Inside an embedded webview a plain `<a href="https://..." target="_blank">`
// either navigates the webview away from the loopback app or (depending on the
// backend) opens an unstyled second pywebview window. Round-tripping through
// `pywebview.api.open_url_in_browser` (which validates the http/https
// allowlist Python-side) gets a real sibling tab in the user's default
// browser instead. Only the right-click "Open in Browser Tab" item in
// `AppContextMenu` did this before; this global interceptor covers every
// anchor -- the Header GitHub button, links rendered inside chat content, the
// image-lightbox "open in new tab" affordance -- without touching their
// markup.
//
// Pure side-effect hook (per `frontend-hooks.mdc`): returns nothing, takes no
// arguments (one global listener), and removes every listener on cleanup.
// Safe to call unconditionally -- the handler no-ops outside desktop mode, so
// terminal/browser mode keeps its native `<a>` behavior entirely.
export function useDesktopExternalLinks() {
  useEffect(() => {
    const routeIfExternal = (event) => {
      // Call-time gate (not render-time): by the time a user clicks,
      // pywebview has long since injected `window.pywebview`, so the
      // mount-time readiness race that bites `useMemo`/render paths does
      // not apply here.
      if (!isDesktopMode()) {
        return;
      }
      // Ignore right-click (and any non-middle auxiliary button): the
      // context menu owns that path. `auxclick` fires for every
      // non-primary button, so middle-click is button 1 and right-click
      // is button 2.
      if (event.type === 'auxclick' && event.button !== 1) {
        return;
      }
      // Some other handler already consumed this click.
      if (event.defaultPrevented) {
        return;
      }

      const target = event.target;
      if (!target || typeof target.closest !== 'function') {
        return;
      }
      // Anchors and image-map <area> elements both implement
      // HTMLHyperlinkElementUtils (href / origin / protocol).
      const link = target.closest('a[href], area[href]');
      if (!link) {
        return;
      }
      // Preserve native behavior for downloads -- the bridge only knows
      // how to hand a URL to the system browser, which would defeat a
      // "save this file" affordance.
      if (link.hasAttribute('download')) {
        return;
      }
      // Only http/https are routed: the bridge rejects every other
      // scheme, and intercepting e.g. mailto:/tel: here would swallow the
      // click instead of letting the platform handle it natively.
      if (link.protocol !== 'http:' && link.protocol !== 'https:') {
        return;
      }
      // Same-origin (loopback) links are in-app navigation (react-router
      // Links, image routes, etc.) and must stay inside the webview.
      if (link.origin === window.location.origin) {
        return;
      }

      const api = window.pywebview && window.pywebview.api;
      if (!api || typeof api.open_url_in_browser !== 'function') {
        // Bridge not ready yet: fall through to native behavior rather
        // than swallowing the click.
        return;
      }

      // Cover middle-click and modifier-click (Cmd/Ctrl/Shift) too -- in
      // desktop mode every variant should land in the single OS browser
      // tab rather than spawning a second webview window. Fire-and-forget:
      // the bridge validates, logs its own failures, and returns a dict
      // the caller does not need.
      event.preventDefault();
      api.open_url_in_browser(link.href);
    };

    // Capture phase so the interceptor runs before react-router or any
    // component-level click handler can act on the anchor.
    document.addEventListener('click', routeIfExternal, true);
    document.addEventListener('auxclick', routeIfExternal, true);
    return () => {
      document.removeEventListener('click', routeIfExternal, true);
      document.removeEventListener('auxclick', routeIfExternal, true);
    };
  }, []);
}
