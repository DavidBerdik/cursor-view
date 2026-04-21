"""Shape extracted chats for the React API and export."""

import logging
import os
import uuid

from cursor_view.projects.git import extract_project_from_git_repos
from cursor_view.projects.inference import extract_project_name_from_path
from cursor_view.timestamps import session_display_date_seconds

logger = logging.getLogger(__name__)


def coalesce_consecutive_messages_by_role(messages):
    """Merge consecutive messages from the same speaker (user vs assistant)."""
    if not isinstance(messages, list) or not messages:
        return []

    def segment_content(msg):
        """Return trimmed message text, or a placeholder when missing or blank."""
        c = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(c, str) and c.strip():
            return c.rstrip()
        return "Content unavailable"

    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = "user" if msg.get("role") == "user" else "assistant"
        segment = segment_content(msg)
        if out and out[-1]["role"] == role:
            prev = out[-1]["content"]
            if prev == "Content unavailable":
                out[-1]["content"] = segment
            elif segment == "Content unavailable":
                pass
            else:
                out[-1]["content"] = prev + "\n\n" + segment
        else:
            out.append({"role": role, "content": segment})
    return out


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
    """Format the chat data to match what the frontend expects."""
    try:
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
        }
    except Exception as e:
        # TODO(bug): swallowing every exception and returning a stub with a
        # fresh ``uuid.uuid4()`` session id breaks the cache's session-id
        # invariant (``_delete_cid_rows`` deletes by the real cid, so the
        # stub row lingers and API lookups by the real id 404). The
        # follow-up bug-fix plan will change this handler to re-raise (or
        # at minimum fall back to ``chat["session"]["composerId"]``); for
        # now the behavior is preserved so this refactor stays purely
        # structural.
        logger.error("Error formatting chat: %s", e)
        return {
            "project": {"name": "Error", "rootPath": "/"},
            "messages": [],
            "date": None,
            "session_id": str(uuid.uuid4()),
            "workspace_id": "error",
            "db_path": "Error retrieving database path",
        }
