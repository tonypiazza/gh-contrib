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
        self.assertIn("not in a GitHub repository", str(ctx.exception))

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

    def test_ci_suspect_renders_with_marker(self):
        items = [{"kind": "pr", "number": 5, "title": "flaky",
                  "url": "u", "court": g.COURT_CI_SUSPECT}]
        out = g.render_dense("o/r", items, glyphs=True)
        self.assertIn("🟠", out)
        self.assertIn("CI suspect", out)


class TestArgParsing(unittest.TestCase):
    def test_issues_and_prs_together_rejected(self):
        with self.assertRaises(SystemExit):
            g.validate_flags(g.build_parser().parse_args(["--issues", "--prs"]))

    def test_two_scope_flags_rejected(self):
        with self.assertRaises(SystemExit):
            g.validate_flags(g.build_parser().parse_args(["--repo", "--all"]))

    def test_rich_and_json_rejected(self):
        with self.assertRaises(SystemExit):
            g.validate_flags(g.build_parser().parse_args(["--rich", "--json"]))

    def test_default_wants_both_types(self):
        ns = g.build_parser().parse_args([])
        want_prs, want_issues = g.resolve_types(ns)
        self.assertTrue(want_prs and want_issues)

    def test_issues_only(self):
        ns = g.build_parser().parse_args(["--issues"])
        want_prs, want_issues = g.resolve_types(ns)
        self.assertEqual((want_prs, want_issues), (False, True))


class TestCanonicalRepo(unittest.TestCase):
    def test_fork_resolves_to_parent(self):
        def gh(args):
            return {"isFork": True,
                    "parent": {"name": "data-prepper",
                               "owner": {"login": "opensearch-project"}}}
        self.assertEqual(
            g.canonical_repo("tonypiazza/data-prepper", gh=gh),
            "opensearch-project/data-prepper",
        )

    def test_non_fork_returns_input(self):
        def gh(args):
            return {"isFork": False, "parent": None}
        self.assertEqual(
            g.canonical_repo("acme/widget", gh=gh),
            "acme/widget",
        )

    def test_fork_missing_parent_falls_back_to_input(self):
        # Defensive: isFork true but parent somehow absent -> keep input.
        def gh(args):
            return {"isFork": True, "parent": None}
        self.assertEqual(
            g.canonical_repo("x/y", gh=gh),
            "x/y",
        )


