#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
GitHub Projects V2 CLI — wraps `gh api graphql` for project management.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def gh_graphql(query: str, dry_run: bool = False, quiet: bool = False, fail_ok: bool = False) -> dict[str, Any] | None:
    if dry_run:
        print(query, file=sys.stderr)
        return {}
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        if fail_ok:
            return None
        err = result.stderr.strip()
        if "INSUFFICIENT_SCOPES" in err:
            print("ERROR: gh token missing 'project' scope.", file=sys.stderr)
            print("       Run: gh auth refresh -s project", file=sys.stderr)
        elif "UNPROCESSABLE" in err:
            print(f"ERROR: {err}", file=sys.stderr)
        else:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(result.stdout)
    if "errors" in data:
        if fail_ok:
            return None
        for e in data["errors"]:
            print(f"GraphQL error: {e.get('message', e)}", file=sys.stderr)
        sys.exit(1)
    return data["data"]


def check_auth() -> None:
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    if "project" not in combined:
        print("ERROR: gh token missing 'project' scope.", file=sys.stderr)
        print("       Run: gh auth refresh -s project", file=sys.stderr)
        sys.exit(1)


def resolve_owner_id(owner: str, dry_run: bool = False) -> str:
    if dry_run:
        return "<resolved-owner-id>"
    q = f'query {{ repository(owner: "{owner}", name: "_does_not_exist_") {{ owner {{ id }} }} }}'
    data = gh_graphql(q)
    if data.get("repository") and data["repository"].get("owner"):
        return data["repository"]["owner"]["id"]
    q = f'query {{ user(login: "{owner}") {{ id }} }}'
    data = gh_graphql(q)
    if data.get("user"):
        return data["user"]["id"]
    q = f'query {{ organization(login: "{owner}") {{ id }} }}'
    data = gh_graphql(q)
    if data.get("organization"):
        return data["organization"]["id"]
    print(f"ERROR: could not resolve owner '{owner}'", file=sys.stderr)
    sys.exit(1)


def resolve_repo_id(repo: str, dry_run: bool = False) -> str:
    if dry_run:
        return "<resolved-repo-id>"
    q = f'query {{ repository(owner: "{repo.split("/")[0]}", name: "{repo.split("/")[1]}") {{ id }} }}'
    data = gh_graphql(q)
    rid = data.get("repository", {}).get("id")
    if not rid:
        print(f"ERROR: could not resolve repo '{repo}'", file=sys.stderr)
        sys.exit(1)
    return rid


def cmd_create_project(args: argparse.Namespace) -> None:
    check_auth()
    owner_id = args.owner_id or resolve_owner_id(args.owner, args.dry_run)
    q = f"""
mutation {{
  createProject(input: {{ ownerId: "{owner_id}", title: "{args.title}" }}) {{
    project {{
      id
      number
      url
      title
    }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    proj = data["createProject"]["project"]
    if args.json:
        print(json.dumps(proj, indent=2))
    else:
        print(f"ID:     {proj['id']}")
        print(f"Number: {proj['number']}")
        print(f"URL:    {proj['url']}")
        print(f"Title:  {proj['title']}")
    if args.repo:
        repo_id = resolve_repo_id(args.repo, args.dry_run)
        cmd_args = argparse.Namespace(
            project_id=proj["id"], repo_id=repo_id,
            dry_run=args.dry_run, json=args.json, quiet=args.quiet,
        )
        cmd_link_repo(cmd_args)


def cmd_list_projects(args: argparse.Namespace) -> None:
    nodes = None
    for owner_type in ("organization", "user"):
        q = f"""
