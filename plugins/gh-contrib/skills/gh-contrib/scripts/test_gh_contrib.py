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


if __name__ == "__main__":
    unittest.main()