class TestCiAndTime(unittest.TestCase):
    def test_parse_iso_roundtrip(self):
        dt = g._parse_iso("2026-08-06T15:10:54Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 15)
        self.assertIsNotNone(dt.tzinfo)

    def test_parse_iso_none(self):
        self.assertIsNone(g._parse_iso(None))
        self.assertIsNone(g._parse_iso(""))

    def test_ci_failing_true_on_failure(self):
        rollup = [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"},
                  {"conclusion": "CANCELLED"}]
        self.assertTrue(g.ci_failing_on_head(rollup))

    def test_ci_failing_false_without_failure(self):
        rollup = [{"conclusion": "SUCCESS"}, {"conclusion": "CANCELLED"},
                  {"conclusion": "SKIPPED"}, {"conclusion": "NEUTRAL"}]
        self.assertFalse(g.ci_failing_on_head(rollup))

    def test_ci_failing_statuscontext_state(self):
        rollup = [{"state": "FAILURE"}]
        self.assertTrue(g.ci_failing_on_head(rollup))

    def test_ci_failing_empty(self):
        self.assertFalse(g.ci_failing_on_head([]))
        self.assertFalse(g.ci_failing_on_head(None))


class TestEventOrderingSignals(unittest.TestCase):
    def _reviews(self):
        return [
            {"author": {"login": "maint"}, "state": "CHANGES_REQUESTED",
             "submittedAt": "2026-08-01T10:00:00Z"},
            {"author": {"login": "maint"}, "state": "CHANGES_REQUESTED",
             "submittedAt": "2026-08-06T15:10:54Z"},
            {"author": {"login": "me"}, "state": "COMMENTED",
             "submittedAt": "2026-08-06T15:32:44Z"},
        ]

    def test_last_changes_requested_ignores_me(self):
        reviews = self._reviews() + [
            {"author": {"login": "me"}, "state": "CHANGES_REQUESTED",
             "submittedAt": "2026-08-09T00:00:00Z"}]
        self.assertEqual(
            g.last_changes_requested_at(reviews, "me"),
            "2026-08-06T15:10:54Z",
        )

    def test_last_changes_requested_latest_wins(self):
        self.assertEqual(
            g.last_changes_requested_at(self._reviews(), "me"),
            "2026-08-06T15:10:54Z",
        )

    def test_last_changes_requested_none(self):
        reviews = [{"author": {"login": "maint"}, "state": "APPROVED",
                    "submittedAt": "2026-08-01T10:00:00Z"}]
        self.assertIsNone(g.last_changes_requested_at(reviews, "me"))
        self.assertIsNone(g.last_changes_requested_at([], "me"))

    def test_last_author_commit_latest(self):
        commits = [
            {"committedDate": "2026-08-01T02:55:13Z"},
            {"committedDate": "2026-08-06T15:32:11Z"},
            {"committedDate": "2026-08-04T23:40:01Z"},
        ]
        self.assertEqual(
            g.last_author_commit_at(commits), "2026-08-06T15:32:11Z")

    def test_last_author_commit_none(self):
        self.assertIsNone(g.last_author_commit_at([]))
        self.assertIsNone(g.last_author_commit_at(None))


class TestExtractPrSignals(unittest.TestCase):
    def _detail(self, **over):
        d = {
            "reviewDecision": "CHANGES_REQUESTED",
            "mergeStateStatus": "BLOCKED",
            "mergeable": "MERGEABLE",
            "reviews": [
                {"author": {"login": "maint"}, "state": "CHANGES_REQUESTED",
                 "submittedAt": "2026-08-06T15:10:54Z"}],
            "commits": [
                {"committedDate": "2026-08-06T15:32:11Z"}],
            "statusCheckRollup": [{"conclusion": "FAILURE"}],
        }
        d.update(over)
        return d

    def test_addressed_true_when_commit_after_cr(self):
        s = g.extract_pr_signals(self._detail(), "me")
        self.assertTrue(s["addressed"])  # commit 15:32 > CR 15:10

    def test_addressed_false_when_no_commit_after_cr(self):
        s = g.extract_pr_signals(
            self._detail(commits=[{"committedDate": "2026-08-01T00:00:00Z"}]), "me")
        self.assertFalse(s["addressed"])

    def test_addressed_false_when_no_changes_requested(self):
        s = g.extract_pr_signals(
            self._detail(reviews=[], reviewDecision="APPROVED"), "me")
        self.assertFalse(s["addressed"])  # nothing to address

    def test_ci_failing_surfaced(self):
        s = g.extract_pr_signals(self._detail(), "me")
        self.assertTrue(s["ciFailing"])

    def test_merge_state_surfaced(self):
        s = g.extract_pr_signals(self._detail(mergeStateStatus="DIRTY"), "me")
        self.assertEqual(s["mergeStateStatus"], "DIRTY")


import datetime as _dt

NOW = _dt.datetime(2026, 8, 10, tzinfo=_dt.timezone.utc)


def _pr(**signals):
    item = {"kind": "pr", "number": 1, "title": "t", "url": "u",
            "updatedAt": "2026-08-09T00:00:00Z"}
    item.update(signals)
    return item


class TestClassifyCourt(unittest.TestCase):
    def test_unaddressed_changes_requested_is_me(self):
        it = _pr(reviewDecision="CHANGES_REQUESTED", addressed=False,
                 mergeStateStatus="BLOCKED", ciFailing=False)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_ME)

    def test_unaddressed_cr_outranks_ci(self):
        it = _pr(reviewDecision="CHANGES_REQUESTED", addressed=False,
                 mergeStateStatus="BLOCKED", ciFailing=True)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_ME)

    def test_base_behind_is_me(self):
        it = _pr(reviewDecision="APPROVED", addressed=False,
                 mergeStateStatus="BEHIND", ciFailing=False)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_ME)

    def test_dirty_is_me(self):
        it = _pr(reviewDecision=None, mergeStateStatus="DIRTY", ciFailing=False)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_ME)

    def test_ci_failing_is_suspect_when_addressed(self):
        it = _pr(reviewDecision="CHANGES_REQUESTED", addressed=True,
                 mergeStateStatus="BLOCKED", ciFailing=True)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_CI_SUSPECT)

    def test_approved_not_merged_is_them(self):
        it = _pr(reviewDecision="APPROVED", mergeStateStatus="BLOCKED",
                 ciFailing=False)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_THEM)

    def test_addressed_cr_is_them(self):
        it = _pr(reviewDecision="CHANGES_REQUESTED", addressed=True,
                 mergeStateStatus="BLOCKED", ciFailing=False)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_THEM)

    def test_stale_pr_is_nudge(self):
        it = _pr(reviewDecision="APPROVED", mergeStateStatus="BLOCKED",
                 ciFailing=False, updatedAt="2026-07-01T00:00:00Z")
        self.assertEqual(g.classify_court(it, NOW, stale_days=14),
                         g.COURT_STALE_NUDGE)

    def test_issue_recent_is_them(self):
        it = {"kind": "issue", "number": 2, "title": "RFC", "url": "u",
              "updatedAt": "2026-08-09T00:00:00Z"}
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_THEM)

    def test_issue_stale_is_nudge(self):
        it = {"kind": "issue", "number": 2, "title": "RFC", "url": "u",
              "updatedAt": "2026-07-01T00:00:00Z"}
        self.assertEqual(g.classify_court(it, NOW, stale_days=14),
                         g.COURT_STALE_NUDGE)

    def test_stale_pr_with_failing_ci_is_suspect(self):
        # CI failing outranks staleness: more actionable than a generic nudge.
        it = _pr(reviewDecision="APPROVED", addressed=True,
                 mergeStateStatus="BLOCKED", ciFailing=True,
                 updatedAt="2026-07-01T00:00:00Z")
        self.assertEqual(g.classify_court(it, NOW, stale_days=14),
                         g.COURT_CI_SUSPECT)

    def test_never_reviewed_recent_pr_is_them(self):
        # Open PR awaiting first review (no signals set) -> waiting on them.
        it = _pr(reviewDecision=None, mergeStateStatus="BLOCKED",
                 ciFailing=False)
        self.assertEqual(g.classify_court(it, NOW), g.COURT_WAITING_ON_THEM)


