// DOM-inspection helpers shared by the app context menu and any future
// feature that needs to classify or locate editable targets. Lives in
// ``utils/`` so components / hooks can pull them in without dragging the
// <Menu> JSX shell along.

// True when ``el`` is a target the browser lets the user type into:
// writable INPUTs of a textual type, writable TEXTAREAs, and elements
// with ``contenteditable``. Disabled or read-only inputs are explicitly
// excluded so we do not offer Paste/Cut on UI widgets the user cannot
// actually modify.
export function isEditableElement(el) {
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
}

// Walk up from ``el`` to the nearest block / flex / grid ancestor so
// Select-All selects the visible content region rather than whichever
// inline span happened to be under the cursor. Falls back to the passed
// element (or ``document.body``) if no block ancestor is found before we
// exit the DOM tree.
export function findSelectionContainer(el) {
  let node = el;
  while (node && node.nodeType === 1) {
    const style = window.getComputedStyle(node);
    if (style.display === 'block' || style.display === 'flex' || style.display === 'grid') {
      return node;
    }
    node = node.parentElement;
  }
  return el || document.body;
}
