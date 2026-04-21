import { useCallback, useRef } from 'react';

import { isEditableElement } from '../utils/dom';

// Preserve the user's text selection across the context-menu open cycle.
// MUI's <Menu> steals focus from the original target when it mounts,
// which on most browsers clears the document selection. Capturing the
// selection at right-click time and restoring it once the menu is on
// screen lets Copy / Cut operate on exactly what the user had selected.
//
// The hook owns two parallel stores:
// - ``rangesRef`` for document-level selections (contenteditable, page
//   text, etc.) which are ``Range`` objects we clone so mutations to
//   the live selection do not invalidate them.
// - ``inputSelRef`` for the INPUT / TEXTAREA case, where the browser
//   tracks selection as (start, end, direction) on the element itself
//   rather than through ``window.getSelection()``.
//
// ``scheduleRestore`` wraps a two-step ``requestAnimationFrame`` chain
// that matches how the component dispatched restore before the hook
// existed: one frame to let MUI's focus trap settle, another to survive
// any final focus nudge the <Menu>'s enter transition makes.
export function useSavedSelection() {
  const rangesRef = useRef([]);
  const inputSelRef = useRef(null);

  const save = useCallback((target) => {
    rangesRef.current = [];
    inputSelRef.current = null;
    const isInputLike = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA');
    if (isEditableElement(target) && isInputLike) {
      const start = target.selectionStart ?? 0;
      const end = target.selectionEnd ?? 0;
      inputSelRef.current = {
        el: target,
        start,
        end,
        direction: target.selectionDirection,
      };
      return;
    }
    const sel = window.getSelection();
    if (!sel) return;
    const ranges = [];
    for (let i = 0; i < sel.rangeCount; i += 1) {
      ranges.push(sel.getRangeAt(i).cloneRange());
    }
    rangesRef.current = ranges;
  }, []);

  const restore = useCallback(() => {
    const inputSel = inputSelRef.current;
    if (inputSel) {
      const { el, start, end, direction } = inputSel;
      try {
        el.setSelectionRange(start, end, direction || 'none');
      } catch (_) { /* noop */ }
      return;
    }
    const ranges = rangesRef.current;
    if (!ranges.length) return;
    const sel = window.getSelection();
    if (!sel) return;
    try {
      sel.removeAllRanges();
      ranges.forEach((r) => sel.addRange(r));
    } catch (_) { /* noop */ }
  }, []);

  const scheduleRestore = useCallback(() => {
    const raf1 = requestAnimationFrame(() => {
      restore();
      requestAnimationFrame(restore);
    });
    return () => cancelAnimationFrame(raf1);
  }, [restore]);

  const reset = useCallback(() => {
    rangesRef.current = [];
    inputSelRef.current = null;
  }, []);

  return { save, restore, reset, scheduleRestore };
}
