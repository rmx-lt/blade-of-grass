import copy
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scan  # noqa: E402

SHARED = json.loads((scan.RULESETS / "shared.json").read_text(encoding="utf-8"))
CI = json.loads((scan.RULESETS / "ci.json").read_text(encoding="utf-8"))


def as_github(ruleset, rid=1):
    r = copy.deepcopy(ruleset)
    r.update(id=rid, node_id="X", source="rmx-lt/x", source_type="Repository",
             _links={}, created_at="a", updated_at="b", current_user_can_bypass="never")
    r["rules"] = list(reversed(r["rules"]))
    return r


def synced(repo):
    return [as_github(r, i) for i, r in enumerate(scan.apply.desired(repo, SHARED, CI), 1)]


class CallerTest(unittest.TestCase):
    def setUp(self):
        self.templates = {
            "component": "name: rmx\nuses: remote\n",
            "dot-github": "name: rmx\nuses: meta\n",
        }

    def test_component_match_ignores_line_endings(self):
        self.assertEqual(
            scan.check_caller("rmx-server-app", "name: rmx\r\nuses: remote\r\n", self.templates),
            [])

    def test_component_differs(self):
        got = scan.check_caller("rmx-server-app", "name: rmx\nuses: other\n", self.templates)
        self.assertEqual(got, [
            "rmx-server-app: .github/workflows/rmx.yml differs from tools/drift/callers/component.yml"])

    def test_missing(self):
        self.assertIn("missing", scan.check_caller("rmx-server-app", None, self.templates)[0])

    def test_dot_github_uses_its_own_template(self):
        self.assertEqual(scan.check_caller(".github", "name: rmx\nuses: meta\n", self.templates), [])
        self.assertTrue(scan.check_caller(".github", "name: rmx\nuses: remote\n", self.templates))

    def test_home_checks_local_uses(self):
        text = "\n".join(scan.HOME_USES) + "\n"
        self.assertEqual(scan.check_caller(scan.HOME, text, self.templates), [])
        self.assertTrue(scan.check_caller(scan.HOME, "name: rmx\n", self.templates))

    def test_ansi_codes_are_stripped_from_gh_json(self):
        self.assertEqual(scan.ANSI.sub("", "\x1b[1;37m[\x1b[m"), "[")

    def test_shipped_templates_match_the_contract(self):
        shipped = scan.load_templates()
        self.assertIn("wiki-dispatch.yml@development", shipped["component"])
        self.assertNotIn("workflows/wiki-dispatch.yml", shipped["dot-github"])
        self.assertIn("add-to-project.yml@development", shipped["dot-github"])


class RulesAndFilesTest(unittest.TestCase):
    def test_in_sync_rules_are_quiet(self):
        self.assertEqual(
            scan.check_rules("rmx-server-app", synced("rmx-server-app"), False, SHARED, CI), [])

    def test_wiki_flag_and_extra_ruleset(self):
        lines = scan.check_rules("rmx-server-app", [], True, SHARED, CI)
        self.assertIn("rmx-server-app: ruleset create rmx: development and production", lines)
        self.assertIn("rmx-server-app: has_wiki true -> false", lines)

    def test_home_wiki_stays_on(self):
        self.assertEqual(
            scan.check_rules(scan.HOME, synced(scan.HOME), True, SHARED, CI), [])
        self.assertIn("false -> true",
                      scan.check_rules(scan.HOME, synced(scan.HOME), False, SHARED, CI)[0])

    def test_missing_readme(self):
        self.assertEqual(
            scan.check_files("rmx-server-app", {"LICENSE": True, "README.md": False}),
            ["rmx-server-app: README.md missing on development"])


class WikiTest(unittest.TestCase):
    def test_publish_tip_ignores_older_edits(self):
        commits = [("abc", "Publish wiki from blade-of-grass@1"),
                   ("def", "Direct edit")]
        self.assertEqual(scan.check_wiki(commits, None), [])

    def test_commits_after_publish(self):
        commits = [("aaa1111", "Fix a typo"), ("bbb2222", "Publish wiki from x")]
        lines = scan.check_wiki(commits, None)
        self.assertEqual(lines[0], "GitHub wiki: 1 commit(s) after the last publish")
        self.assertIn("aaa1111", lines[1])

    def test_no_publish_in_history(self):
        self.assertIn("no publish commit", scan.check_wiki([("abc", "Hand edit")], None)[0])

    def test_unreadable(self):
        self.assertIn("unreadable", scan.check_wiki(None, "authentication failed")[0])