class TestEnrichItem(unittest.TestCase):
    def test_pr_gets_signals_merged(self):
        detail = {
            "reviewDecision": "CHANGES_REQUESTED",
            "mergeStateStatus": "BLOCKED", "mergeable": "MERGEABLE",
            "reviews": [{"author": {"login": "maint"},
                         "state": "CHANGES_REQUESTED",
                         "submittedAt": "2026-08-06T15:10:54Z"}],
            "commits": [{"committedDate": "2026-08-06T15:32:11Z"}],
            "statusCheckRollup": [{"conclusion": "FAILURE"}],
        }
        item = {"kind": "pr", "number": 7036, "url": "u", "title": "t"}
        out = g.enrich_item(item, "o/r", "me", gh=lambda args: detail)
        self.assertTrue(out["addressed"])
        self.assertTrue(out["ciFailing"])
        self.assertEqual(out["reviewDecision"], "CHANGES_REQUESTED")

    def test_issue_passthrough(self):
        called = []
        def gh(args):
            called.append(args)
            return {}
        item = {"kind": "issue", "number": 10, "url": "u", "title": "t"}
        out = g.enrich_item(item, "o/r", "me", gh=gh)
        self.assertEqual(out, item)      # unchanged
        self.assertEqual(called, [])     # no gh call for issues


class TestResolveLogin(unittest.TestCase):
    def test_returns_login(self):
        runner = make_runner([FakeCompleted(stdout="tonypiazza\n", returncode=0)])
        self.assertEqual(g.resolve_login(runner=runner), "tonypiazza")


class TestCurrentBranch(unittest.TestCase):
    def test_returns_branch(self):
        runner = make_runner([FakeCompleted(stdout="rss-source-rewrite\n",
                                            returncode=0)])
        self.assertEqual(g.current_branch(runner=runner), "rss-source-rewrite")

    def test_detached_head_returns_none(self):
        runner = make_runner([FakeCompleted(stdout="HEAD\n", returncode=0)])
        self.assertIsNone(g.current_branch(runner=runner))

    def test_not_a_repo_returns_none(self):
        runner = make_runner([FakeCompleted(returncode=128)])
        self.assertIsNone(g.current_branch(runner=runner))


