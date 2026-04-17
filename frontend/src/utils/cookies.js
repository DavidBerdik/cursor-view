// Minimal document.cookie getter/setter so feature code doesn't keep
// re-implementing the same `split('; ').find(...)` dance. Intentionally
// small: the app only needs name-keyed string values with a path and an
// optional expiry.

// Return the raw string value of cookie `name`, or undefined if not set.
// Values are returned verbatim (no URL decoding) since every existing
// caller writes plain ASCII tokens like "true", "dark", "light".
export function getCookie(name) {
  const prefix = `${name}=`;
  const row = document.cookie
    .split('; ')
    .find((r) => r.startsWith(prefix));
  return row ? row.slice(prefix.length) : undefined;
}

// Write a cookie at path=/. Pass `{ expires: Date }` to make it
// persistent; without an expiry the browser treats it as session-only.
export function setCookie(name, value, { expires } = {}) {
  let cookieStr = `${name}=${value}; path=/`;
  if (expires instanceof Date) {
    cookieStr += `; expires=${expires.toUTCString()}`;
  }
  document.cookie = cookieStr;
}

// Helper for the common "persist for one year from now" pattern this
// codebase uses for both themeMode and dontShowExportWarning.
export function oneYearFromNow() {
  const expiry = new Date();
  expiry.setFullYear(expiry.getFullYear() + 1);
  return expiry;
}
