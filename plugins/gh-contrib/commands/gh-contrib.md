---
description: Show the status of your own GitHub PRs and issues — whose court the ball is in, what to act on or nudge. Use when checking your contributions to the current repo.
argument-hint: "[--repo] [--issues | --prs] [--json] [--no-glyphs]"
allowed-tools: Bash(python3 *)
---

Run the gh-contrib engine with the user's arguments and present the result.

The script requires the `gh` CLI to be installed and authenticated; it operates
only as the authenticated user. Phase 1 supports the current repository (`--repo`).

Run this and show the output to the user verbatim (it is already formatted
markdown). If the script exits with an error, relay the error and its suggested
fix; do not fabricate a digest.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/gh-contrib/scripts/gh_contrib.py" $ARGUMENTS
```
