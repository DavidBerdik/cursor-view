"""Pass 4: infer a project from bubble URIs for still-global composers."""

from __future__ import annotations

from typing import Any, Dict

from cursor_view.projects.inference import (
    _project_from_folder_uri_list,
    _project_from_uri_list,
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
    noisier.
    """
    fallback_cids = set(bubble_folder_uris_by_cid) | set(bubble_file_uris_by_cid)
    for cid in fallback_cids:
        if comp2ws.get(cid) != "(global)":
            continue
        if "_inferred_project" in sessions[cid]:
            continue
        inferred = _project_from_folder_uri_list(
            bubble_folder_uris_by_cid.get(cid, [])
        ) or _project_from_uri_list(
            bubble_file_uris_by_cid.get(cid, [])
        )
        if inferred:
            sessions[cid]["_inferred_project"] = inferred
