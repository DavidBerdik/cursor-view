import { useEffect, useState } from 'react';

// Returns ``value`` delayed by ``delayMs`` so a burst of upstream
// changes (e.g. one per keystroke) coalesces into a single downstream
// update. Pair this with hooks that fire network requests off their
// inputs -- ``useDeferredValue`` only re-prioritizes the render that
// reads the value, so a ``useEffect([query])`` still fires per
// keystroke and pile up server-side; debouncing the dependency itself
// is what reduces the request count.
export function useDebouncedValue(value, delayMs = 200) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const handle = setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);

  return debounced;
}
