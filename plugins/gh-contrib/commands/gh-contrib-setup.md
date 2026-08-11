---
description: Configure gh-contrib — set your digest scope, staleness threshold, and display preferences. Writes ~/.gh-contrib/config.json. Re-run anytime to change settings.
allowed-tools: Bash(gh auth status:*), Bash(gh api user:*), Write, Read
---

Set up or update the user's gh-contrib configuration.

## Steps

1. **Verify gh is authenticated.** Run `gh auth status`. If it fails, stop and tell
   the user to run `gh auth login` — do not write any config.
2. **Show the account.** Run `gh api user --jq .login` and tell the user which account
   gh-contrib will operate as (it always operates as the authenticated user; this is not
   configurable).
3. **Read any existing config** at `~/.gh-contrib/config.json` (it may not exist) so you
   can show current values and preserve unspecified ones.
4. **Ask the user** (one topic at a time; offer the current/default value for each):
   - **Digest scope** for `/gh-contrib --all` — which orgs and/or explicit `owner/repo`
     entries to survey, and which involvement modes (`authored`, `involves`,
     `review-requested`, `assignee`; default `["authored"]`).
   - **Staleness threshold** in days (`thresholds.staleDays`, default 14) — how long
     without activity before an item is a "nudge" candidate.
   - **Display** — emoji glyphs on or off (`display.glyphs`, default true).
5. **Write** `~/.gh-contrib/config.json` with this exact shape (fill from the answers,
   keeping defaults for anything unspecified):

   ```json
   {
     "digestScope": {"orgs": [], "repos": [], "involvement": ["authored"]},
     "thresholds": {"staleDays": 14},
     "display": {"glyphs": true}
   }
   ```

6. **Confirm** what was written and where. Note that settings take effect on the next
   `/gh-contrib` run, and that `digestScope` is what `/gh-contrib --all` surveys.

Notes: never store an account/username in the config (the tool always uses the
authenticated gh user). The config is optional — the plugin works with defaults if this is
never run. Re-running this command updates the file.
