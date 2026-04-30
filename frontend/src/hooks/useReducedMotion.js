import { useEffect, useState } from 'react';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

// Reports whether the user has requested reduced motion via the
// OS-level `prefers-reduced-motion: reduce` media query. The canonical
// consumer is `MermaidDiagramSurface`, which uses this boolean to skip
// mounting the outgoing cross-fade SVG layer entirely when reduced
// motion is preferred. This is a stronger guarantee than the global
// CSS `@media (prefers-reduced-motion: reduce)` rule in `index.css`:
// the CSS rule disables the keyframe `animation` (so the layer would
// stay stuck at opacity 1 forever), while this hook lets the consumer
// avoid mounting the doubled DOM in the first place.
//
// # Live OS-setting flips
//
// The `change` listener is what makes the hook reactive: a user who
// toggles "Reduce motion" in their OS accessibility settings while
// the app is open sees the next theme toggle's cross-fade behavior
// adjust without a reload. Accessibility tooling (system-wide
// screen-reader profiles, motion-sensitivity helpers) flips this
// preference at runtime and expects apps to react.
//
// # Browser support
//
// `MediaQueryList.addEventListener('change', ...)` is the modern API,
// supported by every browser in this project's `browserslist` target
// (`>0.2%, not dead, not op_mini all` for production; "last 1
// chrome/firefox/safari" for development). Safari 14 and older only
// support the legacy `addListener` / `removeListener` shape, but
// "not dead" already excludes those versions, so we do not branch on
// API availability here.
//
// # Per-hook listener vs. module-level singleton
//
// Each hook instance creates its own `MediaQueryList` and listener.
// On a chat with N `MermaidDiagramSurface` instances that means N
// listeners on the same media query, which is a real-but-tiny cost
// (matchMedia listeners are O(1) per change event). If a future
// profiling pass shows the per-instance listener as a hotspot, swap
// in a module-scope `mql` plus a Set-of-subscribers pattern; the
// public hook signature stays the same.
export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return false;
    }
    return window.matchMedia(REDUCED_MOTION_QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return undefined;
    }
    const mql = window.matchMedia(REDUCED_MOTION_QUERY);
    const handler = () => setReduced(mql.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  return reduced;
}
