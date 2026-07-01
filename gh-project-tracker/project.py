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
            return {}
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
            return {}
        for e in data["errors"]:
            print(f"GraphQL error: {e.get('message', e)}", file=sys.stderr)
        sys.exit(1)
    return data["data"]


def _load_options(args: argparse.Namespace) -> list[dict] | None:
    """Load options from --options-file (stdin if '-') or --options string."""
    if args.options_file:
        src = args.options_file
        if src == "-":
            content = sys.stdin.read()
        else:
            content = Path(src).read_text()
        return json.loads(content)
    if args.options:
        return json.loads(args.options)
    return None


def check_auth() -> None:
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    if "project" not in combined:
        print("ERROR: gh token missing 'project' scope.", file=sys.stderr)
        print("       Run: gh auth refresh -s project", file=sys.stderr)
        sys.exit(1)


def fmt_single_select_options(options: list[dict]) -> str:
    """Format option dicts as GraphQL inline array.

    Known enum fields (color) are rendered bare: {name: "Foo", color: GRAY}
    """
    def _val(k: str, v: Any) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return str(v).lower()
        if isinstance(v, int | float):
            return str(v)
        if isinstance(v, str):
            if k in {"color"}:
                return v  # bare enum value
            return json.dumps(v)
        return str(v)

    items = ", ".join(
        "{" + ", ".join(f"{k}: {_val(k, v)}" for k, v in opt.items()) + "}"
        for opt in options
    )
    return f"[{items}]"


