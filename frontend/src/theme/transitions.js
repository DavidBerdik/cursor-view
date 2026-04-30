// Single canonical fade transition for palette-driven UI surfaces. Lives
// in its own file (rather than next to the colors or inline in
// `buildTheme.js`) so both the MUI `components.styleOverrides` map in
// `buildTheme.js` and the handful of raw `<Box>` elements that carry
// palette-derived `backgroundColor` / `borderColor` / `color` in their
// inline `sx` can import the same string. Hardcoding the literal in two
// places would let the curve drift the next time someone tweaks one
// site and forgets the others, which is exactly the inconsistency this
// token exists to prevent.
//
// `PALETTE_TRANSITION_DURATION` and `PALETTE_TRANSITION_CURVE` are split
// out alongside the assembled `PALETTE_TRANSITION` so consumers that
// need the same timing in a CSS keyframe `animation: ...` shorthand
// (where the `transition` shorthand is the wrong tool because the
// property change happens on first paint, not later) can compose the
// duration and curve explicitly without re-typing the literal. The
// canonical use site is `MermaidDiagramSurface`, which cross-fades two
// SVG layers on theme toggle.
//
// The composed `PALETTE_TRANSITION` is a property-list shorthand
// (`'background-color 0.2s ..., color 0.2s ..., ...'`), not the
// `'all 0.2s ...'` form that originally landed with this token. Two
// reasons for the narrowing:
//
//   1. Performance. Long chat-detail pages instantiate the transition
//      on hundreds of MUI elements (every `MessageBubble`'s `Paper`,
//      `Avatar`, `Typography`; every code-block icon; every `Chip`),
//      and the browser keeps a transition entry per element per
//      property. `'all'` keeps an entry for every CSS property the
//      element exposes; the property list keeps entries only for
//      properties we actually animate. The compositor cost during the
//      200ms fade scales with that entry count, and on
//      mermaid-heavy chats the difference is measurable.
//   2. Defensive scope. `'all'` would also animate a future `width` or
//      `height` change introduced by an unrelated refactor, which is
//      almost never what the author intended on a theme-fade element.
//      Listing properties keeps the transition's blast radius
//      explicit and grep-able.
//
// `PALETTE_TRANSITION_PROPERTIES` enumerates every property a
// palette-driven element in this codebase actually animates today:
//
//   - `background-color` — the dominant theme-fade target on every
//     `Paper` / `Card` / `AppBar` / `body` / inner `<Box>`.
//   - `color` — `Typography`, `IconButton`, every text-bearing element
//     whose default color flips between dark/light.
//   - `border-color` — `Divider`, the `'divider'` token consumers
//     (`MessageImageGallery` thumbnails), `MessageBubble`'s
//     `borderColor: accent`.
//   - `fill` and `stroke` — `MuiSvgIcon` fills/strokes for the
//     standalone `colors.highlightColor`-tinted icons in
//     `ChatMetaPanel`, `EmptyState`, etc.
//   - `box-shadow` — `MuiCard` and `MuiPaper` hover shadows
//     (`ChatCard`, `ProjectGroup`'s outer `Paper`).
//
// `transform` is intentionally NOT in the list. The only site that
// animates a `transform` for a theme-fade-adjacent reason is
// `ChatCard`'s `translateY(-8px)` hover-lift, which is a per-card
// hover affordance, not a palette change. Including it here would
// instantiate a `transform` transition entry on every `MessageBubble`
// `Paper`, every `Avatar`, every `Typography`, every `IconButton`,
// every `Chip` — hundreds of elements that never animate `transform`
// at all — purely to support one card's hover. The hover-lift now
// lives as a local `transition` on `ChatCard`'s `Card` `sx` instead,
// composed from `PALETTE_TRANSITION` plus an extra `transform` entry.
//
// The list is the canonical point of extension: when a future palette-
// driven property gets animated (e.g. `outline-color` on a focus
// state), add it here rather than inlining a one-off transition on
// the consuming element. Keep the list short and motivated. Per-
// element non-palette transitions (like `ChatCard`'s `transform`)
// belong in the consuming component's `sx`, composed with
// `PALETTE_TRANSITION` so the centralized properties still fade.
//
// The duration is 200ms, which sits at the lower end of Material
// Design 3's emphasized-curve range (200-250ms). The original token
// landed at 300ms to match `ChatCard`'s historical inline transition
// byte-for-byte, but that value was tuned for a single hover-lift in
// isolation; once the same transition runs on hundreds of elements
// during a theme toggle, 300ms is long enough to read as a flash
// rather than a polish, and the compositor cost during the fade
// scales linearly with the duration. 200ms keeps the fade
// perceptible without dragging.
export const PALETTE_TRANSITION_DURATION = '0.2s';
export const PALETTE_TRANSITION_CURVE = 'cubic-bezier(.17,.67,.83,.67)';

export const PALETTE_TRANSITION_PROPERTIES = Object.freeze([
  'background-color',
  'color',
  'border-color',
  'fill',
  'stroke',
  'box-shadow',
]);

export const PALETTE_TRANSITION = PALETTE_TRANSITION_PROPERTIES
  .map((property) => `${property} ${PALETTE_TRANSITION_DURATION} ${PALETTE_TRANSITION_CURVE}`)
  .join(', ');
