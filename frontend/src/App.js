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
