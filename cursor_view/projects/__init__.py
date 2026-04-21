"""Project resolution helpers.

Public API:

- :func:`workspace_info` — read a workspace's ``state.vscdb`` and return
  ``(project, composer metadata)``.
- :func:`extract_project_name_from_path` — derive a display name from a
  resolved project root.
- :func:`project_from_folder_uri_list` /
  :func:`project_from_global_composer_files` /
  :func:`project_from_uri_list` /
  :func:`project_from_workspace_identifier` — URI-level inference helpers
  the extraction pipeline consumes directly.

The implementation is split across focused submodules
(:mod:`cursor_view.projects.name`, :mod:`.uris`, :mod:`.workspace_json`,
:mod:`.workspace_sources`, :mod:`.workspace_identifier`,
:mod:`.composer_uris`, :mod:`.pane_view`, :mod:`.inference`,
:mod:`.git`). The underscore-prefixed helpers still living under those
modules are package-private; cross-package callers should import the
public aliases re-exported here instead.
"""

from cursor_view.projects.composer_uris import (
    _project_from_folder_uri_list as project_from_folder_uri_list,
)
from cursor_view.projects.composer_uris import (
    _project_from_global_composer_files as project_from_global_composer_files,
)
from cursor_view.projects.composer_uris import (
    _project_from_uri_list as project_from_uri_list,
)
from cursor_view.projects.inference import workspace_info
from cursor_view.projects.name import extract_project_name_from_path
from cursor_view.projects.workspace_identifier import (
    _project_from_workspace_identifier as project_from_workspace_identifier,
)

__all__ = [
    "extract_project_name_from_path",
    "project_from_folder_uri_list",
    "project_from_global_composer_files",
    "project_from_uri_list",
    "project_from_workspace_identifier",
    "workspace_info",
]
