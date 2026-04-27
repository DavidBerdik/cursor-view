"""Export regressions for image-bearing messages and chat-title rendering.

Pins three concerns that share the same in-process exporter harness:

- A8 (``.cursor/plans/image_attachment_post-impl_followup_2b026aae.plan.md``)
  -- Markdown blank-line separator between the last ``<img>`` and the
  trailing ``---`` thematic break.
- A9 (same plan) -- HTML anchor wrapper + CSS for the image gallery
  so the export's ``<img>`` thumbnails open the inlined data URI in
  a new tab.
- Chat-title support
  (``.cursor/plans/chat_title_support_f75142a7.plan.md``) -- header
  / heading / info-strip switching on ``chat.title`` for both
  Markdown and HTML exports.

Both exporters read ``session_id``, ``date``, ``project.name``,
``project.rootPath``, ``title``, and ``messages[*].{role,content,images}``
directly from the chat dict, so these tests feed
``_export_chat_fixture``-built fixtures in-process without needing
the Cursor-DB harness used by the core / regressions sibling modules.

Related siblings:
- ``tests/test_chat_index_images_core.py`` -- original end-to-end
  ``chat_image`` scenarios + two original coalescer unit cases.
- ``tests/test_chat_index_images_regressions.py`` -- E1 regressions
  on the ``chat_image`` pipeline and the coalescer post-loop.
- ``tests/test_chat_index_titles.py`` -- end-to-end (cache + API +
  search + incremental refresh) coverage for the ``title`` column;
  the title-export cases here are the per-format complement.

Shared ``_export_chat_fixture`` helper lives in
``tests/_image_test_helpers.py``.
"""

from __future__ import annotations

import unittest

from tests._image_test_helpers import _export_chat_fixture


class MarkdownExportImageTest(unittest.TestCase):
    """A8: Markdown export must emit a blank line between the last ``<img>`` and ``---``.

    CommonMark renders ``---`` as a thematic break only when preceded
    by a blank line; otherwise the preceding paragraph (the final
    ``<img>`` tag) consumes it as a setext-H2 underline or literal
    text. These tests pin both the image-bearing-message fix and the
    text-only byte-identity invariant so a future edit cannot silently
    regress either shape.
    """

    def test_image_message_has_blank_line_before_thematic_break(self) -> None:
        from cursor_view.export.markdown import generate_markdown

        chat = _export_chat_fixture(
            [
                {
                    "role": "user",
                    "content": "look at this",
                    "images": [
                        {"uuid": "u1", "data_uri": "data:image/png;base64,AAA"},
                    ],
                }
            ]
        )
        out = generate_markdown(chat)
        self.assertIn(
            "/>\n\n---",
            out,
            "image-bearing message must have a blank line between the "
            "last <img/> and its trailing --- thematic break",
        )
        self.assertNotIn(
            "/>\n---",
            out,
            "direct <img/>\\n--- shape breaks CommonMark thematic-break "
            "parsing (parsers fall back to setext-H2 or literal text)",
        )
        lines = out.split("\n")
        last_img_index = max(i for i, line in enumerate(lines) if line.startswith("<img"))
        self.assertEqual(
            lines[last_img_index + 1],
            "",
            "blank separator must immediately follow the last <img> line",
        )
        self.assertEqual(
            lines[last_img_index + 2],
            "---",
            "thematic break must immediately follow the blank separator",
        )

    def test_text_only_message_separator_unchanged(self) -> None:
        from cursor_view.export.markdown import generate_markdown

        chat = _export_chat_fixture(
            [{"role": "user", "content": "plain text", "images": []}]
        )
        out = generate_markdown(chat)
        # Text-only turns already have the required blank from the
        # ``content.rstrip() + ""`` pair in ``_markdown_message_lines``.
        # Pin the exact serialized shape so a future edit cannot
        # accidentally introduce a second blank or strip the one the
        # thematic break depends on.
        self.assertIn("plain text\n\n---\n", out)


