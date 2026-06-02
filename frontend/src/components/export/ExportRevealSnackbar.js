import React from 'react';
import { Snackbar, Button } from '@mui/material';

// Post-export confirmation toast shown after a desktop-mode "Save as..."
// completes. Offers a "Reveal" action that asks the Python bridge to show
// the saved file in the OS file manager (Finder / Explorer), plus a
// Dismiss. Driven entirely by props so `useExportFlow` owns the state; it
// is only ever rendered open in desktop mode because the browser export
// path returns no file path to reveal.
export default function ExportRevealSnackbar({ open, onReveal, onClose }) {
  return (
    <Snackbar
      open={open}
      autoHideDuration={6000}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      onClose={(event, reason) => {
        // Keep the toast up on an incidental click elsewhere; only an
        // explicit Dismiss or the auto-hide timeout closes it.
        if (reason === 'clickaway') {
          return;
        }
        onClose();
      }}
      message="Chat exported"
      action={
        <>
          <Button color="highlight" size="small" onClick={onReveal}>
            Reveal
          </Button>
          <Button color="inherit" size="small" onClick={onClose}>
            Dismiss
          </Button>
        </>
      }
    />
  );
}
