import React, { useMemo } from 'react';
import { flushSync } from 'react-dom';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider, useColorScheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';

import ChatList from './components/chat-list/ChatList';
import ChatDetail from './components/chat-detail/ChatDetail';
import Header from './components/Header';
import AppContextMenu from './components/AppContextMenu';
import { ThemeModeContext } from './contexts/ThemeModeContext';
import { useDesktopExternalLinks } from './hooks/useDesktopExternalLinks';
import { useDesktopMenuEvents } from './hooks/useDesktopMenuEvents';
import { useDesktopReady } from './hooks/useDesktopReady';
import { useGlobalKeyboardShortcuts } from './hooks/useGlobalKeyboardShortcuts';
import { buildTheme } from './theme/buildTheme';
import { readThemeCookie, writeThemeCookie } from './theme/themeCookie';

// Disable the browser's built-in scroll restoration so it cannot fire
// during the loading spinner (when the page is too short to reach the saved
// position) and silently reset scroll to 0. ChatDetail owns manual scroll
// restoration via sessionStorage for the chat detail page.
if ('scrollRestoration' in window.history) {
  window.history.scrollRestoration = 'manual';
}

// Theme is built once at module load; after H1 it is fully static
// (both schemes baked into `colorSchemes`), so the previous per-render
// `useMemo` rebuild on `darkMode` change is gone. MUI's CSS-variables-
// aware `ThemeProvider` picks the active scheme at emit time from
// `defaultMode` + `useColorScheme().setMode`, not at build time.
const theme = buildTheme();

// Initial mode read from the persistent cookie. `ThemeProvider`'s
// `defaultMode` is honored only when the browser's localStorage is
// empty for MUI's mode key; if the user has toggled previously,
// localStorage takes precedence on subsequent loads. Our
// `toggleDarkMode` wrapper writes BOTH the cookie (explicitly via
// `writeThemeCookie`) and localStorage (implicitly via `setMode`),
// so the two stay in sync after every toggle. Cookie wins on cold
// load only when localStorage is empty (e.g. user cleared site data
// but the cookie survived), which is the intended fallback. The
// cookie is also read by the Python export pipeline so exported
// HTML matches the user's chosen theme; that contract motivates
// keeping cookie write parity with the localStorage write here.
const initialMode = readThemeCookie() ? 'dark' : 'light';

