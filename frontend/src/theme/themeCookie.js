import { getCookie, oneYearFromNow, setCookie } from '../utils/cookies';

// Read/write the `themeMode` cookie that persists the user's light/dark
// mode choice across sessions. The cookie is also read by the Python
// side (see export_theme resolution) so the exported HTML can render in
// the same mode the user was viewing when they hit Export.

const COOKIE_NAME = 'themeMode';

export function readThemeCookie() {
  // Absent cookie or any value other than "light" maps to dark; this
  // preserves the pre-utility behavior where the cookie defaults to
  // dark mode when the user has never toggled the theme.
  return getCookie(COOKIE_NAME) !== 'light';
}

export function writeThemeCookie(isDark) {
  setCookie(COOKIE_NAME, isDark ? 'dark' : 'light', { expires: oneYearFromNow() });
}
