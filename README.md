# gh-contrib

A Claude Code plugin that tracks the status of **your own** GitHub pull requests
and issues: whose court the ball is in, what needs your action, and what to nudge.
Built for external contributors to busy open-source repos.

## Requirements

- The [GitHub CLI](https://cli.github.com/) (`gh`), installed and authenticated:
  `gh auth status`. The plugin shells out to `gh`, stores no token of its own, and
  **always operates as the authenticated user** — it cannot be pointed at anyone
  else's account.
- Python 3 (standard library only; no extra packages).

## Install

Add the marketplace and install the plugin:

```
/plugin marketplace add tonypiazza/gh-contrib
/plugin install gh-contrib
```

## Usage

Inside a checkout of a GitHub repository you contribute to:

- `/gh-contrib` (no flags) — if your current branch has an open PR of yours, shows a
  focused view of **that PR**: review state, CI, base-branch movement, and a one-line
  heads-up if any of your other open PRs need attention. On a branch with no PR of yours,
  it lists your open items in the repo instead.
- `/gh-contrib --repo` — your open PRs and issues across the whole current repo, grouped
  by whose court the ball is in (use this to override current-PR mode on a PR branch).
- `/gh-contrib --repo --issues` — issues only. `--prs` for PRs only.
- `/gh-contrib --json` — raw JSON (for scripting); works with any of the above.
- `/gh-contrib --no-glyphs` — ASCII status markers instead of emoji.

You can also just ask in natural language ("what's the status of my PRs here?").

**Working from a fork?** That's the common case for open-source contributors. The
plugin detects when your `origin` is a fork and automatically resolves to the
upstream repository you forked from, so it finds the PRs and issues you actually
opened there.

## Design notes

- **Single machine per repo.** Provenance and history features (later versions)
  read this machine's local data for a repo. The plugin assumes you work a given
  repo from one machine — a deliberate, good-enough choice for the common case.

## Status

Current-repo listing (`--repo`) with real **ball-in-court** classification, grouped
by whose court the ball is in:

- **Waiting on me** — a maintainer requested changes you haven't addressed yet, or the
  base branch moved and your PR is now behind/conflicting.
- **CI suspect** — checks are failing on your latest commit. Flagged as worth a look; the
  plugin does not assert the failure is your fault — see AI attribution below for which
  files (and which model) wrote the code under review.
- **Nudge candidates** — no activity for a while; a good candidate to ping.
- **Waiting on them** — you've responded or pushed since the last review, the PR is
  approved but unmerged, or an RFC is awaiting maintainer engagement.

Classification uses event ordering, not GitHub's raw status: a PR still labeled
"changes requested" is correctly shown as waiting on maintainers once you've pushed
commits addressing the feedback.

**Current-PR mode** (the bare `/gh-contrib` on a PR branch) focuses on the PR you're
working on and includes a one-line footer for any of your *other* open PRs that
currently need attention. That footer reflects each PR's current state; a true
"what changed since last run" view comes with the history/snapshot work later.

**AI attribution.** In current-PR mode the plugin identifies which of the PR's changed
files were AI-authored — and by which model — by reading this machine's local Claude Code
session history. It's a **learning aid, not a blame list**: use it to see where to review
AI-generated code more carefully, and to judge whether the right model was used for the
work (if feedback keeps landing on a weaker model's output, a stronger one may fit
better). In a local checkout you can ask it to read those files' diffs and suggest fixes.
Attribution is file-level (which files the model edited, from local history) — it flags
where to look and which model, not that a specific line is the bug, and it never frames a
maintainer's request as your fault. This relies on the single-machine-per-repo assumption
above; code pasted manually from chat isn't captured.

Arriving in later versions: org/all breadth across many repos, the "what changed since
last run" delta, and the setup/history commands.

## License

Apache-2.0
