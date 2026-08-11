---
name: gh-contrib
description: Use when the user asks about the status of their own GitHub pull requests or issues in the current repository — what needs their attention, what is waiting on maintainers, or what to nudge. Wraps the gh CLI.
allowed-tools: Bash(python3 *)
---

# gh-contrib

Track the status of your own GitHub contributions (PRs and issues) in the current
repository: whose court the ball is in, what to act on, and what to nudge.

**Prerequisite:** the GitHub CLI (`gh`) must be installed and authenticated
(`gh auth status`). The script shells out to `gh`, stores no token, and always
operates as the authenticated user — it cannot query another account.

## Usage

Run the engine, passing through any flags the user mentioned. Use
`${CLAUDE_SKILL_DIR}` (the skill's own directory) to locate the bundled script:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/gh_contrib.py" --repo
```

Flags: `--repo` (current repo), `--org [NAME]` / `--all` (breadth), `--issues` / `--prs`
(type filter), `--json` (raw), `--no-glyphs` (ASCII markers). Bare (no scope flag) on a
PR branch shows the current PR.

Show the script's output to the user verbatim — it is already formatted markdown — then
stop. On error, relay the message and its fix; never fabricate a digest. Run only the
script; do not run other `gh`/`git`/shell commands or investigate further off the back of
the digest. If the user asks a follow-up ("why is CI failing?", "dig into this PR"), handle
it as an ordinary conversational request, not as part of this skill.
