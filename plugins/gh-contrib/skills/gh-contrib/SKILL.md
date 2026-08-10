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

Flags (Phase 1): `--repo` (current repo), `--issues` / `--prs` (type filter),
`--json` (raw), `--no-glyphs` (ASCII markers).

Show the script's output to the user verbatim — it is already formatted markdown.
On error, relay the message and its fix; never fabricate a digest.

## IMPORTANT NOTES ON EXACT CONTENT

- Both files begin with a YAML frontmatter block delimited by lines containing exactly three hyphens (`---`).
- Preserve the em-dashes (—) exactly as shown; do not convert them to hyphens.
- The command file's bash fence uses `${CLAUDE_PLUGIN_ROOT}` and `$ARGUMENTS`.
- The skill file's bash fence uses `${CLAUDE_SKILL_DIR}`.
- Note the skills directory `plugins/gh-contrib/skills/gh-contrib/` already exists (it contains scripts/). The commands directory `plugins/gh-contrib/commands/` does NOT exist yet — create it.
