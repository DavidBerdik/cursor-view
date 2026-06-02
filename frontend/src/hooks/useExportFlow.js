import { useCallback, useState } from 'react';

import { exportChat } from '../utils/exportChat';
import { useExportWarningPreference } from './useExportWarningPreference';

// Owns the shared state machine behind the Export button on both the
// chat list and the chat detail pages:
//
//   [user clicks Export]
//     -> requestExport(sessionId)
//        -> format dialog opens
//   [user picks format + Continue]
//     -> handleFormatConfirm(true)
//        -> if dontShow: proceed() directly
//        -> else:         warning dialog opens
//   [user reads warning + Continue]
//     -> handleWarningConfirm(true)
//        -> persist()  (writes the "don't show again" cookie)
//        -> proceed()  (runs exportChat and surfaces the result)
//
// `proceed()` is internal; callers drive the machine through
// `requestExport` / `handleFormatConfirm` / `handleWarningConfirm` and
// feed `{formatDialogOpen, warningDialogOpen, format, setFormat, dontShow,
// setDontShow}` into the dialog components.
export function useExportFlow({ darkMode }) {
  const [format, setFormat] = useState('html');
  const [pendingSessionId, setPendingSessionId] = useState(null);
  const [formatDialogOpen, setFormatDialogOpen] = useState(false);
  const [warningDialogOpen, setWarningDialogOpen] = useState(false);
  // Post-save "reveal" toast. Only the desktop bridge's save_export
  // returns a `path` (browser mode streams a download with no path), so a
  // non-null `savedPath` already implies desktop mode -- the Snackbar and
  // its Reveal action are never shown in the browser.
  const [savedPath, setSavedPath] = useState(null);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const { dontShow, setDontShow, persist } = useExportWarningPreference();

  const proceed = useCallback(
    async (sessionId, fmt) => {
      const result = await exportChat({ sessionId, format: fmt, darkMode });
      if (result.saved) {
        if (result.path) {
          // Desktop save: replace the old blocking alert with a Snackbar
          // that offers to reveal the file in the OS file manager.
          setSavedPath(result.path);
          setSnackbarOpen(true);
        }
        return;
      }
      if (result.cancelled) {
        return;
      }
      alert(`Failed to export chat: ${result.error || 'Unknown error'}`);
    },
    [darkMode],
  );

  const closeSnackbar = useCallback(() => {
    setSnackbarOpen(false);
  }, []);

  const revealSavedFile = useCallback(() => {
    setSnackbarOpen(false);
    const path = savedPath;
    if (!path) {
      return;
    }
    // Per-method bridge gate (the readiness race does not apply here --
    // by the time a user clicks Reveal, pywebview is long since injected).
    const api =
      typeof window !== 'undefined' && window.pywebview && window.pywebview.api;
    if (api && typeof api.reveal_export === 'function') {
      api.reveal_export(path);
    }
  }, [savedPath]);

  const requestExport = useCallback((sessionId) => {
    setPendingSessionId(sessionId);
    setFormatDialogOpen(true);
  }, []);

  const handleFormatConfirm = useCallback(
    (confirmed) => {
      setFormatDialogOpen(false);
      if (!confirmed) {
        setPendingSessionId(null);
        return;
      }
      if (dontShow && pendingSessionId) {
        proceed(pendingSessionId, format);
        setPendingSessionId(null);
        return;
      }
      if (pendingSessionId) {
        setWarningDialogOpen(true);
      }
    },
    [dontShow, pendingSessionId, format, proceed],
  );

  const handleWarningConfirm = useCallback(
    (confirmed) => {
      setWarningDialogOpen(false);

      if (confirmed) {
        persist();
        if (pendingSessionId) {
          proceed(pendingSessionId, format);
        }
      }
      setPendingSessionId(null);
    },
    [persist, pendingSessionId, format, proceed],
  );

  return {
    format,
    setFormat,
    dontShow,
    setDontShow,
    formatDialogOpen,
    warningDialogOpen,
    requestExport,
    handleFormatConfirm,
    handleWarningConfirm,
    savedPath,
    snackbarOpen,
    closeSnackbar,
    revealSavedFile,
  };
}
