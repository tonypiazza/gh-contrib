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


if __name__ == "__main__":  # pragma: no cover - wired up in Task 6
    pass
