import React, { useContext } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Radio,
  RadioGroup,
} from '@mui/material';
import FileDownloadIcon from '@mui/icons-material/FileDownload';

import { ColorContext } from '../../contexts/ColorContext';

// First dialog in the export flow: pick HTML / JSON / Markdown. Driven
// entirely by props so `useExportFlow` can own the state.
export default function ExportFormatDialog({
  open,
  format,
  onFormatChange,
  onClose,
}) {
  const colors = useContext(ColorContext);

  return (
    <Dialog
      open={open}
      onClose={() => onClose(false)}
      aria-labelledby="format-selection-dialog-title"
    >
      <DialogTitle id="format-selection-dialog-title" sx={{ display: 'flex', alignItems: 'center' }}>
        <FileDownloadIcon sx={{ color: colors.highlightColor, mr: 1 }} />
        Export Format
      </DialogTitle>
      <DialogContent>
        <DialogContentText>
          Please select the export format for your chat:
        </DialogContentText>
        <FormControl component="fieldset" sx={{ mt: 2 }}>
          <RadioGroup
            aria-label="export-format"
            name="export-format"
            value={format}
            onChange={(event) => onFormatChange(event.target.value)}
          >
            <FormControlLabel value="html" control={<Radio />} label="HTML" />
            <FormControlLabel value="json" control={<Radio />} label="JSON" />
            <FormControlLabel value="markdown" control={<Radio />} label="Markdown" />
          </RadioGroup>
        </FormControl>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => onClose(false)} color="highlight">
          Cancel
        </Button>
        <Button onClick={() => onClose(true)} color="highlight" variant="contained">
          Continue
        </Button>
      </DialogActions>
    </Dialog>
  );
}
