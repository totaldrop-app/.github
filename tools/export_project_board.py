#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The TotalDrop Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export and optionally reconcile a public GitHub Organization ProjectV2 Kanban board."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable
import urllib.error
import urllib.request

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
MAX_ITEM_PAGES = 50
MAX_REPO_PAGES = 20

BIDI_CODEPOINTS = frozenset(
    {
        0x061C,  # ARABIC LETTER MARK
        0x200E,  # LEFT-TO-RIGHT MARK
        0x200F,  # RIGHT-TO-LEFT MARK
        0x202A,  # LEFT-TO-RIGHT EMBEDDING
        0x202B,  # RIGHT-TO-LEFT EMBEDDING
        0x202C,  # POP DIRECTIONAL FORMATTING
        0x202D,  # LEFT-TO-RIGHT OVERRIDE
        0x202E,  # RIGHT-TO-LEFT OVERRIDE
        0x2066,  # LEFT-TO-RIGHT ISOLATE
        0x2067,  # RIGHT-TO-LEFT ISOLATE
        0x2068,  # FIRST STRONG ISOLATE
        0x2069,  # POP DIRECTIONAL ISOLATE
    }
)

TITLE_ISSUE_RE = re.compile(r"(?<![A-Za-z0-9_./-])#(\d+)\b")
PRIMARY_BODY_ISSUE_RE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|kapatır):?[ \t]+"
    r"(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)|(?<![A-Za-z0-9_./-])#(\d+))\b"
)
FALLBACK_BODY_ISSUE_RE = re.compile(
    r"(?i)\b(?:refs?|part[ \t]+of):?[ \t]+"
    r"(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)|(?<![A-Za-z0-9_./-])#(\d+))\b"
)

PROJECT_META_QUERY = """
query($org: String!, $number: Int!) {
  organization(login: $org) {
    projectV2(number: $number) {
      id
      number
      title
      shortDescription
      url
      public
      closed
      updatedAt
      views(first: 20) {
        nodes {
          name
          number
          layout
          filter
        }
      }
      fields(first: 50) {
        nodes {
          __typename
          ... on ProjectV2Field {
            id
            name
            dataType
          }
          ... on ProjectV2SingleSelectField {
            id
            name
            dataType
            options {
              id
              name
              description
              color
            }
          }
          ... on ProjectV2IterationField {
            id
            name
            dataType
            configuration {
              iterations {
                id
                title
                startDate
                duration
              }
            }
          }
        }
      }
    }
  }
}
"""

PROJECT_ITEMS_QUERY = """
query($org: String!, $number: Int!, $after: String) {
  organization(login: $org) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          type
          isArchived
          createdAt
          updatedAt
          fieldValues(first: 25) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldTextValue {
                text
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldNumberValue {
                number
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldDateValue {
                date
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                optionId
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldIterationValue {
                title
                startDate
                duration
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
          content {
            __typename
            ... on DraftIssue {
              title
              body
            }
            ... on Issue {
              id
              number
              title
              state
              stateReason
              url
              repository { nameWithOwner }
              milestone { title }
              labels(first: 15) { nodes { name } }
              assignees(first: 10) { nodes { login } }
            }
            ... on PullRequest {
              id
              number
              title
              state
              isDraft
              url
              repository { nameWithOwner }
              reviewDecision
            }
          }
        }
      }
    }
  }
}
"""

ORG_REPOS_QUERY = """
query($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after, isArchived: false) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        nameWithOwner
      }
    }
  }
}
"""

REPO_OPEN_ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, after: $after) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        id
        number
        title
      }
    }
  }
}
"""

REPO_OPEN_PRS_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $after) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        isDraft
        body
        closingIssuesReferences(first: 20) {
          nodes {
            number
            repository { nameWithOwner }
          }
        }
      }
    }
  }
}
"""

ADD_PROJECT_ITEM_MUTATION = """
mutation($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
    item {
      id
    }
  }
}
"""

