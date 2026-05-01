import React, { memo, useCallback, useContext, useEffect, useState } from 'react';
import { Box, Typography } from '@mui/material';
import { ThemeModeContext } from '../contexts/ThemeModeContext';
import { useMermaidBlockHeight } from '../hooks/useMermaidBlockHeight';
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
  // Persisted-across-refresh placeholder height for the
  // `contentVisibility: 'auto'` outer `<Box>` below. Read once via
  // a lazy `useState` initializer inside the hook so the value is
  // stable for this block's lifetime; the hook's `ResizeObserver`
  // writes the latest measured height back to the cache as the
  // user scrolls past, so the next refresh reads the freshest
  // value. See `useMermaidBlockHeight`'s file header for the full
  // rationale.
  const { ref: heightRef, persistedHeight } = useMermaidBlockHeight(source);

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
      ref={heightRef}
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
        // `containIntrinsicSize: '0 Npx'` reserves a placeholder
        // height so the scrollbar doesn't jump as off-screen blocks
        // materialize (`0` = use parent's width). The N is the
        // height the same block measured in a previous session via
        // `useMermaidBlockHeight`'s `ResizeObserver` (persisted in
        // `mermaidHeightCache` under sessionStorage), falling back
        // to a 400px heuristic when no entry exists yet (first-ever
        // load, privacy-mode users where sessionStorage is
        // unavailable, or sources never scrolled into view long
        // enough for the observer to fire). The persisted-height
        // path is what makes `useChatScrollAnchor`'s scroll restore
        // deterministic on refresh of diagram-heavy chats: with the
        // placeholder matching the actual rendered height, the
        // anchor's `offsetTop` is correct on first measurement and
        // the rAF chase loop converges in one frame instead of
        // racing the browser's `content-visibility` evaluator. See
        // `theme-transitions.mdc` "Two CSS containment hints" for
        // the cross-component contract. Browsers without
        // `content-visibility` support (older Firefox) silently
        // ignore both properties.
        contentVisibility: 'auto',
        containIntrinsicSize: `0 ${persistedHeight ?? 400}px`,
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
