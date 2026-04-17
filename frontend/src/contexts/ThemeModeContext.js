import { createContext } from 'react';

// Exposes the boolean dark/light toggle plus the setter to descendants.
// Default to `darkMode: true` so the UI renders in dark mode before App
// mounts and starts providing the real value from the cookie.
export const ThemeModeContext = createContext({
  darkMode: true,
  toggleDarkMode: () => {},
});
