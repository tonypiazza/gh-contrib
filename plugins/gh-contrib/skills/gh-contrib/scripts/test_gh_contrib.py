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


class TestNormalizeAndClassify(unittest.TestCase):
    def test_normalize_pr(self):
        raw = {"number": 7036, "title": "rss rewrite",
               "url": "https://github.com/o/r/pull/7036",
               "createdAt": "2026-07-01T00:00:00Z",
               "updatedAt": "2026-08-01T00:00:00Z"}
        item = g.normalize_item(raw, kind="pr")
        self.assertEqual(item["number"], 7036)
        self.assertEqual(item["kind"], "pr")
        self.assertEqual(item["url"], "https://github.com/o/r/pull/7036")

    def test_normalize_issue(self):
        raw = {"number": 10, "title": "RFC",
               "url": "https://github.com/o/r/issues/10",
               "createdAt": "2026-07-01T00:00:00Z",
               "updatedAt": "2026-07-02T00:00:00Z"}
        item = g.normalize_item(raw, kind="issue")
        self.assertEqual(item["kind"], "issue")

    def test_classify_court_placeholder_is_waiting_on_them(self):
        item = g.normalize_item(
            {"number": 1, "title": "t", "url": "u",
             "createdAt": "2026-07-01T00:00:00Z",
             "updatedAt": "2026-07-02T00:00:00Z"},
            kind="pr",
        )
        self.assertEqual(g.classify_court(item), "WAITING_ON_THEM")

    def test_dedupe_by_url(self):
        a = g.normalize_item({"number": 1, "title": "t", "url": "same",
                              "createdAt": "x", "updatedAt": "y"}, kind="pr")
        b = g.normalize_item({"number": 1, "title": "t", "url": "same",
                              "createdAt": "x", "updatedAt": "y"}, kind="issue")
        deduped = g.dedupe_by_url([a, b])
        self.assertEqual(len(deduped), 1)


class TestFetchItems(unittest.TestCase):
    def _gh(self, prs, issues):
        def gh(args):
            return prs if "prs" in args else issues
        return gh

    def test_filters_pull_requests_from_issues(self):
        issues = [
            {"number": 1, "url": "u1", "isPullRequest": True},
            {"number": 2, "url": "u2", "isPullRequest": False},
        ]
        out = g.fetch_items("o/r", False, True, gh=self._gh([], issues))
        self.assertEqual([i["number"] for i in out], [2])

    def test_dedupes_across_pr_and_issue_union(self):
        prs = [{"number": 1, "url": "same"}]
        issues = [{"number": 1, "url": "same", "isPullRequest": True}]
        out = g.fetch_items("o/r", True, True, gh=self._gh(prs, issues))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "pr")

    def test_both_false_returns_empty(self):
        out = g.fetch_items("o/r", False, False, gh=self._gh([], []))
        self.assertEqual(out, [])


class TestRenderDense(unittest.TestCase):
    def _items(self):
        return [
            {"kind": "pr", "number": 7036, "title": "rss rewrite",
             "url": "https://github.com/o/r/pull/7036",
             "court": g.COURT_WAITING_ON_THEM},
            {"kind": "issue", "number": 10, "title": "RFC MQTT",
             "url": "https://github.com/o/r/issues/10",
             "court": g.COURT_WAITING_ON_THEM},
        ]

    def test_rollup_line_present(self):
        out = g.render_dense("o/r", self._items(), glyphs=True)
        self.assertIn("2 waiting on them", out)

    def test_glyph_marker_used_by_default(self):
        out = g.render_dense("o/r", self._items(), glyphs=True)
        self.assertIn("🟢", out)

    def test_text_marker_when_glyphs_off(self):
        out = g.render_dense("o/r", self._items(), glyphs=False)
        self.assertIn("[THEM]", out)
        self.assertNotIn("🟢", out)

    def test_titles_and_numbers_render(self):
        out = g.render_dense("o/r", self._items(), glyphs=True)
        self.assertIn("rss rewrite", out)
        self.assertIn("#7036", out)

    def test_empty_is_stated_plainly(self):
        out = g.render_dense("o/r", [], glyphs=True)
        self.assertIn("Nothing open", out)

    def test_unknown_court_falls_into_quiet(self):
        items = [{"kind": "pr", "number": 1, "title": "mystery",
                  "url": "u", "court": "BOGUS"}]
        out = g.render_dense("o/r", items, glyphs=True)
        self.assertIn("## Quiet", out)
        self.assertIn("mystery", out)

    def test_missing_court_key_falls_into_quiet(self):
        items = [{"kind": "pr", "number": 1, "title": "keyless", "url": "u"}]
        out = g.render_dense("o/r", items, glyphs=True)
        self.assertIn("## Quiet", out)
        self.assertIn("keyless", out)

    def test_sections_ordered_me_before_them(self):
        items = [
            {"kind": "pr", "number": 2, "title": "theirs", "url": "u2",
             "court": g.COURT_WAITING_ON_THEM},
            {"kind": "pr", "number": 1, "title": "mine", "url": "u1",
             "court": g.COURT_WAITING_ON_ME},
        ]
        out = g.render_dense("o/r", items, glyphs=True)
        self.assertLess(out.index("Waiting on me"), out.index("Waiting on them"))


if __name__ == "__main__":
    unittest.main()
