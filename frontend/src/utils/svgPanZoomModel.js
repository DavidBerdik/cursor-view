// Canonical transform model for modal SVG pan/zoom interactions.
// Keep this file pure: no React hooks, no DOM writes, no mermaid calls.
//
// The hook (`useSvgPanZoom`) consumes `zoomAtAnchor` so wheel zoom and
// button zoom share one anchor-preserving formula. Fit-on-open and
// "Reset view" are not handled here -- they fall out of the consumer's
// identity-transform reset plus the modal's CSS-fit (`& svg`
// `maxWidth/maxHeight: 100%` inside a flex-centered transform layer),
// per `mermaid-rendering.mdc` under "Modal pan/zoom/reset is
// presentation-only". A measured fit-baseline helper used to live in
// this file; it was removed once the simpler identity-reset path
// replaced the plan's original measure-and-compute design (see git
// history for the prior shape if a future caller needs to re-derive
// baselines from `viewBox` + viewport size).

export const SVG_PAN_ZOOM_DEFAULTS = {
  minScale: 0.25,
  maxScale: 6,
  zoomStep: 1.2,
};

export function clampScale(scale, minScale = SVG_PAN_ZOOM_DEFAULTS.minScale, maxScale = SVG_PAN_ZOOM_DEFAULTS.maxScale) {
  if (!Number.isFinite(scale)) {
    return minScale;
  }
  if (scale < minScale) {
    return minScale;
  }
  if (scale > maxScale) {
    return maxScale;
  }
  return scale;
}

// Computes the transform that keeps the world-space point under
// (anchorX, anchorY) fixed while changing scale. This is what prevents
// "diagram jump" during wheel zoom and is the same formula button zoom
// uses when anchoring at viewport center.
export function zoomAtAnchor({
  scale,
  translateX,
  translateY,
  targetScale,
  anchorX,
  anchorY,
  minScale = SVG_PAN_ZOOM_DEFAULTS.minScale,
  maxScale = SVG_PAN_ZOOM_DEFAULTS.maxScale,
}) {
  const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
  const nextScale = clampScale(targetScale, minScale, maxScale);

  if (nextScale === safeScale) {
    return { scale: safeScale, translateX, translateY };
  }

  const worldX = (anchorX - translateX) / safeScale;
  const worldY = (anchorY - translateY) / safeScale;

  return {
    scale: nextScale,
    translateX: anchorX - worldX * nextScale,
    translateY: anchorY - worldY * nextScale,
  };
}
