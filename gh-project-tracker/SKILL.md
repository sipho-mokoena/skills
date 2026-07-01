---
name: gh-project-tracker
description: Manage GitHub Projects v2 — create projects, add issues, set custom fields, query board state.
argument-hint: "What do you need to do with GitHub Projects?"
---

# GitHub Projects V2 Tracker

Manage GitHub Projects (V2) — create projects, add/link issues, set custom field values, and query board state.

No local install needed — this skill runs `project.py` directly from the repo via `uv run <url>`.

## Prerequisites

- `gh` CLI installed and authenticated: `gh auth status`
- `project` scope on the token: `gh auth refresh -s project` if missing
- `uv` installed
- Every mutating command auto-checks the `project` scope before executing.

## Remote script URL

```
_PROJECT_PY = "https://raw.githubusercontent.com/sipho-mokoena/skills/main/gh-project-tracker/project.py"
```

## Quick Reference

| Intent | Command |
|--------|---------|
| Create a project | `uv run {_PROJECT_PY} create-project <owner> "<title>" [--repo owner/repo]` |
| List projects | `uv run {_PROJECT_PY} list-projects <owner>` |
| Create a custom field | `uv run {_PROJECT_PY} create-field <project-id> <name> <TYPE>` |
| Link an issue | `uv run {_PROJECT_PY} add-issue <project-id> <issue-id>` |
| Create a draft issue | `uv run {_PROJECT_PY} add-draft-issue <project-id> "<title>"` |
| Set a field value | `uv run {_PROJECT_PY} set-field <project-id> <item-id> <field-id> <value> --type <type>` |
| List board items | `uv run {_PROJECT_PY} list-items <project-id>` |
| Bootstrap Status/Component | `uv run {_PROJECT_PY} batch-init <project-id>` |
| Link project to repo | `uv run {_PROJECT_PY} link-repo <project-id> <repo-id>` |

All commands accept `--dry-run` to print the GraphQL query without executing.

## Common Workflows

### Create a project from scratch

```bash
_PROJECT_PY="https://raw.githubusercontent.com/sipho-mokoena/skills/main/gh-project-tracker/project.py"
uv run ${_PROJECT_PY} create-project sipho-mokoena "Sprint 2" --repo sipho-mokoena/simo
uv run ${_PROJECT_PY} batch-init <project-id>
uv run ${_PROJECT_PY} add-issue <project-id> <issue-id>
uv run ${_PROJECT_PY} set-field <project-id> <item-id> <field-id> <option-id> --type single-select
```

### Query current board state

```bash
_PROJECT_PY="https://raw.githubusercontent.com/sipho-mokoena/skills/main/gh-project-tracker/project.py"
uv run ${_PROJECT_PY} list-items <project-id> --json
```

### Add a draft issue and set its status

```bash
_PROJECT_PY="https://raw.githubusercontent.com/sipho-mokoena/skills/main/gh-project-tracker/project.py"
uv run ${_PROJECT_PY} add-draft-issue <project-id> "Investigate auth bug" --body "Details here"
uv run ${_PROJECT_PY} set-field <project-id> <item-id> <status-field-id> <option-id> --type single-select
```

## Field Reference (sipho-mokoena/simo)

Status options (created by `batch-init`):

| Option ID | Name |
|-----------|------|
| (auto) | Backlog |
| (auto) | Ready |
| (auto) | In Progress |
| (auto) | In Review |
| (auto) | Done |

Use `list-items --json` to discover actual option IDs.

## Dry-Run

Every command supports `--dry-run`. The GraphQL query/mutation is printed to stderr; nothing is executed:

```bash
_PROJECT_PY="https://raw.githubusercontent.com/sipho-mokoena/skills/main/gh-project-tracker/project.py"
uv run ${_PROJECT_PY} create-project sipho-mokoena "Test" --dry-run
```

## Error Handling

| Condition | Response |
|-----------|----------|
| `gh` not authenticated | Error message, exit code 1 |
| Missing `project` scope | `gh auth refresh -s project` hint shown |
| `UNPROCESSABLE` (duplicate name, etc.) | Actionable error message |
| GraphQL errors in response | Error messages printed, exit code 1 |
