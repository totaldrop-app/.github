#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The TotalDrop Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export a sanitized snapshot of a public GitHub Organization ProjectV2 board."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
import urllib.error
import urllib.request

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
MAX_ITEM_PAGES = 50

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
            "User-Agent": "totaldrop-project-board-exporter/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ProjectExportError(
            "http_error",
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
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            first_msg = str(errors[0].get("message", "GraphQL error"))
        else:
            first_msg = str(errors)
        raise ProjectExportError(
            "graphql_error",
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
    collapsed = " ".join(sanitized_value.replace("\r", " ").replace("\n", " ").replace("\t", " ").split())
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
        description="Export a sanitized snapshot of a GitHub Organization ProjectV2 board."
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
        "--allow-private",
        action="store_true",
        help="Allow exporting private boards (never enable in public CI workflows)",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("ORG_PROJECT_TOKEN") or os.environ.get("GH_TOKEN") or ""
    try:
        snapshot = fetch_project_snapshot(
            args.org,
            args.project_number,
            token,
            allow_private=args.allow_private,
        )
    except ProjectExportError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1

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
