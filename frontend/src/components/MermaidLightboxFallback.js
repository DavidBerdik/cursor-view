import React, { useContext } from 'react';
import { alpha, Box, Typography } from '@mui/material';
import { ColorContext } from '../contexts/ColorContext';
import { ThemeModeContext } from '../contexts/ThemeModeContext';

// Defensive fallback panel for MermaidLightboxModal: a caller-supplied
// `renderError` caption above the raw mermaid `source` as a monospace
// code block. Mirrors the inline behavior in MermaidBlock so the
// "graceful source fallback" invariant from `mermaid-rendering.mdc`
// holds across both surfaces.
//
// MermaidBlock hides its expand affordance whenever `renderError` is set
// or `svg` is null, so this panel is defensive in practice -- it covers
// the case where a future caller opens the modal without first checking
// the success-only gate. Extracted from MermaidLightboxModal alongside
// MermaidZoomControls to keep the modal under the ~250-line soft limit
// in `react-components.mdc` and to keep "diagram surface" and "source
// fallback" rendering as separate concerns.
export default function MermaidLightboxFallback({ source, renderError }) {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  return (
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
  );
}
