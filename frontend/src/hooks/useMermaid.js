import { useContext, useEffect } from 'react';
import mermaid from 'mermaid';
import { ThemeModeContext } from '../contexts/ThemeModeContext';

// Bootstraps the mermaid singleton whenever the dark/light theme changes.
//
// Call this hook once at a component that is an ancestor of all MermaidBlock
// instances (MessageMarkdown is the canonical location). This ensures:
//
//   1. ``startOnLoad: false`` is set before any block tries to render, which
//      prevents mermaid from auto-scanning the DOM and double-rendering.
//   2. The singleton's theme is always current so a darkMode toggle is
//      reflected in the next MermaidBlock render cycle.
//
// useMermaidRender (the per-block render hook consumed by MermaidBlock) also
// calls mermaid.initialize immediately before each mermaid.render because
// React runs child effects before parent effects and queue tasks may run
// after arbitrary delay; that per-block init is the definitive theme source
// at render time. This hook is the global bootstrap and the authoritative
// owner of startOnLoad + securityLevel.
//
// Returns nothing — this is a side-effect-only hook.
export function useMermaid() {
  const { darkMode } = useContext(ThemeModeContext);

  useEffect(() => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: darkMode ? 'dark' : 'default',
    });
  }, [darkMode]);
}
