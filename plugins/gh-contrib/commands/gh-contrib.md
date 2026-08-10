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

## When the output lists AI-authored files

The AI-authored file list is a learning aid, not a blame list: it shows where to
focus review of AI-generated code and which model wrote it. If the digest reports
AI-authored files in a PR that is `CI_SUSPECT` or has changes requested, and you are
in a local checkout of that repo:

1. Look at the local diff for those files (e.g. `git diff origin/main...HEAD -- <file>`),
   focused on the ones the maintainer flagged or that CI implicates.
2. Explain the likely cause in plain terms, and propose a concrete fix.
3. If feedback/CI keeps landing on AI-authored files, note it as a place to review AI
   code more carefully — and, if a weaker model wrote the problematic files, that a
   stronger model may fit that work better.
4. Be honest about certainty: file-level attribution means the model edited the file,
   not that a specific line is the defect. If you cannot pin the cause from the diff,
   say so. Never frame a maintainer's request as the user's fault — lead with the fix.

Do this only on request or when the user is clearly working the PR; do not
auto-run large diffs unprompted.
