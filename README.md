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

Phase 1 (walking skeleton): current-repo listing (`--repo`) with a court-grouped
digest. Court intelligence, current-PR mode, AI attribution, org/all breadth, and
the setup/history commands arrive in later versions.
