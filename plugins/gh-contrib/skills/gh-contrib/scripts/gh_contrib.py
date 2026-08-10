#!/usr/bin/env python3
"""gh-contrib: track your own GitHub PRs/issues via the gh CLI.

Phase 1 (walking skeleton): Level 1 (--repo) only. Lists the authenticated
user's open PRs and issues in the current repository and renders a dense,
court-grouped digest. Court classification is a placeholder in this phase;
event-ordering logic arrives in Phase 2.

Requires the GitHub CLI (`gh`) installed and authenticated (`gh auth status`).
The script always operates as the authenticated user (`@me`) and cannot be
pointed at another account.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

# gh/GitHub errors worth retrying (transient) vs. failing fast (fatal).
TRANSIENT_PATTERN = re.compile(
    r"rate limit|secondary rate|timeout|timed out|502|503|504|"
    r"bad gateway|service unavailable|connection reset|"
    r"could not resolve host|EOF|temporary failure|try again",
    re.IGNORECASE,
)
FATAL_PATTERN = re.compile(
    r"authentication|gh auth login|not resolve to a repository|"
    r"could not resolve to a|HTTP 404|Not Found|permission|forbidden|HTTP 401",
    re.IGNORECASE,
)
MAX_ATTEMPTS = 3
STALE_DAYS = 14  # Phase 2 default; Phase 4 makes this configurable.


def _parse_iso(ts):
    """Parse a GitHub ISO-8601 'Z' timestamp into an aware UTC datetime, or None."""
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def ci_failing_on_head(rollup):
    """True iff any check in the statusCheckRollup has a FAILURE result.

    `gh pr view`'s statusCheckRollup already reflects the head commit's checks.
    CheckRun items carry `conclusion`; StatusContext items carry `state`.
    CANCELLED/SKIPPED/NEUTRAL are not failures (CANCELLED is CI noise).
    """
    for check in rollup or []:
        result = check.get("conclusion") or check.get("state")
        if result == "FAILURE":
            return True
    return False


def last_changes_requested_at(reviews, me):
    """Latest submittedAt among CHANGES_REQUESTED reviews NOT authored by `me`.

    Your own reviews never put the ball in your court, so they are excluded.
    Returns an ISO string or None.
    """
    stamps = [
        r.get("submittedAt")
        for r in (reviews or [])
        if r.get("state") == "CHANGES_REQUESTED"
        and (r.get("author") or {}).get("login") != me
        and r.get("submittedAt")
    ]
    return max(stamps) if stamps else None


def last_author_commit_at(commits):
    """Latest committedDate among the PR's commits. Returns an ISO string or None."""
    stamps = [c.get("committedDate") for c in (commits or []) if c.get("committedDate")]
    return max(stamps) if stamps else None


def extract_pr_signals(detail, me):
    """Derive court-relevant signals from a raw `gh pr view --json` dict (pure).

    `addressed` is True when the author pushed a commit AFTER the maintainer's
    last CHANGES_REQUESTED review — the fix for GitHub's stale reviewDecision.
    """
    cr_at = last_changes_requested_at(detail.get("reviews"), me)
    commit_at = last_author_commit_at(detail.get("commits"))
    addressed = False
    if cr_at and commit_at:
        addressed = _parse_iso(commit_at) > _parse_iso(cr_at)
    return {
        "reviewDecision": detail.get("reviewDecision"),
        "mergeStateStatus": detail.get("mergeStateStatus"),
        "mergeable": detail.get("mergeable"),
        "ciFailing": ci_failing_on_head(detail.get("statusCheckRollup")),
        "changesRequestedAt": cr_at,
        "authorActedAt": commit_at,
        "addressed": addressed,
    }


