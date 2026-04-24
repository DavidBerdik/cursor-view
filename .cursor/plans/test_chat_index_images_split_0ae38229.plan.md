---
name: test_chat_index_images oversize split
overview: Follow-up from the G1 rule-violation audit of the image-attachment post-impl followup plan. One violation of `python-standards.mdc`'s <400-line module soft limit landed in `tests/test_chat_index_images.py` (1005 lines post-E1; was already 524 pre-E1, so the overrun predates E1 and was amplified rather than introduced by it). This plan proposes a split into per-concern sibling test modules plus a shared fixture helper, preserving the stdlib-only test discipline and keeping `python -m unittest discover -s tests` green.
todos:
  - id: S1-split-images-test-module
    content: "Split `tests/test_chat_index_images.py` (1005 lines) into three sibling modules and one shared fixture helper: `tests/test_chat_index_images_core.py` (existing end-to-end rebuild cases plus the coalescer unit cases), `tests/test_chat_index_images_regressions.py` (the seven ChatIndexImageTest E1 cases added for A1 / A4 / B1 / data-uri round-trip / dedup / etc.), `tests/test_chat_index_images_exports.py` (the A8 MarkdownExportImageTest + A9 HtmlExportImageTest classes), and `tests/_image_test_helpers.py` (the `_create_source_schema`, `_put_kv`, `_composer`, `_bubble_with_modern_image`, `_bubble_with_legacy_image`, `_bubble_with_both_shapes_same_uuid`, `_bubble_with_modern_images`, `_encode`, `PNG_PREFIX`, `_export_chat_fixture` fixtures that multiple classes share). Each sibling module stays stdlib-only (no pytest, no Testing Library, no new dependency); `python -m unittest discover -s tests` must stay green and still find the same ~25 tests this module currently owns."
    status: completed
isProject: false
---

# Split `tests/test_chat_index_images.py` into per-concern siblings

## Motivation

The G1 rule-violation audit of the image-attachment post-impl
followup plan (`.cursor/plans/image_attachment_post-impl_followup_2b026aae.plan.md`)
identified one `python-standards.mdc` soft-limit violation that
could not be resolved as a hotfix attributable to a specific todo
in that plan:

- **`tests/test_chat_index_images.py`** is now 1005 lines. The file
  was already 524 lines before E1 ran (original image-attachment
  plan + coalescer cases), so the overrun is pre-existing and was
  amplified — not introduced — by E1's nine regression tests. The
  python-standards.mdc rule says modules over ~400 lines "must be
  split into a subpackage".

Tests are a legitimate exception to the "split into a subpackage"
framing (stdlib `unittest.discover` expects flat `tests/test_*.py`
modules, not nested packages), but the rule's underlying intent —
keep a single module from becoming unmanageable — still applies. A
peer-module split gives us the cohesion of a test package without
the discovery friction.

## Scope

Pure test-file restructuring. No production-code change, no new
tests, no behavioral diff. The goal is only to reorganize the
~25 test methods in `tests/test_chat_index_images.py` so each
sibling module stays well under the 400-line soft limit.

## Proposed split

```
tests/
  _image_test_helpers.py           (new, shared fixtures)
  test_chat_index_images_core.py   (new, original end-to-end + coalescer)
  test_chat_index_images_regressions.py  (new, E1 ChatIndexImageTest cases)
  test_chat_index_images_exports.py      (new, A8 + A9 export cases)
```

Delete the current `tests/test_chat_index_images.py` once the siblings land; git history preserves the pre-split form.

### `tests/_image_test_helpers.py`

Module-level fixtures + the `ChatIndexImageTest` setUp/tearDown
harness that all three peer modules share. Prefix with `_` so
unittest.discover does not try to run it as a test module (the
`-p test_*.py` default pattern already handles this, but the
underscore prefix makes intent explicit for readers).

Contents:
- Module docstring naming the three consumers.
- `PNG_PREFIX`, `_create_source_schema`, `_encode`, `_put_kv`, `_composer`.
- `_bubble_with_modern_image`, `_bubble_with_modern_images`, `_bubble_with_legacy_image`, `_bubble_with_both_shapes_same_uuid`.
- `_export_chat_fixture` (consumed by the A8/A9 export tests).
- A new `BaseChatIndexImageTest(unittest.TestCase)` with `setUp`, `tearDown`, `_build_index`, `_refresh`, `_chat_image_rows`, `_chat_messages`, `_write_png` — the four `cursor_root` patches this harness currently sets up.

