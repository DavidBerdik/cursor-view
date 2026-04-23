"""Tests for mermaid diagram support in the HTML export pipeline.

Covers the five cases called out in
``.cursor/plans/mermaid-diagram-rendering_e9f9690c.plan.md``:

1. A mermaid fenced-code block is rewritten to a ``<div class="mermaid">``
   element and does **not** appear as a ``<code class="language-mermaid">``
   block (``test_mermaid_fence_rewritten_to_div``).
2. The exported HTML contains a large inline ``<script>`` sourced from the
   vendored ``mermaid.min.js`` plus a ``mermaid.initialize({`` call tag
   (``test_mermaid_library_inlined``).
3. Mermaid source containing ``<``, ``>``, and ``&`` characters is
   HTML-escaped inside the ``<div class="mermaid">`` so the browser receives
   safe entity-encoded text (``test_mermaid_fence_source_escaped``).
4. Non-mermaid fenced code blocks still pass through ``fenced_code`` /
   ``codehilite`` normally and produce ``codehilite`` markup, not mermaid
   divs (``test_non_mermaid_fences_untouched``).
5. ``theme_mode="light"`` and ``theme_mode="dark"`` produce the matching
   mermaid theme token in the initializer script
   (``test_theme_selection``).

These tests are purely unit-level: they construct minimal ``chat`` dicts
directly and call :func:`cursor_view.export.html.generate_standalone_html`
without standing up a Flask server or touching the chat-index cache.
"""

from __future__ import annotations

import unittest

from cursor_view.export.html import generate_standalone_html
from cursor_view.export.mermaid import (
    build_mermaid_init_script,
    transform_mermaid_fences_to_html,
)


def _minimal_chat(content: str) -> dict:
    """Return the smallest chat dict that exercises the message path."""
    return {
        "session_id": "test-session-001",
        "date": 1_700_000_000,
        "project": {"name": "Test Project", "rootPath": "/test"},
        "messages": [
            {"role": "assistant", "content": content},
        ],
    }


class TestMermaidFenceRewrite(unittest.TestCase):
    """transform_mermaid_fences_to_html unit tests."""

    def test_plain_fence_becomes_div(self):
        """A mermaid fence is converted to a <div class="mermaid"> block."""
        md = "```mermaid\nflowchart TD\n    A --> B\n```"
        result = transform_mermaid_fences_to_html(md)
        self.assertIn('<div class="mermaid">', result)
        self.assertNotIn("```mermaid", result)

    def test_non_mermaid_fence_untouched(self):
        """A Python fence is not affected by the mermaid rewrite pass."""
        md = "```python\nprint('hello')\n```"
        result = transform_mermaid_fences_to_html(md)
        self.assertNotIn('<div class="mermaid">', result)
        self.assertIn("```python", result)

    def test_multiple_mermaid_fences(self):
        """Multiple mermaid fences in one message are each converted."""
        md = "```mermaid\nA --> B\n```\n\nsome text\n\n```mermaid\nC --> D\n```"
        result = transform_mermaid_fences_to_html(md)
        self.assertEqual(result.count('<div class="mermaid">'), 2)

    def test_body_html_escaped(self):
        """Special HTML characters in the mermaid body are entity-escaped."""
        md = '```mermaid\nA -->|"<b>foo</b>"| B\n```'
        result = transform_mermaid_fences_to_html(md)
        self.assertIn("&lt;b&gt;", result)
        self.assertNotIn("<b>", result)


class TestGenerateStandaloneHtmlMermaid(unittest.TestCase):
    """Integration tests against generate_standalone_html."""

    def test_mermaid_fence_rewritten_to_div(self):
        """Mermaid fences become <div class="mermaid"> in the full HTML output."""
        content = "```mermaid\nflowchart TD\n    A --> B\n```"
        html = generate_standalone_html(_minimal_chat(content))
        self.assertIn('<div class="mermaid">', html)
        self.assertNotIn('class="language-mermaid"', html)

    def test_toggle_infrastructure_present(self):
        """The exported HTML contains the toggle CSS and JS wiring for valid diagrams.

        The actual toggle markup (mermaid-diagram wrapper, mermaid-source pre,
        mermaid-toggle button) is injected at JavaScript runtime in the browser, so
        it cannot be verified from the static Python-generated HTML. This test
        instead checks that the CSS rules and the init-script logic that produces
        the toggle are present, which is sufficient to confirm the feature is wired.
        """
        html = generate_standalone_html(_minimal_chat("```mermaid\nA --> B\n```"))
        # CSS infrastructure.
        self.assertIn("mermaid-toggle", html)
        self.assertIn("mermaid-diagram", html)
        self.assertIn("mermaid-source", html)
        # The init script calls _btn('View source') only for the success path.
        self.assertIn("View source", html)
        # The init script uses 'continue' to skip _btn() for parse errors so
        # the error state never receives a toggle button.
        self.assertIn("continue;", html)

    def test_mermaid_library_inlined(self):
        """The exported HTML contains the vendored mermaid JS and an initialize call."""
        html = generate_standalone_html(_minimal_chat("```mermaid\nA --> B\n```"))
        # The vendored bundle starts with this characteristic string.
        self.assertIn('"use strict"', html)
        # The init script injected by build_mermaid_init_script.
        self.assertIn("mermaid.initialize({", html)
        # startOnLoad is false; rendering is driven by the manual async loop.
        self.assertIn("startOnLoad: false", html)

    def test_mermaid_fence_source_escaped(self):
        """HTML special chars in the mermaid body are escaped in the export."""
        content = '```mermaid\nA -->|"<b>foo</b>"| B\n```'
        html = generate_standalone_html(_minimal_chat(content))
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>foo</b>", html)

    def test_non_mermaid_fences_untouched(self):
        """Python fenced code blocks still render via codehilite, not as mermaid divs."""
        content = "```python\nprint('hello')\n```"
        html = generate_standalone_html(_minimal_chat(content))
        self.assertIn("codehilite", html)
        self.assertNotIn('<div class="mermaid">', html)

    def test_theme_selection_dark(self):
        """Dark theme mode produces mermaid theme: "dark" in the init script."""
        html = generate_standalone_html(
            _minimal_chat("```mermaid\nA --> B\n```"),
            theme_mode="dark",
        )
        self.assertIn('theme: "dark"', html)

    def test_theme_selection_light(self):
        """Light theme mode produces mermaid theme: "default" in the init script."""
        html = generate_standalone_html(
            _minimal_chat("```mermaid\nA --> B\n```"),
            theme_mode="light",
        )
        self.assertIn('theme: "default"', html)


class TestBuildMermaidInitScript(unittest.TestCase):
    """Unit tests for the build_mermaid_init_script helper."""

    def test_dark_theme(self):
        script = build_mermaid_init_script("dark")
        self.assertIn('theme: "dark"', script)
        self.assertIn("startOnLoad: false", script)
        self.assertIn('securityLevel: "strict"', script)

    def test_light_theme_maps_to_default(self):
        script = build_mermaid_init_script("light")
        self.assertIn('theme: "default"', script)

    def test_unknown_theme_maps_to_default(self):
        """Any theme_mode other than 'dark' falls back to mermaid's default theme."""
        script = build_mermaid_init_script("sepia")
        self.assertIn('theme: "default"', script)

    def test_script_tag_wrapping(self):
        script = build_mermaid_init_script("dark")
        self.assertTrue(script.startswith("<script>"))
        self.assertTrue(script.endswith("</script>"))


if __name__ == "__main__":
    unittest.main()
