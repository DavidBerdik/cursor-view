import { useCallback, useEffect, useRef, useState } from 'react';
import { keyframes } from '@emotion/react';
import {
  PALETTE_TRANSITION_CURVE,
  PALETTE_TRANSITION_DURATION,
} from '../theme/transitions';
import { useInView } from './useInView';
import { useReducedMotion } from './useReducedMotion';

// Keyframe defined at module scope via emotion's `keyframes` helper
// rather than as an inline `'@keyframes name': { ... }` entry inside
// the outgoing layer's `sx` prop in the consumer. The inline-in-sx
// form depends on undocumented emotion serialization behavior to
// install the keyframes rule globally and silently fails in some
// MUI 7 / emotion 11 build configurations, leaving the animation
// property pointing at a name no `@keyframes` declaration ever
// defined. The result is an outgoing layer that mounts at
// `opacity: 1`, never animates, never fires `onAnimationEnd`, and
// stays stuck on top of the incoming SVG forever -- no fade at all.
// The `keyframes` helper sidesteps that by inserting a uniquely-
// named global CSS rule once at module load and returning a token
// the `animation` shorthand interpolates safely.
const svgCrossFadeKeyframe = keyframes`
  from { opacity: 1; }
  to { opacity: 0; }
`;

// Pre-composed `animation` shorthand for the outgoing layer's `sx`,
// matching `PALETTE_TRANSITION` in duration and curve so all theme-
// fade timing in the UI moves in lockstep.
const FADE_ANIMATION = `${svgCrossFadeKeyframe} ${PALETTE_TRANSITION_DURATION} ${PALETTE_TRANSITION_CURVE} forwards`;

// Module-scope counter capping how many `useSvgCrossFade` instances
// can have an outgoing layer mounted simultaneously. The compositor
// cost of N concurrent SVG cross-fades scales linearly with N (each
// fade promotes a GPU layer and interpolates alpha per frame), and
// on long chats with many visible diagrams a theme toggle would
// otherwise mount N outgoing layers in the same paint and leave the
// browser doing N alpha interpolations in parallel for the full
// fade duration. Beyond ~5 concurrent fades the diminishing return
// on visual polish stops outweighing the frame-time cost, so
// surfaces that would push the count past the cap fall back to an
// instant swap (the same code path the off-screen and reduced-
// motion gates already use). 5 is a heuristic; tune by measurement.
//
// The counter is module-scope (not per-instance) because the gate
// must be evaluated against the *cross-component* total, not just
// this surface. Mutated only inside `useEffect([outgoingSvg])`
// below, so increments and decrements stay paired through the React
// lifecycle: rapid theme toggles before the previous fade finishes
// transition `outgoingSvg` from one non-null value to another, and
// React fires the cleanup before the new effect runs, keeping the
// counter at +1 for this surface across the swap; unmount-mid-fade
// also runs cleanup, so a component removed while its outgoing
// layer is still mounted does not leak a permanent +1. React
// strict-mode double-invokes both the effect and its cleanup in
// dev, so the net delta is zero there too. The heuristic nature of
// the gate (a transient miscount across components in the same
// render pass would only push N over the cap by a few) means the
// counter does not need to be a correctness invariant.
let activeCrossFades = 0;
const MAX_CONCURRENT_CROSS_FADES = 5;