class CollectTest(unittest.TestCase):
    def test_clean_repo_and_wiki(self):
        repo = "rmx-server-app"
        rules = synced(repo)
        files = {
            scan.CALLER: "name: rmx\nuses: remote\n",
            "LICENSE": "Apache\n",
            "README.md": "Hi\n",
        }

        def gh(args, stdin=None):
            if args[:2] == ["repo", "list"]:
                return json.dumps([{"name": repo}])
            if args[:2] == ["api", "-H"]:
                path = args[3].split("contents/")[1].split("?")[0]
                if path not in files:
                    raise scan.apply.GhError("404 Not Found")
                return files[path]
            if args[1] == f"repos/rmx-lt/{repo}/rulesets":
                return json.dumps([{"id": r["id"]} for r in rules])
            if "/rulesets/" in args[1]:
                rid = int(args[1].rsplit("/", 1)[-1])
                return json.dumps(next(r for r in rules if r["id"] == rid))
            if args[1] == f"repos/rmx-lt/{repo}":
                return json.dumps({"has_wiki": False})
            raise AssertionError(args)

        findings = scan.collect(
            gh, {"component": files[scan.CALLER], "dot-github": "other\n"},
            SHARED, CI, ([("abc", "Publish wiki from x")], None))
        self.assertEqual(findings, [])


class IssueTest(unittest.TestCase):
    def test_creates_then_updates_then_closes(self):
        calls = []
        state = {"open": []}

        def gh(args, stdin=None):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return json.dumps([{"number": n, "title": scan.ISSUE_TITLE} for n in state["open"]])
            if args[:2] == ["issue", "create"]:
                state["open"] = [7]
                return "https://github.com/rmx-lt/blade-of-grass/issues/7\n"
            if args[:2] == ["issue", "close"]:
                state["open"] = [n for n in state["open"] if str(n) != args[2]]
                return ""
            return ""

        self.assertTrue(scan.update_issue(["rmx-server-app: README.md missing on development"], gh)
                        .startswith("created"))
        created = next(a for a in calls if a[:2] == ["issue", "create"])
        self.assertIn(scan.MARKER, created[-1])
        self.assertIn("--type", created)
        calls.clear()
        self.assertEqual(scan.update_issue(["still wrong"], gh), "updated #7")
        self.assertEqual(scan.update_issue([], gh), "closed #7")
        self.assertIn("close", calls[-1])

    def test_clean_with_no_issue(self):
        def gh(args, stdin=None):
            if args[:2] == ["issue", "list"]:
                return "[]"
            raise AssertionError(args)

        self.assertEqual(scan.update_issue([], gh), "in sync")

    def test_main_returns_1_on_gh_error(self):
        err = io.StringIO()
        real = sys.stderr
        sys.stderr = err
        try:
            code = scan.main([], gh=self._boom, wiki=([], None))
        finally:
            sys.stderr = real
        self.assertEqual(code, 1)
        self.assertIn("gh down", err.getvalue())

    def test_main_returns_2_when_wiki_drifted(self):
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        try:
            code = scan.main([], gh=self._one_clean_repo, wiki=([("abc1111", "Hand edit")], None))
        finally:
            sys.stdout = real
        self.assertEqual(code, 2)
        self.assertIn("no publish commit", out.getvalue())
        self.assertNotIn("--update-issue", out.getvalue())

    def _boom(self, args, stdin=None):
        raise scan.apply.GhError("gh down")

    def _one_clean_repo(self, args, stdin=None):
        repo = "rmx-server-app"
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"name": repo}])
        if args[:2] == ["api", "-H"]:
            path = args[3].split("contents/")[1].split("?")[0]
            if path == scan.CALLER:
                return (scan.HERE / "callers" / "component.yml").read_text(encoding="utf-8")
            if path in scan.FILES:
                return "present\n"
            raise scan.apply.GhError("404 Not Found")
        rules = synced(repo)
        if args[1] == f"repos/rmx-lt/{repo}/rulesets":
            return json.dumps([{"id": r["id"]} for r in rules])
        if "/rulesets/" in args[1]:
            rid = int(args[1].rsplit("/", 1)[-1])
            return json.dumps(next(r for r in rules if r["id"] == rid))
        if args[1] == f"repos/rmx-lt/{repo}":
            return json.dumps({"has_wiki": False})
        raise AssertionError(args)


if __name__ == "__main__":
    unittest.main()
