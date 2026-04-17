import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Menu, MenuItem, ListItemIcon, ListItemText, Divider } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ContentCutIcon from '@mui/icons-material/ContentCut';
import ContentPasteIcon from '@mui/icons-material/ContentPaste';
import SelectAllIcon from '@mui/icons-material/SelectAll';

const isEditableElement = (el) => {
  if (!el || el.nodeType !== 1) return false;
  const tag = el.tagName;
  if (tag === 'INPUT') {
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    const textLike = [
      'text', 'search', 'url', 'tel', 'email', 'password', 'number',
    ];
    return !el.disabled && !el.readOnly && textLike.includes(type);
  }
  if (tag === 'TEXTAREA') {
    return !el.disabled && !el.readOnly;
  }
  return el.isContentEditable === true;
};

const findSelectionContainer = (el) => {
  let node = el;
  while (node && node.nodeType === 1) {
    const style = window.getComputedStyle(node);
    if (style.display === 'block' || style.display === 'flex' || style.display === 'grid') {
      return node;
    }
    node = node.parentElement;
  }
  return el || document.body;
};

const AppContextMenu = () => {
  const [anchorPos, setAnchorPos] = useState(null);
  const [selectionText, setSelectionText] = useState('');
  const [editable, setEditable] = useState(false);
  const targetRef = useRef(null);
  const savedRangesRef = useRef([]);
  const savedInputSelectionRef = useRef(null);

  const restoreSelection = useCallback(() => {
    const inputSel = savedInputSelectionRef.current;
    if (inputSel) {
      const { el, start, end, direction } = inputSel;
      try {
        el.setSelectionRange(start, end, direction || 'none');
      } catch (_) { /* noop */ }
      return;
    }
    const ranges = savedRangesRef.current;
    if (!ranges.length) return;
    const sel = window.getSelection();
    if (!sel) return;
    try {
      sel.removeAllRanges();
      ranges.forEach((r) => sel.addRange(r));
    } catch (_) { /* noop */ }
  }, []);

  const handleClose = useCallback(() => {
    setAnchorPos(null);
    targetRef.current = null;
    savedRangesRef.current = [];
    savedInputSelectionRef.current = null;
  }, []);

  useEffect(() => {
    const onContextMenu = (event) => {
      event.preventDefault();

      const target = event.target;
      targetRef.current = target;

      const isEditable = isEditableElement(target);
      setEditable(isEditable);

      const sel = window.getSelection();
      const docText = sel ? sel.toString() : '';

      savedRangesRef.current = [];
      savedInputSelectionRef.current = null;

      if (isEditable && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
        const start = target.selectionStart ?? 0;
        const end = target.selectionEnd ?? 0;
        savedInputSelectionRef.current = {
          el: target,
          start,
          end,
          direction: target.selectionDirection,
        };
        const inputText = start !== end ? target.value.slice(start, end) : '';
        setSelectionText(inputText || docText);
      } else {
        if (sel) {
          const ranges = [];
          for (let i = 0; i < sel.rangeCount; i += 1) {
            ranges.push(sel.getRangeAt(i).cloneRange());
          }
          savedRangesRef.current = ranges;
        }
        setSelectionText(docText);
      }

      setAnchorPos({ top: event.clientY, left: event.clientX });
    };

    document.addEventListener('contextmenu', onContextMenu);
    return () => document.removeEventListener('contextmenu', onContextMenu);
  }, []);

  useEffect(() => {
    if (anchorPos === null) return undefined;
    const raf1 = requestAnimationFrame(() => {
      restoreSelection();
      requestAnimationFrame(restoreSelection);
    });
    return () => cancelAnimationFrame(raf1);
  }, [anchorPos, restoreSelection]);

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
      TransitionProps={{ onEntered: restoreSelection }}
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
