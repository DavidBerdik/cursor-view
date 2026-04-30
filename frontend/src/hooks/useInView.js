import { useEffect, useState } from 'react';

// Reports whether `ref.current` is currently within (or within
// `rootMargin` of) the viewport, using IntersectionObserver. The
// canonical consumer is `useSvgCrossFade` (called by
// `MermaidDiagramSurface`), which gates the outgoing cross-fade
// layer on this boolean: there is no point keeping a doubled SVG
// mounted for the fade duration on a diagram the user cannot see.
//
// # Why default-to-`true` on missing API or null ref
//
// The fallback when `IntersectionObserver` is undefined (very old
// browsers, edge runtimes, or some test environments) flips state to
// `true` so the cross-fade still runs. Skipping the cross-fade would
// be the safer-for-perf default but graceful degradation here means
// "the cross-fade still works", not "perf optimization still applies".
// The same fallback fires when `ref.current` is null at effect time,
// which can happen if a future caller passes a ref before the target
// element commits to the DOM. Returning `true` keeps the visual
// behavior identical to the pre-IntersectionObserver baseline; the
// only thing the fallback loses is the off-screen perf win.
//
// # Why read `ref.current` at the top of the effect
//
// Reading `ref.current` once at the top and closing over `node`
// (rather than reading inside the IntersectionObserver callback) is
// the documented React pattern for ref-stable cleanup. Reading inside
// the callback would close over the LIVE ref, so a ref re-target
// between observe and the next callback fire would cause cleanup to
// run against the wrong node. We never re-target this ref in
// practice, but the effect-top read costs nothing and matches the
// `useSavedSelection` style already established in the codebase.
//
// # Why `observer.disconnect()` rather than `observer.unobserve(node)`
//
// `disconnect` is sufficient because the observer instance is local to
// this effect run (created on observe, destroyed on cleanup). There
// are no other observed nodes to preserve. `disconnect` also handles
// the case where the observer is mid-callback when cleanup runs --
// `unobserve(node)` would leave the observer alive but with no
// observed targets, which is harmless but not as cheap.
export function useInView(ref, { rootMargin = '0px' } = {}) {
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) {
          setInView(entry.isIntersecting);
        }
      },
      { rootMargin },
    );
    observer.observe(node);

    return () => observer.disconnect();
  }, [ref, rootMargin]);

  return inView;
}