def _default_runner(args):
    """Run `gh <args>` and return the CompletedProcess (check=True)."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True)


def run_gh(args, runner=_default_runner, sleep=time.sleep, _attempt=1):
    """Run a gh command and return parsed JSON stdout.

    `runner` and `sleep` are injectable for testing. Transient failures retry
    with exponential backoff; fatal errors exit with a clear message.
    """
    try:
        result = runner(args)
    except FileNotFoundError:
        sys.exit("error: the GitHub CLI ('gh') is not installed or not on PATH.")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if FATAL_PATTERN.search(stderr):
            if "auth" in stderr.lower():
                sys.exit("error: gh is not authenticated. Run 'gh auth login'.")
            sys.exit(f"error: gh command failed: {stderr}")
        if _attempt < MAX_ATTEMPTS and (TRANSIENT_PATTERN.search(stderr) or not stderr):
            sleep(2 ** (_attempt - 1))
            return run_gh(args, runner=runner, sleep=sleep, _attempt=_attempt + 1)
        sys.exit(f"error: gh command failed after {_attempt} attempt(s): {stderr}")

    out = (result.stdout or "").strip()
    if not out:
        # gh can exit 0 with no stdout during a transient hiccup; retry.
        if _attempt < MAX_ATTEMPTS:
            sleep(2 ** (_attempt - 1))
            return run_gh(args, runner=runner, sleep=sleep, _attempt=_attempt + 1)
        sys.exit("error: gh returned empty output after retries.")
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # gh can exit 0 with truncated/partial stdout during a transient
        # hiccup; the partial read fails to parse now but a retry usually
        # returns complete, parseable JSON.
        if _attempt < MAX_ATTEMPTS:
            sleep(2 ** (_attempt - 1))
            return run_gh(args, runner=runner, sleep=sleep, _attempt=_attempt + 1)
        sys.exit("error: gh returned output that could not be parsed as JSON.")


_ORIGIN_RE = re.compile(
    r"(?:^|@|/|//)github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$"
)


def parse_origin(url):
    """Parse a GitHub git remote URL into 'owner/name', or None if not GitHub."""
    if not url:
        return None
    m = _ORIGIN_RE.search(url.strip())
    if not m:
        return None
    return f"{m.group('owner')}/{m.group('name')}"


def _default_git_runner(args):
    """Run `git <args>` and return the CompletedProcess."""
    return subprocess.run(args, capture_output=True, text=True)


def _git_origin(runner=None):
    """Return the origin remote URL, or None if not in a git repo / no origin.

    `runner` is injectable for testing and is called as `runner(["git", ...])`,
    returning an object with `.returncode` and `.stdout`.
    """
    try:
        proc = (runner or _default_git_runner)(
            ["git", "remote", "get-url", "origin"]
        )
    except FileNotFoundError:
        sys.exit("error: git is not installed or not on PATH.")
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _default_branch_runner(args):
    return subprocess.run(args, capture_output=True, text=True)


def current_branch(runner=None):
    """Return the working directory's git branch, or None.

    None when detached (branch reads as 'HEAD') or not in a git repo.
    Injectable runner for testing; called positionally with the args list.
    """
    proc = (runner or _default_branch_runner)(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if proc.returncode != 0:
        return None
    branch = (proc.stdout or "").strip()
    if not branch or branch == "HEAD":
        return None
    return branch


def resolve_repo(runner=None):
    """Resolve the current repo as 'owner/name' from git origin, or exit clearly."""
    origin = _git_origin(runner=runner)
    repo = parse_origin(origin) if origin else None
    if not repo:
        sys.exit(
            "error: not in a GitHub repository (no GitHub 'origin' remote). "
            "Run this from inside a checkout of a repo you contribute to."
        )
    return repo


def canonical_repo(repo, gh=run_gh):
    """Resolve a fork to its upstream parent 'owner/name'.

    External contributors' origin is usually their fork; their PRs/issues live
    on the upstream repo they forked from. Ask GitHub for the parent and use it
    when `repo` is a fork; otherwise return `repo` unchanged.
    """
    info = gh(["repo", "view", repo, "--json", "isFork,parent"])
    if info.get("isFork") and info.get("parent"):
        parent = info["parent"]
        owner = (parent.get("owner") or {}).get("login")
        name = parent.get("name")
        if owner and name:
            return f"{owner}/{name}"
    return repo


def transcript_dir(cwd, env=None):
    """Path to this repo's Claude Code transcript directory (pure).

    Base is $CLAUDE_CONFIG_DIR/projects if set, else $HOME/.claude/projects.
    The per-project slug is the absolute cwd with '/' and '.' both -> '-'.
    """
    env = env if env is not None else os.environ
    config_dir = env.get("CLAUDE_CONFIG_DIR")
    base = (config_dir + "/projects") if config_dir \
        else env.get("HOME", "") + "/.claude/projects"
    slug = cwd.replace("/", "-").replace(".", "-")
    return f"{base}/{slug}"


SNAPSHOT_MAX_AGE_DAYS = 30  # older baseline -> suppress the "since last run" delta


def state_dir(env=None):
    """Directory holding per-scope snapshots. $GH_CONTRIB_HOME/state or ~/.gh-contrib/state."""
    env = env if env is not None else os.environ
    home = env.get("GH_CONTRIB_HOME") or (env.get("HOME", "") + "/.gh-contrib")
    return f"{home}/state"


def snapshot_path(scope_id, env=None):
    """Filesystem path for a scope's snapshot (scope id sanitized for the filename)."""
    safe = re.sub(r"[/:#]+", "-", scope_id)
    return f"{state_dir(env=env)}/{safe}.json"


