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
// ``initialSvg`` and ``initialError`` are produced by prerenderMermaidDiagrams
// in ChatDetail's fetch effect (before setLoading(false)) and cover both
// the happy path and the error path:
//
//  - ``initialSvg`` present  → diagram is valid; start in rendered state,
//    skip the first-mount mermaid.render call entirely.
//  - ``initialError`` present → diagram failed mermaid.parse; start directly
//    in the error+source state. mermaid.render is never called for this
//    diagram, which prevents mermaid from injecting its bomb-graphic error
//    element into document.body (a visible side effect of a failed render).
//  - Neither present          → no pre-render data (e.g. cache miss); the
//    useEffect runs normally on first mount.
export default function MermaidBlock({ source, initialSvg, initialError }) {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  const [mode, setMode] = useState(initialError ? 'source' : 'diagram');
  const [svg, setSvg] = useState(initialSvg ?? null);
  const [renderError, setRenderError] = useState(initialError ?? null);
  // Tracks the latest render attempt so stale async results are discarded.
  const latestRef = useRef(0);
  // Skip the first-mount render when pre-render data is available for either
  // the success or error case. Theme-flip re-renders still go through the
  // effect so the SVG is regenerated with the new theme.
  const skipFirstRenderRef = useRef(Boolean(initialSvg) || Boolean(initialError));

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
    const renderId = nextMermaidId();

    mermaid
      .render(renderId, source)
      .then(({ svg: renderedSvg }) => {
        if (id !== latestRef.current) {
          return;
        }
        setSvg(renderedSvg);
        setRenderError(null);
      })
      .catch((err) => {
        if (id !== latestRef.current) {
          return;
        }
        // Surface the parser message and fall back to source view so the
        // user can see what went wrong without losing the raw text.
        setRenderError(err?.message ?? String(err));
        setMode('source');
      });
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