// Hook owning the cross-fade state machine for a string-typed
// imperative-DOM payload (mermaid SVG today; prism / monaco / similar
// imperative-DOM libraries in the future). The consumer renders both
// the incoming and outgoing layers via `dangerouslySetInnerHTML`; this
// hook decides when the outgoing layer should mount and when it
// should clean up.
//
// Why this lives in a hook rather than inline in the consuming
// component (mirrors the `useMermaidRender` extraction): the consumer
// (`MermaidDiagramSurface`) was 289 lines once `contain: 'layout
// paint style'` and the concurrent-fade cap landed, over the ~250-line
// cap in `react-components.mdc`. The cross-fade state machine
// (`outgoingSvg` / `committedSvg`, the derive-during-render block,
// the counter-tracking effect, the keyframe constant, the module-
// scope cap counter) is a self-contained concern; pulling it here
// drops the consumer back under the cap and keeps the consumer
// focused on the diagram-button JSX, the per-scheme alpha tint, and
// the `contain` containment hint.
//
// Why the prop-change is detected via the "adjusting state during
// render" pattern (the inline `if (svg !== committedSvg)` block
// below) rather than a `useEffect([svg])`: `useEffect` fires *after*
// the browser paints, so a useEffect-based detection makes the user
// see one frame of the new SVG with no outgoing overlay before the
// overlay mounts on the next render -- a visible flash that defeats
// the entire point of the cross-fade. React's documented "Storing
// information from previous renders" pattern from the `useState`
// reference is the right shape: detect the change with an inline
// `if (svg !== committedSvg) { ... }` block, call `setState`
// synchronously to commit the derivation, and let React throw away
// the in-progress render and re-run with the new state. Both renders
// happen before the next paint, so the user only ever sees the final
// state with both layers already mounted.
//
// The outgoing layer mounts only when three gates clear: the surface
// is on-screen, the user has not requested reduced motion, and the
// global concurrent-fade count is below
// `MAX_CONCURRENT_CROSS_FADES`. All three suppress only the *outgoing
// layer*, not the underlying render -- the consumer's incoming SVG
// always updates, only the cross-fade overlay is conditional. The
// reduced-motion gate is a JS-side stronger version of the global
// CSS rule in `index.css`: the CSS rule would disable the keyframe
// animation, leaving the outgoing layer stuck at `opacity: 1`; the
// JS gate avoids mounting the doubled DOM at all.
//
// Returns:
//   - `surfaceRef`: the consumer attaches this to the surface element
//     it wants visibility-gated; the hook uses it for `useInView`.
//   - `outgoingSvg`: the previous SVG string while a fade is in
//     flight, or `null` (instant-swap path or fade complete).
//     Consumer renders it as an absolutely-positioned, `aria-hidden`,
//     `pointer-events: none` overlay via `dangerouslySetInnerHTML`.
//   - `fadeAnimation`: ready-to-use `animation` shorthand string
//     for the outgoing layer's `sx`.
//   - `onAnimationEnd`: handler the consumer wires to the outgoing
//     layer's `onAnimationEnd` prop. Clears `outgoingSvg` so the
//     overlay unmounts cleanly. Stable across renders.
export function useSvgCrossFade(svg) {
  const surfaceRef = useRef(null);
  const inView = useInView(surfaceRef);
  const reducedMotion = useReducedMotion();
  const [outgoingSvg, setOutgoingSvg] = useState(null);
  const [committedSvg, setCommittedSvg] = useState(svg);

  if (svg !== committedSvg) {
    const shouldFade =
      inView && !reducedMotion && activeCrossFades < MAX_CONCURRENT_CROSS_FADES;
    setOutgoingSvg(shouldFade ? committedSvg : null);
    setCommittedSvg(svg);
  }

  // Keep `activeCrossFades` in sync with this surface's contribution
  // to the global concurrent-fade total. The dep is `outgoingSvg` so
  // a transition from one non-null outgoing SVG to another (rapid
  // theme toggles before the previous fade finishes) decrements then
  // re-increments, holding the counter at +1 for this surface across
  // the swap. The early return for the null case avoids a no-op
  // increment / decrement pair that would still survive cleanup
  // ordering in strict mode. Cleanup also runs on unmount-mid-fade,
  // so a component removed while its outgoing layer is still mounted
  // does not leak a permanent +1. See the module-level comment on
  // `activeCrossFades` for the dev-mode strict-mode argument.
  useEffect(() => {
    if (outgoingSvg === null) {
      return undefined;
    }
    activeCrossFades += 1;
    return () => {
      activeCrossFades -= 1;
    };
  }, [outgoingSvg]);

  // TODO(bug): The outgoing cross-fade SVG layer sticks on top of
  // the incoming SVG (until the next svg change for this block) if
  // the user flips OS-level reduced-motion during the ~200ms fade
  // window. Suspected cause: the global
  // `@media (prefers-reduced-motion: reduce)` rule in `index.css`
  // overrides the keyframe `animation` to `none`, firing
  // `animationcancel` (not `animationend`); React's
  // `onAnimationEnd` JSX prop does not catch `animationcancel`, so
  // `setOutgoingSvg(null)` is never called for this fade. Suspected
  // fix is to attach an `animationcancel` listener via
  // `addEventListener` in a `useEffect` (React JSX has no
  // `onAnimationCancel` shorthand) with the same `setOutgoingSvg(null)`
  // payload. Not regression-pinned because the frontend has no JS
  // test harness, so the invariant would be enforced by the
  // cross-referenced rule and by manual verification only.
  const onAnimationEnd = useCallback(() => setOutgoingSvg(null), []);

  return { surfaceRef, outgoingSvg, fadeAnimation: FADE_ANIMATION, onAnimationEnd };
}
