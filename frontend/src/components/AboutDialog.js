import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
} from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

// Ordered (label, diagnostics-key) pairs so the dialog rows and the
// copy-to-clipboard text share one source of truth.
const FIELDS = [
  ['Version', 'version'],
  ['Platform', 'platform'],
  ['Python', 'python_version'],
  ['pywebview', 'pywebview_version'],
  ['Webview backend', 'pywebview_backend'],
  ['Cache directory', 'cache_dir'],
  ['Log directory', 'log_dir'],
];

function diagnosticsToText(diag) {
  return FIELDS.map(([label, key]) => `${label}: ${diag[key] ?? 'unknown'}`).join(
    '\n',
  );
}

// About dialog showing environment diagnostics for bug reports. Opened
// in desktop mode via the Help -> About menu item, which dispatches the
// `cursor-view:open-about` event that `App.js::ThemeModeBridge` turns
// into the `open` prop. Fetches diagnostics from the Python bridge each
// time it opens (the values are static per launch, but fetching lazily
// keeps it a no-op until the user actually asks).
export default function AboutDialog({ open, onClose }) {
  const [diag, setDiag] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    setCopied(false);
    const api =
      typeof window !== 'undefined' && window.pywebview && window.pywebview.api;
    if (!api || typeof api.get_diagnostics !== 'function') {
      return undefined;
    }
    let cancelled = false;
    Promise.resolve(api.get_diagnostics())
      .then((result) => {
        if (!cancelled && result && typeof result === 'object') {
          setDiag(result);
        }
      })
      .catch(() => {
        // Diagnostics are best-effort; leave the prior value in place.
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleCopy = () => {
    if (!diag || !navigator.clipboard) {
      return;
    }
    navigator.clipboard
      .writeText(diagnosticsToText(diag))
      .then(() => setCopied(true))
      .catch(() => {
        // Clipboard can be unavailable/denied; no user-facing failure.
      });
  };

  return (
    <Dialog open={open} onClose={onClose} aria-labelledby="about-dialog-title">
      <DialogTitle
        id="about-dialog-title"
        sx={{ display: 'flex', alignItems: 'center' }}
      >
        <InfoOutlinedIcon
          sx={{ color: 'var(--mui-palette-highlight-main)', mr: 1 }}
        />
        About Cursor View
      </DialogTitle>
      <DialogContent dividers>
        {diag ? (
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'auto 1fr',
              columnGap: 2,
              rowGap: 1,
            }}
          >
            {FIELDS.map(([label, key]) => (
              <React.Fragment key={key}>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {label}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{ wordBreak: 'break-all', fontFamily: 'monospace' }}
                >
                  {diag[key] ?? 'unknown'}
                </Typography>
              </React.Fragment>
            ))}
          </Box>
        ) : (
          <Typography variant="body2">Loading diagnostics…</Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleCopy} color="highlight" disabled={!diag}>
          {copied ? 'Copied' : 'Copy to Clipboard'}
        </Button>
        <Button onClick={onClose} color="highlight" variant="contained">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}
