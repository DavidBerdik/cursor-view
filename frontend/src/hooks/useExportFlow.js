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
  const { dontShow, setDontShow, persist } = useExportWarningPreference();

  const proceed = useCallback(
    async (sessionId, fmt) => {
      const result = await exportChat({ sessionId, format: fmt, darkMode });
      if (result.saved) {
        if (result.path) {
          alert(`Saved to ${result.path}`);
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

      // TODO(bug): persists the cookie regardless of `confirmed`, so a
      // user who ticks "Don't show this warning again" and then clicks
      // Cancel still has the preference recorded. Original behavior was
      // duplicated across both pages before this hook was introduced;
      // preserve it for now and fix in a dedicated change. The guard
      // should be `if (confirmed) { persist(); }`.
      persist();

      if (confirmed && pendingSessionId) {
        proceed(pendingSessionId, format);
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
  };
}
