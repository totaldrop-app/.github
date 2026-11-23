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
    ADD_PROJECT_ITEM_MUTATION,
    LINK_PROJECT_REPO_MUTATION,
    ORG_REPOS_QUERY,
    PROJECT_ITEMS_QUERY,
    PROJECT_META_QUERY,
    REPO_OPEN_ISSUES_QUERY,
    REPO_OPEN_PRS_QUERY,
    UPDATE_PROJECT_STATUS_MUTATION,
    ProjectExportError,
    escape_md_cell,
    extract_pr_linked_issues,
    fetch_project_snapshot,
    main,
    reconcile_project_board,
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

    def test_extract_pr_linked_issues_two_tier_and_cross_repo_guards(self) -> None:
        # Primary target (#29) suppresses secondary `Refs #541` follow-up mentions.
        pr_with_primary = {
            "title": "feat(android): show send QR code (#29)",
            "body": "Closes #29\nRefs #541 (follow-up privacy update)",
            "closingIssuesReferences": {"nodes": []},
        }
        self.assertEqual(
            extract_pr_linked_issues("totaldrop-app/totaldrop", pr_with_primary),
            {("totaldrop-app/totaldrop", 29)},
        )

        # Cross-repo reference in title (`totaldrop#30`) must NOT match local `#30`.
        pr_cross_title = {
            "title": "docs(profile): mark web-wasm shelved per totaldrop#30 (#7)",
            "body": "Closes #7",
            "closingIssuesReferences": {"nodes": []},
        }
        self.assertEqual(
            extract_pr_linked_issues("totaldrop-app/.github", pr_cross_title),
            {("totaldrop-app/.github", 7)},
        )

        # Fallback (`Part of #490` / `Refs #31`) activates when primary is empty.
        pr_fallback = {
            "title": "docs(decisions): translate decision 0016 to English",
            "body": "Part of #490",
            "closingIssuesReferences": {"nodes": []},
        }
        self.assertEqual(
            extract_pr_linked_issues("totaldrop-app/totaldrop", pr_fallback),
            {("totaldrop-app/totaldrop", 490)},
        )

        # Bare `#N` mentions in PR titles must NOT trigger false-positive issue links.
        pr_revert_title = {
            "title": "revert: undo #12",
            "body": "Reverts earlier change pending investigation.",
            "closingIssuesReferences": {"nodes": []},
        }
        self.assertEqual(
            extract_pr_linked_issues("totaldrop-app/totaldrop", pr_revert_title),
            set(),
        )
        pr_followup_title = {
            "title": "chore: follow-up to #40",
            "body": "",
            "closingIssuesReferences": {"nodes": []},
        }
        self.assertEqual(
            extract_pr_linked_issues("totaldrop-app/totaldrop", pr_followup_title),
            set(),
        )

        # GraphQL closingIssuesReferences works for both local and cross-repo issues.
        pr_graphql_refs = {
            "title": "feat: cross-repo fix",
            "body": "Refs #999",
            "closingIssuesReferences": {
                "nodes": [
                    {"number": 42, "repository": {"nameWithOwner": "totaldrop-app/totaldrop-core"}}
                ]
            },
        }
        self.assertEqual(
            extract_pr_linked_issues("totaldrop-app/totaldrop", pr_graphql_refs),
            {("totaldrop-app/totaldrop-core", 42)},
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
                                            "id": "I_29",
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

    def test_reconcile_moves_closed_ready_draft_and_onboards_modular_issues(self) -> None:
        mutations: list[tuple[str, dict]] = []

        def fake_requester(query: str, variables: dict, token: str) -> dict:
            if query == PROJECT_META_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "id": "PVT_1",
                            "number": 1,
                            "title": "totaldrop-kanban",
                            "shortDescription": "",
                            "url": "https://github.com/orgs/totaldrop-app/projects/1",
                            "public": True,
                            "closed": False,
                            "updatedAt": "2026-11-16T10:00:00Z",
                            "repositories": {
                                "nodes": [
                                    {"id": "R_MONO", "nameWithOwner": "totaldrop-app/totaldrop"}
                                ]
                            },
                            "views": {"nodes": []},
                            "fields": {
                                "nodes": [
                                    {
                                        "__typename": "ProjectV2SingleSelectField",
                                        "id": "F_STATUS",
                                        "name": "Status",
                                        "dataType": "SINGLE_SELECT",
                                        "options": [
                                            {"id": "OPT_BACKLOG", "name": "Backlog", "description": "", "color": "GRAY"},
                                            {"id": "OPT_READY", "name": "Ready", "description": "", "color": "BLUE"},
                                            {"id": "OPT_PROG", "name": "In progress", "description": "", "color": "YELLOW"},
                                            {"id": "OPT_REV", "name": "In review", "description": "", "color": "PURPLE"},
                                            {"id": "OPT_DONE", "name": "Done", "description": "", "color": "GREEN"},
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                }
            if query == PROJECT_ITEMS_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "PVTI_450",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-10T00:00:00Z",
                                        "updatedAt": "2026-11-16T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "In review",
                                                    "optionId": "OPT_REV",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "id": "I_450",
                                            "number": 450,
                                            "title": "Low-severity hardenings",
                                            "state": "CLOSED",
                                            "stateReason": "COMPLETED",
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/450",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": None,
                                            "labels": {"nodes": []},
                                            "assignees": {"nodes": []},
                                        },
                                    },
                                    {
                                        "id": "PVTI_32",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-01T00:00:00Z",
                                        "updatedAt": "2026-11-15T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "Backlog",
                                                    "optionId": "OPT_BACKLOG",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "id": "I_32",
                                            "number": 32,
                                            "title": "Direct path upgrade",
                                            "state": "OPEN",
                                            "stateReason": None,
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/32",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": None,
                                            "labels": {"nodes": []},
                                            "assignees": {"nodes": []},
                                        },
                                    },
                                    {
                                        "id": "PVTI_31",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-01T00:00:00Z",
                                        "updatedAt": "2026-11-15T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "Backlog",
                                                    "optionId": "OPT_BACKLOG",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "id": "I_31",
                                            "number": 31,
                                            "title": "Resume transfers",
                                            "state": "OPEN",
                                            "stateReason": None,
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/31",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": None,
                                            "labels": {"nodes": []},
                                            "assignees": {"nodes": []},
                                        },
                                    },
                                ],
                            }
                        }
                    }
                }
            if query == ORG_REPOS_QUERY:
                return {
                    "organization": {
                        "repositories": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "R_MONO",
                                    "name": "totaldrop",
                                    "nameWithOwner": "totaldrop-app/totaldrop",
                                    "isPrivate": False,
                                },
                                {
                                    "id": "R_SITE",
                                    "name": "totaldrop-site",
                                    "nameWithOwner": "totaldrop-app/totaldrop-site",
                                    "isPrivate": False,
                                },
                            ],
                        }
                    }
                }
            if query == REPO_OPEN_ISSUES_QUERY:
                if variables["name"] == "totaldrop":
                    return {
                        "repository": {
                            "issues": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {"id": "I_31", "number": 31, "title": "Resume transfers"},
                                    {"id": "I_32", "number": 32, "title": "Direct path upgrade"},
                                ],
                            }
                        }
                    }
                return {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [{"id": "I_SITE_5", "number": 5, "title": "Remove @mstfyrdmc"}],
                        }
                    }
                }
            if query == REPO_OPEN_PRS_QUERY:
                if variables["name"] == "totaldrop":
                    return {
                        "repository": {
                            "pullRequests": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "number": 546,
                                        "title": "feat: direct upgrade (#32)",
                                        "isDraft": False,
                                        "body": "",
                                        "closingIssuesReferences": {
                                            "nodes": [
                                                {
                                                    "number": 32,
                                                    "repository": {
                                                        "nameWithOwner": "totaldrop-app/totaldrop"
                                                    },
                                                }
                                            ]
                                        },
                                    },
                                    {
                                        "number": 499,
                                        "title": "feat: resume",
                                        "isDraft": True,
                                        "body": "Refs #31",
                                        "closingIssuesReferences": {"nodes": []},
                                    },
                                ],
                            }
                        }
                    }
                return {
                    "repository": {
                        "pullRequests": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "number": 6,
                                    "title": "fix(site): remove Mustafa (#5)",
                                    "isDraft": False,
                                    "body": "Closes #5",
                                    "closingIssuesReferences": {"nodes": []},
                                }
                            ],
                        }
                    }
                }
            if query == LINK_PROJECT_REPO_MUTATION:
                mutations.append(("link_repo", variables))
                return {"linkProjectV2ToRepository": {"repository": {"nameWithOwner": "totaldrop-app/totaldrop-site"}}}
            if query == ADD_PROJECT_ITEM_MUTATION:
                mutations.append(("add", variables))
                return {"addProjectV2ItemById": {"item": {"id": "PVTI_NEW_SITE_5"}}}
            if query == UPDATE_PROJECT_STATUS_MUTATION:
                mutations.append(("update", variables))
                return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": variables["itemId"]}}}
            raise AssertionError(f"Unexpected query: {query}")

        result = reconcile_project_board(
            "totaldrop-app",
            1,
            "write-token",
            repo_read_token="public-token",
            post_add_settle_seconds=0.0,
            requester=fake_requester,
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["applied_status_update_count"], 3)
        self.assertEqual(result["applied_addition_count"], 1)
        self.assertEqual(result["newly_linked_repositories"], ["totaldrop-app/totaldrop-site"])
        self.assertEqual(
            mutations,
            [
                ("link_repo", {"projectId": "PVT_1", "repositoryId": "R_SITE"}),
                ("update", {"projectId": "PVT_1", "itemId": "PVTI_450", "fieldId": "F_STATUS", "optionId": "OPT_DONE"}),
                ("update", {"projectId": "PVT_1", "itemId": "PVTI_32", "fieldId": "F_STATUS", "optionId": "OPT_REV"}),
                ("update", {"projectId": "PVT_1", "itemId": "PVTI_31", "fieldId": "F_STATUS", "optionId": "OPT_PROG"}),
                ("add", {"projectId": "PVT_1", "contentId": "I_SITE_5"}),
                ("update", {"projectId": "PVT_1", "itemId": "PVTI_NEW_SITE_5", "fieldId": "F_STATUS", "optionId": "OPT_REV"}),
            ],
        )

    def test_reconcile_degrades_cleanly_when_token_is_read_only(self) -> None:
        def fake_requester(query: str, variables: dict, token: str) -> dict:
            if query == PROJECT_META_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "id": "PVT_1",
                            "number": 1,
                            "title": "totaldrop-kanban",
                            "shortDescription": "",
                            "url": "https://github.com/orgs/totaldrop-app/projects/1",
                            "public": True,
                            "closed": False,
                            "updatedAt": "2026-11-16T10:00:00Z",
                            "views": {"nodes": []},
                            "fields": {
                                "nodes": [
                                    {
                                        "__typename": "ProjectV2SingleSelectField",
                                        "id": "F_STATUS",
                                        "name": "Status",
                                        "dataType": "SINGLE_SELECT",
                                        "options": [
                                            {"id": "OPT_BACKLOG", "name": "Backlog", "description": "", "color": "GRAY"},
                                            {"id": "OPT_PROG", "name": "In progress", "description": "", "color": "YELLOW"},
                                            {"id": "OPT_REV", "name": "In review", "description": "", "color": "PURPLE"},
                                            {"id": "OPT_DONE", "name": "Done", "description": "", "color": "GREEN"},
                                        ],
                                    }
                                ]
                            },
                        }
                    }
                }
            if query == PROJECT_ITEMS_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [],
                            }
                        }
                    }
                }
            if query == ORG_REPOS_QUERY:
                return {
                    "organization": {
                        "repositories": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [{"name": ".github", "nameWithOwner": "totaldrop-app/.github"}],
                        }
                    }
                }
            if query == REPO_OPEN_ISSUES_QUERY:
                return {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [{"id": "I_GH_5", "number": 5, "title": "Kanban workflow"}],
                        }
                    }
                }
            if query == REPO_OPEN_PRS_QUERY:
                return {
                    "repository": {
                        "pullRequests": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            raise ProjectExportError("forbidden", "Resource not accessible by personal access token")

        result = reconcile_project_board("totaldrop-app", 1, "ro-token", requester=fake_requester)
        self.assertEqual(result["status"], "read_only_token")
        self.assertEqual(result["planned_addition_count"], 1)

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

    @staticmethod
    def _sample_project_meta(*, is_public: bool = True, linked_repos: list[dict] | None = None) -> dict:
        return {
            "organization": {
                "projectV2": {
                    "id": "PVT_1",
                    "number": 1,
                    "title": "totaldrop-kanban",
                    "shortDescription": "",
                    "url": "https://github.com/orgs/totaldrop-app/projects/1",
                    "public": is_public,
                    "closed": False,
                    "updatedAt": "2026-11-16T10:00:00Z",
                    "repositories": {"nodes": linked_repos or []},
                    "views": {"nodes": []},
                    "fields": {
                        "nodes": [
                            {
                                "__typename": "ProjectV2SingleSelectField",
                                "id": "F_STATUS",
                                "name": "Status",
                                "dataType": "SINGLE_SELECT",
                                "options": [
                                    {"id": "OPT_BACKLOG", "name": "Backlog", "description": "", "color": "GRAY"},
                                    {"id": "OPT_READY", "name": "Ready", "description": "", "color": "BLUE"},
                                    {"id": "OPT_PROG", "name": "In progress", "description": "", "color": "YELLOW"},
                                    {"id": "OPT_REV", "name": "In review", "description": "", "color": "PURPLE"},
                                    {"id": "OPT_DONE", "name": "Done", "description": "", "color": "GREEN"},
                                ],
                            }
                        ]
                    },
                }
            }
        }

    def test_org_repos_query_restricts_to_public_and_skips_private_nodes(self) -> None:
        self.assertIn("privacy: PUBLIC", ORG_REPOS_QUERY)
        self.assertIn("isPrivate", ORG_REPOS_QUERY)

        queried_repos: list[str] = []
        linked_repo_ids: list[str] = []

        def fake_requester(query: str, variables: dict, token: str) -> dict:
            if query == PROJECT_META_QUERY:
                return self._sample_project_meta(is_public=True)
            if query == PROJECT_ITEMS_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
                        }
                    }
                }
            if query == ORG_REPOS_QUERY:
                return {
                    "organization": {
                        "repositories": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "R_PUB",
                                    "name": "totaldrop",
                                    "nameWithOwner": "totaldrop-app/totaldrop",
                                    "isPrivate": False,
                                },
                                {
                                    "id": "R_SECRET",
                                    "name": "internal-ops",
                                    "nameWithOwner": "totaldrop-app/internal-ops",
                                    "isPrivate": True,
                                },
                            ],
                        }
                    }
                }
            if query == REPO_OPEN_ISSUES_QUERY:
                queried_repos.append(variables["name"])
                return {
                    "repository": {
                        "issues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
                    }
                }
            if query == REPO_OPEN_PRS_QUERY:
                queried_repos.append(variables["name"])
                return {
                    "repository": {
                        "pullRequests": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            if query == LINK_PROJECT_REPO_MUTATION:
                linked_repo_ids.append(variables["repositoryId"])
                return {"linkProjectV2ToRepository": {"repository": {"nameWithOwner": "totaldrop-app/totaldrop"}}}
            raise AssertionError(f"Unexpected query: {query}")

        result = reconcile_project_board(
            "totaldrop-app",
            1,
            "write-token",
            post_add_settle_seconds=0.0,
            requester=fake_requester,
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(queried_repos, ["totaldrop", "totaldrop"])
        self.assertEqual(linked_repo_ids, ["R_PUB"])
        self.assertEqual(result["newly_linked_repositories"], ["totaldrop-app/totaldrop"])

    def test_reconcile_private_project_fails_closed_before_mutations(self) -> None:
        calls: list[str] = []

        def fake_requester(query: str, variables: dict, token: str) -> dict:
            calls.append(query)
            self.assertEqual(query, PROJECT_META_QUERY)
            return self._sample_project_meta(is_public=False)

        result = reconcile_project_board(
            "totaldrop-app",
            1,
            "write-token",
            post_add_settle_seconds=0.0,
            requester=fake_requester,
        )
        self.assertEqual(calls, [PROJECT_META_QUERY])
        self.assertEqual(result["status"], "skipped_private")
        self.assertEqual(result["applied_status_update_count"], 0)
        self.assertEqual(result["applied_addition_count"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            summary_file = Path(tmp) / "summary.md"
            out_dir = Path(tmp) / "out"
            with (
                mock.patch.dict(os.environ, {"ORG_PROJECT_TOKEN": "tok"}, clear=False),
                mock.patch("export_project_board.graphql_request", side_effect=fake_requester),
            ):
                rc = main(
                    ["--reconcile", "--out-dir", str(out_dir), "--summary-file", str(summary_file)]
                )
            self.assertEqual(rc, 0)
            self.assertFalse(out_dir.exists())
            self.assertIn("Snapshot Skipped", summary_file.read_text(encoding="utf-8"))

    def test_reconcile_re_raises_non_forbidden_repo_link_errors(self) -> None:
        def make_requester(link_error_code: str):
            def fake_requester(query: str, variables: dict, token: str) -> dict:
                if query == PROJECT_META_QUERY:
                    return self._sample_project_meta(is_public=True)
                if query == PROJECT_ITEMS_QUERY:
                    return {
                        "organization": {
                            "projectV2": {
                                "items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
                            }
                        }
                    }
                if query == ORG_REPOS_QUERY:
                    return {
                        "organization": {
                            "repositories": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "R_1",
                                        "name": "totaldrop",
                                        "nameWithOwner": "totaldrop-app/totaldrop",
                                        "isPrivate": False,
                                    }
                                ],
                            }
                        }
                    }
                if query == REPO_OPEN_ISSUES_QUERY:
                    return {
                        "repository": {
                            "issues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
                        }
                    }
                if query == REPO_OPEN_PRS_QUERY:
                    return {
                        "repository": {
                            "pullRequests": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [],
                            }
                        }
                    }
                if query == LINK_PROJECT_REPO_MUTATION:
                    raise ProjectExportError(link_error_code, f"boom: {link_error_code}")
                raise AssertionError(f"Unexpected query: {query}")

            return fake_requester

        with self.assertRaises(ProjectExportError) as ctx:
            reconcile_project_board(
                "totaldrop-app",
                1,
                "write-token",
                post_add_settle_seconds=0.0,
                requester=make_requester("network_error"),
            )
        self.assertEqual(ctx.exception.code, "network_error")

        res = reconcile_project_board(
            "totaldrop-app",
            1,
            "write-token",
            post_add_settle_seconds=0.0,
            requester=make_requester("forbidden"),
        )
        self.assertEqual(res["status"], "applied")
        self.assertIn("boom: forbidden", res["repo_link_warning"])

    def test_reconcile_raises_on_repo_issue_and_pr_pagination_limits(self) -> None:
        for overflow_stage in ("repos", "issues", "prs"):
            with self.subTest(overflow_stage=overflow_stage):
                def fake_requester(query: str, variables: dict, token: str) -> dict:
                    if query == PROJECT_META_QUERY:
                        return self._sample_project_meta(is_public=True)
                    if query == PROJECT_ITEMS_QUERY:
                        return {
                            "organization": {
                                "projectV2": {
                                    "items": {
                                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                                        "nodes": [],
                                    }
                                }
                            }
                        }
                    if query == ORG_REPOS_QUERY:
                        has_next = overflow_stage == "repos"
                        return {
                            "organization": {
                                "repositories": {
                                    "pageInfo": {
                                        "hasNextPage": has_next,
                                        "endCursor": "CUR" if has_next else None,
                                    },
                                    "nodes": [
                                        {
                                            "id": "R_1",
                                            "name": "totaldrop",
                                            "nameWithOwner": "totaldrop-app/totaldrop",
                                            "isPrivate": False,
                                        }
                                    ],
                                }
                            }
                        }
                    if query == REPO_OPEN_ISSUES_QUERY:
                        has_next = overflow_stage == "issues"
                        return {
                            "repository": {
                                "issues": {
                                    "pageInfo": {
                                        "hasNextPage": has_next,
                                        "endCursor": "CUR" if has_next else None,
                                    },
                                    "nodes": [],
                                }
                            }
                        }
                    if query == REPO_OPEN_PRS_QUERY:
                        has_next = overflow_stage == "prs"
                        return {
                            "repository": {
                                "pullRequests": {
                                    "pageInfo": {
                                        "hasNextPage": has_next,
                                        "endCursor": "CUR" if has_next else None,
                                    },
                                    "nodes": [],
                                }
                            }
                        }
                    raise AssertionError(f"Unexpected query: {query}")

                with mock.patch("export_project_board.MAX_REPO_PAGES", 2):
                    with self.assertRaises(ProjectExportError) as ctx:
                        reconcile_project_board(
                            "totaldrop-app",
                            1,
                            "write-token",
                            post_add_settle_seconds=0.0,
                            requester=fake_requester,
                        )
                self.assertEqual(ctx.exception.code, "pagination_limit_exceeded")

    def test_reconcile_moves_unlinked_in_review_issue_back_to_backlog(self) -> None:
        updates: list[dict] = []

        def fake_requester(query: str, variables: dict, token: str) -> dict:
            if query == PROJECT_META_QUERY:
                return self._sample_project_meta(
                    is_public=True,
                    linked_repos=[{"id": "R_MONO", "nameWithOwner": "totaldrop-app/totaldrop"}],
                )
            if query == PROJECT_ITEMS_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "PVTI_STALE_REV",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-01T00:00:00Z",
                                        "updatedAt": "2026-11-15T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "In review",
                                                    "optionId": "OPT_REV",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "id": "I_77",
                                            "number": 77,
                                            "title": "PR closed without closing issue",
                                            "state": "OPEN",
                                            "stateReason": None,
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/77",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": None,
                                            "labels": {"nodes": []},
                                            "assignees": {"nodes": []},
                                        },
                                    },
                                    {
                                        "id": "PVTI_MANUAL_PROG",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-01T00:00:00Z",
                                        "updatedAt": "2026-11-15T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "In progress",
                                                    "optionId": "OPT_PROG",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "id": "I_78",
                                            "number": 78,
                                            "title": "Active local work without PR yet",
                                            "state": "OPEN",
                                            "stateReason": None,
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/78",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": None,
                                            "labels": {"nodes": []},
                                            "assignees": {"nodes": []},
                                        },
                                    },
                                ],
                            }
                        }
                    }
                }
            if query == ORG_REPOS_QUERY:
                return {
                    "organization": {
                        "repositories": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "R_MONO",
                                    "name": "totaldrop",
                                    "nameWithOwner": "totaldrop-app/totaldrop",
                                    "isPrivate": False,
                                }
                            ],
                        }
                    }
                }
            if query == REPO_OPEN_ISSUES_QUERY:
                return {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {"id": "I_77", "number": 77, "title": "PR closed without closing issue"},
                                {"id": "I_78", "number": 78, "title": "Active local work without PR yet"},
                            ],
                        }
                    }
                }
            if query == REPO_OPEN_PRS_QUERY:
                return {
                    "repository": {
                        "pullRequests": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            if query == UPDATE_PROJECT_STATUS_MUTATION:
                updates.append(variables)
                return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": variables["itemId"]}}}
            raise AssertionError(f"Unexpected query: {query}")

        result = reconcile_project_board(
            "totaldrop-app",
            1,
            "write-token",
            post_add_settle_seconds=0.0,
            requester=fake_requester,
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(
            updates,
            [
                {
                    "projectId": "PVT_1",
                    "itemId": "PVTI_STALE_REV",
                    "fieldId": "F_STATUS",
                    "optionId": "OPT_BACKLOG",
                }
            ],
        )
        self.assertEqual(
            result["status_updates"],
            [
                {
                    "ref": "totaldrop-app/totaldrop#77",
                    "from": "In review",
                    "to": "Backlog",
                    "reason": "open issue no longer has a linked open PR",
                }
            ],
        )

    def test_reconcile_read_only_token_reports_partial_writes_and_repo_link_warning(self) -> None:
        update_calls = 0

        def fake_requester(query: str, variables: dict, token: str) -> dict:
            nonlocal update_calls
            if query == PROJECT_META_QUERY:
                return self._sample_project_meta(is_public=True)
            if query == PROJECT_ITEMS_QUERY:
                return {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "PVTI_1",
                                        "type": "ISSUE",
                                        "isArchived": False,
                                        "createdAt": "2026-11-01T00:00:00Z",
                                        "updatedAt": "2026-11-15T00:00:00Z",
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                                    "name": "Backlog",
                                                    "optionId": "OPT_BACKLOG",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                        "content": {
                                            "__typename": "Issue",
                                            "id": "I_1",
                                            "number": 1,
                                            "title": "Closed item",
                                            "state": "CLOSED",
                                            "stateReason": "COMPLETED",
                                            "url": "https://github.com/totaldrop-app/totaldrop/issues/1",
                                            "repository": {"nameWithOwner": "totaldrop-app/totaldrop"},
                                            "milestone": None,
                                            "labels": {"nodes": []},
                                            "assignees": {"nodes": []},
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            if query == ORG_REPOS_QUERY:
                return {
                    "organization": {
                        "repositories": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "R_1",
                                    "name": "totaldrop",
                                    "nameWithOwner": "totaldrop-app/totaldrop",
                                    "isPrivate": False,
                                }
                            ],
                        }
                    }
                }
            if query == REPO_OPEN_ISSUES_QUERY:
                return {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [{"id": "I_2", "number": 2, "title": "New open issue"}],
                        }
                    }
                }
            if query == REPO_OPEN_PRS_QUERY:
                return {
                    "repository": {
                        "pullRequests": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            if query == LINK_PROJECT_REPO_MUTATION:
                raise ProjectExportError("forbidden", "Cannot link repo")
            if query == UPDATE_PROJECT_STATUS_MUTATION:
                update_calls += 1
                return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": variables["itemId"]}}}
            if query == ADD_PROJECT_ITEM_MUTATION:
                raise ProjectExportError("forbidden", "Cannot add item")
            raise AssertionError(f"Unexpected query: {query}")

        result = reconcile_project_board(
            "totaldrop-app",
            1,
            "partial-token",
            post_add_settle_seconds=0.0,
            requester=fake_requester,
        )
        self.assertEqual(result["status"], "read_only_token")
        self.assertEqual(update_calls, 1)
        self.assertEqual(len(result["status_updates"]), 1)
        self.assertEqual(result["status_updates"][0]["ref"], "totaldrop-app/totaldrop#1")
        self.assertEqual(result["added_items"], [])
        self.assertEqual(result["repo_link_warning"], "Cannot link repo")

    def test_render_markdown_summary_escapes_title_and_short_description(self) -> None:
        snapshot = {
            "exported_at": "2026-11-16T11:00:00Z",
            "org": "totaldrop-app",
            "number": 1,
            "title": "TotalDrop | Roadmap\nLine2",
            "short_description": "Track | issues\tacross repos",
            "url": "https://github.com/orgs/totaldrop-app/projects/1",
            "public": True,
            "closed": False,
            "updated_at": "2026-11-16T10:00:00Z",
            "skipped_private": False,
            "views": [],
            "fields": [],
            "active_item_count": 0,
            "archived_item_count": 0,
            "columns": [],
        }
        md = render_markdown_summary(snapshot)
        self.assertIn("# TotalDrop \\| Roadmap Line2 (Project #1)", md)
        self.assertIn("- **Description:** Track \\| issues across repos", md)


if __name__ == "__main__":
    unittest.main()
