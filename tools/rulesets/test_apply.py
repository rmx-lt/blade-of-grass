import contextlib
import copy
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply  # noqa: E402

HERE = Path(__file__).resolve().parent
SHARED = json.loads((HERE / "shared.json").read_text(encoding="utf-8"))
CI = json.loads((HERE / "ci.json").read_text(encoding="utf-8"))


def as_github(ruleset, rid=1):
    """What GitHub returns: extra fields and reordered rules."""
    r = copy.deepcopy(ruleset)
    r.update(id=rid, node_id="X", source="rmx-lt/x", source_type="Repository",
             _links={}, created_at="a", updated_at="b", current_user_can_bypass="never")
    r["rules"] = list(reversed(r["rules"]))
    return r


def synced(repo):
    return [as_github(r, i) for i, r in enumerate(apply.desired(repo, SHARED, CI), 1)]


class NormalizeTest(unittest.TestCase):
    def test_drops_github_fields_and_sorts_rules(self):
        n = apply.normalize(as_github(SHARED[0]))
        for k in ("id", "node_id", "source", "source_type", "_links", "created_at",
                  "updated_at", "current_user_can_bypass"):
            self.assertNotIn(k, n)
        self.assertEqual([r["type"] for r in n["rules"]],
                         ["deletion", "non_fast_forward", "pull_request"])

    def test_does_not_mutate(self):
        r = as_github(SHARED[0])
        before = copy.deepcopy(r)
        apply.normalize(r)
        self.assertEqual(r, before)


class DesiredTest(unittest.TestCase):
    def names(self, repo):
        return [r["name"] for r in apply.desired(repo, SHARED, CI)]

    def test_shared_for_unknown_repo(self):
        self.assertEqual(self.names("brand-new"),
                         ["rmx: development and production", "rmx: wiki-check"])

    def test_ci_only_for_listed_repos(self):
        self.assertIn("rmx: CI", self.names("rmx-server-infra"))
        self.assertIn("rmx: CI", self.names("rmx-server-app-probe"))
        self.assertNotIn("rmx: CI", self.names("rmx-server-app"))

    def test_wiki_check_targets_development_only(self):
        wc = [r for r in SHARED if r["name"] == "rmx: wiki-check"][0]
        self.assertEqual(wc["conditions"]["ref_name"]["include"], ["refs/heads/development"])

    def test_no_bypass_actors(self):
        for r in SHARED:
            self.assertEqual(r["bypass_actors"], [])


class PlanTest(unittest.TestCase):
    def want(self, repo="rmx-server-app"):
        return apply.desired(repo, SHARED, CI)

    def test_empty_creates_two(self):
        p = apply.plan("rmx-server-app", [], self.want())
        self.assertEqual([a for a, _, _ in p], ["create", "create"])

    def test_empty_creates_three_with_ci(self):
        p = apply.plan("rmx-server-infra", [], self.want("rmx-server-infra"))
        self.assertEqual([a for a, _, _ in p], ["create"] * 3)

    def test_in_sync_even_if_reordered(self):
        self.assertEqual(apply.plan("rmx-server-app", synced("rmx-server-app"), self.want()), [])

    def test_changed_check_is_one_update(self):
        cur = synced("rmx-server-app")
        cur[1]["rules"][0]["parameters"]["required_status_checks"][0]["context"] = "old"
        p = apply.plan("rmx-server-app", cur, self.want())
        self.assertEqual([(a, n) for a, n, _ in p], [("update", "rmx: wiki-check")])

    def test_deletes_last(self):
        old = [{"id": 9, "name": "stable branches", "rules": [], "conditions": {}},
               {"id": 8, "name": "main", "rules": [], "conditions": {}}]
        p = apply.plan("rmx-server-app", old, self.want())
        self.assertEqual([a for a, _, _ in p], ["create", "create", "delete", "delete"])
        self.assertTrue(all(b is None for a, _, b in p if a == "delete"))

    def test_update_and_create_before_delete(self):
        cur = [as_github(self.want()[0], 1),
               {"id": 9, "name": "old", "rules": [], "conditions": {}}]
        cur[0]["enforcement"] = "disabled"
        p = apply.plan("rmx-server-app", cur, self.want())
        self.assertEqual([a for a, _, _ in p], ["update", "create", "delete"])


