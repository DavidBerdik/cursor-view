import React, { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { alpha, Box, Typography } from '@mui/material';
import mermaid from 'mermaid';
import { ColorContext } from '../contexts/ColorContext';
import { ThemeModeContext } from '../contexts/ThemeModeContext';
import MermaidLightboxModal from './MermaidLightboxModal';
import MermaidToolbar from './MermaidToolbar';

// Counter used to generate unique IDs for mermaid.render. Mermaid
// requires each call to use a distinct ID; an incrementing module-level
// counter is simpler than uuid and safe for our single-threaded render path.
let _idCounter = 0;

function nextMermaidId() {
  _idCounter += 1;
  return `mermaid-block-${_idCounter}`;
}

// Renders a single mermaid fenced code block as either a live diagram
// (default) or the raw source text. The diagram mode uses mermaid.render,
// which is async; the latestRef pattern from frontend-hooks.mdc ensures
// that a stale render (e.g. a theme flip that triggers a new render while
// the old one is still in flight) cannot overwrite the fresher result.
//
// The render effect always validates with mermaid.parse before calling
// mermaid.render and treats a parse rejection as terminal for that pass.
// This is the invariant that keeps theme flips idempotent: mermaid.render
// injects a "bomb" SVG into document.body as a side effect when its
// internal parse fails, and that DOM mutation cannot be undone from the
// .catch handler — without the parse-first guard, every dark/light toggle
// on a chat containing an invalid diagram would leave one more orphaned
// bomb at the end of the page. prerenderMermaidDiagrams enforces the same
// invariant on the pre-paint path; both pipelines are documented together
// in mermaid-rendering.mdc.
//
// ``initialSvg`` / ``initialError`` / ``initialDarkMode`` come from
// prerenderMermaidDiagrams in ChatDetail's fetch effect (before
// setLoading(false)) so MermaidBlock starts in the correct state on
// first paint. skipFirstRenderRef suppresses the first-mount render
// only when the prerender result is still authoritative: errors
// qualify unconditionally (the message string is theme-independent),
// but a cached SVG qualifies only when the prerender's darkMode
// matches the current darkMode — a mismatch means the user toggled
// theme during ChatDetail's loading window, the cached SVG was themed
// against the prior value, and the per-block effect must run on first
// mount so the diagram is re-themed. Theme flips after first mount
// always go through the effect, so valid diagrams re-render with the
// new theme. See "Theme-tagged prerender entries" in
// mermaid-rendering.mdc.
export default function MermaidBlock({ source, initialSvg, initialError, initialDarkMode }) {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  const [mode, setMode] = useState(initialError ? 'source' : 'diagram');
  const [svg, setSvg] = useState(initialSvg ?? null);
  const [renderError, setRenderError] = useState(initialError ?? null);
  // Tracks the latest render attempt so stale async results are discarded.
  const latestRef = useRef(0);
  // Skip the redundant first-mount render when prerenderMermaidDiagrams
  // already produced a usable result for this source. Errors are
  // theme-independent so they always qualify; cached SVGs only qualify
  // when their prerender-time theme still matches the current darkMode,
  // otherwise the user toggled theme during ChatDetail's loading window
  // and the cached SVG is stale (see "Theme-tagged prerender entries"
  // in mermaid-rendering.mdc).
  const skipFirstRenderRef = useRef(
    Boolean(initialError) || (Boolean(initialSvg) && initialDarkMode === darkMode),
  );

  useEffect(() => {
    if (!source) {
      return;
    }

    if (skipFirstRenderRef.current) {
      skipFirstRenderRef.current = false;
      return;
    }

    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: darkMode ? 'dark' : 'default',
    });

    const id = ++latestRef.current;

    (async () => {
      try {
        await mermaid.parse(source);
      } catch (parseErr) {
        if (id !== latestRef.current) {
          return;
        }
        // Surface the parser message and fall back to source view so the
        // user can see what went wrong without losing the raw text.
        setRenderError(parseErr?.message ?? String(parseErr));
        setMode('source');
        return;
      }

      const renderId = nextMermaidId();
      try {
        const { svg: renderedSvg } = await mermaid.render(renderId, source);
        if (id !== latestRef.current) {
          return;
        }
        setSvg(renderedSvg);
        setRenderError(null);
      } catch (err) {
        if (id !== latestRef.current) {
          return;
        }
        setRenderError(err?.message ?? String(err));
        setMode('source');
      }
    })();
  }, [source, darkMode]);

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
        borderColor: alpha(colors.highlightColor, 0.2),
        borderRadius: 1,
        overflow: 'hidden',
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
        // Diagram body is itself the click surface for the modal
        // (paired with the expand icon in the toolbar above for
        // discoverability/accessibility). Rendered as `<button>` for
        // semantics + keyboard activation; default chrome is reset
        // (`border: 'none'`, transparent backgroundColor below the
        // theme tint, font/color inherited) so the visual is identical
        // to the prior `<Box>`. Mermaid's `securityLevel: 'strict'`
        // disables in-SVG click handlers, so wrapping the diagram in a
        // button cannot suppress library interactivity. `width: 100%`
        // and `textAlign: 'inherit'` undo the default `<button>`
        // shrink-to-fit + center-align that would otherwise reflow the
        // diagram. `userSelect: 'text'` overrides the user-agent
        // default that Safari (and historically other browsers) apply
        // to form elements, so labels inside the rendered SVG remain
        // copy-selectable; drag-to-select does not trigger the click
        // handler because click only fires on a movement-free mouseup.
        <Box
          component="button"
          type="button"
          onClick={handleOpenModal}
          aria-label="Open mermaid diagram in modal"
          dangerouslySetInnerHTML={{ __html: svg }}
          sx={{
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
            backgroundColor: darkMode
              ? alpha(colors.highlightColor, 0.04)
              : alpha(colors.highlightColor, 0.02),
            '& svg': { maxWidth: '100%', height: 'auto' },
          }}
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
            backgroundColor: alpha(colors.highlightColor, darkMode ? 0.08 : 0.04),
            color: colors.text.primary,
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
