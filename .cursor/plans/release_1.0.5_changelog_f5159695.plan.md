---
name: Release 1.0.5 Changelog
overview: Draft the GitHub release changelog markdown for cursor-view 1.0.5 by reviewing the diff between the 1.0.7.3-dev branch and main, separating user-facing changes from internal-only ones.
todos: []
isProject: false
---

## Original user instructions

> This project is a tool for software developers that make use of Cursor IDE. Specifically, this tool enables users to access their Cursor chat history across all of their projects and includes functionality to search through chat history as well as view individual chats. I am about to publish a new release of this project and need a changelog to share on GitHub as part of the release.
>
> Use Git to compare the code changes that were made between this @Branch and `main` and use the result of that diff to write a plan file that contains changelog markdown that I can copy and paste in to the GitHub release page. The changelog should only list changes that have user-facing impacts. For example, the improved caching and support for rendering mermaid charts are good examples of things to mention, however, mentioning that the code was refactored and unit tests were added should not be mentioned. Any changes that you identify that are not user-facing should be put in a separate, bulleted list so that if I change my mind, I can manually add them to the changelog on a case-by-case basis.
>
> The changelog you write should follow the style used by previous release changelogs, which you can see on the GitHub release page for this project here: https://github.com/DavidBerdik/cursor-view/releases
>
> Please note that even though this branch uses 1.0.7.3 as the version number, this release is actually going to be 1.0.5.
>
> Since the changelog you generate will be published on GitHub manually by me, there is no need for you to add any todos to the plan file. Just generate the markdown for me to copy and paste to GitHub along with the list of changes that you found that you do not think are appropriate to share. In addition to looking at the Git diff between this branch and `main`, you may also want to consider looking at individual commits as well.
>
> When writing the plan, make sure to also include a verbatim copy of these instructions.

---

## cursor-view 1.0.5 release changelog (copy/paste to GitHub)

```markdown
Changes:

* Added support for viewing image attachments inline in the chat view UI and in Markdown, HTML, and JSON chat exports. Clicking a thumbnail in the chat view UI opens the full-size image in a new lightbox viewer, and clicking a thumbnail in an HTML export opens the full-size image in a new browser tab.
* Added support for rendering Mermaid diagrams in the chat view UI and in HTML chat exports.
* Added an "Open in New Tab" option to the right-click menu for chat previews on the main page. When the experimental desktop mode is used, the label is changed to "Open in Browser Tab".
* Improved the responsiveness of the cached Cursor chat data introduced in 1.0.4 by only re-processing chats that have actually changed since the previous refresh. This significantly reduces the delay before recent chat messages are available to view and export.
* Improved application upgrade behavior: when the cache format changes between releases, the cache is now automatically rebuilt on first launch instead of producing errors.
* Fixed additional cases where some chats were assigned `(unknown)` category and file path.
* Fixed a bug where orphaned chat messages could be appended to the end of a chat's history.
* Fixed a bug where chat history could appear scrambled.
* Fixed a bug where moving a chat between workspaces could leave it associated with the previous workspace until the cache was manually refreshed.
* Fixed a bug where chats whose only content is images appeared as "Content unavailable" in the chat list and search results.
* Fixed a bug where the `Content-Length` header of HTML chat export downloads could be incorrect for chats containing non-ASCII characters.
* Fixed a minor formatting issue in Markdown chat exports where the separator between messages could render on the same line as an image.

This release only has a build for Windows. If you are using Linux or macOS, please clone the repo and build the application yourself.
```

---

## Changes identified as not user-facing (for optional manual inclusion)

These were intentionally left out of the changelog above. If any of them feel worth highlighting, you can add them manually.

- Large internal refactor splitting several oversized modules into subpackages (`cursor_view/chat_index/`, `cursor_view/cache/diff/`, `cursor_view/cache/delta/`, `cursor_view/extraction/passes/`, `cursor_view/projects/*`, `cursor_view/sources/*`, `cursor_view/images/`, `cursor_view/export/html_styles.py`, etc.).
- Added a large suite of regression unit tests (incremental cache, image attachments, HTML Mermaid export) and split the image test file into per-concern siblings.
- Reorganized developer-oriented documentation out of `README.md` into `.github/CONTRIBUTING.md`, and refreshed the project-layout section of `README.md`.
- Added/updated several `.cursor/rules/*.mdc` rule files (`frontend-hooks.mdc`, `image-attachments.mdc`, `mermaid-rendering.mdc`, `chat-index-refresh.mdc`, plus updates to `project-layout.mdc`, `python-standards.mdc`, `react-components.mdc`, `sqlite-cursor-db.mdc`).
- Stripped narrating / redundant code comments per the project's comments-style rule.
- Added a new `GET /api/chat/<id>/image/<uuid>` endpoint backing the new image viewer (internal API surface, not documented for end users).
- Bumped `INDEX_SCHEMA_VERSION` to 2 and introduced new cache tables (`composer_state`, `source_row`, `tool_call_parent`, `chat_image`) plus row-hash-based invalidation to power the incremental cache updates.
- Added diagnostic `logger.info` counters for modified / deleted / project-only / subagent-propagated composers per refresh, and a warning for out-of-range image positions.
- Hardening tweaks: HTML-escape of image `uuid` in Markdown exports, sanitization of `session_id` when interpolating into the `Content-Disposition` filename, graceful handling of malformed image refs in the frontend gallery, and a guard against non-dict JSON in the bubble parser.
- Extracted several internal helpers (`_markdown_header_lines`, `_markdown_message_lines`, `_attach_images_to_messages`, `_insert_chat_images`, `_fetch_images_for_session`, `image_ref_to_transport_dict`, `image_ref_from_transport_dict`, etc.) and tightened a number of type annotations and docstrings.
- Removed dead code and obsolete `TODO(bug)` markers (hardcoded `known_projects` list, `Documents/codebase` fallback branch, `cursor-view` literal fallback, etc.).
- Deleted several completed Cursor plan files and added new ones (including a not-yet-implemented plan for surfacing Cursor-generated chat titles).
- Bumped several frontend dependencies in `frontend/package.json` / `frontend/package-lock.json` to support the image lightbox modal and Mermaid rendering (e.g., `mermaid`, supporting MUI / utility packages).

---

## Notes on how I categorized

- The incremental cache work touches many commits and several new modules, but its only user-visible payoff is "the post-save delay from 1.0.4 is much shorter", so the changelog collapses all of that into one bullet.
- The "force rebuild on schema mismatch" commit (`f93bf37`) is listed as user-facing because without it, users upgrading across a schema-bump would hit errors; framed as a smoother upgrade experience.
- The Markdown trailing-blank-line fix (`2f40e93`), `Content-Length` byte-length fix (`2d99699`), and the image-only preview fix (`2638bd7`) are small but affect what users see in exported / viewed output, so they are included.
- Security-flavored fixes (uuid HTML-escape, `session_id` sanitization, malformed image graceful degradation, non-dict bubble guard) are internal hardening with no observable behavior change for normal users, so they are in the non-user-facing list.
- `1.0.7.3-dev` is the in-branch version string; the release will ship as `1.0.5`, matching the version numbering scheme used in the [published releases list](https://github.com/DavidBerdik/cursor-view/releases).