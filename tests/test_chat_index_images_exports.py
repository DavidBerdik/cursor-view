"""A8 / A9 export regression cases for image-bearing messages.

Pins the Markdown and HTML exporter behavior called out in
``.cursor/plans/image_attachment_post-impl_followup_2b026aae.plan.md``
sections A8 (Markdown blank-line separator before ``---``) and A9
(HTML anchor wrapper + CSS for the image gallery).

Both exporters read ``session_id``, ``date``, ``project.name``,
``project.rootPath``, and ``messages[*].{role,content,images}``
directly from the chat dict, so these tests feed
``_export_chat_fixture``-built fixtures in-process without needing
the Cursor-DB harness used by the core / regressions sibling modules.

Related siblings:
- ``tests/test_chat_index_images_core.py`` -- original end-to-end
  ``chat_image`` scenarios + two original coalescer unit cases.
- ``tests/test_chat_index_images_regressions.py`` -- E1 regressions
  on the ``chat_image`` pipeline and the coalescer post-loop.

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


if __name__ == "__main__":
    unittest.main()
