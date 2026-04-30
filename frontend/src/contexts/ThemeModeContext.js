import { createContext } from 'react';

// Exposes the boolean dark/light toggle plus the setter to descendants.
// The interface (`{ darkMode: boolean, toggleDarkMode: () => void }`)
// is intentionally stable: every consumer in the app reads `darkMode`
// as a boolean (`MermaidBlock`'s render-effect dep, `useMermaid`'s
// initialize-on-toggle effect, `useExportFlow`'s mode argument,
// `MessageMarkdown`, `MermaidLightboxFallback`), and the boolean form
// outlasts the underlying state mechanism. Originally the value
// came from a top-level `useState(readThemeCookie)` in App.js; today
// it is derived inside `ThemeModeBridge` from MUI's
// `useColorScheme().mode === 'dark'` (mode itself is seeded by
// `defaultMode={readThemeCookie() ? 'dark' : 'light'}` on the
// CSS-variables-aware `ThemeProvider`, with localStorage piggybacking
// per MUI's mode-storage default), and `toggleDarkMode` wraps
// `useColorScheme().setMode(...)` plus a cookie write and a
// View Transitions / `flushSync` invocation. Consumers do not see
// any of that machinery; they keep reading the same boolean. See
// `App.js::ThemeModeBridge` for the wiring.
//
// `darkMode: true` as the default value fires only when a consumer
// is rendered outside any `ThemeModeContext.Provider` (i.e. tests,
// or a misconfigured tree). It mirrors the cookie's "no cookie set
// -> dark mode" default in `themeCookie.js`, so a stray consumer
// under no provider matches the cold-load look of the real app
// rather than flashing light.
export const ThemeModeContext = createContext({
  darkMode: true,
  toggleDarkMode: () => {},
});
