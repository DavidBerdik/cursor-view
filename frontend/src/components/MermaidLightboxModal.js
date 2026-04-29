import React, { useContext } from 'react';
import { alpha, Box, Dialog, IconButton, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { ColorContext } from '../contexts/ColorContext';
import { ThemeModeContext } from '../contexts/ThemeModeContext';

// Full-size modal counterpart to MermaidBlock's inline diagram. The
// parent MermaidBlock holds `modalOpen` state and hands this modal the
// already-rendered SVG (plus the original `source` and any
// `renderError`); the modal does no mermaid work of its own.
//
// SVG-as-prop, not a second render: the singleton config, the
// `latestRef` cancellation, and the bomb-graphic-avoidance discipline
// (parse-before-render) all live in MermaidBlock. Calling
// `mermaid.render` again here would duplicate that work and re-open
// the bomb-graphic risk a failed render injects into document.body
// (see MermaidBlock's top-of-file comment). It would also constitute
// a third mermaid pipeline, which `mermaid-rendering.mdc` forbids.
//
// Theme parity with the inline view is automatic: when ThemeModeContext
// flips, MermaidBlock's `useEffect([source, darkMode])` regenerates
// `svg`, the new value flows down via props, and React reconciles the
// modal body. Do not add a duplicate `useEffect(darkMode)` here -- it
// would race the parent's render and potentially install a stale
// theme'd SVG over a fresh one.
//
// UX invariants: ESC and backdrop-click dismiss via MUI `Dialog`'s
// `onClose`; the close IconButton is the only toolbar control. There
// is exactly one diagram per modal so no prev/next nav row exists --
// the absence of a keydown `useEffect` is intentional, not an
// oversight, and keeps the latest-id pattern from
// `frontend-hooks.mdc` unnecessary.
//
// Parse-error fallback mirrors the inline behavior in MermaidBlock so
// the "graceful source fallback" invariant from
// `mermaid-rendering.mdc` holds across surfaces: Typography error
// caption above a `<pre><code>` block of the raw source. In practice
// MermaidBlock hides its expand affordance whenever `renderError` is
// set, so this branch is defensive -- it covers the case where a
// future caller opens the modal without first checking the
// success-only gate.
//
// All styling uses MUI theme tokens via ColorContext / palette so dark
// / light mode changes flow through automatically; no hard-coded hex.
export default function MermaidLightboxModal({
  open,
  onClose,
  source,
  svg,
  renderError,
}) {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);

  if (!open) {
    return null;
  }

  const hasDiagram = typeof svg === 'string' && svg.length > 0 && !renderError;

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
        {/* Toolbar row above the diagram: close button pinned right via
            `ml: 'auto'`. Laying it out as a flex sibling of the body --
            rather than an absolute overlay -- keeps it on its own
            horizontal band and avoids painting a control on top of the
            diagram content, matching `ImageLightboxModal`'s discipline. */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            minHeight: 32,
            mb: 1.5,
            flexShrink: 0,
          }}
        >
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
            // Hidden, not auto: the SVG itself is sized to fit the
            // container (see the `& svg` rule below), so a scrollbar
            // would only appear in pathological cases where mermaid's
            // own inline style refused our cap. Matching
            // `ImageLightboxModal`'s no-scroll modal body keeps the
            // two lightboxes feeling identical.
            overflow: 'hidden',
          }}
        >
          {hasDiagram ? (
            <Box
              role="img"
              aria-label="Mermaid diagram"
              dangerouslySetInnerHTML={{ __html: svg }}
              sx={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                width: '100%',
                height: '100%',
                p: 2,
                boxSizing: 'border-box',
                // No backgroundColor: the modal Paper already supplies
                // `background.paper` as the surface, and mermaid's
                // own `theme: 'dark'` / `'default'` palette is legible
                // against it. Painting an extra tint here would
                // reintroduce the visible "box behind the diagram"
                // that the inline view shows for visual separation
                // inside a chat bubble -- the modal does not need
                // that separator because the Paper edge already
                // serves the same role.
                // Fit-contain behavior for the inline SVG, mirroring
                // `ImageLightboxModal`'s `objectFit: 'contain'` on its
                // `<img>`. The four rules together cap both axes to the
                // container while preserving the SVG's intrinsic aspect
                // ratio: `width/height: auto` lets the browser solve
                // for the limiting axis, and `maxWidth/maxHeight: 100%`
                // are flagged `!important` because mermaid emits the
                // SVG with an inline `style="max-width: <px>"` that
                // would otherwise win on specificity and re-clip tall
                // diagrams to scroll.
                '& svg': {
                  display: 'block',
                  width: 'auto !important',
                  height: 'auto !important',
                  maxWidth: '100% !important',
                  maxHeight: '100% !important',
                },
              }}
            />
          ) : (
            // Defensive fallback: MermaidBlock hides the expand
            // affordance when `renderError` is set or `svg` is null,
            // but a future caller that forgets that gate must still
            // see something useful instead of an empty Paper.
            <Box sx={{ width: '100%', height: '100%', p: 2, boxSizing: 'border-box' }}>
              {renderError && (
                <Typography
                  variant="caption"
                  color="error"
                  sx={{ display: 'block', mb: 1 }}
                >
                  Mermaid parse error: {renderError}
                </Typography>
              )}
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 2,
                  overflow: 'auto',
                  maxHeight: '100%',
                  fontSize: '0.85em',
                  fontFamily:
                    'source-code-pro, Menlo, Monaco, Consolas, "Courier New", monospace',
                  backgroundColor: alpha(colors.highlightColor, darkMode ? 0.08 : 0.04),
                  color: colors.text.primary,
                  borderRadius: 1,
                }}
              >
                <code>{source}</code>
              </Box>
            </Box>
          )}
        </Box>
      </Box>
    </Dialog>
  );
}
