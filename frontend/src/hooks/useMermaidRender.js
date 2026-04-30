import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { getCachedMermaidSvg, setCachedMermaidSvg } from '../utils/mermaidRenderCache';
import { enqueueMermaidRender } from '../utils/mermaidRenderQueue';

// Module-level counter for `mermaid.render` IDs. Mermaid requires each
// call to use a distinct ID; an incrementing counter is simpler than
// uuid and safe for the single-threaded render path. The prefix
// distinguishes these IDs from `prerenderMermaidDiagrams`'s
// `mermaid-prerender-...` IDs so the two pipelines cannot collide
// even if a pathological clock skew makes their counters overlap.
let _idCounter = 0;

function nextMermaidId() {
  _idCounter += 1;
  return `mermaid-block-${_idCounter}`;
}

// `useMermaidRender` is the per-block owner of the chat-view mermaid
// pipeline. It runs the parse + render sequence, manages the resulting
// `svg` / `renderError` state, and wires the cache + queue per
// `mermaid-rendering.mdc` "Render cache and queue".
//
// Extracted from `MermaidBlock`'s render effect to keep the component
// under the ~250-line cap in `react-components.mdc` (`MermaidBlock`
// also owns the source/diagram mode toggle, the lightbox modal state,
// and the auto-close-on-error effect; folding the render machine on
// top of those pushes the file past the limit). Equivalent in
// behavior to the previous inline effect; the only call-site shift is
// the parent passing a callback for the "switch to source mode on
// render error" side effect, in place of an inline `setMode('source')`
// call inside the effect body. Treat the call site as the canonical
// owner of the imperative mermaid APIs (`mermaid.parse`,
// `mermaid.render`, `mermaid.initialize`) for the chat-view pipeline,
// alongside `prerenderMermaidDiagrams` for the pre-paint pipeline.
//
// `onRenderError` is captured via a ref so the effect deps stay
// `[source, darkMode]`. Using the prop directly would re-run the
// render effect on every parent render that produced a fresh
// callback identity, defeating the latestRef cancellation pattern
// (every effect run bumps `latestRef`, which would invalidate any
// in-flight queued task, even one fired from the same source +
// darkMode). The parent supplies a `useCallback`-stable callback
// today; the ref is belt-and-braces.
//
// Inputs:
//   - source           : the raw mermaid source text.
//   - darkMode         : boolean from `ThemeModeContext`; flips the
//                        `mermaid.initialize` theme.
//   - initialSvg       : SVG returned by `prerenderMermaidDiagrams`,
//                        or undefined / null. See "Theme-tagged
//                        prerender entries" in `mermaid-rendering.mdc`.
//   - initialError     : parse error message from the prerender, if any.
//   - initialDarkMode  : the `darkMode` value the prerender ran
//                        against; used to gate `skipFirstRenderRef`
//                        per "Theme-tagged prerender entries".
//   - onRenderError    : optional callback invoked synchronously
//                        with `setRenderError` so the parent can
//                        flip its mode state in the same React batch
//                        (avoids a brief one-frame inconsistency
//                        where the toolbar shows the wrong mode
//                        toggle button between the error commit and
//                        the parent's auto-switch).
//
// Returns: `{ svg, renderError }`.
//
// Invariants (enforced here, mirrored in `mermaid-rendering.mdc`
// "Wire-up invariants"):
//   1. The cache check runs before the queue. A cache hit calls
//      `setSvg` / `setRenderError` directly and returns — no queued
//      task, no `mermaid.parse`, no `mermaid.render`.
//   2. `latestRef` increments on every effect run, including
//      cache-hit runs. Any in-flight queued task from a prior run
//      sees its captured `id` go stale and bails its post-await
//      state writes.
//   3. `mermaid.initialize` lives inside the queued task body, not
//      at effect time. The task may run with arbitrary delay after
//      the effect (other queued renders ahead of it); a later
//      effect's initialize would otherwise overwrite the singleton
//      between this task's queue position and its render call,
//      producing an SVG themed against the wrong palette.
//   4. Cache writes only on the success path of `mermaid.render`.
//      Errors stay out of the cache.
//   5. `latestRef` stale checks run at every await boundary inside
//      the queued task body. The pre-await stale check at the top
//      of the queued task is a perf optimization; the post-await
//      checks are correctness (do not write stale results into
//      React state).
//   6. `mermaid.parse` runs before `mermaid.render` and a parse
//      rejection skips `mermaid.render` entirely (per "Parse before
//      render" in `mermaid-rendering.mdc`). `mermaid.render` injects
//      a "bomb" SVG into `document.body` as a side effect of an
//      internal parse failure, and that DOM mutation cannot be
//      undone from the `.catch` handler.
export function useMermaidRender({
  source,
  darkMode,
  initialSvg,
  initialError,
  initialDarkMode,
  onRenderError,
}) {
  const [svg, setSvg] = useState(initialSvg ?? null);
  const [renderError, setRenderError] = useState(initialError ?? null);
  // Tracks the latest render attempt so stale async results are discarded.
  const latestRef = useRef(0);
  // Skip the redundant first-mount render when prerenderMermaidDiagrams
  // already produced a usable result for this source. Errors are
  // theme-independent so they always qualify; cached SVGs only qualify
  // when their prerender-time theme still matches the current darkMode,
  // otherwise the user toggled theme during ChatDetail's loading window
  // and the cached SVG is stale (see "Theme-tagged prerender entries"
  // in mermaid-rendering.mdc).
  const skipFirstRenderRef = useRef(
    Boolean(initialError) || (Boolean(initialSvg) && initialDarkMode === darkMode),
  );

  const onRenderErrorRef = useRef(onRenderError);
  useEffect(() => {
    onRenderErrorRef.current = onRenderError;
  }, [onRenderError]);

  useEffect(() => {
    if (!source) {
      return;
    }

    if (skipFirstRenderRef.current) {
      skipFirstRenderRef.current = false;
      return;
    }

    const id = ++latestRef.current;

    // Cache hit short-circuits parse + render entirely. Safe wrt
    // "Parse before render" because cache writes only happen on the
    // render success path; see `mermaidRenderCache.js`.
    const cachedSvg = getCachedMermaidSvg(source, darkMode);
    if (cachedSvg !== undefined) {
      setSvg(cachedSvg);
      setRenderError(null);
      return;
    }

    // Cache miss: route through `mermaidRenderQueue` so N uncached
    // diagrams on theme toggle render one at a time rather than racing
    // the JS thread. `mermaid.initialize` lives inside the queued task
    // because a later effect's initialize would otherwise overwrite
    // the singleton between this task's queue position and its render.
    enqueueMermaidRender(async () => {
      if (id !== latestRef.current) {
        return;
      }

      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: darkMode ? 'dark' : 'default',
      });

      try {
        await mermaid.parse(source);
      } catch (parseErr) {
        if (id !== latestRef.current) {
          return;
        }
        // Surface the parser message and notify the parent so it can
        // flip into source mode in the same React batch. Without the
        // synchronous callback, the toolbar would show the wrong
        // mode-toggle button label for one frame between the error
        // commit and the parent's auto-switch.
        setRenderError(parseErr?.message ?? String(parseErr));
        onRenderErrorRef.current?.();
        return;
      }

      const renderId = nextMermaidId();
      try {
        const { svg: renderedSvg } = await mermaid.render(renderId, source);
        if (id !== latestRef.current) {
          return;
        }
        setCachedMermaidSvg(source, darkMode, renderedSvg);
        setSvg(renderedSvg);
        setRenderError(null);
      } catch (err) {
        if (id !== latestRef.current) {
          return;
        }
        setRenderError(err?.message ?? String(err));
        onRenderErrorRef.current?.();
      }
    });
  }, [source, darkMode]);

  return { svg, renderError };
}