def resolve_owner_id(owner: str, dry_run: bool = False) -> str:
    if dry_run:
        return "<resolved-owner-id>"
    q = f'query {{ repository(owner: "{owner}", name: "_does_not_exist_") {{ owner {{ id }} }} }}'
    data = gh_graphql(q, fail_ok=True)
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
  createProjectV2(input: {{ ownerId: "{owner_id}", title: {json.dumps(args.title)} }}) {{
    projectV2 {{
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
    proj = data["createProjectV2"]["projectV2"]
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
    parsed_opts = _load_options(args)
    if parsed_opts and args.data_type == "SINGLE_SELECT":
            opts_json = f'singleSelectOptions: {fmt_single_select_options(parsed_opts)}'
            options_arg = ""

    q = f"""
mutation {{
  createProjectV2Field(input: {{
    projectId: "{args.project_id}"
    name: "{args.name}"
    dataType: {args.data_type}
    {opts_json}
  }}) {{
    projectV2Field {{
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
    field = data["createProjectV2Field"]["projectV2Field"]
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
    opts = _load_options(args)
    if opts is None:
        print("ERROR: --options or --options-file is required for update-field", file=sys.stderr)
        sys.exit(1)
    q = f"""
mutation {{
  updateProjectV2SingleSelectFieldOptions(input: {{
    fieldId: "{args.field_id}"
    singleSelectOptions: {fmt_single_select_options(opts)}
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
        body_arg = f"body: {json.dumps(args.body)}"
    q = f"""
mutation {{
  addProjectV2DraftIssue(input: {{
    projectId: "{args.project_id}"
    title: {json.dumps(args.title)}
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
          content {{ __typename ... on Issue {{ number title url }} ... on PullRequest {{ number title url }} ... on DraftIssue {{ title }} }}
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
    use_json = args.json or args.output_format == "json"
    if use_json:
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


def cmd_list_fields(args: argparse.Namespace) -> None:
    q = f"""
query {{
  node(id: "{args.project_id}") {{
    ... on ProjectV2 {{
      fields(first: 50) {{
        nodes {{
          __typename
          ... on ProjectV2Field {{ id name dataType }}
          ... on ProjectV2SingleSelectField {{ id name dataType options {{ id name }} }}
          ... on ProjectV2IterationField {{ id name dataType }}
        }}
      }}
    }}
  }}
}}
"""
    data = gh_graphql(q, args.dry_run, args.quiet)
    if args.dry_run:
        return
    fields = data.get("node", {}).get("fields", {}).get("nodes") or []
    use_json = args.json or args.output_format == "json"
    if use_json:
        print(json.dumps(fields, indent=2))
    else:
        if not fields:
            print("No fields found.")
            return
        for f in fields:
            typename = f.get("__typename", "")
            if typename == "ProjectV2SingleSelectField":
                ftype = "SINGLE_SELECT"
            elif typename == "ProjectV2IterationField":
                ftype = "ITERATION"
            else:
                ftype = f.get("dataType") or "TEXT"
            print(f"  {f['id']}")
            print(f"    Name:    {f['name']}")
            print(f"    Type:    {ftype}")
            options = f.get("options")
            if options:
                for opt in options:
                    print(f"    Option:  {opt['name']} ({opt['id']})")
            print()


def _get_project_field_names(project_id: str, dry_run: bool = False) -> set[str]:
    q = f"""
query {{
  node(id: "{project_id}") {{
    ... on ProjectV2 {{
      fields(first: 50) {{
        nodes {{
          __typename
          ... on ProjectV2Field {{ name }}
          ... on ProjectV2SingleSelectField {{ name }}
          ... on ProjectV2IterationField {{ name }}
        }}
      }}
    }}
  }}
}}
"""
    data = gh_graphql(q, dry_run=dry_run, quiet=True)
    if dry_run:
        return set()
    nodes = data.get("node", {}).get("fields", {}).get("nodes") or []
    return {n["name"] for n in nodes if n.get("name")}


def cmd_batch_init(args: argparse.Namespace) -> None:
    check_auth()
    existing = _get_project_field_names(args.project_id, args.dry_run)

    if "Status" not in existing:
        status_opts = fmt_single_select_options([
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
    projectV2Field {{ ... on ProjectV2SingleSelectField {{ id name options {{ id name }} }} }}
  }}
}}
"""
        data_status = gh_graphql(q_status, args.dry_run, args.quiet)
        if not args.dry_run and not args.quiet:
            sid = data_status["createProjectV2Field"]["projectV2Field"]["id"]
            print(f"Created Status field ({sid}) with 5 options.")
    elif not args.quiet:
        print("Status field already exists, skipping.")

    if "Component" not in existing:
        comp_opts = fmt_single_select_options([
            {"name": "None", "color": "GRAY"},
        ])
        q_comp = f"""
mutation {{
  createProjectV2Field(input: {{
    projectId: "{args.project_id}"
    name: "Component"
    dataType: SINGLE_SELECT
    singleSelectOptions: {comp_opts}
  }}) {{
    projectV2Field {{ ... on ProjectV2SingleSelectField {{ id name }} }}
  }}
}}
"""
        data_comp = gh_graphql(q_comp, args.dry_run, args.quiet)
        if not args.dry_run and not args.quiet:
            cid = data_comp["createProjectV2Field"]["projectV2Field"]["id"]
            print(f"Created Component field ({cid}).")
    elif not args.quiet:
        print("Component field already exists, skipping.")


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

    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--dry-run", action="store_true", help="Print GraphQL query without executing")
    base.add_argument("--json", action="store_true", help="Output raw JSON")
    base.add_argument("--quiet", action="store_true", help="Suppress output except errors")

    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("create-project", parents=[base], help="Create a new GitHub Project V2")
    sp.add_argument("owner")
    sp.add_argument("title")
    sp.add_argument("--owner-id", help="Node ID of the owner (skips lookup)")
    sp.add_argument("--repo", help="Link project to this repo after creation (owner/repo)")

    sp = sub.add_parser("list-projects", parents=[base], help="List projects for an owner")
    sp.add_argument("owner")

    sp = sub.add_parser("create-field", parents=[base], help="Create a custom field")
    sp.add_argument("project_id")
    sp.add_argument("name")
    sp.add_argument("data_type", choices=["TEXT", "NUMBER", "DATE", "SINGLE_SELECT", "ITERATION"])
    sp.add_argument("--options", help="JSON string of option objects for SINGLE_SELECT")
    sp.add_argument("--options-file", help="Read options JSON from file (use '-' for stdin)")

    sp = sub.add_parser("update-field", parents=[base], help="Update a single-select field's options")
    sp.add_argument("field_id")
    sp.add_argument("--options", help="JSON string of option objects")
    sp.add_argument("--options-file", help="Read options JSON from file (use '-' for stdin)")

    sp = sub.add_parser("add-issue", parents=[base], help="Link an existing issue to a project")
    sp.add_argument("project_id")
    sp.add_argument("issue_id")

    sp = sub.add_parser("add-draft-issue", parents=[base], help="Create a draft issue in a project")
    sp.add_argument("project_id")
    sp.add_argument("title")
    sp.add_argument("--body", help="Draft issue body text")

    sp = sub.add_parser("set-field", parents=[base], help="Set a field value on a project item")
    sp.add_argument("project_id")
    sp.add_argument("item_id")
    sp.add_argument("field_id")
    sp.add_argument("value")
    sp.add_argument("--type", choices=["text", "number", "date", "single-select", "iteration"],
                    default="text", dest="field_type")

    sp = sub.add_parser("list-items", parents=[base], help="List items in a project")
    sp.add_argument("project_id")
    sp.add_argument("--format", choices=["table", "json"], default="table", dest="output_format")
    sp.add_argument("--filter-field", help="Field ID to filter on")
    sp.add_argument("--filter-value", help="Value to filter by")

    sp = sub.add_parser("list-fields", parents=[base], help="List fields and option IDs in a project")
    sp.add_argument("project_id")
    sp.add_argument("--format", choices=["table", "json"], default="table", dest="output_format")

    sp = sub.add_parser("batch-init", parents=[base], help="Set up Status + Component fields")
    sp.add_argument("project_id")

    sp = sub.add_parser("link-repo", parents=[base], help="Link a project to a repository")
    sp.add_argument("project_id")
    sp.add_argument("repo_id", help="Repository node ID or owner/name")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Python 3.14+ subparsers merge a fresh namespace, so parent-parser
    # values for --dry-run / --json / --quiet are lost when the flags
    # appear before the subcommand.  Re-check sys.argv to catch that case.
    for flag in ("--dry-run", "--json", "--quiet"):
        if flag in sys.argv:
            dest = flag.lstrip("-").replace("-", "_")
            setattr(args, dest, True)

    handlers = {
        "create-project": cmd_create_project,
        "list-projects": cmd_list_projects,
        "create-field": cmd_create_field,
        "update-field": cmd_update_field,
        "add-issue": cmd_add_issue,
        "add-draft-issue": cmd_add_draft_issue,
        "set-field": cmd_set_field,
        "list-items": cmd_list_items,
        "list-fields": cmd_list_fields,
        "batch-init": cmd_batch_init,
        "link-repo": cmd_link_repo,
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()
