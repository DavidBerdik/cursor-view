"""Shape extracted chats for the React API and export."""

import logging
import os
import re
import uuid

from cursor_view.projects.git import extract_project_from_git_repos
from cursor_view.projects.inference import extract_project_name_from_path
from cursor_view.timestamps import session_display_date_seconds

logger = logging.getLogger(__name__)

# Synthetic placeholders invented by ``cursor_view/extraction/passes/`` when
# Cursor itself never assigned a ``composerData.name``. The two regex shapes
# match the ``"Chat <8hex>"`` and ``"Global Chat <8hex>"`` fallbacks emitted
# from the finalize pass; ``""`` and ``"(untitled)"`` are the literal-string
# variants. Compiled at module load per python-standards.mdc.
_SYNTHETIC_TITLE_RE = re.compile(r"^(?:Chat|Global Chat) [0-9a-f]{8}$")


def coalesce_consecutive_messages_by_role(messages):
    """Merge consecutive messages from the same speaker (user vs assistant).

    Each output record carries ``{"role", "content", "images"}`` with
    ``images`` always a list (never missing or ``None``) so downstream
    consumers can iterate without a guard. Image-only turns keep empty
    text so the UI does not stamp "Content unavailable" next to the
    gallery; the placeholder is reserved for segments with neither text
    nor images.
    """
    if not isinstance(messages, list) or not messages:
        return []

    def segment_text(msg):
        """Return trimmed message text, or empty string when missing or blank."""
        c = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(c, str) and c.strip():
            return c.rstrip()
        return ""

    def segment_images(msg):
        """Return a defensive copy of the message's images list, or an empty list when missing."""
        imgs = msg.get("images") if isinstance(msg, dict) else None
        return list(imgs) if isinstance(imgs, list) else []

    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = "user" if msg.get("role") == "user" else "assistant"
        text = segment_text(msg)
        images = segment_images(msg)
        if out and out[-1]["role"] == role:
            prev_content = out[-1]["content"]
            prev_had_no_text = prev_content in ("", "Content unavailable")
            if text and prev_had_no_text:
                out[-1]["content"] = text
            elif text:
                out[-1]["content"] = prev_content + "\n\n" + text
            out[-1]["images"] = out[-1]["images"] + images
        else:
            if text:
                content = text
            elif images:
                content = ""
            else:
                content = "Content unavailable"
            out.append({"role": role, "content": content, "images": images})

    # An earlier truly-empty segment emits "Content unavailable" and may
    # then merge with a same-role image-only segment that concatenates
    # images. Clear the placeholder on those merged records so the
    # gallery is not visually paired with a misleading label.
    for m in out:
        if m["content"] == "Content unavailable" and m["images"]:
            m["content"] = ""
    return out


def _real_chat_title(title):
    """Return a trimmed Cursor-assigned title, or ``""`` for synthetic placeholders.

    Extraction always invents a title string (``"(untitled)"``,
    ``"Chat <8hex>"``, ``"Global Chat <8hex>"``) so downstream passes
    can rely on the field being populated. Those fallbacks carry no
    user-visible signal, so they collapse to ``""`` here. Storing the
    empty string in the cache lets every downstream consumer (UI cards,
    chat-detail header, Markdown / HTML exports, FTS search blob) gate
    rendering with a plain ``if title:`` check rather than re-running
    this classifier.
    """
    if not isinstance(title, str):
        return ""
    trimmed = title.strip()
    if not trimmed or trimmed == "(untitled)":
        return ""
    if _SYNTHETIC_TITLE_RE.match(trimmed):
        return ""
    return trimmed


def messages_for_json_export(messages):
    """Return a copy of messages with assistant role renamed to cursor for JSON export."""
    if not isinstance(messages, list):
        return []
    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = dict(msg)
        if m.get("role") == "assistant":
            m["role"] = "cursor"
        out.append(m)
    return out


def format_chat_for_frontend(chat):
    """Format the chat data to match what the frontend expects.

    Raises on malformed input rather than swallowing errors and returning
    a stub. The cache's session-id invariant
    (``session_id == composerData.composerId``, used by
    ``cursor_view.cache.delta.composer_rows._delete_cid_rows``) cannot
    survive a synthetic UUID, so callers that iterate over many chats
    (the full rebuild in ``cursor_view/chat_index/rebuild.py`` and the
    incremental apply in ``cursor_view/cache/delta/engine.py``) skip a
    malformed chat with a logged warning instead.
    """
    session_id = str(uuid.uuid4())
    if "session" in chat and chat["session"] and isinstance(chat["session"], dict):
        session_id = chat["session"].get("composerId", session_id)

    # Prefer createdAt, then lastUpdatedAt; omit date if unknown (UI shows "Unknown date")
    date = None
    if "session" in chat and chat["session"] and isinstance(chat["session"], dict):
        date = session_display_date_seconds(chat["session"])

    project = chat.get("project", {})
    if not isinstance(project, dict):
        project = {}

    workspace_id = chat.get("workspace_id", "unknown")
    db_path = chat.get("db_path", "Unknown database path")

    # If project name is a username or unknown, try to extract a better name from rootPath
    if project.get("rootPath"):
        current_name = project.get("name", "")
        username = os.path.basename(os.path.expanduser("~"))

        # Only try to improve when the current name looks generic/unhelpful
        # (username-as-project, literal "(unknown)", or a shallow home path).
        if (
            current_name == username
            or current_name == "(unknown)"
            or current_name == "Root"
            or (
                project.get("rootPath").startswith(f"/Users/{username}")
                and project.get("rootPath").count("/") <= 3
            )
        ):

            project_name = extract_project_name_from_path(project.get("rootPath"), debug=False)

            # Reject replacements that re-introduce the same generic names
            # we were trying to move away from.
            if (
                project_name
                and project_name != "Unknown Project"
                and project_name != username
                and project_name not in ["Documents", "Downloads", "Desktop"]
            ):

                logger.debug("Improved project name from '%s' to '%s'", current_name, project_name)
                project["name"] = project_name

    # Fall back to a workspace-id-scoped synthetic rootPath when the project has
    # no real root so the frontend still shows a distinct entry per workspace.
    if not project.get("rootPath") or project.get("rootPath") == "/" or project.get("rootPath") == "/Users":
        if workspace_id != "unknown":
            if not project.get("rootPath"):
                project["rootPath"] = f"/workspace/{workspace_id}"
            elif project.get("rootPath") == "/" or project.get("rootPath") == "/Users":
                project["rootPath"] = f"{project['rootPath']}/workspace/{workspace_id}"

    # Last-resort: ask SCM (git repos registered in the workspace) for a name.
    pname = project.get("name") or ""
    if pname in ["Home Directory", "(unknown)", "Root"] or (len(pname) <= 2 and pname.endswith(":")):
        git_project_name = extract_project_from_git_repos(workspace_id, debug=True)
        if git_project_name:
            logger.debug(
                "Improved project name from '%s' to '%s' using git repo",
                project.get("name"),
                git_project_name,
            )
            project["name"] = git_project_name

    project["workspace_id"] = workspace_id

    messages = chat.get("messages", [])
    if not isinstance(messages, list):
        messages = []

    return {
        "project": project,
        "messages": messages,
        "date": date,
        "session_id": session_id,
        "workspace_id": workspace_id,
        "db_path": db_path,
        "title": _real_chat_title((chat.get("session") or {}).get("title")),
    }
