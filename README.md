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
- `/gh-contrib --org [NAME]` — your open PRs and issues across a whole org: the current
  repo's org, or a named one (`--org acme`). Items are grouped by court and labeled with
  their repository.
- `/gh-contrib --all` — your open items across the digest scope you configured with
  `/gh-contrib-setup` (orgs, repos, involvement modes). Run setup first to define it.
- `/gh-contrib --json` — raw JSON (for scripting); works with any of the above.
- `/gh-contrib --no-glyphs` — ASCII status markers instead of emoji.

**Breadth cost & scope.** `--org`/`--all` run one GitHub search per (org/repo × involvement
mode), so a broad `--all` scope means more calls; keep the configured scope focused. In
breadth views the plugin shows each item's current court but does **not** compute the
"what changed since last run" delta or AI attribution — those need a local checkout and
are only available in the repo and current-PR views.

You can also just ask in natural language ("what's the status of my PRs here?").

**Working from a fork?** That's the common case for open-source contributors. The
plugin detects when your `origin` is a fork and automatically resolves to the
upstream repository you forked from, so it finds the PRs and issues you actually
opened there.

## Configuration

Configuration is **optional** — with no config file the plugin uses sensible defaults
(staleness threshold 14 days, emoji glyphs on). Run `/gh-contrib-setup` to create or
update `~/.gh-contrib/config.json`:

```json
{
  "digestScope": {"orgs": [], "repos": [], "involvement": ["authored"]},
  "thresholds": {"staleDays": 14},
  "display": {"glyphs": true}
}
```

- **`thresholds.staleDays`** — how many days without activity before an item is a
  "nudge" candidate.
- **`display.glyphs`** — emoji status markers (`true`) or ASCII markers like `[ME]`
  (`false`). The `--no-glyphs` flag overrides this per-run.
- **`digestScope`** — the orgs, repos, and involvement modes (`authored`, `involves`,
  `review-requested`, `assignee`) that `/gh-contrib --all` surveys.

The config is read tolerantly: a missing, partial, or malformed file falls back to
defaults rather than erroring. No account is stored — the plugin always operates as the
authenticated `gh` user.

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
currently need attention.

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

**What changed since your last run.** Each run leads with a short delta: PRs **merged**
(celebrated) or closed since you last looked, items whose court flipped, and newly-appeared
items. This is backed by a single local snapshot per scope under `~/.gh-contrib/state/`. It
compares against your *immediately previous* run only (not dated history); if you haven't
run in over a month the baseline is treated as stale and the delta is suppressed in favor
of the current state. A merge that both opened and completed between two runs won't appear,
since it was never seen open — an accepted limit of the single-snapshot design.

**Breadth (`--org` / `--all`).** Beyond a single repo, `--org [NAME]` surveys your open
PRs/issues across an org and `--all` across your configured digest scope — grouped by
court, each item labeled with its repository. Breadth shows current court only (no delta
or AI attribution, which need a local checkout).

Arriving in later versions: the `/gh-contrib-history` command (a chronological timeline
for a single PR or issue).

## License

Apache-2.0
