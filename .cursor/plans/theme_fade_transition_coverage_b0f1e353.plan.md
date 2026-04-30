---
name: Theme Fade Transition Coverage
overview: Centralize the canonical dark/light theme fade transition (`'all 0.3s cubic-bezier(.17,.67,.83,.67)'`) in the MUI theme so every palette-driven `MuiCard`, `MuiPaper`, `MuiAppBar`, `MuiButton`, `MuiChip`, `MuiIconButton`, `MuiAvatar`, `MuiSvgIcon`, `MuiTypography`, `MuiDivider`, `MuiOutlinedInput` and the `body` itself fades instead of flashing on toggle, and add inline `sx` only on the raw `<Box>` elements (`ProjectGroup` header, `ChatCard` highlight panel, `MessageBubble` markdown wrapper, `MermaidBlock`, `MessageMarkdown` code blocks, `MessageImageGallery` thumbnails) that carry palette-derived colors. Skip dialogs/modals/context menu per scope decision.
todos:
  - id: add_transitions_module
    content: Create `frontend/src/theme/transitions.js` exporting `PALETTE_TRANSITION = 'all 0.3s cubic-bezier(.17,.67,.83,.67)'`.
    status: completed
  - id: fade_app_background
    content: "In `frontend/src/theme/buildTheme.js`, add a `MuiCssBaseline.styleOverrides.body` override that sets `transition: PALETTE_TRANSITION` so the app's full-page background (driven by `theme.palette.background.default` via MUI's `CssBaseline` reset) fades on dark/light toggle instead of flashing instantly. This is the single largest visible surface in the UI."
    status: completed
  - id: extend_build_theme
    content: "In `frontend/src/theme/buildTheme.js`: import `PALETTE_TRANSITION`, add it to existing `MuiCard` / `MuiPaper` / `MuiAppBar` / `MuiButton` / `MuiChip` overrides, and add new `MuiIconButton` / `MuiAvatar` / `MuiSvgIcon` / `MuiTypography` / `MuiDivider` / `MuiOutlinedInput` overrides (the body fade is its own todo above)."
    status: completed
  - id: update_index_css_scrollbar
    content: Update the three scrollbar `transition` rules in `frontend/src/index.css` from `200ms ease` to `0.3s cubic-bezier(.17,.67,.83,.67)` so the scrollbar fade matches the canonical curve.
    status: completed
  - id: fix_project_group_box
    content: "In `frontend/src/components/chat-list/ProjectGroup.js`, drop the now-redundant `transition: 'all 0.3s ease-in-out'` on the outer `Paper` and add `transition: PALETTE_TRANSITION` to the inner header `<Box>` (the visible chat-category color block)."
    status: completed
  - id: clean_chat_card
    content: "In `frontend/src/components/chat-list/ChatCard.js`, remove the inline `transition` on the `Card` (now centralized) and add `transition: PALETTE_TRANSITION` to the inner highlight-colored `<Box>` panel that holds the preview text."
    status: completed
  - id: fade_message_bubble_table
    content: "In `frontend/src/components/chat-detail/MessageBubble.js`, add `transition: PALETTE_TRANSITION` to the inner content `<Box>` and to its `'& th'` / `'& tr:nth-of-type(even)'` selectors so the table-row tints fade with the rest of the bubble."
    status: completed
  - id: fade_mermaid_block_chrome
    content: "In `frontend/src/components/MermaidBlock.js`, add `transition: PALETTE_TRANSITION` to the outer wrapper `<Box>`, the diagram-body `<Box component=\"button\">`, and the source-mode `<Box component=\"pre\">`. Do not touch the mermaid render path or `useSvgPanZoom`."
    status: completed
  - id: fade_message_markdown_code
    content: "In `frontend/src/components/MessageMarkdown.js`, add `transition: PALETTE_TRANSITION` inside the `'& pre'` rule of the outer `<Box>` and the `'& :not(pre) > code'` rule of the inner `<Box>`."
    status: completed
  - id: fade_image_gallery_thumbs
    content: "In `frontend/src/components/chat-detail/MessageImageGallery.js`, add `transition: PALETTE_TRANSITION` to the thumbnail `<Box component=\"button\">` so its `borderColor: 'divider'` fades."
    status: completed
  - id: add_theme_transitions_rule
    content: "Add `.cursor/rules/theme-transitions.mdc` capturing: the canonical string lives in `theme/transitions.js`; palette-driven MUI components get it via `buildTheme.js` `styleOverrides`; raw `<Box>` elements get it via inline `sx` importing the same constant; dialogs/modals/context menu inherit only via the global MUI override and are not separately decorated."
    status: completed
  - id: cross_reference_react_components
    content: Update `.cursor/rules/react-components.mdc` "Theme ownership" section with one sentence cross-referencing the new `theme-transitions.mdc`.
    status: completed
  - id: update_readme_features
    content: Add a Features bullet to `README.md` mentioning the smooth dark/light fade across the UI.
    status: completed
  - id: update_contributing_theme
    content: Update the `theme/` bullet in `.github/CONTRIBUTING.md`'s Frontend section to list `transitions.js` alongside `colors.js`, `buildTheme.js`, and `themeCookie.js`.
    status: completed
  - id: review_rules_followed
    content: Review every modified file against `react-components.mdc` (theme ownership / size cap), `mermaid-rendering.mdc` (no new pipeline; render path untouched), `frontend-hooks.mdc` (no hook changes), and `comments-style.mdc` (intent-only comments). Confirm no `# TODO(bug):` markers were introduced.
    status: completed
  - id: final_bug_check
    content: "Final pass: ripgrep `transition:` over `frontend/src/` to confirm no stale literal duplicates the constant; verify pan/zoom inside `MermaidLightboxModal` still feels responsive (the global `MuiPaper` `'all'` transition could in theory cascade — narrow it to color/border/box-shadow if it lags); verify `ProjectGroup`'s old `ease-in-out` is gone and `ChatCard`'s old inline transition is gone (or unchanged-and-redundant). Note any new bug suspicions with the `# TODO(bug):` marker per `known-bugs.mdc` rather than silently editing."
    status: completed
