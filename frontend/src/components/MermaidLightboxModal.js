import React from 'react';
import { Box, Dialog, IconButton } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useSvgPanZoom } from '../hooks/useSvgPanZoom';
import MermaidLightboxFallback from './MermaidLightboxFallback';
import MermaidZoomControls from './MermaidZoomControls';

// Full-size modal counterpart to MermaidBlock's inline diagram. The
// parent MermaidBlock holds `modalOpen` state and hands this modal the
// already-rendered SVG (plus the original `source` and any
// `renderError`); the modal does no mermaid work of its own.
//
// SVG-as-prop, not a second render: the singleton config, the
// `latestRef` cancellation, and the bomb-graphic-avoidance discipline
// (parse-before-render) all live in `useMermaidRender` (consumed by
// MermaidBlock). Calling `mermaid.render` again here would duplicate
// that work and re-open the bomb-graphic risk a failed render injects
// into document.body (see `useMermaidRender`'s top-of-file comment).
// It would also constitute a third mermaid pipeline, which
// `mermaid-rendering.mdc` forbids.
//
// Theme parity with the inline view is automatic: when ThemeModeContext
// flips, `useMermaidRender`'s `useEffect([source, darkMode])`
// regenerates `svg`, the new value flows down via props through
// MermaidBlock, and React reconciles the modal body. Do not add a
// duplicate `useEffect(darkMode)` here -- it would race the parent's
// render and potentially install a stale theme'd SVG over a fresh one.
//
// UX invariants: ESC/backdrop dismiss via `Dialog onClose`; all
// controls live in the toolbar row (never overlaid on diagram content);
// no prev/next nav exists because this modal hosts one diagram.
//
// Parse-error fallback mirrors the inline behavior in MermaidBlock so
// the "graceful source fallback" invariant from
// `mermaid-rendering.mdc` holds across surfaces; the rendered panel
// (Typography error caption above a `<pre><code>` block of the raw
// source) lives in MermaidLightboxFallback, which this modal renders
// in the non-`hasDiagram` branch. In practice MermaidBlock hides its
// expand affordance whenever `renderError` is set, so this branch is
// defensive -- it covers the case where a future caller opens the
// modal without first checking the success-only gate.
//
// All styling uses MUI theme tokens via `sx` / palette so dark / light
// mode changes flow through automatically; no hard-coded hex. The
// fallback panel's own theming lives in MermaidLightboxFallback.
export default function MermaidLightboxModal({
  open,
  onClose,
  source,
  svg,
  renderError,
}) {
  const {
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
    onPointerUp,
    onPointerCancel,
  } = useSvgPanZoom({ open, svg });
  const hasDiagram = typeof svg === 'string' && svg.length > 0 && !renderError;

  if (!open) {
    return null;
  }

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth={false}
      PaperProps={{
        // Viewport-fixed dimensions match `ImageLightboxModal` so both
        // lightboxes feel identical regardless of diagram size; the
        // SVG inside scales to fit via `& svg: { maxWidth: 100%; height: auto }`.
        // `m: 0.5` keeps a thin backdrop strip rather than butting the
        // Paper against the viewport edge.
        sx: {
          bgcolor: 'background.paper',
          m: 0.5,
          p: 0,
          borderRadius: 2,
          width: '95vw',
          height: '95vh',
          maxWidth: '95vw',
          maxHeight: '95vh',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
      aria-label="Mermaid diagram preview"
    >
      <Box
        sx={{
          p: 2,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 0,
          boxSizing: 'border-box',
        }}
      >
        {/* Toolbar row above the diagram; close remains pinned right. */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            minHeight: 32,
            mb: 1.5,
            flexShrink: 0,
          }}
        >
          {hasDiagram && (
            <MermaidZoomControls
              canZoomIn={controls.canZoomIn}
              canZoomOut={controls.canZoomOut}
              onZoomIn={zoomIn}
              onZoomOut={zoomOut}
              onReset={reset}
            />
          )}
          <IconButton
            aria-label="Close"
            onClick={onClose}
            size="small"
            sx={{ ml: 'auto', color: 'text.primary' }}
          >
            <CloseIcon />
          </IconButton>
        </Box>

        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            // Hidden, not auto: interactive pan/zoom applies a
            // translate+scale transform inside this viewport, so the
            // viewport itself must stay fixed and clip overflow rather
            // than participate in scrolling.
            overflow: 'hidden',
          }}
        >
          {hasDiagram ? (
            <Box
              ref={viewportRef}
              role="application"
              aria-label="Mermaid diagram pan and zoom viewport"
              onWheel={onWheel}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerCancel}
              sx={{
                position: 'relative',
                width: '100%',
                height: '100%',
                cursor: isDragging ? 'grabbing' : 'grab',
                touchAction: 'none',
                overflow: 'hidden',
                // Drag-to-pan over diagrams with text labels would
                // otherwise trigger native text selection, which the
                // browser repaints rapidly while the pointer moves and
                // flickers the highlight. Disabling user-select on the
                // pan/zoom surface keeps the cursor as a grab affordance
                // and matches the "the diagram is a manipulable canvas,
                // not a text field" intent of the modal.
                userSelect: 'none',
                WebkitUserSelect: 'none',
              }}
            >
              {/*
                The transform layer fills the viewport so its natural
                CSS-flex centering already matches the previous "fit to
                viewport, centered" baseline at the identity transform.
                Pan/zoom transforms apply on top of that centered state,
                with `transformOrigin: '0 0'` keeping the anchor-zoom
                math in `useSvgPanZoom` aligned with viewport coords.

                The `& svg` rule mirrors the inline diagram's responsive
                sizing convention plus `!important` overrides because
                mermaid emits both a `width="100%"` attribute and a
                `style="max-width: ..."` inline rule that would
                otherwise win on specificity inside this surface.
              */}
              <Box
                role="img"
                aria-label="Mermaid diagram"
                dangerouslySetInnerHTML={{ __html: svg }}
                sx={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  p: 2,
                  boxSizing: 'border-box',
                  transformOrigin: '0 0',
                  transform: `translate(${transform.translateX}px, ${transform.translateY}px) scale(${transform.scale})`,
                  willChange: 'transform',
                  '& svg': {
                    display: 'block',
                    width: 'auto !important',
                    height: 'auto !important',
                    maxWidth: '100% !important',
                    maxHeight: '100% !important',
                  },
                }}
              />
            </Box>
          ) : (
            // Defensive fallback: MermaidBlock hides the expand
            // affordance when `renderError` is set or `svg` is null,
            // but a future caller that forgets that gate must still
            // see something useful instead of an empty Paper. The
            // panel itself lives in MermaidLightboxFallback so this
            // component stays focused on the diagram-surface branch.
            <MermaidLightboxFallback source={source} renderError={renderError} />
          )}
        </Box>
      </Box>
    </Dialog>
  );
}