class TestResolveCurrentPr(unittest.TestCase):
    def test_one_pr(self):
        raw = [{"number": 7036, "title": "rss rewrite",
                "url": "https://github.com/o/r/pull/7036",
                "createdAt": "2026-07-28T00:00:00Z",
                "updatedAt": "2026-08-06T00:00:00Z"}]
        prs = g.resolve_current_pr("o/r", "rss-source-rewrite",
                                   gh=lambda args: raw)
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]["number"], 7036)
        self.assertEqual(prs[0]["kind"], "pr")

    def test_none(self):
        prs = g.resolve_current_pr("o/r", "main", gh=lambda args: [])
        self.assertEqual(prs, [])

    def test_many(self):
        raw = [{"number": 1, "title": "a", "url": "u1",
                "createdAt": "x", "updatedAt": "y"},
               {"number": 2, "title": "b", "url": "u2",
                "createdAt": "x", "updatedAt": "y"}]
        prs = g.resolve_current_pr("o/r", "shared-branch", gh=lambda args: raw)
        self.assertEqual([p["number"] for p in prs], [1, 2])

    def test_passes_head_and_author(self):
        seen = {}
        def gh(args):
            seen["args"] = args
            return []
        g.resolve_current_pr("o/r", "my-branch", gh=gh)
        self.assertIn("--head=my-branch", seen["args"])
        self.assertIn("--author=@me", seen["args"])


