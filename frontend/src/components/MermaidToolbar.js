import React, { useContext } from 'react';
import { Box, IconButton, SvgIcon, Tooltip } from '@mui/material';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import CodeIcon from '@mui/icons-material/Code';
import { ColorContext } from '../contexts/ColorContext';

// Lucide-style "open in full screen" glyph used by Cursor: two
// stroke-only L-shape arrowheads at the top-left and bottom-right
// corners with diagonals pointing inward. Material's `OpenInFullIcon`
// is filled rather than stroked, so it does not match Cursor's UI;
// shipping a small inline SvgIcon avoids pulling in another icon set
// just for this glyph.
function FullScreenIcon(props) {
  return (
    <SvgIcon
      {...props}
      viewBox="0 0 24 24"
      sx={{
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 2,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
      }}
    >
      <polyline points="3 9 3 3 9 3" />
      <polyline points="21 15 21 21 15 21" />
      <line x1="3" y1="3" x2="10" y2="10" />
      <line x1="21" y1="21" x2="14" y2="14" />
    </SvgIcon>
  );
}

// Absolute-positioned overlay rendered inside `MermaidBlock`'s outer
// border. Houses the diagram/source toggle (always shown when the
// parent says the diagram is renderable) and the expand-into-modal
// affordance (shown only in diagram mode, since the lightbox modal is
// diagram-only by design -- see `MermaidLightboxModal`).
//
// Two reasons this lives in its own file:
//
// 1. `react-components.mdc` decomposes any component over ~250 lines
//    into siblings. `MermaidBlock` owns the heavyweight async
//    `mermaid.parse` + `mermaid.render` effect, the `latestRef`
//    cancellation pattern, the `skipFirstRenderRef` first-mount
//    suppression, and the diagram/source/error tri-state. The toolbar
//    is none of that -- it's a stateless overlay -- so extracting it
//    keeps both files focused on a single concern.
// 2. The `<Box onClick={(e) => e.stopPropagation()}>` wrapper exists
//    because the diagram body underneath is itself a clickable
//    `<button>` (the second affordance for opening the modal). Without
//    `stopPropagation`, a click on either toolbar IconButton would
//    bubble to the underlying button and double-fire the modal-open
//    handler. Keeping that quirk here, next to the buttons that
//    motivate it, keeps the parent JSX from carrying overlay-specific
//    plumbing.
//
// The expand-button gate is the parent's `showDiagram` boolean (passed
// as `showExpand`). Re-deriving it here would require passing `mode`,
// `svg`, and `renderError`, defeating the extraction.
export default function MermaidToolbar({ mode, showExpand, onToggleMode, onOpenModal }) {
  const colors = useContext(ColorContext);

  return (
    <Box
      onClick={(e) => e.stopPropagation()}
      sx={{
        position: 'absolute',
        top: 4,
        right: 4,
        zIndex: 1,
        display: 'flex',
        gap: 0.5,
      }}
    >
      {showExpand && (
        <Tooltip title="Full screen">
          <IconButton
            aria-label="Open mermaid diagram in modal"
            size="small"
            onClick={onOpenModal}
            sx={{
              color: colors.text.secondary,
              '&:hover': { color: colors.highlightColor },
            }}
          >
            <FullScreenIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Tooltip title={mode === 'diagram' ? 'View source' : 'View diagram'}>
        <IconButton
          aria-label={mode === 'diagram' ? 'View diagram source' : 'View rendered diagram'}
          aria-pressed={mode === 'source'}
          size="small"
          onClick={onToggleMode}
          sx={{
            color: colors.text.secondary,
            '&:hover': { color: colors.highlightColor },
          }}
        >
          {mode === 'diagram' ? <CodeIcon fontSize="small" /> : <AccountTreeIcon fontSize="small" />}
        </IconButton>
      </Tooltip>
    </Box>
  );
}
