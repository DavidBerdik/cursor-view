import mermaid from 'mermaid';
import { setCachedMermaidSvg } from './mermaidRenderCache';

// Pre-renders all mermaid code blocks found in a pre-rendered HTML string.
//
// Returns a Map of source-text → { svg, error, darkMode }, where each
// entry has the shape:
//
//   - svg: string | null      — rendered SVG markup when parse + render
//                                both succeeded; null otherwise.
//   - error: string | null    — parser/renderer error message when either
//                                step failed; null otherwise.
//   - darkMode: boolean       — the darkMode value this entry was
//                                rendered against, mirrored from the
//                                argument so consumers can detect a
//                                theme shift between prerender and mount.
//
// MermaidBlock uses the `darkMode` field to decide whether the cached
// SVG is still authoritative for the current theme — if the user toggled
// dark/light mode during ChatDetail's loading window, the entry's
// darkMode no longer matches React's current darkMode and MermaidBlock's
// first-mount render must run so the diagram is re-themed; see
// mermaid-rendering.mdc.
//
// Both valid and invalid diagrams get entries so MermaidBlock can start
// in the correct state (rendered diagram or error+source) on first
// paint, without needing to call mermaid.render itself.
//
// Critically, mermaid.render is never called for a diagram that fails
// mermaid.parse. mermaid.render injects a bomb-graphic element into
// document.body as a side effect of a failed render; mermaid.parse is a
// DOM-free syntax check that throws without any visible side effects.
//
// This is called in ChatDetail's fetch effect *before* setLoading(false)
// so every diagram result is ready when the spinner disappears.
//
// Uses DOMParser to locate <pre><code class="language-mermaid"> nodes,
// mirroring what MessageMarkdown's replaceNode interceptor does.
//
// As a side effect, every successful render is written into the
// session-scoped `mermaidRenderCache` (`setCachedMermaidSvg`) so the
// cold-page prerender doubles as the cache-warmer for `MermaidBlock`'s
// theme-toggle path. The cache is keyed by `(source, darkMode)`, so a
// user who first lands on a chat in dark mode and then toggles to
// light mode pays the parse + render cost only for the new theme; a
// subsequent toggle back to dark hits the prerender-warmed entry. The
// write only happens on the success path here -- errors deliberately
// stay out of the cache, mirroring the contract documented in
// `mermaidRenderCache.js`.
export async function prerenderMermaidDiagrams(html, darkMode) {
  if (!html || typeof html !== 'string') {
    return new Map();
  }

  const doc = new DOMParser().parseFromString(html, 'text/html');
  const codeNodes = doc.querySelectorAll('pre > code.language-mermaid');

  if (codeNodes.length === 0) {
    return new Map();
  }

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: darkMode ? 'dark' : 'default',
  });

  const resultMap = new Map();
  let counter = 0;

  await Promise.all(
    Array.from(codeNodes).map(async (node) => {
      const source = node.textContent ?? '';
      if (!source || resultMap.has(source)) {
        return;
      }

      // Validate syntax first. mermaid.parse is DOM-free: it throws on
      // invalid syntax without touching document.body, so no bomb graphic
      // is ever injected for diagrams that will not render.
      try {
        await mermaid.parse(source);
      } catch (parseErr) {
        resultMap.set(source, {
          svg: null,
          error: parseErr?.message ?? String(parseErr),
          darkMode,
        });
        return;
      }

      // Only call mermaid.render for diagrams that passed the parse check.
      counter += 1;
      const renderId = `mermaid-prerender-${Date.now()}-${counter}`;
      try {
        const { svg } = await mermaid.render(renderId, source);
        setCachedMermaidSvg(source, darkMode, svg);
        resultMap.set(source, { svg, error: null, darkMode });
      } catch (renderErr) {
        resultMap.set(source, {
          svg: null,
          error: renderErr?.message ?? String(renderErr),
          darkMode,
        });
      }
    }),
  );

  return resultMap;
}
