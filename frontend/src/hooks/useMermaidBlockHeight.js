import { useEffect, useRef, useState } from 'react';
import {
  getCachedMermaidHeight,
  setCachedMermaidHeight,
} from '../utils/mermaidHeightCache';

// Records each `MermaidBlock`'s rendered DOM height into
// `mermaidHeightCache` via a `ResizeObserver`, and exposes the
// previously-recorded height to the caller so the block can use it
// as `containIntrinsicSize` on the next refresh.
//
// Returns `{ ref, persistedHeight }`. The consumer attaches `ref` to
// the outer `<Box>` it wants observed (the same element that carries
// `contentVisibility: 'auto'`), and reads `persistedHeight` to seed
// the placeholder size; `null` when no entry exists yet, in which
// case the consumer falls back to the static placeholder heuristic.
//
// # Why a single-value lazy `useState` initializer
//
// `persistedHeight` is read once on mount via the lazy `useState`
// initializer and stays stable for the block's lifetime. Re-reading
// during the session would be wasteful: the `ResizeObserver`
// callback writes the latest height back to the cache *behind* this
// hook's state, so the next refresh of the same chat reads the
// freshest value, but flipping `containIntrinsicSize` mid-session
// would itself cause a layout shift (the very symptom we are
// closing). Stable across the lifetime is the right trade.
//
// Source is treated as effectively immutable per `MermaidBlock` --
// a fenced code block whose text content changed would be a
// different DOM node entirely. The hook's `useEffect` keys on
// `source` so a source change does swap the observed key, but
// `persistedHeight` deliberately does not re-read; if the source
// genuinely changes mid-mount the next refresh picks up the new
// recorded height. See [`frontend-hooks.mdc`](.cursor/rules/frontend-hooks.mdc)
// "Expose minimal state" for the narrow-return discipline this
// follows.
//
// # Why observe the outer block, not the inner SVG
//
// `containIntrinsicSize` controls the placeholder height of the
// element that carries `contentVisibility: 'auto'`. That element is
// `MermaidBlock`'s outer `<Box>` (the wrapper around the toolbar,
// the diagram surface, and the parse-error fallback), not the inner
// SVG. Observing the outer box captures toolbar height + padding +
// SVG height as one number, which is exactly what the placeholder
// needs to match.
//
// # ResizeObserver vs MutationObserver / `getBoundingClientRect`
//
// `ResizeObserver` fires precisely when the observed element's
// content-box size changes, including the transition between
// content-visibility-skipped (placeholder) and rendered (actual)
// states; this is the documented cross-browser way to detect the
// materialization the `useChatScrollAnchor` rAF chase loop is
// chasing. A `MutationObserver` on the inner SVG would miss the
// content-visibility transition entirely (no DOM mutation fires when
// content-visibility relevance flips), and a per-frame
// `getBoundingClientRect` poll would force layout from JS rather
// than reacting to one. ResizeObserver also avoids the
// strict-mode-double-fire concern: subscriptions clean up cleanly
// across the dev double-mount because the observer is created and
// disconnected per-effect-run.
//
// # Defensive against missing API
//
// `ResizeObserver` is supported in every browser the chat view
// targets, but the hook still degrades gracefully when the API is
// absent (some test environments, very old browsers): the effect
// short-circuits, no observer is created, and the cache simply
// never accumulates an entry for this block. The consumer keeps
// using the static placeholder fallback, matching the
// pre-persisted-height baseline.
export function useMermaidBlockHeight(source) {
  const ref = useRef(null);
  const [persistedHeight] = useState(() => {
    const cached = getCachedMermaidHeight(source);
    return typeof cached === 'number' ? cached : null;
  });

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === 'undefined') {
      return undefined;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      // `contentRect` is the content-box (excludes border/padding).
      // For our placeholder match we want the border-box, since
      // `containIntrinsicSize` sizes the outer box. `borderBoxSize`
      // is the standard accessor; `contentRect.height` is the
      // legacy fallback for the rare browser that ships
      // `ResizeObserver` without the `borderBoxSize` field.
      const borderBox = entry.borderBoxSize?.[0];
      const height = borderBox ? borderBox.blockSize : entry.contentRect.height;
      setCachedMermaidHeight(source, height);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [source]);

  return { ref, persistedHeight };
}
