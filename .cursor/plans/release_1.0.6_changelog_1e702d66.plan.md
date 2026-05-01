---
name: release 1.0.6 changelog
overview: Draft the GitHub release changelog markdown for cursor-view 1.0.6 by reviewing the diff between the 1.0.6-dev branch and 1.0.5-dev, separating user-facing changes from internal-only ones.
todos: []
isProject: false
---

## Original user instructions

> This project is a tool for software developers that make use of Cursor IDE. Specifically, this tool enables users to access their Cursor chat history across all of their projects and includes functionality to search through chat history as well as view individual chats. I am about to publish a new release of this project and need a changelog to share on GitHub as part of the release.
>
> Use Git to compare the code changes that were made between this @Branch and `1.0.5-dev` and use the result of that diff to write a plan file that contains changelog markdown that I can copy and paste in to the GitHub release page. The changelog should only list changes that have user-facing impacts. For example, the improved caching and support for mermaid chart modals with pan and zoom support are good examples of things to mention, however, mentioning that the code was refactored and unit tests were added should not be mentioned. Any changes that you identify that are not user-facing should be put in a separate, bulleted list so that if I change my mind, I can manually add them to the changelog on a case-by-case basis.
>
> The changelog you write should follow the style used by previous release changelogs, which you can see on the GitHub release page for this project here: https://github.com/DavidBerdik/cursor-view/releases
>
> Please note that even though this branch uses 1.0.6 as the version number, 1.0.5 has not been released yet, so there is no changelog for it listed on the GitHub release page I shared with you.
>
> Since the changelog you generate will be published on GitHub manually by me, there is no need for you to add any todos to the plan file. Just generate the markdown for me to copy and paste to GitHub along with the list of changes that you found that you do not think are appropriate to share. In addition to looking at the Git diff between this branch and 1.0.5-dev, you may also want to consider looking at individual commits as well.
>
> When writing the plan, make sure to also include a verbatim copy of these instructions.

---

## cursor-view 1.0.6 release changelog (copy/paste to GitHub)

```markdown
Changes:

* Added support for displaying Cursor-generated chat titles inline in the card grid, the chat-detail header, and the Markdown, HTML, and JSON chat exports. Untitled chats fall back to the existing project-based heading.
* Search queries now also match Cursor-generated chat titles in addition to message content.
* Added support for opening mermaid diagrams in a full-size modal by clicking the diagram body or the new expand icon. The modal supports drag-to-pan, wheel and button zoom, reset-to-fit, and dismissal via the close button, ESC key, or backdrop click.
* Added smooth fade animations across the entire UI (page background, cards, chat bubbles, code blocks, and mermaid diagrams) when switching between light and dark mode, instead of a single-frame flash on toggle.
* Added support for the system-wide `prefers-reduced-motion` accessibility setting. When enabled, theme toggles, hover transitions, and the mermaid diagram cross-fade all become instant.
* Chats are now sorted by creation date from newest to oldest within each project group.
* Improved the responsiveness of the Refresh button by switching it to the delta caching system introduced in 1.0.5. Refreshes now reprocess only chats that have actually changed since the previous refresh, instead of triggering a full cache rebuild.
* Fixed UI lag when typing quickly in the chat search box on the home page.
* Fixed additional cases where some chats were assigned `(unknown)` category and file path. A new built-in CLI diagnostic (`python3 -m cursor_view.extraction.diagnostics --cid <session-id>`) is also available to classify which underlying cause is responsible for any specific chat that still shows up under `(unknown)` / `(global)`. See the README for usage details.
* Fixed a bug where moving a chat between workspaces or deleting a parent chat could leave its `task-<toolCallId>` subagent chats associated with the old project until an unrelated future refresh.
* Fixed mermaid diagrams sometimes rendering with the wrong theme colors on first paint in chats containing multiple messages.
* Fixed mermaid diagrams displaying with the previous theme if the user toggled dark/light mode while a chat was still loading.
* Fixed an "error bomb" SVG accumulating at the bottom of the page when toggling dark/light mode on a chat containing an invalid mermaid diagram.
* Fixed the mermaid diagram cross-fade outgoing layer sticking on top of the new diagram if the user toggled the OS-level reduced motion preference mid-fade.
* Fixed the title bar painting near-black instead of blue in dark mode.
* Fixed scroll position drifting slightly when refreshing a chat that contains embedded mermaid diagrams.
* Fixed a single malformed chat being able to prevent the entire chat list refresh from completing.

This release only has a build for Windows. If you are using Linux or macOS, please clone the repo and build the application yourself.
```

---

## Changes identified as not user-facing (for optional manual inclusion)

These were intentionally left out of the changelog above. If any of them feel worth highlighting, you can add them manually.

