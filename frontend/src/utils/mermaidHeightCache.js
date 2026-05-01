// Persistent cache of rendered MermaidBlock heights keyed by mermaid
// source text. Layout-axis sibling of `mermaidRenderCache` (which
// caches rendered SVGs on the content axis) -- both make the
// chat-detail page deterministic across refreshes, and both live in
// `frontend/src/utils/` so the chat-detail render path can reach them
// without crossing a `hooks/` import boundary.
//
// # Why this exists
//
// `MermaidBlock`'s outer `<Box>` carries `contentVisibility: 'auto'`
// plus a static `containIntrinsicSize: '0 400px'` placeholder so the
// browser can skip layout/paint of off-screen diagrams. The 400px
// figure is a coarse heuristic: real diagrams range from ~200px (a
// short sequence diagram) to >1000px (a deep flowchart). On a refresh
// of a chat the user has scrolled past mermaid blocks in, the saved
// scroll anchor expects the layout above it to match what was on
// screen at save time, but every off-screen block is at the 400px
// placeholder until `content-visibility: auto` materializes it. The
// cumulative actual-vs-placeholder delta drifts the anchor by the
// time the rAF chase loop in `useChatScrollAnchor` settles -- on long
// diagram-heavy chats the cascade exceeds the loop's safety cap and
// the user lands above or below their saved position.
//
// Persisting heights here closes that gap. `useMermaidBlockHeight`
// records each block's rendered height via `ResizeObserver` as the
// user scrolls past it; on the next refresh `MermaidBlock` reads the
// recorded height and uses it as `containIntrinsicSize` so the
// placeholder matches the actual rendered size and the layout above
// the scroll anchor is deterministic before the first `scrollTo`
// runs. See [`theme-transitions.mdc`](.cursor/rules/theme-transitions.mdc)
// "Two CSS containment hints" for the consumer-side restore contract
// this cache satisfies.
//
// # Why source-only keying (no `darkMode`)
//
// Rendered mermaid heights vary by ~few pixels across themes
// (different stroke widths, label-tint metrics) -- well inside the
// 1-px tolerance window of the rAF chase loop in
// `useChatScrollAnchor`. Adding a `darkMode` axis would double the
// storage footprint and force a full re-measure on every theme
// toggle for no perceptible drift improvement. Contrast with
// `mermaidRenderCache`, which keys by `(source, darkMode)` because
// the SVG *content* genuinely differs across themes. Height is a
// layout property; SVG markup is not.
//
// # Why `sessionStorage` and not `localStorage`
//
// Scroll restoration is per-tab anyway -- `useChatScrollAnchor`
// already writes its anchor entries into `sessionStorage`, and
// reusing the same backing avoids a "scroll position was saved but
// heights were not" partial-state inconsistency on incognito /
// privacy-mode users. Session-bounded lifetime also caps unbounded
// growth on users with hundreds of long-running tabs.
//
// # In-memory parsed copy
//
// `sessionStorage` reads themselves are cheap, but `JSON.parse` on
// the full height map per `getCachedMermaidHeight` call would walk
// the whole object once per `MermaidBlock` mount. On a long chat
// with N diagrams that turns one O(N) parse on first paint into
// O(N^2) (each block re-parses, paying for the heights of every
// block). The module-scope `cache` Map is initialized lazily from a
// single `JSON.parse` on first access and stays in lockstep with
// every subsequent write, so per-mount lookups are O(1).
//
// # Defensive storage access
//
// `sessionStorage` access can throw -- privacy mode, disabled
// storage, quota exceeded -- and the chat view must keep working
// regardless. Every read and write is wrapped in `try`/`catch` so a
// throwing backend silently degrades to "no persisted heights": the
// in-memory Map remains empty, every `get` returns `undefined`,
// `MermaidBlock` falls back to the static 400px placeholder, and the
// rAF chase loop in `useChatScrollAnchor` (the safety net) handles
// the residual drift the way it would on a first-ever-load anyway.

const STORAGE_KEY = 'mermaid-block-heights';

// `null` until the first `get` or `set` triggers the lazy hydrate
// from `sessionStorage`. Sentinel rather than an empty `Map` so a
// genuinely-empty cached entry and a not-yet-loaded cache are
// distinguishable -- the lazy hydrate must not fire twice.
let cache = null;

function ensureLoaded() {
  if (cache !== null) {
    return;
  }
  cache = new Map();
  let raw;
  try {
    raw = sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return;
  }
  if (raw === null) {
    return;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return;
  }
  if (!parsed || typeof parsed !== 'object') {
    return;
  }
  for (const [source, height] of Object.entries(parsed)) {
    if (typeof height === 'number' && Number.isFinite(height) && height > 0) {
      cache.set(source, height);
    }
  }
}

function persist() {
  // Serialize from the in-memory `cache` rather than mutating an
  // already-parsed object so a corrupt-on-disk entry from an older
  // build cannot survive past the first write of the session.
  const obj = {};
  for (const [source, height] of cache) {
    obj[source] = height;
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    // Quota exceeded / storage disabled. The in-memory copy still
    // serves the rest of this session; we just can't carry it across
    // the next refresh. Acceptable degradation.
  }
}

// Returns the previously-recorded rendered height for `source`, or
// `undefined` when no entry exists. Callers must check for
// `undefined` (not falsy) -- `0` is filtered out at hydrate time
// because a zero-height block is meaningless as a placeholder.
export function getCachedMermaidHeight(source) {
  ensureLoaded();
  return cache.get(source);
}

// Records the rendered height for `source`. No-op for non-positive
// or non-finite values: `ResizeObserver` can fire with `0` during
// the brief interval between mount and first layout, and recording
// a zero would poison the placeholder for the next refresh.
export function setCachedMermaidHeight(source, height) {
  if (typeof height !== 'number' || !Number.isFinite(height) || height <= 0) {
    return;
  }
  ensureLoaded();
  const existing = cache.get(source);
  if (existing === height) {
    return;
  }
  cache.set(source, height);
  persist();
}
