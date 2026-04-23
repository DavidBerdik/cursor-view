import mermaid from 'mermaid';

// Pre-renders all mermaid code blocks found in a pre-rendered HTML string.
//
// Returns a Map of source-text → { svg: string|null, error: string|null }.
// Both valid and invalid diagrams get entries so MermaidBlock can start in
// the correct state (rendered diagram or error+source) on first paint,
// without needing to call mermaid.render itself.
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
        });
        return;
      }

      // Only call mermaid.render for diagrams that passed the parse check.
      counter += 1;
      const renderId = `mermaid-prerender-${Date.now()}-${counter}`;
      try {
        const { svg } = await mermaid.render(renderId, source);
        resultMap.set(source, { svg, error: null });
      } catch (renderErr) {
        resultMap.set(source, {
          svg: null,
          error: renderErr?.message ?? String(renderErr),
        });
      }
    }),
  );

  return resultMap;
}