UPDATE_PROJECT_STATUS_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(
    input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: {singleSelectOptionId: $optionId}
    }
  ) {
    projectV2Item {
      id
    }
  }
}
"""


class ProjectExportError(RuntimeError):
    """Raised when the GitHub ProjectV2 GraphQL query fails or returns invalid data."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sanitize_text(
    value: str | None,
    *,
    collapse_whitespace: bool = False,
    escape_markdown_table: bool = False,
) -> str:
    """Escape control, Unicode Bidi, and optional Markdown characters in a single pass."""
    if not value:
        return ""
    out: list[str] = []
    prev_space = False
    for ch in value:
        cp = ord(ch)
        if cp in BIDI_CODEPOINTS:
            out.append(f"\\u{cp:04x}")
            prev_space = False
        elif ch == "\\":
            out.append("\\\\")
            prev_space = False
        elif escape_markdown_table and ch == "|":
            out.append("\\|")
            prev_space = False
        elif ch in (" ", "\n", "\r", "\t") and collapse_whitespace:
            if not prev_space:
                out.append(" ")
                prev_space = True
        elif ch in ("\n", "\t") and not collapse_whitespace:
            out.append(ch)
            prev_space = False
        elif cp < 0x20 or (0x7F <= cp <= 0x9F):
            out.append(f"\\x{cp:02x}")
            prev_space = False
        else:
            out.append(ch)
            prev_space = False
    result = "".join(out)
    return result.strip(" ") if collapse_whitespace else result


def escape_md_cell(value: str | None) -> str:
    """Sanitize a string for safe inclusion inside a GitHub Markdown table cell."""
    return sanitize_text(value, collapse_whitespace=True, escape_markdown_table=True)


def graphql_request(
    query: str,
    variables: dict[str, Any],
    token: str,
    endpoint: str = GRAPHQL_ENDPOINT,
) -> dict[str, Any]:
    """Execute a single authenticated GitHub GraphQL POST request."""
    if not token:
        raise ProjectExportError("missing_token", "ORG_PROJECT_TOKEN is empty or unset.")

    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "totaldrop-project-board-exporter/1.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        code = "forbidden" if exc.code == 403 else "http_error"
        raise ProjectExportError(
            code,
            f"GitHub GraphQL HTTP {exc.code}: {sanitize_text(exc.reason, collapse_whitespace=True)}",
        ) from None
    except urllib.error.URLError as exc:
        raise ProjectExportError(
            "network_error",
            f"GitHub GraphQL network error: {sanitize_text(str(exc.reason), collapse_whitespace=True)}",
        ) from None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectExportError("invalid_json", f"Invalid JSON from GraphQL endpoint: {exc}") from None

    if not isinstance(parsed, dict):
        raise ProjectExportError("invalid_payload", "GraphQL response root must be a JSON object.")

    errors = parsed.get("errors")
    if errors:
        first_msg = ""
        err_type = ""
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            first_msg = str(errors[0].get("message", "GraphQL error"))
            err_type = str(errors[0].get("type", "")).upper()
        else:
            first_msg = str(errors)
        lowered = first_msg.lower()
        is_forbidden = (
            err_type in ("FORBIDDEN", "INSUFFICIENT_SCOPES")
            or "resource not accessible" in lowered
            or "forbidden" in lowered
            or "insufficient" in lowered
        )
        raise ProjectExportError(
            "forbidden" if is_forbidden else "graphql_error",
            f"GitHub GraphQL error: {sanitize_text(first_msg, collapse_whitespace=True)}",
        )

    data = parsed.get("data")
    if not isinstance(data, dict):
        raise ProjectExportError("missing_data", "GraphQL response did not contain a data object.")
    return data


