// Return true iff the React app is running inside pywebview's desktop
// shell. `window.pywebview` is only injected by pywebview's runtime,
// so its mere existence is the runtime signal.
//
// Bridge *readiness* (whether a specific Python method is callable
// yet) is intentionally a separate per-method check -- keep that
// next to each caller so a bridge that comes up out-of-order cannot
// silently break one feature while another still works. Callers that
// want to fan out over multiple bridge methods (e.g. `save_export`,
// `open_url_in_browser`) compose this helper with an explicit
// `typeof window.pywebview.api.<method> === 'function'` gate at the
// call site.
export function isDesktopMode() {
  return typeof window !== 'undefined' && !!window.pywebview;
}