class HtmlExportImageTest(unittest.TestCase):
    """A9: HTML export must wrap each ``<img>`` in a clickable anchor opening the data URI in a new tab.

    Parity with the live React gallery's one-click full-size behavior.
    The wrapper's ``href`` and the image's ``src`` must carry the same
    data URI (no double-payload; same inlined resource). Two companion
    CSS rules neutralize the global ``.message-content a:hover`` underline
    under image-wrapping anchors so hovered images do not sprout a line
    beneath them.
    """

    def test_image_message_wraps_img_in_anchor(self) -> None:
        import re
        from cursor_view.export.html import generate_standalone_html

        data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAAAA"
        chat = _export_chat_fixture(
            [
                {
                    "role": "user",
                    "content": "look",
                    "images": [{"uuid": "u1", "data_uri": data_uri}],
                }
            ]
        )
        out = generate_standalone_html(chat)

        # Anchor wrapper + <img> + close tag form a single substring
        # because ``_render_message_images_html`` joins them without
        # intervening whitespace. Regex pulls href and src so we can
        # assert they point at the same data URI.
        pattern = re.compile(
            r'<a href="(?P<href>[^"]+)" target="_blank" rel="noopener">'
            r'<img src="(?P<src>[^"]+)" alt="[^"]*" />'
            r'</a>'
        )
        match = pattern.search(out)
        self.assertIsNotNone(
            match,
            "each <img> inside .message-images must be wrapped in "
            '<a href="..." target="_blank" rel="noopener">...</a>',
        )
        self.assertEqual(
            match.group("href"),
            match.group("src"),
            "anchor href and <img> src must reference the same data URI",
        )

        self.assertIn(
            ".message-content .message-images a {",
            out,
            "CSS rule scoping link styling to .message-images must be present",
        )
        self.assertIn(
            ".message-content .message-images a:hover {",
            out,
            ":hover override must be present so the global underline "
            "does not manifest under hovered images",
        )
        # The global ``.message-content a:hover`` rule keeps its own
        # ``text-decoration: underline``; the new base+hover rules for
        # ``.message-images a`` each carry ``text-decoration: none``.
        # Including the pre-existing ``.message-content a``
        # ``text-decoration: none``, three ``text-decoration: none``
        # occurrences are the post-A9 minimum.
        self.assertGreaterEqual(
            out.count("text-decoration: none"),
            3,
            "expected at least 3 text-decoration: none CSS declarations "
            "(existing .message-content a plus A9's base and :hover)",
        )

    def test_text_only_message_has_no_anchor_wrapper(self) -> None:
        from cursor_view.export.html import generate_standalone_html

        chat = _export_chat_fixture(
            [{"role": "user", "content": "plain text", "images": []}]
        )
        out = generate_standalone_html(chat)
        self.assertNotIn(
            '<div class="message-images">',
            out,
            "text-only message must not emit a .message-images container",
        )
        self.assertNotIn(
            '<a href="data:',
            out,
            "text-only message must not emit a data-URI anchor; "
            "A9's wrapper applies only to image-bearing messages",
        )


class MarkdownExportTitleTest(unittest.TestCase):
    """Markdown header must switch shape on ``chat.title`` presence.

    Pins both halves of the branch in
    :func:`cursor_view.export.markdown._markdown_header_lines`:
    a real title promotes to the H1 and prepends a
    ``- **Title:**`` bullet, while an empty title keeps today's
    ``# Cursor Chat: {project_name}`` heading and bullet list
    untouched so users with a long archive of pre-title exports
    don't see spurious diffs the next time they re-export an
    untitled chat.
    """

    def test_titled_chat_promotes_title_to_h1_and_adds_bullet(self) -> None:
        from cursor_view.export.markdown import generate_markdown

        chat = _export_chat_fixture(
            [{"role": "user", "content": "hi", "images": []}],
            title="My great plan",
        )
        out = generate_markdown(chat)
        self.assertIn("# My great plan\n", out)
        self.assertIn("- **Title:** My great plan\n", out)
        self.assertIn("- **Project:** Test\n", out)
        self.assertNotIn("# Cursor Chat: Test", out)

    def test_untitled_chat_keeps_legacy_header(self) -> None:
        from cursor_view.export.markdown import generate_markdown

        chat = _export_chat_fixture(
            [{"role": "user", "content": "hi", "images": []}],
            title="",
        )
        out = generate_markdown(chat)
        self.assertIn("# Cursor Chat: Test\n", out)
        self.assertNotIn("- **Title:**", out)


class HtmlExportTitleTest(unittest.TestCase):
    """HTML ``<title>`` / ``<h1>`` / info-strip must switch on ``chat.title``.

    Locks down the three branched interpolations in
    :func:`cursor_view.export.html.generate_standalone_html`:
    titled chats use ``Cursor Chat - {title}`` for the head
    ``<title>``, the bare ``{title}`` for the page ``<h1>``, and
    add a ``Title:`` info-strip row above the project / path /
    date / session-id rows. Untitled chats keep the legacy
    ``Cursor Chat - {project_name}`` / ``Cursor Chat: {project_name}``
    shape and omit the info-strip row entirely so the meta strip
    never renders an empty ``Title:`` label.
    """

    def test_titled_chat_emits_title_in_head_h1_and_info_strip(self) -> None:
        from cursor_view.export.html import generate_standalone_html

        chat = _export_chat_fixture(
            [{"role": "user", "content": "hi", "images": []}],
            title="My great plan",
        )
        out = generate_standalone_html(chat)
        self.assertIn("<title>Cursor Chat - My great plan</title>", out)
        self.assertIn("<h1>My great plan</h1>", out)
        self.assertIn(
            '<div class="info-item"><span class="info-label">Title:</span> '
            '<span>My great plan</span></div>',
            out,
        )

    def test_untitled_chat_keeps_legacy_head_and_h1_without_title_row(self) -> None:
        from cursor_view.export.html import generate_standalone_html

        chat = _export_chat_fixture(
            [{"role": "user", "content": "hi", "images": []}],
            title="",
        )
        out = generate_standalone_html(chat)
        self.assertIn("<title>Cursor Chat - Test</title>", out)
        self.assertIn("<h1>Cursor Chat: Test</h1>", out)
        self.assertNotIn(
            '<span class="info-label">Title:</span>',
            out,
            "untitled exports must not render an empty Title: info row",
        )


if __name__ == "__main__":
    unittest.main()