// Bridge between MUI's `useColorScheme()` (which must be called
// inside the CSS-variables-aware `ThemeProvider`) and the existing
// `ThemeModeContext` shape (`{ darkMode: boolean, toggleDarkMode:
// () => void }`). Palette consumers no longer read from React
// context at all -- they reference `var(--mui-palette-*)` CSS
// variables directly, which the browser swaps on
// `data-mui-color-scheme` flip without any React re-render. This
// bridge survives only as the toggle/state layer: components that
// need the boolean `darkMode` (e.g. `MermaidBlock`'s render-effect
// dep, `useMermaid`'s initialize-on-toggle effect, `useExportFlow`'s
// mode argument) still read it from `ThemeModeContext` rather than
// calling `useColorScheme()` themselves, so the boolean-vs-string
// API decision stays one place.
function ThemeModeBridge({ children }) {
  const { mode, setMode } = useColorScheme();
  // `mode` may be `'light' | 'dark' | 'system' | undefined`. We
  // never put the provider in 'system' mode (no UI exposes it) and
  // `defaultMode` is set explicitly, so anything other than 'dark'
  // is treated as light here. Defaulting to false on undefined
  // keeps the first-render closure from crashing during the brief
  // window before `useColorScheme` resolves the initial mode.
  const darkMode = mode === 'dark';

  // `toggleDarkMode` retains the View Transitions + flushSync shape
  // from before the migration. `setMode` triggers an internal
  // ThemeProvider state update that flips `data-mui-color-scheme`
  // on `<html>`; `flushSync` forces React to commit that update
  // synchronously inside the View Transition callback so the
  // browser captures the post-snapshot from a DOM that already
  // reflects the new scheme. Without `flushSync`, React would
  // batch the update past the post-snapshot capture and the View
  // Transition would cross-fade two identical snapshots (no
  // visible animation). The fallback path covers browsers without
  // View Transitions (Chromium <111, Safari <18, Firefox <137).
  const toggleDarkMode = () => {
    const next = !darkMode;
    const nextMode = next ? 'dark' : 'light';
    writeThemeCookie(next);
    if (typeof document.startViewTransition === 'function') {
      document.startViewTransition(() => {
        flushSync(() => setMode(nextMode));
      });
      return;
    }
    setMode(nextMode);
  };

  // Translate native desktop-menu actions (View -> Toggle Theme today)
  // into the same toggle the Header button drives. Installed here, at the
  // single ThemeModeBridge mount, so the listener is global and shares the
  // exact toggle path (cookie write + View Transition) rather than
  // duplicating theme logic on the Python side. No-op in terminal mode.
  useDesktopMenuEvents({ onToggleTheme: toggleDarkMode });

  // Route external (non-same-origin) link clicks to the OS default browser
  // through the bridge in desktop mode, so a `<a target="_blank">` (the
  // Header GitHub button, links in chat content, the image lightbox) opens a
  // real browser tab instead of navigating the embedded webview away or
  // spawning an unstyled second pywebview window. No-op in terminal mode.
  useDesktopExternalLinks();

  // Global keyboard shortcuts. Bound only in desktop mode: in browser mode
  // these combos collide with the browser's own (Ctrl/Cmd+T new tab,
  // Ctrl/Cmd+R reload, Ctrl/Cmd+Q quit), so we leave the browser in charge
  // there. In the chromeless desktop window the same combos are the only way
  // to drive Reload / Quit / Toggle Theme by keyboard, since pywebview cannot
  // bind the accelerators it displays in the native menu (see
  // cursor_view/desktop/menu.py). Reload and Quit route through the bridge so
  // the menu, the keyboard, and any future affordance share one code path;
  // theme reuses the same toggle as the menu and Header button. The empty map
  // in terminal mode means the hook's listener never matches anything. Edit
  // shortcuts (Cmd/Ctrl+C etc.) are intentionally absent so the embedded
  // webview keeps handling them natively.
  //
  // The gate is `desktopReady` (reactive), NOT a render-time
  // `isDesktopMode()` call. pywebview's WebView2 backend injects
  // `window.pywebview` from `NavigationCompleted`, which runs after the React
  // bundle has executed and `App` has already mounted -- so a synchronous
  // mount-time check sees `false`, this memo would resolve to `{}`, and
  // pywebview's later injection would never re-fire the memo (its only other
  // dep being `darkMode`). `useDesktopReady` flips `true` when pywebview's
  // `pywebviewready` event fires, the memo recomputes, and the shortcut map
  // is installed.
  const desktopReady = useDesktopReady();
  const shortcuts = useMemo(() => {
    if (!desktopReady) {
      return {};
    }
    const callBridge = (method) => {
      const api = typeof window !== 'undefined' && window.pywebview && window.pywebview.api;
      if (api && typeof api[method] === 'function') {
        api[method]();
      }
    };
    return {
      'mod+t': () => toggleDarkMode(),
      'mod+r': () => callBridge('reload_window'),
      'mod+q': () => callBridge('quit_app'),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [darkMode, desktopReady]);
  useGlobalKeyboardShortcuts(shortcuts);

  // Memoize the context value so consumers re-render only when
  // `darkMode` actually flips, not on every parent re-render.
  // `setMode` is already a stable reference from `useColorScheme`,
  // so `toggleDarkMode`'s closure is correct as long as it
  // recomputes whenever `darkMode` changes -- which it does, since
  // `darkMode` is the only `useMemo` dep.
  const themeModeValue = useMemo(
    () => ({ darkMode, toggleDarkMode }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [darkMode],
  );

  return (
    <ThemeModeContext.Provider value={themeModeValue}>
      {children}
    </ThemeModeContext.Provider>
  );
}

function App() {
  return (
    <ThemeProvider theme={theme} defaultMode={initialMode}>
      <CssBaseline />
      <ThemeModeBridge>
        <Router>
          <Header />
          <AppContextMenu />
          <Routes>
            <Route path="/" element={<ChatList />} />
            <Route path="/chat/:sessionId" element={<ChatDetail />} />
          </Routes>
        </Router>
      </ThemeModeBridge>
    </ThemeProvider>
  );
}

export default App;
