---
description: Show the status of your own GitHub PRs and issues — whose court the ball is in, what to act on or nudge. Use when checking your contributions to the current repo.
argument-hint: "[--repo | --org [NAME] | --all] [--issues | --prs] [--json] [--no-glyphs]"
allowed-tools: Bash(python3 *)
---

Run the gh-contrib engine with the user's arguments and present the result.

The script requires the `gh` CLI to be installed and authenticated; it operates
only as the authenticated user. Scopes: the current PR (bare, on a PR branch), the
current repo (`--repo`), an org (`--org [NAME]`), or your configured digest scope
(`--all`).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/gh-contrib/scripts/gh_contrib.py" $ARGUMENTS
```

Show the script's output to the user verbatim (it is already formatted markdown),
then **stop**. If the script exits with an error, relay the error and its suggested
fix; do not fabricate a digest.

Run only the one command above. Do not run any other `gh`, `git`, or shell commands
as a result of this digest — no `gh run view`, no `gh api`, no log-scraping, no diffs,
no fetching anything the script didn't return. The digest's own lines (e.g. "CI failing
on latest commit — check whether it's yours") are notes for the user, not cues for you
to investigate. If the user later asks a follow-up ("why is CI failing?", "dig into this
PR"), handle it as an ordinary request in conversation — this command's job is done once
the digest is shown.
