"""Shape extracted chats for the React API and export."""

import logging
import os
import uuid

from cursor_view.git_project import extract_project_from_git_repos
from cursor_view.project_inference import extract_project_name_from_path
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
        # Generate a unique ID for this chat if it doesn't have one
        session_id = str(uuid.uuid4())
        if "session" in chat and chat["session"] and isinstance(chat["session"], dict):
            session_id = chat["session"].get("composerId", session_id)

        # Prefer createdAt, then lastUpdatedAt; omit date if unknown (UI shows "Unknown date")
        date = None
        if "session" in chat and chat["session"] and isinstance(chat["session"], dict):
            date = session_display_date_seconds(chat["session"])

        # Ensure project has expected fields
        project = chat.get("project", {})
        if not isinstance(project, dict):
            project = {}

        # Get workspace_id from chat
        workspace_id = chat.get("workspace_id", "unknown")

        # Get the database path information
        db_path = chat.get("db_path", "Unknown database path")

        # If project name is a username or unknown, try to extract a better name from rootPath
        if project.get("rootPath"):
            current_name = project.get("name", "")
            username = os.path.basename(os.path.expanduser("~"))

            # Check if project name is username or unknown or very generic
            if (
                current_name == username
                or current_name == "(unknown)"
                or current_name == "Root"
                or (
                    project.get("rootPath").startswith(f"/Users/{username}")
                    and project.get("rootPath").count("/") <= 3
                )
            ):

                # Try to extract a better name from the path
                project_name = extract_project_name_from_path(project.get("rootPath"), debug=False)

                # Only use the new name if it's meaningful
                if (
                    project_name
                    and project_name != "Unknown Project"
                    and project_name != username
                    and project_name not in ["Documents", "Downloads", "Desktop"]
                ):

                    logger.debug(f"Improved project name from '{current_name}' to '{project_name}'")
                    project["name"] = project_name
                elif project.get("rootPath").startswith(f"/Users/{username}/Documents/codebase/"):
                    # Special case for /Users/saharmor/Documents/codebase/X
                    parts = project.get("rootPath").split("/")
                    if len(parts) > 5:  # /Users/username/Documents/codebase/X
                        project["name"] = parts[5]
                        logger.debug(f"Set project name to specific codebase subdirectory: {parts[5]}")
                    else:
                        project["name"] = "cursor-view"  # Current project as default

        # If the project doesn't have a rootPath or it's very generic, enhance it with workspace_id
        if not project.get("rootPath") or project.get("rootPath") == "/" or project.get("rootPath") == "/Users":
            if workspace_id != "unknown":
                # Use workspace_id to create a more specific path
                if not project.get("rootPath"):
                    project["rootPath"] = f"/workspace/{workspace_id}"
                elif project.get("rootPath") == "/" or project.get("rootPath") == "/Users":
                    project["rootPath"] = f"{project['rootPath']}/workspace/{workspace_id}"

        # FALLBACK: If project name is still generic, try git repositories
        pname = project.get("name") or ""
        if pname in ["Home Directory", "(unknown)", "Root"] or (len(pname) <= 2 and pname.endswith(":")):
            git_project_name = extract_project_from_git_repos(workspace_id, debug=True)
            if git_project_name:
                logger.debug(
                    f"Improved project name from '{project.get('name')}' to '{git_project_name}' using git repo"
                )
                project["name"] = git_project_name

        # Add workspace_id to the project data explicitly
        project["workspace_id"] = workspace_id

        # Ensure messages exist and are properly formatted
        messages = chat.get("messages", [])
        if not isinstance(messages, list):
            messages = []

        # Create properly formatted chat object
        return {
            "project": project,
            "messages": messages,
            "date": date,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "db_path": db_path,  # Include the database path in the output
        }
    except Exception as e:
        logger.error(f"Error formatting chat: {e}")
        # Return a minimal valid object if there's an error
        return {
            "project": {"name": "Error", "rootPath": "/"},
            "messages": [],
            "date": None,
            "session_id": str(uuid.uuid4()),
            "workspace_id": "error",
            "db_path": "Error retrieving database path",
        }