def _extract_field_values(raw_values: list[dict[str, Any]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in raw_values:
        if not isinstance(node, dict):
            continue
        field_info = node.get("field")
        if not isinstance(field_info, dict):
            continue
        field_name = sanitize_text(field_info.get("name"), collapse_whitespace=True)
        if not field_name or field_name == "Title":
            continue
        typename = node.get("__typename")
        if typename == "ProjectV2ItemFieldSingleSelectValue":
            val = sanitize_text(node.get("name"), collapse_whitespace=True)
        elif typename == "ProjectV2ItemFieldTextValue":
            val = sanitize_text(node.get("text"), collapse_whitespace=True)
        elif typename == "ProjectV2ItemFieldNumberValue":
            num = node.get("number")
            val = "" if num is None else str(num)
        elif typename == "ProjectV2ItemFieldDateValue":
            val = sanitize_text(node.get("date"), collapse_whitespace=True)
        elif typename == "ProjectV2ItemFieldIterationValue":
            val = sanitize_text(node.get("title"), collapse_whitespace=True)
        else:
            continue
        if val:
            values[field_name] = val
    return values


def _normalize_item(node: dict[str, Any]) -> dict[str, Any]:
    field_nodes = ((node.get("fieldValues") or {}).get("nodes")) or []
    fields = _extract_field_values(field_nodes)
    status = fields.get("Status", "(No Status)")

    content = node.get("content") or {}
    kind = sanitize_text(content.get("__typename") or node.get("type"), collapse_whitespace=True)

    normalized_content: dict[str, Any] = {"kind": kind}
    if kind == "Issue":
        repo = ((content.get("repository") or {}).get("nameWithOwner")) or ""
        milestone = ((content.get("milestone") or {}).get("title")) or ""
        labels = [
            sanitize_text(lbl.get("name"), collapse_whitespace=True)
            for lbl in (((content.get("labels") or {}).get("nodes")) or [])
            if isinstance(lbl, dict) and lbl.get("name")
        ]
        assignees = [
            sanitize_text(usr.get("login"), collapse_whitespace=True)
            for usr in (((content.get("assignees") or {}).get("nodes")) or [])
            if isinstance(usr, dict) and usr.get("login")
        ]
        normalized_content.update(
            {
                "node_id": sanitize_text(content.get("id"), collapse_whitespace=True),
                "repo": sanitize_text(repo, collapse_whitespace=True),
                "number": content.get("number"),
                "title": sanitize_text(content.get("title"), collapse_whitespace=True),
                "state": sanitize_text(content.get("state"), collapse_whitespace=True),
                "state_reason": sanitize_text(content.get("stateReason"), collapse_whitespace=True),
                "url": sanitize_text(content.get("url"), collapse_whitespace=True),
                "milestone": sanitize_text(milestone, collapse_whitespace=True),
                "labels": labels,
                "assignees": assignees,
            }
        )
    elif kind == "PullRequest":
        repo = ((content.get("repository") or {}).get("nameWithOwner")) or ""
        normalized_content.update(
            {
                "node_id": sanitize_text(content.get("id"), collapse_whitespace=True),
                "repo": sanitize_text(repo, collapse_whitespace=True),
                "number": content.get("number"),
                "title": sanitize_text(content.get("title"), collapse_whitespace=True),
                "state": sanitize_text(content.get("state"), collapse_whitespace=True),
                "is_draft": bool(content.get("isDraft", False)),
                "review_decision": sanitize_text(
                    content.get("reviewDecision"), collapse_whitespace=True
                ),
                "url": sanitize_text(content.get("url"), collapse_whitespace=True),
            }
        )
    elif kind == "DraftIssue":
        normalized_content.update(
            {
                "title": sanitize_text(content.get("title"), collapse_whitespace=True),
                "body": sanitize_text(content.get("body"), collapse_whitespace=False),
                "state": "DRAFT_CARD",
            }
        )
    else:
        normalized_content.update({"title": "(Redacted or unsupported item)", "state": "UNKNOWN"})

    return {
        "id": sanitize_text(node.get("id"), collapse_whitespace=True),
        "type": sanitize_text(node.get("type"), collapse_whitespace=True),
        "is_archived": bool(node.get("isArchived", False)),
        "created_at": sanitize_text(node.get("createdAt"), collapse_whitespace=True),
        "updated_at": sanitize_text(node.get("updatedAt"), collapse_whitespace=True),
        "status": status,
        "fields": fields,
        "content": normalized_content,
    }


def extract_pr_linked_issues(
    repo_full_name: str, pr_node: dict[str, Any]
) -> set[tuple[str, int]]:
    """Extract target (repo_full_name, issue_number) pairs linked to an open PR.

    Uses a two-tier rule:
    1. Primary targets: GraphQL `closingIssuesReferences`, standalone `#N` in the PR title,
       and `Closes`/`Fixes`/`Resolves` directives in the PR body.
    2. Fallback targets (only when primary is empty): `Refs #N` / `Part of #N` in the PR body,
       avoiding false positives on follow-up tracking issues mentioned in PRs that already
       close their own primary issue.
    """
    primary: set[tuple[str, int]] = set()
    closing_nodes = ((pr_node.get("closingIssuesReferences") or {}).get("nodes")) or []
    for ref in closing_nodes:
        if not isinstance(ref, dict):
            continue
        num = ref.get("number")
        ref_repo = ((ref.get("repository") or {}).get("nameWithOwner")) or repo_full_name
        if isinstance(num, int):
            primary.add((str(ref_repo), num))

    title = str(pr_node.get("title") or "")
    for match_num in TITLE_ISSUE_RE.findall(title):
        primary.add((repo_full_name, int(match_num)))

    body = str(pr_node.get("body") or "")
    for cross_repo, cross_num, local_num in PRIMARY_BODY_ISSUE_RE.findall(body):
        if cross_repo and cross_num:
            primary.add((cross_repo, int(cross_num)))
        elif local_num:
            primary.add((repo_full_name, int(local_num)))

    if primary:
        return primary

    fallback: set[tuple[str, int]] = set()
    for cross_repo, cross_num, local_num in FALLBACK_BODY_ISSUE_RE.findall(body):
        if cross_repo and cross_num:
            fallback.add((cross_repo, int(cross_num)))
        elif local_num:
            fallback.add((repo_full_name, int(local_num)))
    return fallback


def _fetch_paginated_items(
    org: str,
    number: int,
    token: str,
    requester: Callable[[str, dict[str, Any], str], dict[str, Any]],
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(MAX_ITEM_PAGES):
        page_data = requester(
            PROJECT_ITEMS_QUERY,
            {"org": org, "number": number, "after": cursor},
            token,
        )
        p_node = ((page_data.get("organization") or {}).get("projectV2")) or {}
        items_conn = p_node.get("items") or {}
        for raw_item in items_conn.get("nodes") or []:
            if isinstance(raw_item, dict):
                all_items.append(_normalize_item(raw_item))
        page_info = items_conn.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    else:
        raise ProjectExportError(
            "pagination_limit_exceeded",
            f"Exceeded {MAX_ITEM_PAGES} pages while exporting Project #{number}.",
        )
    return all_items


def _fetch_org_repo_state(
    org: str,
    read_token: str,
    requester: Callable[[str, dict[str, Any], str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[tuple[str, int]], set[tuple[str, int]]]:
    """Return all open issues across non-archived org repos plus ready/draft PR issue sets."""
    repos: list[tuple[str, str]] = []
    cursor: str | None = None
    for _ in range(MAX_REPO_PAGES):
        data = requester(ORG_REPOS_QUERY, {"org": org, "after": cursor}, read_token)
        repos_conn = ((data.get("organization") or {}).get("repositories")) or {}
        for rnode in repos_conn.get("nodes") or []:
            if isinstance(rnode, dict) and rnode.get("name") and rnode.get("nameWithOwner"):
                repos.append((str(rnode["name"]), str(rnode["nameWithOwner"])))
        pinfo = repos_conn.get("pageInfo") or {}
        if not pinfo.get("hasNextPage") or not pinfo.get("endCursor"):
            break
        cursor = str(pinfo["endCursor"])

    open_issues: list[dict[str, Any]] = []
    ready_linked: set[tuple[str, int]] = set()
    draft_linked: set[tuple[str, int]] = set()

    for repo_name, repo_full in sorted(repos, key=lambda pair: pair[1]):
        icursor: str | None = None
        for _ in range(MAX_REPO_PAGES):
            idata = requester(
                REPO_OPEN_ISSUES_QUERY,
                {"owner": org, "name": repo_name, "after": icursor},
                read_token,
            )
            iconn = ((idata.get("repository") or {}).get("issues")) or {}
            for inode in iconn.get("nodes") or []:
                if isinstance(inode, dict) and isinstance(inode.get("number"), int) and inode.get("id"):
                    open_issues.append(
                        {
                            "repo": sanitize_text(repo_full, collapse_whitespace=True),
                            "number": inode["number"],
                            "node_id": sanitize_text(str(inode["id"]), collapse_whitespace=True),
                            "title": sanitize_text(inode.get("title"), collapse_whitespace=True),
                        }
                    )
            ipinfo = iconn.get("pageInfo") or {}
            if not ipinfo.get("hasNextPage") or not ipinfo.get("endCursor"):
                break
            icursor = str(ipinfo["endCursor"])

        pcursor: str | None = None
        for _ in range(MAX_REPO_PAGES):
            pdata = requester(
                REPO_OPEN_PRS_QUERY,
                {"owner": org, "name": repo_name, "after": pcursor},
                read_token,
            )
            pconn = ((pdata.get("repository") or {}).get("pullRequests")) or {}
            for pr_node in pconn.get("nodes") or []:
                if not isinstance(pr_node, dict):
                    continue
                targets = extract_pr_linked_issues(repo_full, pr_node)
                if bool(pr_node.get("isDraft", False)):
                    draft_linked.update(targets)
                else:
                    ready_linked.update(targets)
            ppinfo = pconn.get("pageInfo") or {}
            if not ppinfo.get("hasNextPage") or not ppinfo.get("endCursor"):
                break
            pcursor = str(ppinfo["endCursor"])

    return open_issues, ready_linked, draft_linked - ready_linked


def _find_option_id(option_map: dict[str, tuple[str, str]], target_label: str) -> tuple[str, str]:
    key = target_label.strip().lower()
    if key not in option_map:
        raise ProjectExportError(
            "missing_status_option",
            f"Project Status field does not define required option '{sanitize_text(target_label, collapse_whitespace=True)}'.",
        )
    return option_map[key]


def reconcile_project_board(
    org: str,
    number: int,
    project_token: str,
    *,
    repo_read_token: str | None = None,
    requester: Callable[[str, dict[str, Any], str], dict[str, Any]] = graphql_request,
) -> dict[str, Any]:
    """Synchronize ProjectV2 Status columns and onboard missing open organization issues."""
    meta_data = requester(PROJECT_META_QUERY, {"org": org, "number": number}, project_token)
    org_node = meta_data.get("organization")
    if not isinstance(org_node, dict) or not isinstance(org_node.get("projectV2"), dict):
        raise ProjectExportError(
            "project_not_found",
            f"Organization '{sanitize_text(org, collapse_whitespace=True)}' Project #{number} was not found.",
        )

    project = org_node["projectV2"]
    project_id = str(project.get("id") or "")
    status_field_id = ""
    option_map: dict[str, tuple[str, str]] = {}
    for fnode in ((project.get("fields") or {}).get("nodes")) or []:
        if (
            isinstance(fnode, dict)
            and fnode.get("__typename") == "ProjectV2SingleSelectField"
            and fnode.get("name") == "Status"
        ):
            status_field_id = str(fnode.get("id") or "")
            for opt in fnode.get("options") or []:
                if isinstance(opt, dict) and opt.get("id") and opt.get("name"):
                    clean_name = sanitize_text(str(opt["name"]), collapse_whitespace=True)
                    option_map[clean_name.lower()] = (str(opt["id"]), clean_name)
            break

    if not project_id or not status_field_id:
        raise ProjectExportError(
            "missing_status_field",
            f"Project #{number} is missing a SingleSelect 'Status' field.",
        )

    backlog_id, backlog_name = _find_option_id(option_map, "Backlog")
    in_progress_id, in_progress_name = _find_option_id(option_map, "In progress")
    in_review_id, in_review_name = _find_option_id(option_map, "In review")
    done_id, done_name = _find_option_id(option_map, "Done")

    existing_items = _fetch_paginated_items(org, number, project_token, requester)
    read_tok = repo_read_token or project_token
    open_issues, ready_linked, draft_only_linked = _fetch_org_repo_state(org, read_tok, requester)

    tracked_issues: set[tuple[str, int]] = set()
    planned_updates: list[dict[str, Any]] = []

    for item in existing_items:
        if item["is_archived"]:
            continue
        content = item["content"]
        if content.get("kind") != "Issue":
            continue
        repo_full = str(content.get("repo") or "")
        issue_num = content.get("number")
        if not repo_full or not isinstance(issue_num, int):
            continue
        key = (repo_full, issue_num)
        tracked_issues.add(key)

        current_status = item["status"]
        state = str(content.get("state") or "")
        desired_option: tuple[str, str] | None = None
        reason = ""

        if state == "CLOSED":
            if current_status.lower() != done_name.lower():
                desired_option = (done_id, done_name)
                reason = "issue is CLOSED"
        elif state == "OPEN":
            if key in ready_linked:
                if current_status.lower() != in_review_name.lower():
                    desired_option = (in_review_id, in_review_name)
                    reason = "linked open non-draft PR"
            elif key in draft_only_linked:
                if current_status.lower() in (backlog_name.lower(), "(no status)"):
                    desired_option = (in_progress_id, in_progress_name)
                    reason = "linked open draft PR"

        if desired_option is not None:
            planned_updates.append(
                {
                    "item_id": item["id"],
                    "ref": f"{repo_full}#{issue_num}",
                    "from_status": current_status,
                    "to_status": desired_option[1],
                    "option_id": desired_option[0],
                    "reason": reason,
                }
            )

    planned_additions: list[dict[str, Any]] = []
    for issue in open_issues:
        key = (issue["repo"], issue["number"])
        if key in tracked_issues:
            continue
        if key in ready_linked:
            opt_id, opt_name = in_review_id, in_review_name
            reason = "new org issue with open non-draft PR"
        elif key in draft_only_linked:
            opt_id, opt_name = in_progress_id, in_progress_name
            reason = "new org issue with open draft PR"
        else:
            opt_id, opt_name = backlog_id, backlog_name
            reason = "new org issue"
        planned_additions.append(
            {
                "content_id": issue["node_id"],
                "ref": f"{issue['repo']}#{issue['number']}",
                "to_status": opt_name,
                "option_id": opt_id,
                "reason": reason,
            }
        )

    applied_updates: list[dict[str, str]] = []
    applied_additions: list[dict[str, str]] = []

    try:
        for upd in planned_updates:
            requester(
                UPDATE_PROJECT_STATUS_MUTATION,
                {
                    "projectId": project_id,
                    "itemId": upd["item_id"],
                    "fieldId": status_field_id,
                    "optionId": upd["option_id"],
                },
                project_token,
            )
            applied_updates.append(
                {
                    "ref": upd["ref"],
                    "from": upd["from_status"],
                    "to": upd["to_status"],
                    "reason": upd["reason"],
                }
            )

        for add in planned_additions:
            add_resp = requester(
                ADD_PROJECT_ITEM_MUTATION,
                {"projectId": project_id, "contentId": add["content_id"]},
                project_token,
            )
            new_item_id = str(
                (((add_resp.get("addProjectV2ItemById") or {}).get("item")) or {}).get("id") or ""
            )
            if new_item_id:
                requester(
                    UPDATE_PROJECT_STATUS_MUTATION,
                    {
                        "projectId": project_id,
                        "itemId": new_item_id,
                        "fieldId": status_field_id,
                        "optionId": add["option_id"],
                    },
                    project_token,
                )
            applied_additions.append(
                {
                    "ref": add["ref"],
                    "to": add["to_status"],
                    "reason": add["reason"],
                }
            )
    except ProjectExportError as exc:
        if exc.code == "forbidden":
            return {
                "status": "read_only_token",
                "message": str(exc),
                "planned_status_update_count": len(planned_updates),
                "planned_addition_count": len(planned_additions),
                "applied_status_update_count": len(applied_updates),
                "applied_addition_count": len(applied_additions),
            }
        raise

    return {
        "status": "applied",
        "planned_status_update_count": len(planned_updates),
        "planned_addition_count": len(planned_additions),
        "applied_status_update_count": len(applied_updates),
        "applied_addition_count": len(applied_additions),
        "status_updates": applied_updates,
        "added_items": applied_additions,
    }


def fetch_project_snapshot(
    org: str,
    number: int,
    token: str,
    *,
    allow_private: bool = False,
    requester: Callable[[str, dict[str, Any], str], dict[str, Any]] = graphql_request,
    exported_at: str | None = None,
) -> dict[str, Any]:
    """Fetch ProjectV2 metadata and paginated items, enforcing public-visibility safety."""
    meta_data = requester(PROJECT_META_QUERY, {"org": org, "number": number}, token)
    org_node = meta_data.get("organization")
    if not isinstance(org_node, dict) or not isinstance(org_node.get("projectV2"), dict):
        raise ProjectExportError(
            "project_not_found",
            f"Organization '{sanitize_text(org, collapse_whitespace=True)}' Project #{number} was not found.",
        )

    project = org_node["projectV2"]
    is_public = bool(project.get("public", False))
    timestamp = exported_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not is_public and not allow_private:
        return {
            "exported_at": timestamp,
            "org": sanitize_text(org, collapse_whitespace=True),
            "number": number,
            "public": False,
            "skipped_private": True,
        }

    status_options: list[dict[str, str]] = []
    fields_summary: list[dict[str, Any]] = []
    for fnode in ((project.get("fields") or {}).get("nodes")) or []:
        if not isinstance(fnode, dict):
            continue
        fname = sanitize_text(fnode.get("name"), collapse_whitespace=True)
        ftype = sanitize_text(fnode.get("dataType"), collapse_whitespace=True)
        entry: dict[str, Any] = {"name": fname, "data_type": ftype}
        if fnode.get("__typename") == "ProjectV2SingleSelectField":
            opts = [
                {
                    "name": sanitize_text(opt.get("name"), collapse_whitespace=True),
                    "description": sanitize_text(opt.get("description"), collapse_whitespace=True),
                    "color": sanitize_text(opt.get("color"), collapse_whitespace=True),
                }
                for opt in (fnode.get("options") or [])
                if isinstance(opt, dict) and opt.get("name")
            ]
            entry["options"] = opts
            if fname == "Status":
                status_options = opts
        fields_summary.append(entry)

    views_summary = [
        {
            "number": v.get("number"),
            "name": sanitize_text(v.get("name"), collapse_whitespace=True),
            "layout": sanitize_text(v.get("layout"), collapse_whitespace=True),
            "filter": sanitize_text(v.get("filter"), collapse_whitespace=True),
        }
        for v in (((project.get("views") or {}).get("nodes")) or [])
        if isinstance(v, dict)
    ]

    all_items = _fetch_paginated_items(org, number, token, requester)
    active_items = [item for item in all_items if not item["is_archived"]]
    archived_count = len(all_items) - len(active_items)

    ordered_column_names = [opt["name"] for opt in status_options]
    for item in active_items:
        if item["status"] not in ordered_column_names:
            ordered_column_names.append(item["status"])

    columns: list[dict[str, Any]] = []
    for col_name in ordered_column_names:
        col_items = [item for item in active_items if item["status"] == col_name]
        columns.append(
            {
                "name": col_name,
                "count": len(col_items),
                "items": col_items,
            }
        )

    return {
        "exported_at": timestamp,
        "org": sanitize_text(org, collapse_whitespace=True),
        "number": project.get("number", number),
        "title": sanitize_text(project.get("title"), collapse_whitespace=True),
        "short_description": sanitize_text(
            project.get("shortDescription"), collapse_whitespace=True
        ),
        "url": sanitize_text(project.get("url"), collapse_whitespace=True),
        "public": is_public,
        "closed": bool(project.get("closed", False)),
        "updated_at": sanitize_text(project.get("updatedAt"), collapse_whitespace=True),
        "skipped_private": False,
        "views": views_summary,
        "fields": fields_summary,
        "active_item_count": len(active_items),
        "archived_item_count": archived_count,
        "columns": columns,
    }


def _md_table_cell(sanitized_value: str | None) -> str:
    """Format an already-sanitized snapshot string for a GitHub Markdown table cell."""
    if not sanitized_value:
        return ""
    collapsed = " ".join(
        sanitized_value.replace("\r", " ").replace("\n", " ").replace("\t", " ").split()
    )
    return collapsed.replace("|", "\\|")


def render_markdown_summary(snapshot: dict[str, Any]) -> str:
    """Render a sanitized GitHub-Flavored Markdown report from a project snapshot."""
    if snapshot.get("skipped_private"):
        return (
            f"## Organization Project #{snapshot.get('number')} Snapshot Skipped\n\n"
            f"`{_md_table_cell(snapshot.get('org'))}` Project #{snapshot.get('number')} "
            "is currently set to **Private** visibility (`public=false`). "
            "Skipping public artifact export to prevent exposing private project items.\n"
        )

    lines: list[str] = [
        f"# {snapshot.get('title', '')} (Project #{snapshot.get('number')})",
        "",
        f"- **URL:** {snapshot.get('url', '')}",
        f"- **Exported at:** `{snapshot.get('exported_at', '')}`",
        f"- **Last updated:** `{snapshot.get('updated_at', '')}`",
        f"- **Active items:** `{snapshot.get('active_item_count', 0)}` "
        f"(archived: `{snapshot.get('archived_item_count', 0)}`)",
    ]
    desc = snapshot.get("short_description") or ""
    if desc:
        lines.append(f"- **Description:** {desc}")

    views = snapshot.get("views") or []
    if views:
        view_labels = [
            f"`{_md_table_cell(v.get('name'))}` ({_md_table_cell(v.get('layout'))})"
            for v in views
        ]
        lines.append(f"- **Views:** {', '.join(view_labels)}")

    reconcile = snapshot.get("reconcile")
    if isinstance(reconcile, dict):
        r_status = _md_table_cell(str(reconcile.get("status") or ""))
        if r_status == "applied":
            lines.append(
                f"- **Reconciliation:** `applied` "
                f"(status updates: `{reconcile.get('applied_status_update_count', 0)}`, "
                f"newly onboarded org issues: `{reconcile.get('applied_addition_count', 0)}`)"
            )
        elif r_status == "read_only_token":
            lines.append(
                f"- **Reconciliation:** `read_only_token` — `ORG_PROJECT_TOKEN` lacks "
                f"`Projects: Read and write` permission "
                f"(pending updates: `{reconcile.get('planned_status_update_count', 0)}`, "
                f"pending additions: `{reconcile.get('planned_addition_count', 0)}`)"
            )

    lines.extend(
        [
            "",
            "## Column Counts",
            "",
            "| Column | Active Items |",
            "| :--- | ---: |",
        ]
    )
    for col in snapshot.get("columns") or []:
        lines.append(f"| {_md_table_cell(col.get('name'))} | {col.get('count', 0)} |")

    for col in snapshot.get("columns") or []:
        col_name = col.get("name") or ""
        items = col.get("items") or []
        lines.extend(["", f"## {col_name} ({len(items)})", ""])
        if not items:
            lines.append("_No active items._")
            continue
        lines.extend(
            [
                "| Item | Title | State | Milestone | Extra Fields |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for item in items:
            content = item.get("content") or {}
            kind = content.get("kind")
            if kind in ("Issue", "PullRequest") and content.get("number") is not None:
                repo_short = (content.get("repo") or "").split("/")[-1]
                ref_label = f"{_md_table_cell(repo_short)}#{content.get('number')}"
                url = str(content.get("url") or "")
                ref_cell = f"[{ref_label}]({url})" if url.startswith("https://") else ref_label
            elif kind == "DraftIssue":
                ref_cell = "`Draft`"
            else:
                ref_cell = "`Item`"

            title_cell = _md_table_cell(content.get("title"))
            state_cell = _md_table_cell(content.get("state"))
            if kind == "PullRequest" and content.get("is_draft"):
                state_cell = f"{state_cell} (DRAFT)"
            milestone_cell = _md_table_cell(content.get("milestone") or "-")

            extra_pairs = [
                f"{_md_table_cell(k)}={_md_table_cell(v)}"
                for k, v in sorted((item.get("fields") or {}).items())
                if k != "Status"
            ]
            extra_cell = ", ".join(extra_pairs) if extra_pairs else "-"
            lines.append(
                f"| {ref_cell} | {title_cell} | {state_cell} | {milestone_cell} | {extra_cell} |"
            )

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export and optionally reconcile a GitHub Organization ProjectV2 board."
    )
    parser.add_argument("--org", default="totaldrop-app", help="GitHub organization login")
    parser.add_argument("--project-number", type=int, default=1, help="Organization ProjectV2 number")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for JSON and Markdown snapshot files",
    )
    parser.add_argument(
        "--summary-file",
        default="",
        help="Optional path (such as GITHUB_STEP_SUMMARY) to append Markdown output",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Reconcile item Status columns from live PR/Issue state and onboard missing open org issues",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Allow exporting private boards (never enable in public CI workflows)",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("ORG_PROJECT_TOKEN") or os.environ.get("GH_TOKEN") or ""
    repo_read_token = os.environ.get("GH_PUBLIC_TOKEN") or token

    reconcile_summary: dict[str, Any] | None = None
    try:
        if args.reconcile:
            reconcile_summary = reconcile_project_board(
                args.org,
                args.project_number,
                token,
                repo_read_token=repo_read_token,
            )
        snapshot = fetch_project_snapshot(
            args.org,
            args.project_number,
            token,
            allow_private=args.allow_private,
        )
    except ProjectExportError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1

    if reconcile_summary is not None and not snapshot.get("skipped_private"):
        snapshot["reconcile"] = reconcile_summary

    markdown = render_markdown_summary(snapshot)
    if args.summary_file:
        summary_path = Path(args.summary_file)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(markdown)

    if snapshot.get("skipped_private"):
        print(
            f"Notice: {snapshot['org']} Project #{snapshot['number']} has private visibility "
            "(public=false); skipped writing public snapshot artifacts."
        )
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    num = snapshot["number"]
    json_path = out_dir / f"project-{num}-snapshot.json"
    md_path = out_dir / f"project-{num}-snapshot.md"

    json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    print(
        f"Exported {snapshot['org']} Project #{num} ({snapshot['active_item_count']} active items) "
        f"to {json_path} and {md_path}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
