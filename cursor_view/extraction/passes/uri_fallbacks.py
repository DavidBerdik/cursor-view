"""Pass 4: infer a project from bubble URIs for still-global composers."""

from __future__ import annotations

from typing import Any, Dict

from cursor_view.projects import (
    project_from_folder_uri_list,
    project_from_uri_list,
)


def _apply_uri_fallbacks(
    sessions: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    bubble_file_uris_by_cid: Dict[str, list[str]],
    bubble_folder_uris_by_cid: Dict[str, list[str]],
) -> None:
    """Pass 4: infer a project from bubble URIs for composers still tagged ``(global)``.

    Folder URIs are preferred since they are candidate project roots
    as-is; file URIs require common-prefix + filename-trim logic and are
    noisier. The folder bucket includes working directories mined from
    tool-call args (terminal ``cwd``, glob ``targetDirectory``; see
    ``cursor_view.sources.bubbles._tool_call_folder_uris``), so a
    workspace-less chat whose only signal is the local checkout its tool
    calls ran against resolves here.

    Because this runs before Pass 6, a subagent that itself touched the
    filesystem gets its own ``_inferred_project`` from its tool-call dirs
    and therefore keeps it rather than inheriting the parent's project --
    deliberate: the subagent is categorized by what it actually worked on,
    and parent inheritance (Pass 6) remains the fallback only for subagents
    with no signal of their own.
    """
    fallback_cids = set(bubble_folder_uris_by_cid) | set(bubble_file_uris_by_cid)
    for cid in fallback_cids:
        if comp2ws.get(cid) != "(global)":
            continue
        if "_inferred_project" in sessions[cid]:
            continue
        inferred = project_from_folder_uri_list(
            bubble_folder_uris_by_cid.get(cid, [])
        ) or project_from_uri_list(
            bubble_file_uris_by_cid.get(cid, [])
        )
        if inferred:
            sessions[cid]["_inferred_project"] = inferred
