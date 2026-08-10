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

- `/gh-contrib --repo` — your open PRs and issues in the current repo, grouped by
  whose court the ball is in.
- `/gh-contrib --repo --issues` — issues only. `--prs` for PRs only.
- `/gh-contrib --repo --json` — raw JSON (for scripting).
- `/gh-contrib --repo --no-glyphs` — ASCII status markers instead of emoji.

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
  plugin does not yet judge whether the failure is caused by your change (that comes with
  AI attribution in a later version).
- **Nudge candidates** — no activity for a while; a good candidate to ping.
- **Waiting on them** — you've responded or pushed since the last review, the PR is
  approved but unmerged, or an RFC is awaiting maintainer engagement.

Classification uses event ordering, not GitHub's raw status: a PR still labeled
"changes requested" is correctly shown as waiting on maintainers once you've pushed
commits addressing the feedback.

Arriving in later versions: current-PR mode (deep view of the PR on your branch),
AI attribution (which failing files are AI-authored, and suggested fixes), org/all
breadth across many repos, and the setup/history commands.

## License

Apache-2.0
