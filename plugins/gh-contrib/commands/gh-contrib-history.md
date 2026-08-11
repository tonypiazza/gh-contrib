---
description: Show the full chronological history of one of your GitHub PRs or issues — reviews, comments, commits, and CI over time — with ball-in-court reasoning at each step. Read-only.
argument-hint: "<owner/repo#number | #number | PR/issue URL>"
allowed-tools: Bash(python3 *)
---

Show the chronological timeline for the PR or issue the user referenced, then narrate
what it means.

Run the engine to get the timeline as JSON (pass the user's reference as `--history`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/gh-contrib/scripts/gh_contrib.py" --history $ARGUMENTS
```

Then present it as a **chronological narrative**, not a raw dump:

1. Lead with the item: `<kind> <repo>#<number> — <title>` and its current state.
2. Walk the timeline in order. For each event give the date, who acted, and what
   happened (commit / review / comment / CI).
3. Annotate the ball-in-court reasoning as it changes over time, e.g. "maintainer
   requested changes here → ball to you", "you pushed commits after that → ball back
   to them", "N days of silence since → a nudge candidate". Use event ordering, not
   raw status: a commit after a changes-requested review means you've responded.
4. End with where the ball is **now** and a concrete suggested next action (nudge,
   rebase, reply, wait).

Be honest: this is read-only and based on what the API exposes. Don't invent events
not in the timeline. If the script errors (bad reference, no such item, not
authenticated), relay the message and its fix; don't fabricate a history.