Target size: ~200 lines.

### `tests/test_chat_index_images_core.py`

The pre-E1 content: the five end-to-end scenarios from the original
image-attachment plan (modern-shape rebuild, legacy-shape rebuild,
modification-via-incremental-apply, missing-disk skip, multiple
images round-trip) plus the two original coalescer unit cases
(same-role image concatenation, image-only turn placeholder).

Each class subclasses `BaseChatIndexImageTest` from the helpers
module. The `CoalescerImageTest` class (no Cursor-DB harness
needed) stays a plain `unittest.TestCase`.

Target size: ~300 lines.

### `tests/test_chat_index_images_regressions.py`

The E1 regressions that sit on the `ChatIndexImageTest` harness
(five new tests added to that class, plus the E1-extended
`test_missing_disk_image_is_skipped_not_fatal` wrapped in
`assertLogs`), plus the new coalescer `test_coalesce_post_loop_placeholder_clear`.

Consumes `BaseChatIndexImageTest` from the helpers module.

Target size: ~320 lines.

### `tests/test_chat_index_images_exports.py`

The A8 `MarkdownExportImageTest` (two cases) and A9
`HtmlExportImageTest` (two cases). Both consume `_export_chat_fixture`
from the helpers module. No Cursor-DB harness needed.

Target size: ~180 lines.

## Invariants to preserve

- **Stdlib-only.** No new dependency in `requirements.txt`. No
  pytest, no Testing Library. Only `unittest`, `json`, `pathlib`,
  `shutil`, `sqlite3`, `tempfile`, `re`, `base64`, and
  `unittest.mock.patch` (all already in use today).

- **`unittest.discover`-compatible.** Running `python -m unittest
  discover -s tests` must find and run the same ~25 tests as
  before. The default discovery pattern `test_*.py` matches the
  three peer modules; the helpers module's leading-underscore
  name keeps it out of discovery.

- **No behavioral diff.** Each test's assertions stay byte-for-byte
  identical to the pre-split form. If a test's logger-name argument
  to `assertLogs` or its seeded-bubble shape changes during the
  split, that's a bug in the split, not a scope expansion.

- **Logger-name stability.** The `assertLogs("cursor_view.images.loading",
  level="WARNING")` and `assertLogs("cursor_view.chat_index.rows",
  level="WARNING")` call sites in the regression module must keep
  the exact logger paths the production code uses. The `BaseChatIndexImageTest`
  helper's `cursor_root` patches are independent of logger name.

## Rule compliance

- **`python-standards.mdc`** soft limit — every sibling lands well
  under 400 lines (core ~300, regressions ~320, exports ~180,
  helpers ~200).

- **`project-layout.mdc`** — tests stay under `tests/`. The
  `_image_test_helpers.py` module is a test-internal helper (not a
  top-level Python file in the project-layout.mdc sense; it lives
  inside the `tests/` folder and has no production-code caller).
  No `tests/__init__.py` added — the flat layout `unittest.discover`
  expects is preserved.

- **`comments-style.mdc`** — module docstrings on all four new
  files summarize what the module owns and point at the other
  sibling for related cases, so a future contributor grepping
  `test_chat_index_images_*` sees the full surface from any entry.

## Why no regression test of the split itself

The existing ~25 tests ARE the regression test. If the split
accidentally changes any test's behavior, that test fails after
the split — `python -m unittest discover -s tests` staying green
is the contract the split must satisfy. No additional scaffolding
needed.

## Non-goals

- Adding pytest / pytest-cov / Testing Library / any JS test
  harness. Explicitly out of scope per
  `.cursor/rules/project-layout.mdc` and the original feature
  plan's "no new dependency" posture.
- Splitting `tests/test_chat_index_incremental.py` (808 lines
  today, also over the 400-line soft limit). That file was not
  touched by the post-impl-followup plan; its overrun is a
  separate concern and should get its own follow-up plan if it
  ever warrants one.
- Renaming any test method. The discovery pattern depends on
  method names starting with `test_`; renames are out of scope
  and would obscure the git-history connection to the pre-split
  form.

## Rollout

One PR with the four new files and the deletion of the current
`tests/test_chat_index_images.py` in the same commit. Reviewers
can verify by running `python -m unittest discover -s tests -v`
before and after applying the PR: the test-ID list must match
exactly (barring the module-name prefix in each test ID).
