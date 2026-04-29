"""CLI entry point: ``python -m cursor_view.extraction.diagnostics --cid <id>``.

Reads source DBs and the chat-index cache read-only and prints a
human-readable resolution-trace report for the given session id, or
the raw trace dict as JSON when ``--json`` is passed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from cursor_view.extraction.diagnostics.trace import trace_project_resolution

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cursor_view.extraction.diagnostics",
        description=(
            "Trace why a Cursor chat resolved to (unknown) / (global). "
            "Reads source DBs and the chat-index cache read-only; never "
            "modifies any file."
        ),
    )
    parser.add_argument(
        "--cid",
        required=True,
        help="composerId / session id to trace (e.g. task-toolu_01XvF39QpU8SG7TECB7EWnWg).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the trace dict as JSON on stdout instead of the human report.",
    )
    return parser


def _log_trace(trace: dict[str, Any]) -> None:
    """Render ``trace`` to the configured logger as a human-readable report."""
    logger.info("===== trace_project_resolution(%s) =====", trace["cid"])
    logger.info("global_db: %s", trace["global_db"])
    logger.info("cache_db:  %s", trace["cache_db"])
    logger.info("is_task_subagent: %s", trace["is_task_subagent"])
    if trace["is_task_subagent"]:
        logger.info("tool_call_id:     %s", trace["tool_call_id"])
    _log_composer_probe(trace)
    _log_bubble_probe(trace)
    _log_cache_summary(trace)
    _log_chain(trace)
    logger.info("chain_terminus: %s", trace["chain_terminus"])
    logger.info("DIAGNOSIS: %s", trace["cause"])


def _log_composer_probe(trace: dict[str, Any]) -> None:
    composer = trace["probes"].get("composer")
    if composer is None:
        logger.info("composerData row: MISSING")
        return
    logger.info(
        "composerData: name=%r subagentInfo=%s headers=%d ws_id=%s",
        composer.get("name"),
        composer.get("subagent_info"),
        composer.get("headers_count"),
        composer.get("has_workspace_identifier"),
    )


def _log_bubble_probe(trace: dict[str, Any]) -> None:
    bubble_count = trace["probes"].get("bubble_count")
    if bubble_count is not None:
        logger.info("bubble rows in cursorDiskKV: %s", bubble_count)
    if not trace["is_task_subagent"]:
        return
    logger.info(
        "tool_call_parent[%s] in cache: %s",
        trace["tool_call_id"],
        trace["probes"].get("tool_call_parent_in_cache"),
    )
    orphan = trace["probes"].get("orphan_bubble_with_tcid")
    if orphan is None:
        logger.info("no on-disk bubble carries this toolCallId")
        return
    logger.info(
        "on-disk bubble for toolCallId: parent=%s bubbleId=%s tool=%r in_parent_headers=%s",
        orphan.get("parent_cid"),
        orphan.get("bubble_id"),
        orphan.get("tool_name"),
        orphan.get("in_parent_headers"),
    )


def _log_cache_summary(trace: dict[str, Any]) -> None:
    cache_summary = trace.get("cache_summary")
    if cache_summary is None:
        logger.info("chat_summary row: MISSING from cache")
        return
    logger.info(
        "chat_summary: workspace_id=%r project_name=%r rootPath=%r",
        cache_summary.get("workspace_id"),
        cache_summary.get("project_name"),
        cache_summary.get("project_root_path"),
    )


def _log_chain(trace: dict[str, Any]) -> None:
    logger.info("--- chain ---")
    for i, hop in enumerate(trace["chain"]):
        logger.info(
            "  [%d] %s ws=%r name=%r root=%r in_cache=%s",
            i,
            hop["cid"],
            hop.get("workspace_id"),
            hop.get("project_name"),
            hop.get("project_root_path"),
            hop.get("in_cache"),
        )


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and run the trace.

    The ``logging.basicConfig`` call lives here (not at module load)
    so importing the diagnostics package does not silently install a
    root-logger handler in callers that already configured logging.
    """
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    trace = trace_project_resolution(args.cid)
    if args.json:
        print(json.dumps(trace, indent=2, default=str))
    else:
        _log_trace(trace)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
