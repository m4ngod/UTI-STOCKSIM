# Current Work Status - Module Notes

This directory stores module-level work status notes.

## Rules

- Record status by module, not in one giant status file.
- Do not record line numbers.
- For each change, record:
  - task id
  - date/time
  - goal
  - files involved
  - total changed line count
  - code anchors using the **first line** and **last line** of each modified code fragment
  - change summary
  - purpose
  - impact / risk
  - next actions
- If a task touches multiple code fragments, list each fragment separately.
- These notes are not a git diff replacement. They should explain intent, scope, and continuation state.

## Suggested module files

- `mainwindow.md`
- `compat-retirement.md`
- `market-detail.md`
- `engine.md`
- `account.md`
- `agents.md`

## Status labels

- planned
- in-progress
- blocked
- done
- verification-needed