- Large internal refactor splitting the monolithic `frontend/src/components/MermaidBlock.js` into smaller pieces: `MermaidDiagramSurface.js`, `MermaidLightboxModal.js`, `MermaidLightboxFallback.js`, `MermaidToolbar.js`, `MermaidZoomControls.js`, plus the new hooks `useMermaid.js`, `useMermaidRender.js`, `useSvgCrossFade.js`, `useSvgPanZoom.js`, `useReducedMotion.js`, `useInView.js`, `useMermaidBlockHeight.js`, `useChatScrollAnchor.js`, `useDebouncedValue.js`, and the new utilities `mermaidRenderCache.js`, `mermaidRenderQueue.js`, `mermaidHeightCache.js`, `svgPanZoomModel.js`, and `theme/transitions.js`.
- Internal restructuring of the chat-detail fetch effect in `frontend/src/components/chat-detail/ChatDetail.js` into three sequential outer phases (markdown prep, theme A prerender, theme B prerender) so concurrent mermaid renders within a phase share one theme.
- Migration of the MUI theme to a single `cssVariables` / `colorSchemes` instance built once instead of being rebuilt on every dark/light toggle.
- Bumped `INDEX_SCHEMA_VERSION` from 2 to 3 to add the new `chat_title` column. This causes a one-time automatic cache rebuild on first launch under 1.0.6, which is transparent to users thanks to the auto-rebuild behavior added in 1.0.5.
- Internal refactoring of the chat caching system, including a new conditional subagent-propagation engine in `cursor_view/cache/delta/propagation.py` and tightened propagation triggers for soft-deleted parents.
- Added a large suite of regression unit tests (`tests/test_chat_index_titles.py`, `tests/test_chat_index_sort_order.py`, `tests/test_chat_index_propagation_gating.py`, `tests/test_known_bug_fixes.py`, plus expansions to `tests/test_chat_index_incremental.py` and `tests/test_chat_index_images_exports.py`).
- Internal hardening so a single malformed chat is logged and skipped rather than killing the refresh, including narrowing exception types in `cursor_view/sources/item_table.py::iter_global_legacy_chatdata`, removing a stub-and-swallow handler in `cursor_view/chat_format.py::format_chat_for_frontend`, and wrapping the per-chat insert path in `cursor_view/chat_index/rebuild.py` and `cursor_view/cache/delta/engine.py`.
- Internal reorganization of the `(unknown)` / `(global)` diagnostic machinery into the new `cursor_view/extraction/diagnostics/` subpackage (`probes.py`, `walker.py`, `trace.py`, plus the existing workspace dump moved to `diagnostics/workspace_dump.py`) and removal of the unused hashing helpers in `cursor_view/cache/diff/hashing.py`.
- Moved `cleanup_orphan_temp_files()` and `create_app()` out of `cursor_view/terminal.py` module scope into `run_server()`, mirroring `run_desktop()`, and dropped the module-level `app` symbol.
- Added/updated several `.cursor/rules/*.mdc` rule files (new `theme-transitions.mdc`, plus extensive updates to `frontend-hooks.mdc`, `mermaid-rendering.mdc`, `react-components.mdc`, `known-bugs.mdc`, `chat-index-refresh.mdc`, `sqlite-cursor-db.mdc`, `python-standards.mdc`, `project-layout.mdc`).
- Documentation refresh of `.github/CONTRIBUTING.md` covering the new modules, hooks, and bug-fix history.
- Stripped narrating / redundant code comments per the project's comments-style rule, and removed retired `# TODO(bug):` markers as the underlying bugs were fixed.
- Removed several completed Cursor plan files and added new ones for in-progress work.

---

## Notes on how I categorized

- The four "Bug 1 / Bug 2 / Bug 3 / Bug 4" fixes (cross-fade cancel gap, mermaid singleton race, AppBar dark mode, mermaid scroll drift) are each user-observable on their own, so they each get their own bullet in the changelog rather than being collapsed.
- The "soft-deleted parent subagent propagation gap" fix and the "another `(unknown)` category" fix are described together because end users observe them as the same underlying class of "wrong project for a `task-<toolCallId>` chat" symptom.
- The new CLI diagnostic (`python3 -m cursor_view.extraction.diagnostics --cid ...`) is mentioned in the same bullet as the related `(unknown)` fix because that is how a user would discover it (and how the README presents it), rather than as a standalone feature bullet.
- The Refresh button delta-cache change is listed user-facing because it is observable as a faster refresh after a Cursor edit, even though the underlying machinery was already shipping in 1.0.5.
- The chat-title schema bump (`INDEX_SCHEMA_VERSION = 3`) is in the non-user-facing list because the auto-rebuild-on-schema-mismatch behavior introduced in 1.0.5 makes the upgrade transparent; there is nothing the user has to do.
- The malformed-chat hardening (skip-and-continue instead of crash-the-refresh) is described in user terms ("a single malformed chat ... prevent the entire chat list refresh from completing") rather than as the four separate internal commits that implemented it.
- All of the frontend hook / component extraction commits are in the non-user-facing list because they were structural refactors enabling the user-facing features; the user-facing payoff (mermaid modal, theme fades, search debouncing, scroll anchoring) is what is mentioned in the changelog.
- `1.0.6-dev` is the in-branch version string. The release is intended to ship as 1.0.6 per the user's instructions, matching the version numbering scheme used in the [published releases list](https://github.com/DavidBerdik/cursor-view/releases).