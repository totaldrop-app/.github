#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The TotalDrop Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for tools/export_project_board.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from export_project_board import (
    PROJECT_ITEMS_QUERY,
    PROJECT_META_QUERY,
    ProjectExportError,
    escape_md_cell,
    fetch_project_snapshot,
    main,
    render_markdown_summary,
    sanitize_text,
)


class ExportProjectBoardTests(unittest.TestCase):
    def test_sanitize_text_escapes_control_and_bidi_in_single_pass(self) -> None:
        raw = "Fix\\path\x1b[31m\u202eevil\u202c\x00\u2066name\u2069\x85"
        self.assertEqual(
            sanitize_text(raw),
            "Fix\\\\path\\x1b[31m\\u202eevil\\u202c\\x00\\u2066name\\u2069\\x85",
        )
        # Literal backslash sequences in input must not collide with escaped Bidi sequences.
        self.assertEqual(
            escape_md_cell("col1 | a\\b\nline2\u200f"),
            "col1 \\| a\\\\b line2\\u200f",
        )

    def test_private_project_fails_closed_without_querying_items(self) -> None:
        calls: list[str] = []

        def fake_requester(query: str, variables: dict, token: str) -> dict:
            calls.append(query)
            self.assertEqual(token, "test-token")
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_1",
                        "number": 1,
                        "title": "Secret Internal Board",
                        "shortDescription": "Private",
                        "url": "https://github.com/orgs/totaldrop-app/projects/1",
                        "public": False,
                        "closed": False,
                        "updatedAt": "2026-11-16T10:00:00Z",
                        "views": {"nodes": []},
                        "fields": {"nodes": []},
                    }
                }
            }

        snapshot = fetch_project_snapshot(
            "totaldrop-app",
            1,
            "test-token",
            requester=fake_requester,
            exported_at="2026-11-16T11:00:00Z",
        )
        self.assertEqual(calls, [PROJECT_META_QUERY])
        self.assertTrue(snapshot["skipped_private"])
        self.assertFalse(snapshot["public"])
        self.assertNotIn("title", snapshot)
        md = render_markdown_summary(snapshot)
        self.assertNotIn("Secret Internal Board", md)
        self.assertIn("Private", md)

    def test_pagination_column_ordering_and_markdown_rendering(self) -> None:
        def fake_requester(query: str, variables: dict, token: str) -> dict:
            if query == PROJECT_META_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "id": "PVT_1",
                            "number": 1,
                            "title": "TotalDrop Roadmap",
                            "shortDescription": "Kanban board",
                            "url": "https://github.com/orgs/totaldrop-app/projects/1",
                            "public": True,
                            "closed": False,
                            "updatedAt": "2026-11-16T10:00:00Z",
                            "views": {
                                "nodes": [
                                    {
                                        "number": 1,
                                        "name": "Kanban",
                                        "layout": "BOARD_LAYOUT",
                                        "filter": None,
                                    }
                                ]
                            },
                            "fields": {
                                "nodes": [
                                    {
                                        "__typename": "ProjectV2SingleSelectField",
                                        "id": "PVTSSF_status",
                                        "name": "Status",
                                        "dataType": "SINGLE_SELECT",
                                        "options": [
                                            {"id": "1", "name": "Todo", "description": "", "color": "GRAY"},
                                            {
                                                "id": "2",
                                                "name": "In Progress",
                                                "description": "",
                                                "color": "YELLOW",
                                            },
                                            {"id": "3", "name": "Done", "description": "", "color": "GREEN"},
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                }
            self.assertEqual(query, PROJECT_ITEMS_QUERY)
            if variables.get("after") is None:
                return {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": True, "endCursor": "CUR_1"},
                                "nodes": [
                                    {
                                        "id": "ITEM_1",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-01T00:00:00Z",
                                        "updatedAt": "2026-11-15T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "In Progress",
                                                    "optionId": "2",
                                                    "field": {"name": "Status"},
                                                },
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "High",
                                                    "optionId": "p1",
                                                    "field": {"name": "Priority"},
                                                },
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "number": 29,
                                            "title": "Android: scan QR code\u202e",
                                            "state": "OPEN",
                                            "stateReason": None,
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/29",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": {"title": "Now — November 2026"},
                                            "labels": {"nodes": [{"name": "area: android"}]},
                                            "assignees": {"nodes": [{"login": "ozdil"}]},
                                        },
                                    },
                                    {
                                        "id": "ITEM_ARCHIVED",
                                        "type": "ISSUE",
                                        "isArchived": True,
                                        "createdAt": "2026-10-01T00:00:00Z",
                                        "updatedAt": "2026-10-02T00:00:00Z",
                                        "fieldValues": {"nodes": []},
                                        "content": {"__typename": "DraftIssue", "title": "Old", "body": ""},
                                    },
                                ],
                            }
                        }
                    }
                }
            return {
                "organization": {
                    "projectV2": {
                        "items": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "ITEM_2",
                                    "type": "DRAFT_ISSUE",
                                    "isArchived": False,
                                    "createdAt": "2026-11-10T00:00:00Z",
                                    "updatedAt": "2026-11-12T00:00:00Z",
                                    "fieldValues": {"nodes": []},
                                    "content": {
                                        "__typename": "DraftIssue",
                                        "title": "Triage | unscheduled card",
                                        "body": "Notes",
                                    },
                                }
                            ],
                        }
                    }
                }
            }

        snapshot = fetch_project_snapshot(
            "totaldrop-app",
            1,
            "test-token",
            requester=fake_requester,
            exported_at="2026-11-16T11:00:00Z",
        )
        self.assertEqual(snapshot["active_item_count"], 2)
        self.assertEqual(snapshot["archived_item_count"], 1)
        self.assertEqual(
            [c["name"] for c in snapshot["columns"]],
            ["Todo", "In Progress", "Done", "(No Status)"],
        )
        md = render_markdown_summary(snapshot)
        self.assertIn(
            "| [totaldrop#29](https://github.com/totaldrop-app/totaldrop/issues/29) "
            "| Android: scan QR code\\u202e | OPEN | Now — November 2026 | Priority=High |",
            md,
        )
        self.assertNotIn("\\\\u202e", md)
        self.assertIn("Triage \\| unscheduled card", md)

    def test_missing_project_and_missing_token_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ORG_PROJECT_TOKEN": "", "GH_TOKEN": ""}, clear=False):
                rc = main(["--out-dir", tmp])
                self.assertEqual(rc, 1)
                self.assertEqual(list(Path(tmp).iterdir()), [])

        def empty_requester(query: str, variables: dict, token: str) -> dict:
            return {"organization": {"projectV2": None}}

        with self.assertRaises(ProjectExportError) as ctx:
            fetch_project_snapshot("totaldrop-app", 99, "tok", requester=empty_requester)
        self.assertEqual(ctx.exception.code, "project_not_found")

    def test_cli_writes_json_and_markdown_files_for_public_board(self) -> None:
        sample_snapshot = {
            "exported_at": "2026-11-16T11:00:00Z",
            "org": "totaldrop-app",
            "number": 1,
            "title": "TotalDrop Board",
            "short_description": "",
            "url": "https://github.com/orgs/totaldrop-app/projects/1",
            "public": True,
            "closed": False,
            "updated_at": "2026-11-16T10:00:00Z",
            "skipped_private": False,
            "views": [],
            "fields": [],
            "active_item_count": 0,
            "archived_item_count": 0,
            "columns": [{"name": "Todo", "count": 0, "items": []}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            summary_file = Path(tmp) / "summary.md"
            out_dir = Path(tmp) / "out"
            with (
                mock.patch.dict(os.environ, {"ORG_PROJECT_TOKEN": "tok"}, clear=False),
                mock.patch("export_project_board.fetch_project_snapshot", return_value=sample_snapshot),
            ):
                rc = main(["--out-dir", str(out_dir), "--summary-file", str(summary_file)])
            self.assertEqual(rc, 0)
            parsed = json.loads((out_dir / "project-1-snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["title"], "TotalDrop Board")
            self.assertIn("# TotalDrop Board", (out_dir / "project-1-snapshot.md").read_text(encoding="utf-8"))
            self.assertIn("# TotalDrop Board", summary_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
