import React from 'react';
import { IconButton } from '@mui/material';
import ReplayIcon from '@mui/icons-material/Replay';
import ZoomInIcon from '@mui/icons-material/ZoomIn';
import ZoomOutIcon from '@mui/icons-material/ZoomOut';

// Toolbar controls for modal mermaid interactions. Extracted from
// MermaidLightboxModal to keep that component under the ~250-line soft
// limit in `react-components.mdc` and to isolate "zoom command bar"
// rendering from "dialog layout + diagram surface" concerns.
export default function MermaidZoomControls({
  canZoomIn,
  canZoomOut,
  onZoomIn,
  onZoomOut,
  onReset,
}) {
  return (
    <>
      <IconButton
        aria-label="Zoom out"
        onClick={onZoomOut}
        disabled={!canZoomOut}
        size="small"
        sx={{ color: 'text.primary' }}
      >
        <ZoomOutIcon />
      </IconButton>
      <IconButton
        aria-label="Reset view"
        onClick={onReset}
        size="small"
        sx={{ color: 'text.primary' }}
      >
        <ReplayIcon />
      </IconButton>
      <IconButton
        aria-label="Zoom in"
        onClick={onZoomIn}
        disabled={!canZoomIn}
        size="small"
        sx={{ color: 'text.primary' }}
      >
        <ZoomInIcon />
      </IconButton>
    </>
  );
}