class FakeGh:
    def __init__(self, repos, rulesets, wiki=None, fail_on=None):
        self.repos, self.rulesets = repos, rulesets
        self.wiki = wiki or {}
        self.fail_on = fail_on
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        if self.fail_on and self.fail_on in " ".join(args):
            raise apply.GhError("gh: missing scope admin:org")
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"name": r} for r in self.repos])
        if args[0] == "api" and "-X" not in args:
            parts = args[1].split("/")  # repos/rmx-lt/<repo>[/rulesets[/<id>]]
            repo = parts[2]
            if len(parts) == 3:
                return json.dumps({"has_wiki": self.wiki.get(repo, False)})
            if len(parts) == 4:
                return json.dumps([{"id": r["id"], "name": r["name"]}
                                   for r in self.rulesets.get(repo, [])])
            rid = int(parts[4])
            return json.dumps([r for r in self.rulesets[repo] if r["id"] == rid][0])
        return ""


class MainTest(unittest.TestCase):
    def run_main(self, gh, argv=()):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = apply.main(list(argv), gh=gh)
        return rc, out.getvalue(), err.getvalue()

    def test_new_repo_gets_shared_rulesets_dry_run(self):
        gh = FakeGh(["brand-new"], {})
        rc, out, _ = self.run_main(gh)
        self.assertEqual(rc, 2)
        self.assertEqual(out.count("create"), 2)
        self.assertFalse([c for c in gh.calls if "-X" in c or c[:2] == ["repo", "edit"]])

    def test_in_sync(self):
        gh = FakeGh(["blade-of-grass"], {"blade-of-grass": synced("blade-of-grass")},
                    wiki={"blade-of-grass": True})
        rc, out, _ = self.run_main(gh)
        self.assertEqual((rc, out.strip()), (0, "blade-of-grass: in sync"))

    def test_wiki_change_reported(self):
        gh = FakeGh(["rmx-server-app"], {"rmx-server-app": synced("rmx-server-app")},
                    wiki={"rmx-server-app": True})
        rc, out, _ = self.run_main(gh)
        self.assertEqual(rc, 2)
        self.assertIn("has_wiki", out)
        self.assertNotIn("in sync", out)

    def test_gh_error_stops_without_in_sync(self):
        gh = FakeGh(["a", "b"], {}, fail_on="repos/rmx-lt/a/rulesets")
        rc, out, err = self.run_main(gh)
        self.assertEqual(rc, 1)
        self.assertIn("missing scope", err)
        self.assertNotIn("in sync", out)

    def test_apply_creates_before_deletes(self):
        old = {"id": 9, "name": "main", "rules": [], "conditions": {}}
        gh = FakeGh(["rmx-server-app"], {"rmx-server-app": [old]})
        rc, _, _ = self.run_main(gh, ["--apply"])
        self.assertEqual(rc, 0)
        verbs = [c[c.index("-X") + 1] for c in gh.calls if "-X" in c]
        self.assertEqual(verbs, ["POST", "POST", "DELETE"])

    def test_apply_sets_wiki(self):
        gh = FakeGh(["rmx-server-app"], {"rmx-server-app": synced("rmx-server-app")},
                    wiki={"rmx-server-app": True})
        self.run_main(gh, ["--apply"])
        edits = [c for c in gh.calls if c[:2] == ["repo", "edit"]]
        self.assertEqual(len(edits), 1)
        self.assertIn("--enable-wiki=false", edits[0])

    def test_repo_filter(self):
        gh = FakeGh(["a", "b"], {})
        _, out, _ = self.run_main(gh, ["--repo", "b"])
        self.assertNotIn("a:", out)
        self.assertIn("b:", out)


if __name__ == "__main__":
    unittest.main()
