import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Menu, MenuItem, ListItemIcon, ListItemText, Divider } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ContentCutIcon from '@mui/icons-material/ContentCut';
import ContentPasteIcon from '@mui/icons-material/ContentPaste';
import SelectAllIcon from '@mui/icons-material/SelectAll';

import { findSelectionContainer, isEditableElement } from '../utils/dom';
import { useSavedSelection } from '../hooks/useSavedSelection';

const AppContextMenu = () => {
  const [anchorPos, setAnchorPos] = useState(null);
  const [selectionText, setSelectionText] = useState('');
  const [editable, setEditable] = useState(false);
  const targetRef = useRef(null);
  const { save, restore, reset, scheduleRestore } = useSavedSelection();

  const handleClose = useCallback(() => {
    setAnchorPos(null);
    targetRef.current = null;
    reset();
  }, [reset]);

  useEffect(() => {
    const onContextMenu = (event) => {
      event.preventDefault();

      const target = event.target;
      targetRef.current = target;

      const isEditable = isEditableElement(target);
      setEditable(isEditable);

      save(target);

      const sel = window.getSelection();
      const docText = sel ? sel.toString() : '';
      if (isEditable && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
        const start = target.selectionStart ?? 0;
        const end = target.selectionEnd ?? 0;
        // When the user right-clicks inside an INPUT/TEXTAREA with a
        // live selection we prefer that selection's text over whatever
        // ``window.getSelection()`` reports (the document-level API is
        // blind to form-control selections on most browsers).
        const inputText = start !== end ? target.value.slice(start, end) : '';
        setSelectionText(inputText || docText);
      } else {
        setSelectionText(docText);
      }

      setAnchorPos({ top: event.clientY, left: event.clientX });
    };

    document.addEventListener('contextmenu', onContextMenu);
    return () => document.removeEventListener('contextmenu', onContextMenu);
  }, [save]);

  useEffect(() => {
    if (anchorPos === null) return undefined;
    return scheduleRestore();
  }, [anchorPos, scheduleRestore]);

  const open = anchorPos !== null;
  const hasSelection = selectionText.length > 0;

  const handleCopy = async () => {
    const text = selectionText;
    handleClose();
    if (!text) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
    } catch (_) {
      // fall through to execCommand
    }
    try {
      document.execCommand('copy');
    } catch (_) { /* noop */ }
  };

  const handleCut = async () => {
    const text = selectionText;
    const t = targetRef.current;
    handleClose();
    if (!editable || !text) return;

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      }
    } catch (_) { /* noop */ }

    if (t && typeof t.focus === 'function') {
      try { t.focus(); } catch (_) { /* noop */ }
    }
    try {
      const ok = document.execCommand('delete');
      if (!ok) {
        document.execCommand('cut');
      }
    } catch (_) { /* noop */ }
  };

  const handlePaste = async () => {
    const t = targetRef.current;
    handleClose();
    if (!editable) return;

    let text = '';
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        text = await navigator.clipboard.readText();
      }
    } catch (_) {
      return;
    }
    if (!text) return;

    if (t && typeof t.focus === 'function') {
      try { t.focus(); } catch (_) { /* noop */ }
    }
    try {
      const ok = document.execCommand('insertText', false, text);
      if (ok) return;
    } catch (_) { /* noop */ }

    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) {
      const start = t.selectionStart ?? t.value.length;
      const end = t.selectionEnd ?? t.value.length;
      const next = t.value.slice(0, start) + text + t.value.slice(end);
      const setter = Object.getOwnPropertyDescriptor(
        t.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
        'value',
      )?.set;
      if (setter) {
        setter.call(t, next);
        t.dispatchEvent(new Event('input', { bubbles: true }));
        const caret = start + text.length;
        try { t.setSelectionRange(caret, caret); } catch (_) { /* noop */ }
      }
    }
  };

  const handleSelectAll = () => {
    const t = targetRef.current;
    const wasEditable = editable;
    handleClose();

    if (wasEditable && t) {
      try { t.focus(); } catch (_) { /* noop */ }
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') {
        try { t.select(); return; } catch (_) { /* noop */ }
      }
      try { document.execCommand('selectAll'); return; } catch (_) { /* noop */ }
    }

    const container = findSelectionContainer(t);
    const sel = window.getSelection();
    if (sel && container) {
      try {
        sel.removeAllRanges();
        const range = document.createRange();
        range.selectNodeContents(container);
        sel.addRange(range);
      } catch (_) { /* noop */ }
    }
  };

  return (
    <Menu
      open={open}
      onClose={handleClose}
      anchorReference="anchorPosition"
      anchorPosition={anchorPos || undefined}
      autoFocus={false}
      disableAutoFocus
      disableAutoFocusItem
      disableEnforceFocus
      disableRestoreFocus
      slotProps={{ paper: { sx: { minWidth: 180 } } }}
      MenuListProps={{ dense: true, autoFocus: false, autoFocusItem: false }}
      TransitionProps={{ onEntered: restore }}
    >
      <MenuItem onClick={handleCopy} disabled={!hasSelection}>
        <ListItemIcon><ContentCopyIcon fontSize="small" /></ListItemIcon>
        <ListItemText>Copy</ListItemText>
      </MenuItem>
      <MenuItem onClick={handleCut} disabled={!(editable && hasSelection)}>
        <ListItemIcon><ContentCutIcon fontSize="small" /></ListItemIcon>
        <ListItemText>Cut</ListItemText>
      </MenuItem>
      <MenuItem onClick={handlePaste} disabled={!editable}>
        <ListItemIcon><ContentPasteIcon fontSize="small" /></ListItemIcon>
        <ListItemText>Paste</ListItemText>
      </MenuItem>
      <Divider />
      <MenuItem onClick={handleSelectAll}>
        <ListItemIcon><SelectAllIcon fontSize="small" /></ListItemIcon>
        <ListItemText>Select All</ListItemText>
      </MenuItem>
    </Menu>
  );
};

export default AppContextMenu;
