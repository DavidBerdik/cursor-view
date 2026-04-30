// Session-scoped cache of rendered mermaid SVGs keyed by
// `(source, darkMode)`. Eliminates the cost of re-running
// `mermaid.parse` + `mermaid.render` on repeat dark/light toggles: the
// second toggle of any diagram already rendered in the current session
// is effectively free -- a `Map.get` plus a `setSvg(cached)`.
//
// On a long mermaid-heavy chat-detail page this is the highest-leverage
// performance lever for the theme toggle. Without it, every toggle pays
// the full cost of N concurrent `mermaid.render` calls (one per visible
// diagram) racing the JS thread; with it, only the first toggle of
// each `(source, darkMode)` pair pays that cost.
//
// # Why this is safe wrt "Parse before render"
//
// `mermaid.render` injects a "bomb" SVG element into `document.body`
// as a side effect of a failed internal parse, a DOM mutation that
// cannot be undone from a `.catch` handler. The
// [`mermaid-rendering.mdc`](.cursor/rules/mermaid-rendering.mdc)
// "Parse before render" invariant requires every call site to run
// `mermaid.parse` first and skip `mermaid.render` on parse rejection.
//
// A cache hit implies `setCachedMermaidSvg` was called with the same
// `(source, darkMode)` previously, and the only call sites that write
// to the cache (`useMermaidRender`'s render effect, consumed by
// `MermaidBlock`, and `prerenderMermaidDiagrams`) write **only on
// the success path** of `mermaid.render`. A successful `mermaid.render` requires a successful
// preceding `mermaid.parse`. Therefore: cache hit => source previously
// parsed cleanly => safe to reuse the SVG without re-running either
// `mermaid.parse` or `mermaid.render`. The bomb-graphic risk only
// fires when invalid syntax reaches `mermaid.render`; cached entries
// were produced from valid syntax by construction.
//
// Errors deliberately do not enter the cache. Parser messages can
// evolve across mermaid versions, and a transient render failure (e.g.
// a one-off resource hiccup inside mermaid's internal layout pass)
// should be re-evaluated on the next attempt rather than poisoning
// the cache permanently.
//
// # Cache lifecycle and bounds
//
// Module-scope `Map`, lives for the page's lifetime, cleared on a full
// reload. SVG strings are tens of KB each; even a heavy session with
// hundreds of `(source, darkMode)` pairs typically stays under a few
// MB. There is no LRU or TTL today because the workload does not
// warrant the complexity -- if memory pressure ever becomes a concern
// we can swap the `Map` for an LRU without changing the public API.
//
// The key separator is the NUL byte (`\0`), which mermaid source
// (DOMPurify-sanitized markdown text) cannot contain literally, so
// `${darkMode ? 'd' : 'l'}\0${source}` is unambiguous: no two distinct
// `(source, darkMode)` pairs can collide on the same key.

const cache = new Map();

function cacheKey(source, darkMode) {
  return `${darkMode ? 'd' : 'l'}\0${source}`;
}

// Returns the previously-rendered SVG string for the given
// `(source, darkMode)` pair, or `undefined` if no entry exists.
// Callers should check for `undefined` (not falsy) since a successfully-
// cached entry is always a non-empty SVG string.
export function getCachedMermaidSvg(source, darkMode) {
  return cache.get(cacheKey(source, darkMode));
}

// Stores `svg` under the cache key for `(source, darkMode)`. Call this
// only on the success path of `mermaid.render` -- writing on the error
// path would poison the cache (see the "Why this is safe" comment
// above).
export function setCachedMermaidSvg(source, darkMode, svg) {
  cache.set(cacheKey(source, darkMode), svg);
}
