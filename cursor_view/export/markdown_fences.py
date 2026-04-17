"""Normalize Cursor-specific fenced code blocks before Markdown rendering.

Cursor chats store code blocks with headers like ``start:end:path/to/file.py``
on the same line as the fence backticks. Stock Python-Markdown's
``fenced_code`` extension treats that entire string as the language tag and
produces nonsense ``language-10:42:...`` classes. These helpers rewrite the
fence to a real language tag derived from the filename extension, and move
any inline code that accidentally ended up on the fence line down onto the
next line.
"""

import re

from pygments.lexers import find_lexer_class_for_filename


CURSOR_METADATA_PATTERN = re.compile(r"^(\d+):(\d+):(.+)$")


def infer_language_from_filename(filename: str) -> str | None:
    """Infer a fenced-code language tag from a filename."""
    if not filename:
        return None

    lexer_class = find_lexer_class_for_filename(filename)
    if lexer_class is None:
        return None

    if lexer_class.aliases:
        return lexer_class.aliases[0]
    return None


def normalize_markdown_for_html_export(content: str) -> str:
    """Normalize malformed markdown patterns seen in chat exports."""
    normalized_lines = []

    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("```"):
            fence_tail = stripped[3:]

            if fence_tail:
                cursor_metadata = CURSOR_METADATA_PATTERN.match(fence_tail)
                if cursor_metadata:
                    filename = cursor_metadata.group(3)
                    language = infer_language_from_filename(filename)
                    normalized_lines.append(f"{indent}```{language or ''}")
                    continue

                language_and_content = re.match(r"^([A-Za-z0-9_+-]+)\s+(.+)$", fence_tail)
                if language_and_content:
                    language, inline_code = language_and_content.groups()
                    normalized_lines.append(f"{indent}```{language}")
                    normalized_lines.append(f"{indent}{inline_code}")
                    continue

        normalized_lines.append(line)

    return "\n".join(normalized_lines)