_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _default_lister(directory):
    import glob
    return glob.glob(f"{directory}/*.jsonl")


def _default_opener(path):
    with open(path) as fh:
        yield from fh


def claude_touched_files(cwd, opener=None, lister=None, env=None):
    """Map of files Claude edited in `cwd` to the model(s) that edited them.

    Returns {repo-relative path: sorted list of model ids}. Mines assistant
    tool_use records (Edit/Write/MultiEdit/NotebookEdit) for file_path, keeps
    only paths under cwd, and records `message.model` (or "unknown"). A file
    edited by multiple models across sessions lists all of them. Tolerates a
    missing dir and malformed lines. lister/opener are injectable for testing.
    """
    lister = lister or _default_lister
    opener = opener or _default_opener
    prefix = cwd.rstrip("/") + "/"
    touched = {}  # path -> set of models
    for path in lister(transcript_dir(cwd, env=env)):
        try:
            lines = opener(path)
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            model = msg.get("model") or "unknown"
            for block in (msg.get("content") or []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in _EDIT_TOOLS:
                    fp = (block.get("input") or {}).get("file_path")
                    if isinstance(fp, str) and fp.startswith(prefix):
                        touched.setdefault(fp[len(prefix):], set()).add(model)
    return {path: sorted(models) for path, models in touched.items()}


def pr_changed_files(repo, number, gh=run_gh):
    """Repo-relative paths of a PR's changed files."""
    detail = gh(["pr", "view", str(number), "--repo", repo, "--json", "files"])
    return [f["path"] for f in (detail.get("files") or [])]


def attributed_files(touched, changed):
    """Changed files that Claude touched, with their model(s) (pure).

    `touched` is the {path: [models]} map from claude_touched_files. Returns a
    sorted list of {"path", "models"} for each changed file present in the map.
    """
    return [
        {"path": p, "models": touched[p]}
        for p in sorted(changed)
        if p in touched
    ]


def resolve_login(runner=None):
    """Return the authenticated user's login (for excluding their own reviews).

    Uses a raw subprocess call (not run_gh): `gh api user --jq .login` emits a
    bare word, not JSON, so it must not go through run_gh's json parsing.
    """
    def _default(args):
        import subprocess as _sp
        return _sp.run(args, capture_output=True, text=True)

    proc = (runner or _default)(["gh", "api", "user", "--jq", ".login"])
    if proc.returncode != 0:
        sys.exit("error: could not determine the authenticated gh user.")
    return (proc.stdout or "").strip()


COURT_WAITING_ON_ME = "WAITING_ON_ME"
COURT_WAITING_ON_THEM = "WAITING_ON_THEM"
COURT_STALE_NUDGE = "STALE_NUDGE"
COURT_QUIET = "QUIET"
COURT_CI_SUSPECT = "CI_SUSPECT"


def normalize_item(raw, kind):
    """Normalize a gh search result into the common item shape."""
    return {
        "kind": kind,  # "pr" or "issue"
        "number": raw.get("number"),
        "title": raw.get("title") or "",
        "url": raw.get("url") or "",
        "createdAt": raw.get("createdAt"),
        "updatedAt": raw.get("updatedAt"),
    }


def _is_stale(item, now, stale_days):
    updated = _parse_iso(item.get("updatedAt"))
    if not updated:
        return False
    return (now - updated).days >= stale_days


def classify_court(item, now, stale_days=STALE_DAYS):
    """Decide whose court an item is in (pure; event-ordering, not raw status).

    PRs read signals merged by `extract_pr_signals`. Precedence (first match):
      1. unaddressed changes requested          -> WAITING_ON_ME
      2. base moved / conflicts (behind/dirty)  -> WAITING_ON_ME
      3. CI failing on head                     -> CI_SUSPECT (not pinned; Phase 3 attributes)
      4. approved, not merged (unless stale)      -> WAITING_ON_THEM
      5. addressed changes requested (unless stale) -> WAITING_ON_THEM
      6. no activity in stale_days              -> STALE_NUDGE
      7. otherwise                              -> WAITING_ON_THEM
    Issues skip PR-only rules and classify on staleness alone.

    now must be a timezone-aware (UTC) datetime.
    """
    if item.get("kind") == "pr":
        decision = item.get("reviewDecision")
        if decision == "CHANGES_REQUESTED" and not item.get("addressed"):
            return COURT_WAITING_ON_ME
        if (item.get("mergeStateStatus") in ("BEHIND", "DIRTY")
                or item.get("mergeable") == "CONFLICTING"):
            return COURT_WAITING_ON_ME
        if item.get("ciFailing"):
            return COURT_CI_SUSPECT
        if decision == "APPROVED" and not _is_stale(item, now, stale_days):
            return COURT_WAITING_ON_THEM
        if decision == "CHANGES_REQUESTED" and item.get("addressed") \
                and not _is_stale(item, now, stale_days):
            return COURT_WAITING_ON_THEM
    if _is_stale(item, now, stale_days):
        return COURT_STALE_NUDGE
    return COURT_WAITING_ON_THEM


def describe_pr_state(pr):
    """Ordered human-readable status phrases for an enriched PR (pure).

    Always returns at least one line.
    """
    lines = []
    decision = pr.get("reviewDecision")
    if decision == "CHANGES_REQUESTED" and not pr.get("addressed"):
        lines.append("Changes requested — not yet addressed")
    elif decision == "CHANGES_REQUESTED" and pr.get("addressed"):
        lines.append("Changes addressed — awaiting re-review")
    elif decision == "APPROVED":
        lines.append("Approved — not yet merged")
    else:  # None, REVIEW_REQUIRED, or any other value -> awaiting review
        lines.append("Awaiting review")

    if pr.get("mergeStateStatus") == "BEHIND":
        lines.append("Base branch moved ahead — update/rebase needed")
    if pr.get("mergeStateStatus") == "DIRTY" or pr.get("mergeable") == "CONFLICTING":
        lines.append("Merge conflicts — resolve needed")

    if pr.get("ciFailing"):
        lines.append("CI failing on latest commit — check whether it's yours")
    return lines


def dedupe_by_url(items):
    """Drop duplicate items sharing a URL, preserving first-seen order."""
    seen = set()
    out = []
    for it in items:
        key = it.get("url")
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def fetch_items(repo, want_prs, want_issues, gh=run_gh):
    """Fetch the authenticated user's open PRs/issues in `repo` as @me."""
    items = []
    if want_prs:
        prs = gh([
            "search", "prs", "--author=@me", f"--repo={repo}",
            "--state=open", "--json", "number,title,url,createdAt,updatedAt",
        ])
        items.extend(normalize_item(p, kind="pr") for p in prs)
    if want_issues:
        issues = gh([
            "search", "issues", "--author=@me", f"--repo={repo}",
            "--state=open", "--json",
            "number,title,url,createdAt,updatedAt,isPullRequest",
        ])
        # gh search issues can include PRs; keep only true issues.
        items.extend(
            normalize_item(i, kind="issue")
            for i in issues if not i.get("isPullRequest")
        )
    return dedupe_by_url(items)


_PR_DETAIL_FIELDS = ("number,reviewDecision,mergeable,mergeStateStatus,"
                     "updatedAt,isDraft,reviews,commits,statusCheckRollup")


def enrich_item(item, repo, me, gh=run_gh):
    """For a PR, fetch detail and merge court signals onto the item.

    Issues have no reviews/CI/merge state, so they pass through unchanged.
    """
    if item.get("kind") != "pr":
        return item
    detail = gh([
        "pr", "view", str(item["number"]), "--repo", repo,
        "--json", _PR_DETAIL_FIELDS,
    ])
    item.update(extract_pr_signals(detail, me))
    return item


def resolve_current_pr(repo, branch, gh=run_gh):
    """Return the user's open PRs in `repo` whose head branch is `branch`.

    Normally length 0 (branch has no PR of yours) or 1. Length >1 is rare
    (multiple open PRs sharing a head branch) and handled by the caller.
    """
    raw = gh([
        "pr", "list", f"--repo={repo}", f"--head={branch}",
        "--author=@me", "--state=open",
        "--json", "number,title,url,createdAt,updatedAt",
    ])
    return [normalize_item(p, kind="pr") for p in raw]


_FOOTER_COURTS = (COURT_WAITING_ON_ME, COURT_CI_SUSPECT)


def other_prs_needing_attention(repo, me, exclude_number, now, gh=run_gh):
    """The user's other open PRs in `repo` currently needing attention.

    Excludes `exclude_number` (the PR shown in full). Enriches + classifies each
    and keeps only WAITING_ON_ME / CI_SUSPECT. This is a current-state check, not
    a since-last-run delta (the delta arrives with the Phase-4 snapshot).
    """
    raw = gh([
        "pr", "list", f"--repo={repo}", "--author=@me", "--state=open",
        "--json", "number,title,url,createdAt,updatedAt",
    ])
    out = []
    for p in raw:
        if p.get("number") == exclude_number:
            continue
        item = normalize_item(p, kind="pr")
        enrich_item(item, repo, me, gh=gh)
        item["court"] = classify_court(item, now)
        if item["court"] in _FOOTER_COURTS:
            out.append(item)
    return out


# court -> (glyph, text marker, section heading, rollup phrase)
COURT_DISPLAY = {
    COURT_WAITING_ON_ME:   ("🔴", "[ME]",    "Waiting on me",     "waiting on you"),
    COURT_CI_SUSPECT:      ("🟠", "[CI?]",   "CI suspect (check it)", "CI suspect"),
    COURT_STALE_NUDGE:     ("🟡", "[NUDGE]", "Nudge candidates",  "to nudge"),
    COURT_WAITING_ON_THEM: ("🟢", "[THEM]",  "Waiting on them",   "waiting on them"),
    COURT_QUIET:           ("⚪", "[quiet]", "Quiet",             "quiet"),
}
COURT_ORDER = [
    COURT_WAITING_ON_ME, COURT_CI_SUSPECT, COURT_STALE_NUDGE,
    COURT_WAITING_ON_THEM, COURT_QUIET,
]


def _marker(court, glyphs):
    glyph, text, _, _ = COURT_DISPLAY[court]
    return glyph if glyphs else text


def render_dense(repo, items, glyphs=True):
    """Render items as a dense, court-grouped markdown digest string."""
    if not items:
        return f"**{repo}** — Nothing open of yours here.\n"

    by_court = {c: [] for c in COURT_ORDER}
    for it in items:
        by_court.get(it.get("court"), by_court[COURT_QUIET]).append(it)

    rollup = " · ".join(
        f"{len(by_court[c])} {COURT_DISPLAY[c][3]}"
        for c in COURT_ORDER if by_court[c]
    )
    lines = [f"**{repo}** — {rollup}", ""]
    for court in COURT_ORDER:
        group = by_court[court]
        if not group:
            continue
        lines.append(f"## {COURT_DISPLAY[court][2]}")
        for it in group:
            marker = _marker(court, glyphs)
            lines.append(f"- {marker} {it['title']} · #{it['number']} · {it['url']}")
        lines.append("")
    return "\n".join(lines)


def render_pr_detail(repo, pr, others, glyphs=True):
    """Render the Level-0 focused view: one PR in depth + an exception-only footer."""
    marker = _marker(pr["court"], glyphs)
    lines = [
        f"**{repo}** — current PR",
        "",
        f"{marker} **#{pr['number']} {pr['title']}**",
        pr["url"],
        "",
    ]
    for phrase in describe_pr_state(pr):
        lines.append(f"- {phrase}")

    ai_files = pr.get("aiAuthoredFiles") or []
    if ai_files:
        lines.append("")
        lines.append(f"**AI-authored files in this PR ({len(ai_files)}):**")
        for entry in ai_files:
            models = ", ".join(entry.get("models") or ["unknown"])
            lines.append(f"- {entry['path']} ({models})")
        lines.append("_Attribution is file-level (from local session history) — it "
                     "shows where to focus your review and which model wrote the code, "
                     "not that a specific line is the bug._")

    if others:
        refs = ", ".join(f"#{p['number']}" for p in others)
        lines.append("")
        lines.append(
            f"⚠ {len(others)} other open PR(s) need attention: {refs} "
            f"— run `/gh-contrib --repo` for the full list."
        )
    return "\n".join(lines) + "\n"


def build_parser():
    p = argparse.ArgumentParser(
        prog="gh_contrib.py",
        description="Track your own GitHub PRs/issues via the gh CLI.",
    )
    # Scope flags (mutually exclusive; validated in validate_flags).
    p.add_argument("--repo", action="store_true",
                   help="whole current repo (Level 1)")
    p.add_argument("--org", nargs="?", const=True, default=None,
                   help="current repo's org, or a named org (Level 2) [later phase]")
    p.add_argument("--all", action="store_true",
                   help="configured digest scope (Level 3) [later phase]")
    # Type filters.
    p.add_argument("--issues", action="store_true", help="issues only")
    p.add_argument("--prs", action="store_true", help="PRs only")
    # Output.
    p.add_argument("--rich", action="store_true",
                   help="per-item reasoning [later phase]")
    p.add_argument("--json", action="store_true", help="raw JSON output")
    p.add_argument("--no-glyphs", action="store_true",
                   help="ASCII court markers instead of emoji")
    return p


def validate_flags(ns):
    """Reject incoherent flag combinations with a clear message."""
    scope_flags = [bool(ns.repo), ns.org is not None, bool(ns.all)]
    if sum(scope_flags) > 1:
        sys.exit("error: choose at most one scope flag (--repo, --org, --all).")
    if ns.issues and ns.prs:
        sys.exit("error: --issues and --prs are mutually exclusive.")
    if ns.rich and ns.json:
        sys.exit("error: --rich and --json are mutually exclusive.")
    return ns


def resolve_types(ns):
    """Return (want_prs, want_issues). No type flag -> both."""
    if ns.issues:
        return (False, True)
    if ns.prs:
        return (True, False)
    return (True, True)


def level0_eligible(ns):
    """True when the bare command should try current-PR mode (Level 0).

    Any scope flag (--repo/--org/--all) or --issues forces a wider/other view.
    """
    return not (ns.repo or ns.org is not None or ns.all or ns.issues)


def main(argv=None):
    ns = validate_flags(build_parser().parse_args(argv))

    # Phase 1 supports Level 1 only. --org/--all arrive in Phase 4.
    if ns.org is not None or ns.all:
        sys.exit("error: --org and --all are not available yet (later phase). "
                 "Use --repo for the current repository.")
    if ns.rich:
        sys.exit("error: --rich is not available yet (later phase).")

    repo = canonical_repo(resolve_repo())
    me = resolve_login()
    now = datetime.now(timezone.utc)

    # Level 0: current-PR mode — a branch mapping to your open PR(s).
    # Exactly one -> focused view; more than one -> ask; none -> fall through.
    if level0_eligible(ns):
        branch = current_branch()
        prs = resolve_current_pr(repo, branch) if branch else []
        if len(prs) == 1:
            pr = prs[0]
            enrich_item(pr, repo, me)
            pr["court"] = classify_court(pr, now)
            touched = claude_touched_files(os.getcwd())
            pr["aiAuthoredFiles"] = attributed_files(
                touched, pr_changed_files(repo, pr["number"]))
            others = other_prs_needing_attention(repo, me, pr["number"], now)
            if ns.json:
                print(json.dumps({"repo": repo, "currentPr": pr,
                                  "othersNeedingAttention": others}, indent=2))
                return
            print(render_pr_detail(repo, pr, others, glyphs=not ns.no_glyphs))
            return
        if len(prs) > 1:
            refs = ", ".join(f"#{p['number']}" for p in prs)
            sys.exit(f"Multiple open PRs on this branch ({refs}). "
                     f"Run `/gh-contrib --repo` to see them all.")
        # len 0 -> fall through to the repo-wide (Level 1) view.

    want_prs, want_issues = resolve_types(ns)
    items = fetch_items(repo, want_prs, want_issues)
    for it in items:
        enrich_item(it, repo, me)
        it["court"] = classify_court(it, now)

    if ns.json:
        print(json.dumps({"repo": repo, "items": items}, indent=2))
        return
    print(render_dense(repo, items, glyphs=not ns.no_glyphs))


if __name__ == "__main__":
    main()
