// Read/write the `themeMode` cookie that persists the user's light/dark
// mode choice across sessions. The cookie is also read by the Python
// side (see export_theme resolution) so the exported HTML can render in
// the same mode the user was viewing when they hit Export.

export function readThemeCookie() {
  const match = document.cookie
    .split('; ')
    .find((r) => r.startsWith('themeMode='));
  return match ? match.split('=')[1] !== 'light' : true;
}

export function writeThemeCookie(isDark) {
  const expiry = new Date();
  expiry.setFullYear(expiry.getFullYear() + 1);
  document.cookie = `themeMode=${isDark ? 'dark' : 'light'}; expires=${expiry.toUTCString()}; path=/`;
}
