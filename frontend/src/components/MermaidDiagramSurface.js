import React, { memo } from 'react';
import { Box } from '@mui/material';
import { useSvgCrossFade } from '../hooks/useSvgCrossFade';
import { PALETTE_TRANSITION } from '../theme/transitions';

// Diagram-mode click surface for `MermaidBlock`. Owns the
// `<Box component="button">` that opens the lightbox modal on click
// PLUS the layered JSX for a cross-fade between the previous and
// current SVG strings whenever `svg` changes. The cross-fade state
// machine itself (outgoing-layer state, derive-during-render, the
// concurrent-fade cap, the visibility/reduced-motion gates, the
// keyframe constant) lives in `useSvgCrossFade`; this component is
// the consumer and owns only layout, theming, and event wiring.
//
// Why this lives in its own file (decompose-before-growth, same
// pattern `MermaidLightboxFallback` and `MermaidZoomControls`
// follow):
//
// 1. Without the cross-fade, a dark/light toggle re-runs
//    `useMermaidRender`'s effect, `mermaid.render` produces a new
//    SVG, and React reconciles `dangerouslySetInnerHTML` instantly.
//    Mermaid emits a brand-new tree of inline-styled DOM nodes that
//    share no element identity with the previous render, so a CSS
//    `transition` on the SVG itself cannot bridge the two states --
//    every `stroke` / `fill` / label color flips in a single frame.
//    The fix has to keep the previous SVG visually present long
//    enough for the new SVG to settle in beneath it.
// 2. Folding the cross-fade JSX plus its theming and click-surface
//    plumbing into `MermaidBlock` would push it past the ~250-line
//    cap in `react-components.mdc`. The "diagram surface" concern
//    is also independent of the source/error mode switching the
//    parent owns, so extraction keeps both files focused on a
//    single concern.
//
// Per `mermaid-rendering.mdc` "Two rendering pipelines, one source
// format", this component is a *presentation surface* like
// `MermaidLightboxModal`: it consumes the SVG `MermaidBlock` already
// produced via `mermaid.render` (through `useMermaidRender`) and
// never calls `mermaid.parse`, `mermaid.render`, or
// `mermaid.initialize` itself. The bomb-graphic risk closed by the
// parse-first guard stays closed because the only callers of those
// imperative APIs are still `useMermaidRender` and
// `prerenderMermaidDiagrams`.
function MermaidDiagramSurface({ svg, darkMode, onOpenModal }) {
  const { surfaceRef, outgoingRef, outgoingSvg, fadeAnimation, onAnimationEnd } =
    useSvgCrossFade(svg);

  // Diagram body is itself the click surface for the modal (paired
  // with the expand icon in the toolbar above for discoverability /
  // accessibility). Rendered as `<button>` for semantics + keyboard
  // activation; default chrome is reset (`border: 'none'`,
  // transparent background below the theme tint, font/color
  // inherited) so the visual is identical to the prior `<Box>` shape
  // in `MermaidBlock`. Mermaid's `securityLevel: 'strict'` disables
  // in-SVG click handlers, so wrapping the diagram in a button cannot
  // suppress library interactivity. `width: 100%` and `textAlign:
  // 'inherit'` undo the default `<button>` shrink-to-fit + center-
  // align that would otherwise reflow the diagram. `userSelect:
  // 'text'` overrides the user-agent default that Safari (and
  // historically other browsers) apply to form elements, so labels
  // inside the rendered SVG remain copy-selectable; drag-to-select
  // does not trigger the click handler because click only fires on
  // a movement-free mouseup.
  //
  // `position: 'relative'` scopes the absolutely-positioned outgoing
  // layer below to this button rather than letting it escape to the
  // page.
  return (
    <Box
      ref={surfaceRef}
      component="button"
      type="button"
      onClick={onOpenModal}
      aria-label="Open mermaid diagram in modal"
      sx={{
        position: 'relative',
        display: 'flex',
        justifyContent: 'center',
        p: 2,
        width: '100%',
        border: 'none',
        cursor: 'pointer',
        font: 'inherit',
        color: 'inherit',
        textAlign: 'inherit',
        userSelect: 'text',
        // Alpha differs per scheme (4% dark, 2% light) so the tint
        // stays readable on each scheme's `background.paper`. A
        // single CSS var cannot encode "different alpha per scheme"
        // without a per-scheme override, so the `darkMode` boolean
        // still picks the alpha value.
        backgroundColor: darkMode
          ? 'rgba(var(--mui-palette-highlight-mainChannel) / 0.04)'
          : 'rgba(var(--mui-palette-highlight-mainChannel) / 0.02)',
        transition: PALETTE_TRANSITION,
        // Tell the browser this surface's layout, paint, and style
        // cannot affect siblings or ancestors so it can short-circuit
        // a lot of the work it would otherwise do during a theme
        // toggle (recompute the diagram's intrinsic dimensions,
        // re-paint the SVG region, propagate style invalidation up
        // the tree). Safe because nothing inside the subtree needs
        // to leak out: the lightbox modal is portal-rendered (lives
        // outside this DOM subtree, so MUI 7's `Modal` escapes
        // containment by construction), and the cross-fade outgoing
        // layer below is `position: absolute; inset: 0` scoped to
        // *this* button's `position: relative` -- it cannot reach a
        // sibling or ancestor either way. `style` containment is
        // included because the SVG's inline `stroke`/`fill` colors
        // are theme-derived but only consumed within this subtree;
        // no descendant defines a `counter-reset` or other
        // tree-scoped style we would care about leaking.
        contain: 'layout paint style',
        '& svg': { maxWidth: '100%', height: 'auto' },
      }}
    >
      <Box
        sx={{ width: '100%', display: 'flex', justifyContent: 'center' }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      {outgoingSvg && (
        // The outgoing SVG layer sits absolutely on top of the
        // incoming layer for the duration of the cross-fade.
        // `pointerEvents: 'none'` lets clicks pass through to the
        // underlying button. `aria-hidden` keeps screen readers from
        // announcing two diagrams. The `key` tied to the SVG content
        // is what makes rapid theme toggles restart the animation
        // cleanly: when the outgoing string changes mid-fade, React
        // unmounts the old layer and remounts a fresh one, which
        // restarts the keyframe. `onAnimationEnd` (from the hook)
        // clears the outgoing slot once the fade completes so the
        // layer is removed from the DOM (no lingering overlay
        // capturing memory or stacking-context budget). The hook's
        // `outgoingRef` attaches an `animationcancel` listener to
        // this node so a reduced-motion flip mid-fade -- which
        // rewrites the keyframe to `animation: none !important` and
        // fires `animationcancel` (not `animationend`) -- still
        // unmounts the layer; React's JSX has no
        // `onAnimationCancel` shorthand, so the wire-up has to live
        // in the hook's `useEffect`.
        <Box
          ref={outgoingRef}
          key={outgoingSvg}
          aria-hidden="true"
          onAnimationEnd={onAnimationEnd}
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            p: 2,
            boxSizing: 'border-box',
            pointerEvents: 'none',
            // Promote to a GPU compositor layer for the duration of
            // the fade so the browser interpolates alpha on the GPU
            // rather than rasterizing the SVG every frame. The
            // standard "do not keep `will-change` permanently"
            // caveat does not apply because the outgoing layer
            // unmounts at animation-end; the lifetime is bounded.
            willChange: 'opacity',
            animation: fadeAnimation,
          }}
          dangerouslySetInnerHTML={{ __html: outgoingSvg }}
        />
      )}
    </Box>
  );
}

// Memo so `MermaidBlock`'s modal-open / modal-close re-renders (which
// flip `modalOpen` state at the parent without changing any of this
// surface's props) skip the diagram-body subtree and the outgoing
// cross-fade layer. Without memo, every modal toggle would reconcile
// the `dangerouslySetInnerHTML` SVG nodes pointlessly.
export default memo(MermaidDiagramSurface);
