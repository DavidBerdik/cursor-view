import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SVG_PAN_ZOOM_DEFAULTS, zoomAtAnchor } from '../utils/svgPanZoomModel';

const IDENTITY_TRANSFORM = { scale: 1, translateX: 0, translateY: 0 };

// Modal-local pan/zoom state machine for a rendered SVG. The default
// state is the identity transform (`scale: 1, translate: 0,0`); the
// caller is expected to fit-and-center the SVG via CSS so that "no
// transform applied" already matches the desired baseline view. This
// lets pan/zoom layer additively on top of the CSS-fit state without
// the modal needing to measure dimensions before first paint.
//
// The hook is intentionally display-only: it transforms DOM that
// already exists and never calls mermaid APIs.
export function useSvgPanZoom({
  open,
  svg,
  minScale = SVG_PAN_ZOOM_DEFAULTS.minScale,
  maxScale = SVG_PAN_ZOOM_DEFAULTS.maxScale,
  zoomStep = SVG_PAN_ZOOM_DEFAULTS.zoomStep,
}) {
  const viewportRef = useRef(null);
  const draggingRef = useRef({
    active: false,
    pointerId: null,
    startClientX: 0,
    startClientY: 0,
    startTranslateX: 0,
    startTranslateY: 0,
  });

  const [transform, setTransform] = useState(IDENTITY_TRANSFORM);
  const [isDragging, setIsDragging] = useState(false);

  // Reset to identity whenever the modal opens or the SVG content
  // changes so a previously-zoomed state does not survive a reopen
  // or theme-driven SVG swap. Also clears any leftover dragging
  // state: closing the modal mid-drag (ESC, backdrop click,
  // programmatic close) unmounts the viewport DOM, so the captured
  // `pointerup` event never reaches `stopDragging` and the hook's
  // `isDragging` / `draggingRef.current.active` would otherwise
  // remain true into the next open. The cursor would render as
  // `grabbing` on first paint after reopen, and a stale `pointerId`
  // match in `onPointerMove` could resume a drag the user never
  // started. Resetting on every open/svg change is idempotent for
  // the no-prior-drag case (refs already inactive, state already
  // false) and cheap.
  useEffect(() => {
    if (!open) {
      return;
    }
    draggingRef.current.active = false;
    draggingRef.current.pointerId = null;
    setIsDragging(false);
    setTransform(IDENTITY_TRANSFORM);
  }, [open, svg]);

  const reset = useCallback(() => {
    setTransform(IDENTITY_TRANSFORM);
  }, []);

  const zoomIn = useCallback(() => {
    const viewportEl = viewportRef.current;
    if (!viewportEl) {
      return;
    }
    const rect = viewportEl.getBoundingClientRect();
    const anchorX = rect.width / 2;
    const anchorY = rect.height / 2;
    setTransform((prev) => zoomAtAnchor({
      scale: prev.scale,
      translateX: prev.translateX,
      translateY: prev.translateY,
      targetScale: prev.scale * zoomStep,
      anchorX,
      anchorY,
      minScale,
      maxScale,
    }));
  }, [maxScale, minScale, zoomStep]);

  const zoomOut = useCallback(() => {
    const viewportEl = viewportRef.current;
    if (!viewportEl) {
      return;
    }
    const rect = viewportEl.getBoundingClientRect();
    const anchorX = rect.width / 2;
    const anchorY = rect.height / 2;
    setTransform((prev) => zoomAtAnchor({
      scale: prev.scale,
      translateX: prev.translateX,
      translateY: prev.translateY,
      targetScale: prev.scale / zoomStep,
      anchorX,
      anchorY,
      minScale,
      maxScale,
    }));
  }, [maxScale, minScale, zoomStep]);

  const onWheel = useCallback((event) => {
    event.preventDefault();

    const viewportEl = viewportRef.current;
    if (!viewportEl) {
      return;
    }
    const rect = viewportEl.getBoundingClientRect();
    const anchorX = event.clientX - rect.left;
    const anchorY = event.clientY - rect.top;
    const factor = event.deltaY < 0 ? zoomStep : 1 / zoomStep;

    setTransform((prev) => zoomAtAnchor({
      scale: prev.scale,
      translateX: prev.translateX,
      translateY: prev.translateY,
      targetScale: prev.scale * factor,
      anchorX,
      anchorY,
      minScale,
      maxScale,
    }));
  }, [maxScale, minScale, zoomStep]);

  const onPointerDown = useCallback((event) => {
    if (event.button !== 0) {
      return;
    }

    const viewportEl = viewportRef.current;
    if (!viewportEl) {
      return;
    }

    viewportEl.setPointerCapture?.(event.pointerId);
    draggingRef.current = {
      active: true,
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startTranslateX: transform.translateX,
      startTranslateY: transform.translateY,
    };
    setIsDragging(true);
  }, [transform.translateX, transform.translateY]);

  const onPointerMove = useCallback((event) => {
    const drag = draggingRef.current;
    if (!drag.active || drag.pointerId !== event.pointerId) {
      return;
    }

    const deltaX = event.clientX - drag.startClientX;
    const deltaY = event.clientY - drag.startClientY;
    setTransform((prev) => ({
      scale: prev.scale,
      translateX: drag.startTranslateX + deltaX,
      translateY: drag.startTranslateY + deltaY,
    }));
  }, []);

  const stopDragging = useCallback((event) => {
    const drag = draggingRef.current;
    if (!drag.active || drag.pointerId !== event.pointerId) {
      return;
    }
    const viewportEl = viewportRef.current;
    viewportEl?.releasePointerCapture?.(event.pointerId);
    draggingRef.current.active = false;
    draggingRef.current.pointerId = null;
    setIsDragging(false);
  }, []);

  const onPointerCancel = useCallback((event) => {
    stopDragging(event);
  }, [stopDragging]);

  const controls = useMemo(() => {
    const epsilon = 1e-6;
    return {
      canZoomIn: transform.scale < maxScale - epsilon,
      canZoomOut: transform.scale > minScale + epsilon,
    };
  }, [maxScale, minScale, transform.scale]);

  return {
    viewportRef,
    transform,
    isDragging,
    controls,
    zoomIn,
    zoomOut,
    reset,
    onWheel,
    onPointerDown,
    onPointerMove,
    onPointerUp: stopDragging,
    onPointerCancel,
  };
}