query {{
  {owner_type}(login: "{args.owner}") {{
    projectsV2(first: 50) {{
      nodes {{ id number title url }}
    }}
  }}
}}
"""
        data = gh_graphql(q, args.dry_run, args.quiet, fail_ok=True)
        if args.dry_run:
            return
        if data:
            nodes = data.get(owner_type, {}).get("projectsV2", {}).get("nodes")
            if nodes is not None:
                break
    if nodes is None:
        nodes = []
    if args.json:
        print(json.dumps(nodes, indent=2))
    else:
        if not nodes:
            print("No projects found.")
            return
        col_w = max((len(n["title"]) for n in nodes), default=10) + 2
        header = f"{'#':<6} {'Title':<{col_w}} URL"
        print(header)
        print("-" * len(header))
        for n in nodes:
            print(f"{n['number']:<6} {n['title']:<{col_w}} {n['url']}")


def cmd_create_field(args: argparse.Namespace) -> None:
    check_auth()
    opts_json = ""
    options_arg = ""
    if args.options:
        parsed_opts = json.loads(args.options)
        if args.data_type == "SINGLE_SELECT" and parsed_opts:
            opts_json = f'singleSelectOptions: {json.dumps(parsed_opts)}'
            options_arg = ""

    q = f"""
mutation {{
  createProjectV2Field(input: {{
    projectId: "{args.project_id}"
    name: "{args.name}"
    dataType: {args.data_type}
    {opts_json}
  }}) {{
    field {{
      __typename
      ... on ProjectV2Field {{ id name dataType }}
      ... on ProjectV2SingleSelectField {{ id name options {{ id name }} }}
      ... on ProjectV2IterationField {{ id name }}
    }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    field = data["createProjectV2Field"]["field"]
    if args.json:
        print(json.dumps(field, indent=2))
    else:
        print(f"Field ID:   {field['id']}")
        print(f"Name:       {field['name']}")
        if "options" in field:
            for opt in field["options"]:
                print(f"  Option: {opt['name']} ({opt['id']})")


def cmd_update_field(args: argparse.Namespace) -> None:
    check_auth()
    if not args.options:
        print("ERROR: --options is required for update-field", file=sys.stderr)
        sys.exit(1)
    opts = json.loads(args.options)
    q = f"""
mutation {{
  updateProjectV2SingleSelectFieldOptions(input: {{
    fieldId: "{args.field_id}"
    singleSelectOptions: {json.dumps(opts)}
  }}) {{
    field {{
      __typename
      ... on ProjectV2SingleSelectField {{ id name options {{ id name }} }}
    }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    field = data["updateProjectV2SingleSelectFieldOptions"]["field"]
    if args.json:
        print(json.dumps(field, indent=2))
    else:
        print(f"Field ID:   {field['id']}")
        print(f"Name:       {field['name']}")
        for opt in field.get("options", []):
            print(f"  Option: {opt['name']} ({opt['id']})")


def cmd_add_issue(args: argparse.Namespace) -> None:
    check_auth()
    q = f"""
mutation {{
  addProjectV2ItemById(input: {{
    projectId: "{args.project_id}"
    contentId: "{args.issue_id}"
  }}) {{
    item {{ id }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    item_id = data["addProjectV2ItemById"]["item"]["id"]
    if args.json:
        print(json.dumps({"itemId": item_id}, indent=2))
    else:
        print(f"Item ID: {item_id}")


def cmd_add_draft_issue(args: argparse.Namespace) -> None:
    check_auth()
    body_arg = ""
    if args.body:
        body_arg = f'body: "{args.body}"'
    q = f"""
mutation {{
  addProjectV2DraftIssue(input: {{
    projectId: "{args.project_id}"
    title: "{args.title}"
    {body_arg}
  }}) {{
    projectItem {{ id }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    item_id = data["addProjectV2DraftIssue"]["projectItem"]["id"]
    if args.json:
        print(json.dumps({"itemId": item_id}, indent=2))
    else:
        print(f"Item ID: {item_id}")


def cmd_set_field(args: argparse.Namespace) -> None:
    check_auth()
    field_type = args.field_type or "text"
    value_str = ""
    if field_type == "single-select":
        value_str = f'singleSelectOptionId: "{args.value}"'
    elif field_type == "number":
        value_str = f'number: {args.value}'
    elif field_type == "date":
        value_str = f'date: "{args.value}"'
    elif field_type == "iteration":
        value_str = f'iterationId: "{args.value}"'
    else:
        value_str = f'text: "{args.value}"'

    q = f"""
mutation {{
  updateProjectV2ItemFieldValue(input: {{
    projectId: "{args.project_id}"
    itemId: "{args.item_id}"
    fieldId: "{args.field_id}"
    value: {{ {value_str} }}
  }}) {{
    projectV2Item {{ id }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    _ = data  # success - no useful return data beyond confirmation


def cmd_list_items(args: argparse.Namespace) -> None:
    filter_clause = ""
    if args.filter_field and args.filter_value:
        filter_clause = f'filterBy: {{ fieldId: "{args.filter_field}", operator: EQUALS, value: "{args.filter_value}" }}'
    q = f"""
query {{
  node(id: "{args.project_id}") {{
    ... on ProjectV2 {{
      items(first: 100 {filter_clause}) {{
        nodes {{
          id
          type
          content {{ __typename ... on Issue {{ number title url }} ... on PullRequest {{ number title url }} }}
          fieldValues(first: 20) {{
            nodes {{
              __typename
              ... on ProjectV2ItemFieldTextValue {{ text field {{ ... on ProjectV2Field {{ id name }} }} }}
              ... on ProjectV2ItemFieldSingleSelectValue {{ name optionId field {{ ... on ProjectV2SingleSelectField {{ id name }} }} }}
              ... on ProjectV2ItemFieldDateValue {{ date field {{ ... on ProjectV2Field {{ id name }} }} }}
              ... on ProjectV2ItemFieldNumberValue {{ number field {{ ... on ProjectV2Field {{ id name }} }} }}
              ... on ProjectV2ItemFieldIterationValue {{ title field {{ ... on ProjectV2IterationField {{ id name }} }} }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    items = data.get("node", {}).get("items", {}).get("nodes") or []
    if args.json:
        print(json.dumps(items, indent=2))
    else:
        if not items:
            print("No items found.")
            return
        for item in items:
            content = item.get("content") or {}
            title = content.get("title") or "(draft)"
            url = content.get("url") or ""
            status = ""
            component = ""
            for fv in item.get("fieldValues", {}).get("nodes", []):
                typename = fv.get("__typename", "")
                if typename == "ProjectV2ItemFieldSingleSelectValue":
                    fname = (fv.get("field") or {}).get("name", "")
                    val = fv.get("name", "")
                    if fname.lower() == "status":
                        status = val
                    elif fname.lower() == "component":
                        component = val
            print(f"  {item['id']}")
            print(f"    Title:     {title}")
            print(f"    Type:      {item.get('type', '')}")
            if status:
                print(f"    Status:    {status}")
            if component:
                print(f"    Component: {component}")
            if url:
                print(f"    URL:       {url}")
            print()


def cmd_batch_init(args: argparse.Namespace) -> None:
    check_auth()
    status_opts = json.dumps([
        {"name": "Backlog", "color": "GRAY", "description": ""},
        {"name": "Ready", "color": "BLUE", "description": ""},
        {"name": "In Progress", "color": "GREEN", "description": ""},
        {"name": "In Review", "color": "YELLOW", "description": ""},
        {"name": "Done", "color": "PURPLE", "description": ""},
    ])
    q_status = f"""
mutation {{
  createProjectV2Field(input: {{
    projectId: "{args.project_id}"
    name: "Status"
    dataType: SINGLE_SELECT
    singleSelectOptions: {status_opts}
  }}) {{
    field {{ ... on ProjectV2SingleSelectField {{ id name options {{ id name }} }} }}
  }}
}}
"""
    data_status = gh_graphql(q_status, args.dry_run, args.quiet)
    if not args.dry_run and not args.quiet:
        sid = data_status["createProjectV2Field"]["field"]["id"]
        print(f"Created Status field ({sid}) with 5 options.")

    q_comp = f"""
mutation {{
  createProjectV2Field(input: {{
    projectId: "{args.project_id}"
    name: "Component"
    dataType: SINGLE_SELECT
  }}) {{
    field {{ ... on ProjectV2SingleSelectField {{ id name }} }}
  }}
}}
"""
    data_comp = gh_graphql(q_comp, args.dry_run, args.quiet)
    if not args.dry_run and not args.quiet:
        cid = data_comp["createProjectV2Field"]["field"]["id"]
        print(f"Created Component field ({cid}).")


def cmd_link_repo(args: argparse.Namespace) -> None:
    check_auth()
    repo_id = args.repo_id
    if "/" in repo_id:
        repo_id = resolve_repo_id(repo_id, args.dry_run)
    q = f"""
mutation {{
  linkProjectV2ToRepository(input: {{
    projectId: "{args.project_id}"
    repositoryId: "{repo_id}"
  }}) {{
    repository {{ id }}
  }}
}}
"""
    _ = gh_graphql(q, args.dry_run, args.quiet)
    if not args.dry_run and not args.quiet:
        print(f"Linked project to repository ({repo_id}).")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="project.py",
        description="Manage GitHub Projects V2 via gh GraphQL API",
    )
    p.add_argument("--dry-run", action="store_true", help="Print GraphQL query without executing")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.add_argument("--quiet", action="store_true", help="Suppress output except errors")

    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("create-project", help="Create a new GitHub Project V2")
    sp.add_argument("owner")
    sp.add_argument("title")
    sp.add_argument("--owner-id", help="Node ID of the owner (skips lookup)")
    sp.add_argument("--repo", help="Link project to this repo after creation (owner/repo)")

    sp = sub.add_parser("list-projects", help="List projects for an owner")
    sp.add_argument("owner")

    sp = sub.add_parser("create-field", help="Create a custom field")
    sp.add_argument("project_id")
    sp.add_argument("name")
    sp.add_argument("data_type", choices=["TEXT", "NUMBER", "DATE", "SINGLE_SELECT", "ITERATION"])
    sp.add_argument("--options", help="JSON array of option objects for SINGLE_SELECT")

    sp = sub.add_parser("update-field", help="Update a single-select field's options")
    sp.add_argument("field_id")
    sp.add_argument("--options", required=True, help="JSON array of option objects")

    sp = sub.add_parser("add-issue", help="Link an existing issue to a project")
    sp.add_argument("project_id")
    sp.add_argument("issue_id")

    sp = sub.add_parser("add-draft-issue", help="Create a draft issue in a project")
    sp.add_argument("project_id")
    sp.add_argument("title")
    sp.add_argument("--body", help="Draft issue body text")

    sp = sub.add_parser("set-field", help="Set a field value on a project item")
    sp.add_argument("project_id")
    sp.add_argument("item_id")
    sp.add_argument("field_id")
    sp.add_argument("value")
    sp.add_argument("--type", choices=["text", "number", "date", "single-select", "iteration"],
                    default="text", dest="field_type")

    sp = sub.add_parser("list-items", help="List items in a project")
    sp.add_argument("project_id")
    sp.add_argument("--format", choices=["table", "json"], default="table", dest="output_format")
    sp.add_argument("--filter-field", help="Field ID to filter on")
    sp.add_argument("--filter-value", help="Value to filter by")

    sp = sub.add_parser("batch-init", help="Set up Status + Component fields")
    sp.add_argument("project_id")

    sp = sub.add_parser("link-repo", help="Link a project to a repository")
    sp.add_argument("project_id")
    sp.add_argument("repo_id", help="Repository node ID or owner/name")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "create-project": cmd_create_project,
        "list-projects": cmd_list_projects,
        "create-field": cmd_create_field,
        "update-field": cmd_update_field,
        "add-issue": cmd_add_issue,
        "add-draft-issue": cmd_add_draft_issue,
        "set-field": cmd_set_field,
        "list-items": cmd_list_items,
        "batch-init": cmd_batch_init,
        "link-repo": cmd_link_repo,
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()
