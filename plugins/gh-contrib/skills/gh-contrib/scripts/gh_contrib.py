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
import re
import subprocess
import sys
import time

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


def resolve_repo(runner=None):
    """Resolve the current repo as 'owner/name' from git origin, or exit clearly."""
    origin = _git_origin(runner=runner)
    repo = parse_origin(origin) if origin else None
    if not repo:
        sys.exit(
            "error: not in a GitHub repository (no GitHub 'origin' remote). "
            "Use --all to query your configured cross-repo scope instead."
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


COURT_WAITING_ON_ME = "WAITING_ON_ME"
COURT_WAITING_ON_THEM = "WAITING_ON_THEM"
COURT_STALE_NUDGE = "STALE_NUDGE"
COURT_QUIET = "QUIET"


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


def classify_court(item):
    """Phase-1 placeholder: an item you authored is, by default, awaiting others.

    Phase 2 replaces this with event-ordering logic (review state, CI, base
    movement). Kept intentionally trivial so Phase 1 ships without prematurely
    implementing correctness-critical logic.
    """
    return COURT_WAITING_ON_THEM


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


# court -> (glyph, text marker, section heading, rollup phrase)
COURT_DISPLAY = {
    COURT_WAITING_ON_ME:   ("🔴", "[ME]",    "Waiting on me",     "waiting on you"),
    COURT_STALE_NUDGE:     ("🟡", "[NUDGE]", "Nudge candidates",  "to nudge"),
    COURT_WAITING_ON_THEM: ("🟢", "[THEM]",  "Waiting on them",   "waiting on them"),
    COURT_QUIET:           ("⚪", "[quiet]", "Quiet",             "quiet"),
}
COURT_ORDER = [
    COURT_WAITING_ON_ME, COURT_STALE_NUDGE, COURT_WAITING_ON_THEM, COURT_QUIET,
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


def main(argv=None):
    ns = validate_flags(build_parser().parse_args(argv))

    # Phase 1 supports Level 1 only. --org/--all arrive in Phase 4.
    if ns.org is not None or ns.all:
        sys.exit("error: --org and --all are not available yet (later phase). "
                 "Use --repo for the current repository.")
    if ns.rich:
        sys.exit("error: --rich is not available yet (later phase).")

    repo = canonical_repo(resolve_repo())
    want_prs, want_issues = resolve_types(ns)
    items = fetch_items(repo, want_prs, want_issues)
    for it in items:
        it["court"] = classify_court(it)

    if ns.json:
        print(json.dumps({"repo": repo, "items": items}, indent=2))
        return
    print(render_dense(repo, items, glyphs=not ns.no_glyphs))


if __name__ == "__main__":
    main()
