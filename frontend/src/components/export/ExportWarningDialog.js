import React from 'react';
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
} from '@mui/material';
import WarningIcon from '@mui/icons-material/Warning';

// Second dialog in the export flow: the "check for sensitive data"
// warning, with the persistent "don't show again" checkbox. Driven
// entirely by props. Both buttons use `color="highlight"` so the
// dialog looks the same regardless of which page opened it (the
// pre-refactor chat list version used `color="primary"` on Cancel by
// mistake).
export default function ExportWarningDialog({
  open,
  dontShow,
  onDontShowChange,
  onClose,
}) {
  return (
    <Dialog
      open={open}
      onClose={() => onClose(false)}
      aria-labelledby="export-warning-dialog-title"
    >
      <DialogTitle id="export-warning-dialog-title" sx={{ display: 'flex', alignItems: 'center' }}>
        <WarningIcon sx={{ color: 'warning.main', mr: 1 }} />
        Export Warning
      </DialogTitle>
      <DialogContent>
        <DialogContentText>
          Please make sure your exported chat doesn&apos;t include sensitive data such as API keys and customer information.
        </DialogContentText>
        <FormControlLabel
          control={(
            <Checkbox
              checked={dontShow}
              onChange={(event) => onDontShowChange(event.target.checked)}
            />
          )}
          label="Don't show this warning again"
          sx={{ mt: 2 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={() => onClose(false)} color="highlight">
          Cancel
        </Button>
        <Button onClick={() => onClose(true)} color="highlight" variant="contained">
          Continue Export
        </Button>
      </DialogActions>
    </Dialog>
  );
}
