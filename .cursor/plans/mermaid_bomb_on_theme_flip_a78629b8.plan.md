---
name: mermaid bomb on theme flip
overview: Prevent `MermaidBlock` from re-invoking `mermaid.render` on a theme flip when the diagram source is known-invalid, so the mermaid library no longer injects an orphaned "bomb" error SVG into `document.body` on every dark/light mode toggle.
todos:
  - id: review-mermaidblock
    content: Re-read `frontend/src/components/MermaidBlock.js`, `frontend/src/utils/prerenderMermaidDiagrams.js`, and `frontend/src/hooks/useMermaid.js` end-to-end before editing so the fix lands as a minimal diff against the existing patterns.
    status: completed
  - id: implement-parse-first
    content: In `frontend/src/components/MermaidBlock.js`, refactor the render `useEffect` body so it calls `mermaid.parse(source)` first inside its own try/catch (with a `latestRef` gate), short-circuits to `setRenderError` + `setMode('source')` on a parse failure, and only calls `mermaid.render` when parse succeeded. Preserve the existing `mermaid.initialize`, `latestRef` cancellation, and post-render success/error handling.
    status: completed
  - id: update-comments
    content: Update the comment block at the top of `frontend/src/components/MermaidBlock.js` and the inline comments in the render effect so they accurately describe the new invariant (parse-first prevents `mermaid.render` from injecting a bomb element on every theme flip), and drop the previous comment text that overstated what `skipFirstRenderRef` alone guarantees. Comments must follow `.cursor/rules/comments-style.mdc` (intent-only, no narration of mechanics).
    status: completed
  - id: lint-frontend
    content: Run `ReadLints` on `frontend/src/components/MermaidBlock.js` after the edit and resolve any new lint errors.
    status: completed
  - id: update-mermaid-rule
    content: Update `.cursor/rules/mermaid-rendering.mdc` so the 'Theme sync' (or a new sibling) section documents the parse-first invariant in *both* the runtime path (`MermaidBlock`'s effect) and the prerender path (`prerenderMermaidDiagrams`), citing each file path. The rule must explain why (mermaid.render injects the bomb on a failed parse) so a future contributor cannot regress the invariant by accident.
    status: completed
  - id: update-known-bugs-rule
    content: Add a one-line entry to the 'retired examples' section of `.cursor/rules/known-bugs.mdc` citing the bomb-on-theme-flip fix in `frontend/src/components/MermaidBlock.js`. Do NOT add a `TODO(bug):` marker - the bug is being fixed in this change, not deferred.
    status: completed
  - id: review-other-rules
    content: Walk every file under `.cursor/rules/` and confirm none of the others (`comments-style.mdc`, `frontend-hooks.mdc`, `react-components.mdc`, `project-layout.mdc`, plus the backend-focused ones) need updating. Document the conclusion inline in the chat reply when handing the change back.
    status: completed
  - id: verify-docs
    content: Re-read the mermaid-related lines in `README.md` (currently a single bullet near line 102) and the `MermaidBlock` paragraph in `.github/CONTRIBUTING.md` (under the `components/` section) and confirm both stay accurate. Per `.cursor/rules/project-layout.mdc`, this fix does not change layout or user-facing setup/binary/features, so no edits should be required - record that finding explicitly.
    status: completed
  - id: manual-verify
    content: "Manually verify the fix on `http://127.0.0.1:5000/chat/ec60d4dd-9bac-45af-84e7-bc7e35022378`: toggle dark/light at least four times and confirm no new bomb SVG appears at the bottom of the page; also confirm the in-block 'Mermaid parse error: ...' caption + source fallback still render for the broken diagram, and that a valid diagram in another chat still re-renders with the new theme on each toggle."
    status: completed
  - id: final-bug-review
    content: "Final review pass: re-read `frontend/src/components/MermaidBlock.js`, `frontend/src/hooks/useMermaid.js`, `frontend/src/utils/prerenderMermaidDiagrams.js`, and `frontend/src/components/MessageMarkdown.js` looking for adjacent bugs - missing `latestRef` gates after `await` boundaries, stale singletons, leaked DOM nodes from prior render attempts, theme/source dep mismatches in the effect, race conditions between the prerender Map and prop identity in `MessageMarkdown`'s `replaceNode`, etc. Report any findings (and whether they warrant a `TODO(bug):` marker per `.cursor/rules/known-bugs.mdc`) before declaring the fix complete."
    status: completed
isProject: false
---

# Fix mermaid bomb SVG accumulating on theme toggle

## Symptom

On the chat view, when the user toggles between dark and light mode, mermaid's "bomb" error graphic is appended to the bottom of the page once per toggle. The four screenshots show a strict 1-bomb-per-toggle cadence: after one toggle there is one bomb, after two there are two, etc. The bombs are siblings of the chat container, not children of the `MermaidBlock` that owns the invalid diagram, so they survive across React re-renders.

The chat used to reproduce this contains a `mermaid` fenced block whose source fails `mermaid.parse`. Valid diagrams in the same chat re-render cleanly on each toggle. The bomb appears only for the invalid one.

## Root cause

The bug lives entirely in [`frontend/src/components/MermaidBlock.js`](frontend/src/components/MermaidBlock.js). Two facts collide:

1. `mermaid.render(...)` injects a visible "bomb" `<svg>` error element directly into `document.body` as a side effect when its internal parse fails. The catch handler can swallow the JS rejection but cannot undo the DOM mutation. The companion utility [`frontend/src/utils/prerenderMermaidDiagrams.js`](frontend/src/utils/prerenderMermaidDiagrams.js) already documents this and works around it by calling `mermaid.parse(source)` first and only calling `mermaid.render` for diagrams that pass parse.

2. `MermaidBlock`'s render effect does not. It runs on `[source, darkMode]` and is gated only by `skipFirstRenderRef`, which is consumed exactly once on first mount:

```37:87:frontend/src/components/MermaidBlock.js
export default function MermaidBlock({ source, initialSvg, initialError }) {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  const [mode, setMode] = useState(initialError ? 'source' : 'diagram');
  const [svg, setSvg] = useState(initialSvg ?? null);
  const [renderError, setRenderError] = useState(initialError ?? null);
  const latestRef = useRef(0);
  const skipFirstRenderRef = useRef(Boolean(initialSvg) || Boolean(initialError));

  useEffect(() => {
    if (!source) {
      return;
    }

    if (skipFirstRenderRef.current) {
      skipFirstRenderRef.current = false;
      return;
    }

    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: darkMode ? 'dark' : 'default',
    });

    const id = ++latestRef.current;
    const renderId = nextMermaidId();

    mermaid
      .render(renderId, source)
      .then(({ svg: renderedSvg }) => { ... })
      .catch((err) => { ... });
  }, [source, darkMode]);
```

Step-by-step for an invalid diagram:

- First mount. The fetch effect in [`frontend/src/components/chat-detail/ChatDetail.js`](frontend/src/components/chat-detail/ChatDetail.js) ran `prerenderMermaidDiagrams`, which used `mermaid.parse` first, caught the parse error, and produced `{ svg: null, error: "..." }`. `MermaidBlock` mounts with `initialError` set, so `skipFirstRenderRef.current` is `true`. The effect runs once, returns early, and clears the ref. No `mermaid.render` call, no bomb.
- First theme toggle. `darkMode` flips, the effect re-runs. `skipFirstRenderRef.current` is now `false`, so the effect calls `mermaid.render(renderId, source)`. The render rejects (same source, same syntax error). Mermaid injects bomb #1 into `document.body`. The catch handler sets `renderError` and forces `mode = 'source'`, but the DOM mutation is already done.
- Second theme toggle. Same thing again, bomb #2.
- And so on. The bombs accumulate because they are appended to `document.body`, not to anything React owns.

The doc comment at the top of `MermaidBlock` actually claims this case is already handled ("`mermaid.render` is never called for this diagram, which prevents mermaid from injecting its bomb-graphic error element into document.body"), but the implementation only delivers that guarantee on first mount.

## Fix

Mirror the parse-first discipline already documented in `prerenderMermaidDiagrams` inside `MermaidBlock`'s effect. `mermaid.parse` is DOM-free and throws on invalid syntax with no side effects; `mermaid.render` is what injects the bomb. Once the effect parses first, an invalid diagram can never reach `mermaid.render`, regardless of how many times the theme flips.

### Implementation steps

The bulk of the work is in [`frontend/src/components/MermaidBlock.js`](frontend/src/components/MermaidBlock.js). All other changes are documentation / rule sync per [`.cursor/rules/project-layout.mdc`](.cursor/rules/project-layout.mdc) and [`.cursor/rules/comments-style.mdc`](.cursor/rules/comments-style.mdc).

1. Replace the body of the existing render effect with an inline async function that:
   - Increments `latestRef` before any `await` (per the cancellation discipline in [`.cursor/rules/frontend-hooks.mdc`](.cursor/rules/frontend-hooks.mdc)).
   - Calls `mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: darkMode ? 'dark' : 'default' })` first, exactly as today.
   - Calls `await mermaid.parse(source)` inside its own try/catch. On failure, gates on `latestRef` and then calls `setRenderError(parseErr?.message ?? String(parseErr))` and `setMode('source')` — same UX as today's render-catch path. Critically, it does **not** fall through to `mermaid.render`.
   - On a successful parse, allocates `renderId = nextMermaidId()` and calls `await mermaid.render(renderId, source)`, gating success and failure on `latestRef` exactly as today. The success path keeps `setSvg` / `setRenderError(null)`; the failure path keeps `setRenderError` / `setMode('source')` as a belt-and-braces backstop for any post-parse render-time failures.

2. Keep `skipFirstRenderRef` in place. Its job is to skip the first-mount re-render of valid diagrams (so the SVG produced by the prerender does not flicker through a second render); the new parse-first guard is what neutralises invalid-source theme flips. Update the surrounding comment block to reflect both responsibilities accurately, and to drop the inaccurate claim that the current implementation already prevents bomb injection.

3. Per [`.cursor/rules/comments-style.mdc`](.cursor/rules/comments-style.mdc), the new comment near the parse call should explain *intent* — that `mermaid.parse` is DOM-free and `mermaid.render` injects a bomb element into `document.body` on a failed parse, so we must validate first to keep theme flips idempotent. Do **not** narrate "validate the source" or similar mechanics.

### Why not other approaches

- "Track `renderError` and skip the effect when it's set": fragile because the same `MermaidBlock` instance can receive a new `source` prop, and we would need extra resetting logic; a parse failure on the new source still takes the bomb path. Parse-first naturally handles all those cases because it runs every time.
- "Clean up the bomb after the fact" (querySelectorAll on `document.body` for the error element): a band-aid that mutates global DOM state owned by a third-party library, and runs the risk of removing legitimate output if mermaid changes its DOM shape. The preventive fix is strictly better.
- "Drop `darkMode` from the effect deps": breaks valid-diagram theme sync, which the [`mermaid-rendering.mdc`](.cursor/rules/mermaid-rendering.mdc) rule explicitly mandates ("`MermaidBlock` reads `darkMode` from `ThemeModeContext` and re-renders when it flips").

### Rule sync

- [`.cursor/rules/mermaid-rendering.mdc`](.cursor/rules/mermaid-rendering.mdc): the "Theme sync" section currently describes only the `mermaid.initialize` + `mermaid.render` pair. Extend it to state that **both** rendering paths (`MermaidBlock`'s effect *and* `prerenderMermaidDiagrams`) call `mermaid.parse` before `mermaid.render` so a failed parse cannot inject mermaid's bomb error element into `document.body`. Cross-reference both file paths so a future contributor sees the invariant in one place.
- [`.cursor/rules/known-bugs.mdc`](.cursor/rules/known-bugs.mdc): per the "When the next deferred bug surfaces" sentence, this is a **fix**, not a deferral, so no live `TODO(bug):` marker is needed. The rule's "retired examples" list is the appropriate home for a one-line entry citing the new invariant pinned in `MermaidBlock` (parse-first guard for theme-flip idempotence). Add it next to the three existing retired entries.
- [`.cursor/rules/project-layout.mdc`](.cursor/rules/project-layout.mdc) "Documentation sync": this fix does not change the repo layout and does not change user-facing setup, binary usage, or features. The `MermaidBlock` blurb in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) ("renders a mermaid fenced code block as a live diagram (default) or raw source, with a per-block toggle and a parse-error fallback") stays accurate, and [`README.md`](README.md) only mentions mermaid in a single bullet that is unaffected. No edits needed in either file; the review todo below confirms that explicitly.
- [`.cursor/rules/frontend-hooks.mdc`](.cursor/rules/frontend-hooks.mdc) and [`.cursor/rules/react-components.mdc`](.cursor/rules/react-components.mdc): the canonical patterns these rules enforce (`latestRef` cancellation, `useEffect`-only library calls, `useMermaid` as the singleton owner) are preserved. No changes needed.

### Tests

The repo's automated test suite is Python-only (`tests/` + stdlib `unittest`, per [`.cursor/rules/project-layout.mdc`](.cursor/rules/project-layout.mdc)). There is no Jest / React Testing Library infrastructure under `frontend/`, so a frontend regression test is out of scope for this fix and would constitute a separate piece of work to introduce a JS test runner. Verification will be manual:

- Reproduce on the cited URL (`/chat/ec60d4dd-9bac-45af-84e7-bc7e35022378`), toggle dark/light mode at least four times, confirm zero new SVGs accrue at the end of the page.
- Confirm a valid diagram in another chat still re-renders with the new theme on each toggle.
- Confirm the in-block "Mermaid parse error: ..." caption still appears for the broken diagram, and the source text is still shown (the [`mermaid-rendering.mdc`](.cursor/rules/mermaid-rendering.mdc) "Graceful source fallback on parse error" invariant).

## Out of scope

- Adding a frontend JS test harness.
- Changing the prerender path; it already does the right thing.
- Touching the HTML export's mermaid pipeline (`cursor_view/export/mermaid.py`); the bug only exists in the chat view.