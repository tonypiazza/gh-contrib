import json
import unittest
import gh_contrib as g


class FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def make_runner(responses):
    """Return a runner callable that pops queued (result-or-exception) items."""
    queue = list(responses)

    def runner(args):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return runner


class TestRunGh(unittest.TestCase):
    def test_parses_json_stdout(self):
        runner = make_runner([FakeCompleted(stdout='[{"n": 1}]')])
        out = g.run_gh(["search", "prs"], runner=runner, sleep=lambda s: None)
        self.assertEqual(out, [{"n": 1}])

    def test_fatal_auth_error_exits(self):
        import subprocess
        err = subprocess.CalledProcessError(1, "gh", stderr="gh auth login required")
        runner = make_runner([err])
        with self.assertRaises(SystemExit) as ctx:
            g.run_gh(["search", "prs"], runner=runner, sleep=lambda s: None)
        self.assertIn("gh auth login", str(ctx.exception))

    def test_transient_then_success_retries(self):
        import subprocess
        err = subprocess.CalledProcessError(1, "gh", stderr="rate limit exceeded")
        runner = make_runner([err, FakeCompleted(stdout='{"ok": true}')])
        out = g.run_gh(["api", "x"], runner=runner, sleep=lambda s: None)
        self.assertEqual(out, {"ok": True})

    def test_missing_gh_binary_exits(self):
        runner = make_runner([FileNotFoundError()])
        with self.assertRaises(SystemExit) as ctx:
            g.run_gh(["search", "prs"], runner=runner, sleep=lambda s: None)
        self.assertIn("not installed", str(ctx.exception))

    def test_backoff_sleep_values(self):
        import subprocess
        errs = [subprocess.CalledProcessError(1, "gh", stderr="rate limit"),
                subprocess.CalledProcessError(1, "gh", stderr="rate limit")]
        runner = make_runner(errs + [FakeCompleted(stdout='{"ok": true}')])
        slept = []
        out = g.run_gh(["api", "x"], runner=runner, sleep=slept.append)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(slept, [1, 2])  # 2**0, 2**1


class TestResolveRepo(unittest.TestCase):
    def test_ssh_url(self):
        self.assertEqual(
            g.parse_origin("git@github.com:opensearch-project/data-prepper.git"),
            "opensearch-project/data-prepper",
        )

    def test_https_url(self):
        self.assertEqual(
            g.parse_origin("https://github.com/tonypiazza/gh-metrics.git"),
            "tonypiazza/gh-metrics",
        )

    def test_https_url_no_suffix(self):
        self.assertEqual(
            g.parse_origin("https://github.com/acme/widget"),
            "acme/widget",
        )

    def test_non_github_returns_none(self):
        self.assertIsNone(g.parse_origin("git@gitlab.com:acme/widget.git"))

    def test_empty_returns_none(self):
        self.assertIsNone(g.parse_origin(""))

    def test_resolve_repo_success(self):
        runner = make_runner([FakeCompleted(
            stdout="https://github.com/acme/widget.git", returncode=0)])
        self.assertEqual(g.resolve_repo(runner=runner), "acme/widget")

    def test_resolve_repo_no_origin_exits(self):
        runner = make_runner([FakeCompleted(returncode=1)])
        with self.assertRaises(SystemExit) as ctx:
            g.resolve_repo(runner=runner)
        self.assertIn("--all", str(ctx.exception))

    def test_resolve_repo_non_github_exits(self):
        runner = make_runner([FakeCompleted(
            stdout="git@gitlab.com:acme/widget.git", returncode=0)])
        with self.assertRaises(SystemExit):
            g.resolve_repo(runner=runner)


if __name__ == "__main__":
    unittest.main()
