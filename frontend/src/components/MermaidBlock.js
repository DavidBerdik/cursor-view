import React, { useContext, useEffect, useRef, useState } from 'react';
import { alpha, Box, IconButton, Tooltip, Typography } from '@mui/material';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import CodeIcon from '@mui/icons-material/Code';
import mermaid from 'mermaid';
import { ColorContext } from '../contexts/ColorContext';
import { ThemeModeContext } from '../contexts/ThemeModeContext';

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
        <Tooltip title={mode === 'diagram' ? 'View source' : 'View diagram'}>
          <IconButton
            aria-label={mode === 'diagram' ? 'View diagram source' : 'View rendered diagram'}
            aria-pressed={mode === 'source'}
            size="small"
            onClick={toggleMode}
            sx={{
              position: 'absolute',
              top: 4,
              right: 4,
              zIndex: 1,
              color: colors.text.secondary,
              '&:hover': { color: colors.highlightColor },
            }}
          >
            {mode === 'diagram' ? (
              <CodeIcon fontSize="small" />
            ) : (
              <AccountTreeIcon fontSize="small" />
            )}
          </IconButton>
        </Tooltip>
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
        <Box
          role="img"
          aria-label="Mermaid diagram"
          dangerouslySetInnerHTML={{ __html: svg }}
          sx={{
            display: 'flex',
            justifyContent: 'center',
            p: 2,
            // Mermaid inlines its own colors; set a neutral background
            // so the SVG is legible in both light and dark themes.
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
    </Box>
  );
}
