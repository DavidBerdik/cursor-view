import React, { memo, useCallback, useContext, useEffect, useState } from 'react';
import { Box, Typography } from '@mui/material';
import { ThemeModeContext } from '../contexts/ThemeModeContext';
import { useMermaidRender } from '../hooks/useMermaidRender';
import { PALETTE_TRANSITION } from '../theme/transitions';
import MermaidDiagramSurface from './MermaidDiagramSurface';
import MermaidLightboxModal from './MermaidLightboxModal';
import MermaidToolbar from './MermaidToolbar';

// Renders a single mermaid fenced code block as either a live diagram
// (default) or the raw source text. The async parse + render machinery
// (cache check, queue, latestRef cancellation, parse-before-render,
// theme-tagged prerender suppression) lives in `useMermaidRender`; this
// component owns the diagram/source mode toggle, the lightbox modal
// state, and the auto-close-on-error effect.
//
// `initialSvg` / `initialError` / `initialDarkMode` come from
// `prerenderMermaidDiagrams` in `ChatDetail`'s fetch effect (before
// `setLoading(false)`) so `MermaidBlock` starts in the correct state
// on first paint; the hook honors the same theme-tagged-prerender
// invariants documented in `mermaid-rendering.mdc`.
function MermaidBlock({ source, initialSvg, initialError, initialDarkMode }) {
  const { darkMode } = useContext(ThemeModeContext);
  const [mode, setMode] = useState(initialError ? 'source' : 'diagram');

  // The hook fires this synchronously alongside its own
  // `setRenderError` so both state updates land in the same React
  // batch -- avoids a one-frame inconsistency where the toolbar would
  // otherwise show the wrong mode-toggle button label between the
  // hook's commit and a parent-side `useEffect([renderError])`
  // auto-switch. `useCallback` keeps the prop identity stable so the
  // hook's effect deps stay `[source, darkMode]` and a parent
  // re-render does not bump `latestRef` mid-flight.
  const handleRenderError = useCallback(() => setMode('source'), []);
  const { svg, renderError } = useMermaidRender({
    source,
    darkMode,
    initialSvg,
    initialError,
    initialDarkMode,
    onRenderError: handleRenderError,
  });

  const toggleMode = () =>
    setMode((prev) => (prev === 'diagram' ? 'source' : 'diagram'));

  const showDiagram = mode === 'diagram' && svg !== null && renderError === null;

  // The lightbox modal opens on click of the diagram body or the
  // dedicated expand icon. State lives on the inline block so each
  // diagram has its own modal instance and the SVG flows through props
  // without an extra fetch or re-render. Stable callbacks per
  // `frontend-hooks.mdc` "Stable callback references" -- the modal
  // does not register them in effects today, but a future regression
  // that adds one (e.g. a keydown listener) must not silently re-bind
  // per parent render.
  const [modalOpen, setModalOpen] = useState(false);
  const handleOpenModal = useCallback(() => setModalOpen(true), []);
  const handleCloseModal = useCallback(() => setModalOpen(false), []);

  // Auto-close the modal if a render pass flips this block into the
  // error state while the modal is still open. The toolbar's expand
  // affordance disappears the instant `renderError` becomes non-null
  // (it gates on `showDiagram`), so without this effect a stale
  // `modalOpen=true` from before the failure would surface the
  // modal's defensive parse-error fallback branch instead of just
  // closing -- jarring UX on a theme flip that happens to expose a
  // late-detected parse error in a previously-rendering diagram. The
  // dependency is the boolean transition, not `renderError` itself,
  // so changing the message text of an already-failed parse does not
  // re-fire close().
  const isErrored = renderError !== null;
  useEffect(() => {
    if (isErrored) {
      setModalOpen(false);
    }
  }, [isErrored]);

  return (
    <Box
      sx={{
        position: 'relative',
        my: 1.5,
        border: '1px solid',
        borderColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.2)',
        borderRadius: 1,
        overflow: 'hidden',
        transition: PALETTE_TRANSITION,
        // Skip layout/paint for off-screen mermaid blocks. Long chats
        // routinely contain 5+ diagrams; on a theme toggle the browser
        // would otherwise re-layout and re-paint every one of them
        // (each containing a non-trivial inline-styled SVG subtree)
        // even for blocks scrolled far above or below the viewport.
        // `containIntrinsicSize: '0 400px'` reserves a placeholder
        // height so the scrollbar doesn't jump as off-screen blocks
        // materialize (`0` = use parent's width). 400px is a
        // heuristic for a typical mermaid diagram height in this UI;
        // a future enhancement could measure rendered heights per
        // source and feed them back through the prerender cache, but
        // any heuristic that's roughly right is dramatically better
        // than the unbounded reflow from `auto` with no intrinsic
        // size hint. Browsers without `content-visibility` support
        // (older Firefox) silently ignore both properties.
        contentVisibility: 'auto',
        containIntrinsicSize: '0 400px',
      }}
    >
      {renderError === null && (
        <MermaidToolbar
          mode={mode}
          showExpand={showDiagram}
          onToggleMode={toggleMode}
          onOpenModal={handleOpenModal}
        />
      )}

      {renderError !== null && (
        <Typography
          variant="caption"
          color="error"
          sx={{ display: 'block', px: 1.5, pt: 1 }}
        >
          Mermaid parse error: {renderError}
        </Typography>
      )}

      {showDiagram ? (
        // The cross-fade between the outgoing and incoming SVG on theme
        // toggle lives inside `MermaidDiagramSurface`, not here. mermaid
        // emits a fresh tree of inline-styled DOM nodes per render that
        // share no element identity with the previous SVG, so a CSS
        // `transition` on the surrounding chrome (which we have via
        // `MuiPaper` + the outer wrapper's `PALETTE_TRANSITION` below)
        // cannot bridge the two SVG states. Layering two SVGs through
        // an absolutely-positioned `aria-hidden` outgoing copy is the
        // only fix that does not require a third mermaid pipeline (see
        // `mermaid-rendering.mdc`).
        <MermaidDiagramSurface
          svg={svg}
          darkMode={darkMode}
          onOpenModal={handleOpenModal}
        />
      ) : (
        <Box
          component="pre"
          sx={{
            m: 0,
            p: 2,
            overflowX: 'auto',
            fontSize: '0.85em',
            fontFamily: 'source-code-pro, Menlo, Monaco, Consolas, "Courier New", monospace',
            // Alpha differs by scheme (8% in dark, 4% in light) so the
            // tint stays subtle against each scheme's `background.paper`.
            // `darkMode` is still a React boolean here because the alpha
            // *value* changes per scheme, not just the underlying color;
            // a single CSS variable cannot encode "different alpha per
            // active scheme" without a full per-scheme override.
            backgroundColor: darkMode
              ? 'rgba(var(--mui-palette-highlight-mainChannel) / 0.08)'
              : 'rgba(var(--mui-palette-highlight-mainChannel) / 0.04)',
            color: 'var(--mui-palette-text-primary)',
            transition: PALETTE_TRANSITION,
          }}
        >
          <code>{source}</code>
        </Box>
      )}

      <MermaidLightboxModal
        open={modalOpen}
        onClose={handleCloseModal}
        source={source}
        svg={svg}
        renderError={renderError}
      />
    </Box>
  );
}

// Memo so parent re-renders that don't change source / prerender
// props skip this subtree. Theme context still propagates via
// `useContext`, so the cache-hit fast path fires on dark/light flip.
export default memo(MermaidBlock);