class TestDescribePrState(unittest.TestCase):
    def test_unaddressed_changes_requested(self):
        pr = {"kind": "pr", "reviewDecision": "CHANGES_REQUESTED",
              "addressed": False, "mergeStateStatus": "BLOCKED",
              "mergeable": "MERGEABLE", "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertTrue(any("not yet addressed" in l.lower() for l in lines))

    def test_addressed_awaiting_rereview(self):
        pr = {"kind": "pr", "reviewDecision": "CHANGES_REQUESTED",
              "addressed": True, "mergeStateStatus": "BLOCKED",
              "mergeable": "MERGEABLE", "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertTrue(any("re-review" in l.lower() for l in lines))

    def test_approved(self):
        pr = {"kind": "pr", "reviewDecision": "APPROVED",
              "mergeStateStatus": "BLOCKED", "mergeable": "MERGEABLE",
              "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertTrue(any("approved" in l.lower() for l in lines))

    def test_awaiting_first_review(self):
        pr = {"kind": "pr", "reviewDecision": None,
              "mergeStateStatus": "BLOCKED", "mergeable": "MERGEABLE",
              "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertTrue(any("awaiting review" in l.lower() for l in lines))

    def test_behind_base(self):
        pr = {"kind": "pr", "reviewDecision": "APPROVED",
              "mergeStateStatus": "BEHIND", "mergeable": "MERGEABLE",
              "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertTrue(any("base branch" in l.lower() for l in lines))

    def test_conflicts(self):
        pr = {"kind": "pr", "reviewDecision": "APPROVED",
              "mergeStateStatus": "DIRTY", "mergeable": "CONFLICTING",
              "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertTrue(any("conflict" in l.lower() for l in lines))

    def test_ci_failing_is_hedged(self):
        pr = {"kind": "pr", "reviewDecision": "APPROVED",
              "mergeStateStatus": "BLOCKED", "mergeable": "MERGEABLE",
              "ciFailing": True}
        lines = g.describe_pr_state(pr)
        joined = " ".join(lines).lower()
        self.assertIn("ci failing", joined)
        self.assertIn("whether", joined)  # hedged, not "your fault"

    def test_review_required_is_awaiting_review(self):
        pr = {"kind": "pr", "reviewDecision": "REVIEW_REQUIRED",
              "mergeStateStatus": "BLOCKED", "mergeable": "MERGEABLE",
              "ciFailing": False}
        lines = g.describe_pr_state(pr)
        self.assertEqual(len(lines), 1)
        self.assertIn("awaiting review", lines[0].lower())

    def test_multiple_signals_all_appear_in_order(self):
        pr = {"kind": "pr", "reviewDecision": "CHANGES_REQUESTED",
              "addressed": False, "mergeStateStatus": "BEHIND",
              "mergeable": "MERGEABLE", "ciFailing": True}
        lines = g.describe_pr_state(pr)
        self.assertEqual(len(lines), 3)
        self.assertIn("not yet addressed", lines[0].lower())
        self.assertIn("base branch", lines[1].lower())
        self.assertIn("ci failing", lines[2].lower())


class TestOtherPrsNeedingAttention(unittest.TestCase):
    def _gh_factory(self, listing, details):
        # listing: returned for `pr list`; details: {number: detail dict} for `pr view`.
        def gh(args):
            if "list" in args:
                return listing
            num = int([a for a in args if a.isdigit()][0])
            return details[num]
        return gh

    def test_keeps_only_needs_attention_and_excludes_current(self):
        listing = [
            {"number": 7036, "title": "current", "url": "u36",
             "createdAt": "x", "updatedAt": "2026-08-09T00:00:00Z"},
            {"number": 40, "title": "behind one", "url": "u40",
             "createdAt": "x", "updatedAt": "2026-08-09T00:00:00Z"},
            {"number": 50, "title": "healthy one", "url": "u50",
             "createdAt": "x", "updatedAt": "2026-08-09T00:00:00Z"},
        ]
        details = {
            40: {"reviewDecision": "APPROVED", "mergeStateStatus": "BEHIND",
                 "mergeable": "MERGEABLE", "reviews": [], "commits": [],
                 "statusCheckRollup": []},               # BEHIND -> WAITING_ON_ME
            50: {"reviewDecision": "APPROVED", "mergeStateStatus": "BLOCKED",
                 "mergeable": "MERGEABLE", "reviews": [], "commits": [],
                 "statusCheckRollup": []},               # approved, healthy -> THEM
        }
        now = _dt.datetime(2026, 8, 10, tzinfo=_dt.timezone.utc)
        out = g.other_prs_needing_attention(
            "o/r", "me", 7036, now, gh=self._gh_factory(listing, details))
        self.assertEqual([p["number"] for p in out], [40])  # 7036 excluded, 50 healthy

    def test_empty_when_none_need_attention(self):
        listing = [{"number": 50, "title": "healthy", "url": "u50",
                    "createdAt": "x", "updatedAt": "2026-08-09T00:00:00Z"}]
        details = {50: {"reviewDecision": "APPROVED", "mergeStateStatus": "BLOCKED",
                        "mergeable": "MERGEABLE", "reviews": [], "commits": [],
                        "statusCheckRollup": []}}
        now = _dt.datetime(2026, 8, 10, tzinfo=_dt.timezone.utc)
        out = g.other_prs_needing_attention(
            "o/r", "me", 999, now, gh=self._gh_factory(listing, details))
        self.assertEqual(out, [])


class TestRenderPrDetail(unittest.TestCase):
    def _pr(self):
        return {"kind": "pr", "number": 7036, "title": "rss rewrite",
                "url": "https://github.com/o/r/pull/7036",
                "court": g.COURT_CI_SUSPECT, "reviewDecision": "CHANGES_REQUESTED",
                "addressed": True, "mergeStateStatus": "BLOCKED",
                "mergeable": "MERGEABLE", "ciFailing": True}

    def test_shows_pr_header_and_marker(self):
        out = g.render_pr_detail("o/r", self._pr(), [], glyphs=True)
        self.assertIn("#7036", out)
        self.assertIn("rss rewrite", out)
        self.assertIn("🟠", out)  # CI_SUSPECT marker

    def test_shows_status_lines(self):
        out = g.render_pr_detail("o/r", self._pr(), [], glyphs=True)
        self.assertIn("re-review", out.lower())
        self.assertIn("ci failing", out.lower())

    def test_footer_silent_when_no_others(self):
        out = g.render_pr_detail("o/r", self._pr(), [], glyphs=True)
        self.assertNotIn("other open PR", out)

    def test_footer_lists_others(self):
        others = [{"kind": "pr", "number": 40, "title": "behind",
                   "url": "u40", "court": g.COURT_WAITING_ON_ME}]
        out = g.render_pr_detail("o/r", self._pr(), others, glyphs=True)
        self.assertIn("other open pr", out.lower())
        self.assertIn("#40", out)
        self.assertIn("--repo", out)  # points to the wider view

    def test_shows_ai_authored_files_with_models(self):
        pr = dict(self._pr())
        pr["aiAuthoredFiles"] = [
            {"path": "src/A.java", "models": ["claude-opus-4-8"]},
            {"path": "src/B.java",
             "models": ["claude-opus-4-8", "claude-sonnet-4-6"]},
        ]
        out = g.render_pr_detail("o/r", pr, [], glyphs=True)
        self.assertIn("AI-authored", out)
        self.assertIn("src/A.java", out)
        self.assertIn("claude-opus-4-8", out)
        self.assertIn("claude-sonnet-4-6", out)  # multi-model file lists both
        # the anti-blame caveat is load-bearing for this learning feature — pin it
        self.assertIn("not that a specific line is the bug", out)
        # single-model file renders as "path (model)"
        self.assertIn("src/A.java (claude-opus-4-8)", out)

    def test_no_ai_line_when_none(self):
        pr = dict(self._pr())
        pr["aiAuthoredFiles"] = []
        out = g.render_pr_detail("o/r", pr, [], glyphs=True)
        self.assertNotIn("AI-authored", out)


class TestLevel0Eligible(unittest.TestCase):
    def test_bare_is_eligible(self):
        ns = g.build_parser().parse_args([])
        self.assertTrue(g.level0_eligible(ns))

    def test_prs_only_is_eligible(self):
        ns = g.build_parser().parse_args(["--prs"])
        self.assertTrue(g.level0_eligible(ns))

    def test_repo_flag_not_eligible(self):
        ns = g.build_parser().parse_args(["--repo"])
        self.assertFalse(g.level0_eligible(ns))

    def test_issues_not_eligible(self):
        ns = g.build_parser().parse_args(["--issues"])
        self.assertFalse(g.level0_eligible(ns))

    def test_all_not_eligible(self):
        ns = g.build_parser().parse_args(["--all"])
        self.assertFalse(g.level0_eligible(ns))


class TestTranscriptDir(unittest.TestCase):
    def test_default_base_and_slug(self):
        d = g.transcript_dir("/Users/x/repos/data-prepper",
                             env={"HOME": "/Users/x"})
        self.assertEqual(
            d, "/Users/x/.claude/projects/-Users-x-repos-data-prepper")

    def test_dot_in_path_becomes_dash(self):
        d = g.transcript_dir("/Users/x/.supacode/repos/foo",
                             env={"HOME": "/Users/x"})
        self.assertEqual(
            d, "/Users/x/.claude/projects/-Users-x--supacode-repos-foo")

    def test_config_dir_override(self):
        d = g.transcript_dir("/Users/x/repos/foo",
                             env={"HOME": "/Users/x",
                                  "CLAUDE_CONFIG_DIR": "/cfg"})
        self.assertEqual(d, "/cfg/projects/-Users-x-repos-foo")


class TestClaudeTouchedFiles(unittest.TestCase):
    def _transcript_lines(self):
        # opus edits A and B; a later sonnet session also edits B; scratch filtered.
        rec1 = {"type": "assistant", "message": {"model": "claude-opus-4-8",
            "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "/repo/src/A.java"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/repo/src/B.java"}},
                {"type": "text", "text": "ignore me"},
            ]}}
        rec2 = {"type": "assistant", "message": {"model": "claude-sonnet-4-6",
            "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/repo/src/B.java"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/home/u/.claude/scratch/notes.md"}},
            ]}}
        user_rec = {"type": "user", "message": {"content": "hi"}}
        return [json.dumps(rec1), json.dumps(user_rec), json.dumps(rec2)]

    def test_maps_files_to_models(self):
        lister = lambda d: ["t1.jsonl"]
        opener = lambda p: self._transcript_lines()
        out = g.claude_touched_files("/repo", opener=opener, lister=lister)
        self.assertEqual(out, {
            "src/A.java": ["claude-opus-4-8"],
            "src/B.java": ["claude-opus-4-8", "claude-sonnet-4-6"],
        })

    def test_missing_dir_returns_empty(self):
        lister = lambda d: []
        out = g.claude_touched_files("/repo", opener=lambda p: [], lister=lister)
        self.assertEqual(out, {})

    def test_malformed_line_skipped(self):
        lister = lambda d: ["t.jsonl"]
        opener = lambda p: ["not json", json.dumps({"type": "assistant",
            "message": {"model": "claude-opus-4-8", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "/repo/x.py"}}]}})]
        out = g.claude_touched_files("/repo", opener=opener, lister=lister)
        self.assertEqual(out, {"x.py": ["claude-opus-4-8"]})

    def test_missing_model_is_unknown(self):
        lister = lambda d: ["t.jsonl"]
        opener = lambda p: [json.dumps({"type": "assistant", "message": {
            "content": [{"type": "tool_use", "name": "Write",
                         "input": {"file_path": "/repo/y.py"}}]}})]
        out = g.claude_touched_files("/repo", opener=opener, lister=lister)
        self.assertEqual(out, {"y.py": ["unknown"]})

    def test_merges_across_multiple_files(self):
        def opener(p):
            if p == "a.jsonl":
                return [json.dumps({"type": "assistant", "message": {
                    "model": "claude-opus-4-8", "content": [
                        {"type": "tool_use", "name": "Write",
                         "input": {"file_path": "/repo/a.py"}}]}})]
            return [json.dumps({"type": "assistant", "message": {
                "model": "claude-opus-4-8", "content": [
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "/repo/b.py"}}]}})]
        out = g.claude_touched_files("/repo", opener=opener,
                                     lister=lambda d: ["a.jsonl", "b.jsonl"])
        self.assertEqual(out, {"a.py": ["claude-opus-4-8"],
                               "b.py": ["claude-opus-4-8"]})

    def test_tolerates_malformed_records(self):
        lines = [
            "42",                                   # valid JSON, not an object
            json.dumps({"type": "assistant", "message": "a string"}),  # message not dict
            json.dumps({"type": "assistant", "message": {"model": "m",
                "content": [{"type": "tool_use", "name": "Write",
                             "input": {"file_path": 123}}]}}),  # non-string path
            json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-8",
                "content": [{"type": "tool_use", "name": "Write",
                             "input": {"file_path": "/repo/ok.py"}}]}}),  # good
        ]
        out = g.claude_touched_files("/repo", opener=lambda p: lines,
                                     lister=lambda d: ["t.jsonl"])
        self.assertEqual(out, {"ok.py": ["claude-opus-4-8"]})  # bad lines skipped, good kept

    def test_tool_use_without_file_path_skipped(self):
        lines = [json.dumps({"type": "assistant", "message": {"model": "m",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})]
        out = g.claude_touched_files("/repo", opener=lambda p: lines,
                                     lister=lambda d: ["t.jsonl"])
        self.assertEqual(out, {})


class TestAttribution(unittest.TestCase):
    def test_pr_changed_files(self):
        detail = {"files": [{"path": "a/b.java"}, {"path": "c/d.md"}]}
        out = g.pr_changed_files("o/r", 7036, gh=lambda args: detail)
        self.assertEqual(out, ["a/b.java", "c/d.md"])

    def test_attributed_carries_models_sorted(self):
        touched = {"a/b.java": ["claude-opus-4-8"],
                   "z/other.java": ["claude-opus-4-8"],
                   "c/d.md": ["claude-opus-4-8", "claude-sonnet-4-6"]}
        changed = ["c/d.md", "a/b.java", "e/f.py"]
        self.assertEqual(g.attributed_files(touched, changed), [
            {"path": "a/b.java", "models": ["claude-opus-4-8"]},
            {"path": "c/d.md",
             "models": ["claude-opus-4-8", "claude-sonnet-4-6"]},
        ])

    def test_attributed_empty_when_disjoint(self):
        self.assertEqual(g.attributed_files({"x": ["m"]}, ["y", "z"]), [])


if __name__ == "__main__":
    unittest.main()