isProject: false
---

## Goal

Today the dark/light toggle visually splits into two camps:

- Faded: `ChatCard` (`'all 0.3s cubic-bezier(.17,.67,.83,.67)'` on the `Card` itself) and the html/scrollbar in [`frontend/src/index.css`](frontend/src/index.css) (`200ms ease`).
- Flashing: the `Header` `AppBar`, the `ChatList` typography/buttons, the `ProjectGroup` header `<Box>` (the outer `Paper` does have `'all 0.3s ease-in-out'`, but it's clipped by `overflow: 'hidden'` and the inner palette-colored `<Box>` is what the user actually sees), the `EmptyState` panel, the `SearchBar` `TextField`, the `ChatMetaPanel` `Paper` + `Chip` + icons, every `MessageBubble` (`Avatar`, `Paper`, table cells), every `MermaidBlock` (border / diagram body / source `<pre>`), the `MermaidToolbar` icons, and the inline-code spans inside `MessageMarkdown`.

We will unify all of those (except dialogs/modals and the `AppContextMenu`) on one canonical fade string, defined exactly once and applied through MUI's `components` override map plus targeted inline `sx` on the handful of raw `<Box>` elements that don't have a `styleOverrides` slot.

## Canonical transition

```js
export const PALETTE_TRANSITION = 'all 0.3s cubic-bezier(.17,.67,.83,.67)';
```

This matches `ChatCard`'s existing inline transition byte-for-byte. We deliberately keep `'all'` (not the narrower `background-color, color, border-color`) for two reasons:

- It matches the existing canonical site (`ChatCard`, line 43).
- It preserves the behavior where hover-driven `transform: translateY(-8px)` and `boxShadow` on `ChatCard` cross-fade. Splitting to a property list would diverge from "identical style".

A side effect is that several hover bg/border changes (e.g. `Refresh` button, `ProjectGroup` IconButton expand) become 300ms cubic-bezier instead of instant; that's an acceptable small UX improvement and stays internally consistent.

## File map

### New file: [frontend/src/theme/transitions.js](frontend/src/theme/transitions.js)

Single-purpose token module so components that need the same string in inline `sx` can import it instead of hardcoding the literal. One concept, one import path:

```js
export const PALETTE_TRANSITION = 'all 0.3s cubic-bezier(.17,.67,.83,.67)';
```

### [frontend/src/theme/buildTheme.js](frontend/src/theme/buildTheme.js)

Import `PALETTE_TRANSITION` and add it to:

- **`MuiCssBaseline.styleOverrides.body`** — this is the app-wide page background fade. MUI's `CssBaseline` reset is what writes `body { background-color: theme.palette.background.default; color: theme.palette.text.primary }` on every render, so today the full-page background is the single largest surface that flashes on theme toggle. Adding `transition: PALETTE_TRANSITION` here is the highest-leverage change in the whole plan: one rule, one override slot, the entire viewport fades. This is its own todo (`fade_app_background`) precisely because it's the most prominent flash and deserves a dedicated step.
- existing `MuiCard.root`, `MuiPaper.root`, `MuiAppBar.root`, `MuiButton.root` (covers contained + outlined hover bg), `MuiChip.root` overrides;
- new `MuiIconButton.styleOverrides.root`, `MuiAvatar.styleOverrides.root`, `MuiSvgIcon.styleOverrides.root` (covers all the standalone `colors.highlightColor`-tinted icons in `ChatMetaPanel` etc.), `MuiTypography.styleOverrides.root` (covers `text.primary` / `text.secondary` flips), `MuiDivider.styleOverrides.root` (covers `ChatCard`'s divider), `MuiOutlinedInput.styleOverrides.root` (covers the `SearchBar` border/text color flip — the existing `MuiTextField` override only resets bg, not the border).

Note: the override is global, so MUI components inside the dialogs/modals will also pick up the transition as a benign side effect. Per the scope decision, we just don't *also* add inline `sx` on those modal files.

### [frontend/src/index.css](frontend/src/index.css)

Update the three scrollbar `transition` rules from `200ms ease` to `0.3s cubic-bezier(.17,.67,.83,.67)` so the scrollbar fade matches the canonical transition.

### [frontend/src/components/chat-list/ProjectGroup.js](frontend/src/components/chat-list/ProjectGroup.js)

- Drop the inline `transition: 'all 0.3s ease-in-out'` on the outer `Paper` (lines 53-58). Now redundant with `MuiPaper`'s override and the `ease-in-out` curve mismatched the canonical `cubic-bezier`.
- Add `transition: PALETTE_TRANSITION` to the inner header `<Box>`'s `sx` (lines 60-72). This is the box whose `background: colors.background.paper` is what users perceive as "the chat-categories box" (the user's exact motivating example).

### [frontend/src/components/chat-list/ChatCard.js](frontend/src/components/chat-list/ChatCard.js)

- Remove the inline `transition` on the `Card` (line 43); now provided by the centralized `MuiCard` override.
- Add `transition: PALETTE_TRANSITION` to the inline `sx` of the highlight-colored inner `<Box>` (lines 105-114) — that's a raw `<Box>` with `backgroundColor: alpha(colors.highlightColor, 0.1)` and palette-derived `borderColor`, so it doesn't pick up `MuiPaper`/`MuiCard` automatically.

### [frontend/src/components/chat-detail/MessageBubble.js](frontend/src/components/chat-detail/MessageBubble.js)

- The outer `Avatar` and the `Paper` are covered by the new `MuiAvatar` / existing-and-extended `MuiPaper` overrides.
- Add `transition: PALETTE_TRANSITION` to the inline `sx` of the inner `<Box>` (lines 57-87) that owns the table-cell `'& th'` / `'& tr:nth-of-type(even)'` `backgroundColor: alpha(colors.highlightColor, ...)` rules. This is a raw `<Box>` and its descendant `<th>` / `<tr>` are HTML-not-MUI, so the `MuiPaper` override doesn't reach them. The transition on the parent `<Box>` cascades to children only if we put it under each selector — extend the same pattern by adding `transition: PALETTE_TRANSITION` inside `'& th'` and `'& tr:nth-of-type(even)'` rules so the table-row tints fade too.

### [frontend/src/components/MermaidBlock.js](frontend/src/components/MermaidBlock.js)

Three raw `<Box>` surfaces with palette-derived colors:

- Outer wrapper (lines 154-164): add `transition: PALETTE_TRANSITION` so the `borderColor: alpha(colors.highlightColor, 0.2)` fades.
- Diagram body `<Box component="button">` (lines 201-223): add `transition: PALETTE_TRANSITION` so the `backgroundColor: alpha(colors.highlightColor, ...)` (the term that flips on `darkMode`) fades.
- Source-mode `<Box component="pre">` (lines 225-238): add `transition: PALETTE_TRANSITION` so its `darkMode`-conditional bg fades.

Important constraint from [`mermaid-rendering.mdc`](.cursor/rules/mermaid-rendering.mdc) "Two rendering pipelines, one source format" + "Modal pan/zoom/reset is presentation-only": we are **only** adding CSS transitions. We are not touching `mermaid.parse` / `mermaid.render` / `mermaid.initialize`, the `latestRef`/`skipFirstRenderRef` cancellation, the per-block render effect's deps `[source, darkMode]`, or anything in `useSvgPanZoom`. The transition is a presentational concern; the SVG itself still re-renders on theme flip exactly as before, but the surrounding chrome no longer flashes.

Also: do **not** apply `transition: 'all'` to the diagram-body `<Box component="button">` while pan/zoom is active — but pan/zoom only happens inside the modal (a different element managed by `useSvgPanZoom`), not on the inline diagram body, so this is safe. The `transform` property the hook writes lives on the modal's transform layer (`MermaidLightboxModal.js`), and we are deliberately not modifying any modal file per the scope decision.

### [frontend/src/components/MessageMarkdown.js](frontend/src/components/MessageMarkdown.js)

Add `transition: PALETTE_TRANSITION` to the two `sx` blocks that set `backgroundColor` and `color` from the palette: the outer `<Box>`'s `'& pre'` rule (lines 76-84) and the inner `<Box>`'s `'& :not(pre) > code'` rule (lines 100-109). These are raw selectors, not MUI components, so they won't pick up the global override.

We deliberately do **not** target the starry-night syntax-highlight `<span>` colors — the user's scope choice was "skip syntax-highlight spans". The `<pre>` background fade alone already softens the perceived flash for code blocks.

### [frontend/src/components/chat-detail/MessageImageGallery.js](frontend/src/components/chat-detail/MessageImageGallery.js)

Add `transition: PALETTE_TRANSITION` to the thumbnail `<Box component="button">`'s `sx` (lines 78-88) so the `borderColor: 'divider'` fades. The image inside is a raster `<img>` — no theme color, no transition needed.

### Pages-side (no edits required, just verification)

- `Header.js`: AppBar gets the override; the GitHub `Button` and theme-toggle `IconButton` get the override; nothing else carries palette colors here.
- `ChatList.js`, `ChatDetail.js`: only Buttons / Typography / Container — all picked up by overrides.
- `ChatMetaPanel.js`: Paper / Chip / Typography / SvgIcon — all picked up by overrides.
- `EmptyState.js`: Paper / Typography / Button / SvgIcon — all picked up.
- `SearchBar.js`: TextField — already overridden, plus the new `MuiOutlinedInput` override covers border/text color.
- Mermaid `Toolbar` / `LightboxModal` / `LightboxFallback` / `ZoomControls`: covered by the new `MuiIconButton` / `MuiSvgIcon` / existing `MuiPaper` overrides where relevant; the modal itself is in the "skip" set per scope but its IconButtons get the transition as a benign side effect. The `MermaidLightboxFallback` `<pre>` is a raw `<Box component="pre">` inside a modal body and is in scope-skip — leave alone.

### Files explicitly not touched (per scope decision "visible_only_no_modals")

- [frontend/src/components/export/ExportFormatDialog.js](frontend/src/components/export/ExportFormatDialog.js)
- [frontend/src/components/export/ExportWarningDialog.js](frontend/src/components/export/ExportWarningDialog.js)
- [frontend/src/components/chat-detail/ImageLightboxModal.js](frontend/src/components/chat-detail/ImageLightboxModal.js)
- [frontend/src/components/MermaidLightboxModal.js](frontend/src/components/MermaidLightboxModal.js)
- [frontend/src/components/MermaidLightboxFallback.js](frontend/src/components/MermaidLightboxFallback.js)
- [frontend/src/components/MermaidZoomControls.js](frontend/src/components/MermaidZoomControls.js)
- [frontend/src/components/AppContextMenu.js](frontend/src/components/AppContextMenu.js)

These still inherit the global MUI overrides (Paper, Button, IconButton, Avatar, Typography) so their MUI components fade. We just don't add inline `sx` to their raw `<Box>` elements.

## Rule compliance

The applicable rules under `.cursor/rules/` and how this plan satisfies each:

- [`react-components.mdc`](.cursor/rules/react-components.mdc) "Theme ownership": "MUI theme tokens (`palette`, `sx`) own the visual language" — centralizing the transition in `buildTheme.js` is the textbook expression of this rule. The inline-`sx` exceptions are justified because raw `<Box>` elements don't have a `styleOverrides` slot.
- [`react-components.mdc`](.cursor/rules/react-components.mdc) "Component size": every change is a one-line `sx` addition. None of the touched files crosses ~250 lines after the edit (largest is `MermaidBlock.js` at ~250; we add 3 short `transition:` keys, taking it to ~253. We will check this with a line count after edits and decompose only if it actually crosses the threshold materially. If it does, the natural decomposition is to extract the source-mode `<pre>` box into a sibling component — but ~3 lines is borderline and probably fine as a small overage matching the rule's "soft" character).
- [`react-components.mdc`](.cursor/rules/react-components.mdc) "Third-party imperative-DOM libraries": we do not call `mermaid.initialize` / `mermaid.parse` / `mermaid.render` from any new place. We only add CSS to the `<Box>` chrome around the SVG.
- [`mermaid-rendering.mdc`](.cursor/rules/mermaid-rendering.mdc) "Two rendering pipelines": no new pipeline. "Parse before render": untouched. "Theme-tagged prerender entries": untouched. "Modal pan/zoom/reset is presentation-only": we deliberately skip the modal files entirely.
- [`frontend-hooks.mdc`](.cursor/rules/frontend-hooks.mdc): no hook changes. The `[source, darkMode]` deps on `MermaidBlock`'s render effect stay; `useMermaid` stays; `useSvgPanZoom` stays.
- [`comments-style.mdc`](.cursor/rules/comments-style.mdc): every comment we add must explain *why* (e.g. "Centralizes the dark/light fade so palette-driven elements stop flashing on toggle; canonical curve matches `ChatCard`'s historical transition"), never *what* (don't write "300ms cubic-bezier transition for fade").
- [`known-bugs.mdc`](.cursor/rules/known-bugs.mdc): no `TODO(bug):` markers introduced — this is a UX change, not a known-broken behavior.
- [`project-layout.mdc`](.cursor/rules/project-layout.mdc): the new `frontend/src/theme/transitions.js` lives under the canonical `theme/` subpackage. No new top-level files, no Python touched, layout unchanged. Documentation-sync clause requires updating `.github/CONTRIBUTING.md` if layout changed: we are adding one file inside an existing subpackage, which is a small layout note worth recording in CONTRIBUTING's `theme/` bullet.

## New rule

Add [`.cursor/rules/theme-transitions.mdc`](.cursor/rules/theme-transitions.mdc) capturing:

- The canonical transition string lives in `frontend/src/theme/transitions.js` as `PALETTE_TRANSITION`. Do not hardcode the literal elsewhere.
- Palette-driven MUI components get the transition through `buildTheme.js` `styleOverrides`. New MUI components added later (e.g. `MuiAccordion`, `MuiTabs`) must be added to the override map in the same change that introduces them.
- Raw `<Box>` / `<pre>` / `<button>` elements with `backgroundColor` / `color` / `borderColor` derived from `ColorContext` get the transition through inline `sx` importing `PALETTE_TRANSITION`. Do not duplicate the literal string.
- Dialogs / modals / context menus inherit the transition through the global MUI override but are not separately decorated; this is the scope decision documented here so a future contributor doesn't "complete the coverage" for those surfaces without intent.
- Cross-references: [`react-components.mdc`](.cursor/rules/react-components.mdc) "Theme ownership", since the transition is the time-domain extension of the same rule.

## Existing rule update

Update [`.cursor/rules/react-components.mdc`](.cursor/rules/react-components.mdc) "Theme ownership" section to add a single sentence cross-referencing the new `theme-transitions.mdc` so the two rules stay linked. Keep the change small — one sentence, no other restructuring.

## Documentation sync

- [`README.md`](README.md): add one bullet to the Features list (around line 102) noting the smooth dark/light fade across the UI. The README's "user-facing setup, binary usage, or features" clause from `project-layout.mdc` is the trigger here — this is a feature-visible polish.
- [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md): under the `theme/` bullet (currently `colors.js`, `buildTheme.js`, `themeCookie.js`), add `transitions.js` and one sentence on its purpose so the layout map reflects reality.

## Verification

After the edits land, do a final pass that:

1. Re-reads each modified file via `Read` and verifies the only added comments are intent comments per `comments-style.mdc` (no "// Set the transition for fade" mechanics).
2. Confirms `MermaidBlock.js` and other files stayed under the 250-line soft cap, or accepts a small overage with no further obligation, per `react-components.mdc`.
3. Checks that no inline `transition:` literal duplicates the constant — every inline transition imports `PALETTE_TRANSITION`.
4. Checks for visible bugs introduced by the change set:
   - The `'all'` curve animates `transform`, so any `transform: translateY(-8px)` hover (`ChatCard`) and any `transform: translate/scale` (the modal pan/zoom transform layer) could in theory pick up the 300ms fade. The modal transform layer is in `MermaidLightboxModal.js` which we did not touch and which already has its own `willChange: transform` — verify that `MuiPaper` override transition does not cascade in a way that causes the pan/zoom drag to feel laggy. If it does, narrow the `MuiPaper.root` override to scope the transition (`'background-color, color, border-color, box-shadow'`) instead of `'all'`. This is the most plausible regression vector.
   - The `MuiTypography.styleOverrides.root = { transition: PALETTE_TRANSITION }` with `'all'` could in principle animate `text-shadow` / `letter-spacing` if a future page sets those in `sx`. Today no page does. Note this in the new rule so a future contributor knows the override scope.
   - `MuiOutlinedInput.styleOverrides.root` plus the existing `MuiTextField` override that resets `'& .MuiOutlinedInput-root': { backgroundColor: 'transparent' }` shouldn't conflict — the `MuiTextField` override is targeting a child selector, not setting `transition` itself; verify no precedence collision.
   - Verify the `ProjectGroup` outer `Paper` no longer has a stale local `transition: 'all 0.3s ease-in-out'` that would shadow the centralized override.
   - Verify the `ChatCard` `Card` no longer has a stale local transition that would shadow the override (or, equivalently, that the local transition still uses the same string and therefore is harmless if kept — but DRY says drop it).
   - Verify no other component file has a hardcoded transition literal that should now point at the constant (`rg "transition:"` over `frontend/src/`).