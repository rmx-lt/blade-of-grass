import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_pr  # noqa: E402

CODE = ["src/a.py"]
WIKI = ["wiki/Home.md"]
MERGED_DEV = {"merged": True, "base": {"ref": "development"}}


class WikiReason(unittest.TestCase):
    def test_reason(self):
        self.assertEqual(check_pr.wiki_reason("Wiki: none: CI only"), "CI only")

    def test_case_insensitive(self):
        self.assertEqual(check_pr.wiki_reason("WIKI: None:  x  "), "x")

    def test_empty_reason(self):
        self.assertIsNone(check_pr.wiki_reason("Wiki: none:   "))

    def test_no_line(self):
        self.assertIsNone(check_pr.wiki_reason("Closes #1\nWiki: Home"))

    def test_multiline(self):
        self.assertEqual(check_pr.wiki_reason("a\r\nWiki: none: why\r\nb"), "why")


TEMPLATE = (
    "Closes #\n\n<!-- What changes and why, in a few lines. -->\n\n"
    "Wiki: <!-- the wiki/ pages this PR adds or changes, or: none: <reason>. Rules: "
    "https://github.com/rmx-lt/blade-of-grass/wiki/Wiki-Policy (section 4) -->\n\n"
    "<!-- If this PR needs another PR merged into development first, add a line:\n"
    "Depends on: rmx-lt/<repo>#<PR>\n"
    'and mark the issues "Blocked by" each other. -->\n'
)


class Template(unittest.TestCase):
    def test_template_fails_for_code(self):
        p = check_pr.evaluate(TEMPLATE, CODE, {})
        self.assertEqual(len(p), 1)
        self.assertIn("Wiki", p[0])

    def test_template_no_dependency_problems(self):
        self.assertEqual(check_pr.parse_depends(TEMPLATE), ([], []))

    def test_comment_hides_reason(self):
        self.assertIsNone(check_pr.wiki_reason("<!-- Wiki: none: x -->"))

    def test_placeholder_reason(self):
        self.assertIsNone(check_pr.wiki_reason("Wiki: none: <reason>"))
        self.assertEqual(len(check_pr.evaluate("Wiki: none: <reason>", CODE, {})), 1)


class Escape(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(check_pr.escape_cmd("a%b\r\nc"), "a%25b%0D%0Ac")

class Hardening(unittest.TestCase):
    def test_404_message(self):
        p = check_pr.evaluate("Depends on: rmx-lt/x#1", WIKI, {("x", 1): None})
        self.assertIn("not found or not a pull request", p[0])

    def test_dot_repos_rejected(self):
        for r in (".", "..", ".x"):
            _, problems = check_pr.parse_depends(f"Depends on: rmx-lt/{r}#1")
            self.assertEqual(len(problems), 1, r)

    def test_dotted_repo_ok(self):
        deps, problems = check_pr.parse_depends("Depends on: rmx-lt/a.b-c_d#1")
        self.assertEqual((deps, problems), ([("a.b-c_d", 1)], []))

    def test_trailing_comma(self):
        self.assertEqual(
            check_pr.parse_depends("Depends on: rmx-lt/x#1, "), ([("x", 1)], [])
        )

    def test_empty_depends_line(self):
        for b in ("Depends on:", "Depends on:   ", "Depends on: , ,"):
            deps, problems = check_pr.parse_depends(b)
            self.assertEqual((deps, problems), ([], ["empty Depends on line"]), b)


class ParseDepends(unittest.TestCase):
    def test_ok(self):
        deps, problems = check_pr.parse_depends(
            "Depends on: rmx-lt/rmx-server-infra#61, rmx-lt/x#2\nDepends on: rmx-lt/y#3"
        )
        self.assertEqual(deps, [("rmx-server-infra", 61), ("x", 2), ("y", 3)])
        self.assertEqual(problems, [])

    def test_bad_item(self):
        deps, problems = check_pr.parse_depends("Depends on: rmx-lt/x#1, foo")
        self.assertEqual(deps, [("x", 1)])
        self.assertEqual(len(problems), 1)
        self.assertIn("foo", problems[0])

    def test_none(self):
        self.assertEqual(check_pr.parse_depends(""), ([], []))


class Evaluate(unittest.TestCase):
    def test_wiki_only_no_line_passes(self):
        self.assertEqual(check_pr.evaluate("", WIKI, {}), [])

    def test_code_and_wiki_passes(self):
        self.assertEqual(check_pr.evaluate("", CODE + WIKI, {}), [])

    def test_code_valid_reason_passes(self):
        self.assertEqual(check_pr.evaluate("Wiki: none: CI only", CODE, {}), [])

    def test_code_no_line_fails(self):
        self.assertEqual(len(check_pr.evaluate("", CODE, {})), 1)

    def test_empty_reason_fails(self):
        self.assertEqual(len(check_pr.evaluate("Wiki: none:   ", CODE, {})), 1)

    def test_informational_wiki_line_fails_for_code_only(self):
        self.assertEqual(len(check_pr.evaluate("Wiki: Home", CODE, {})), 1)

    def test_dep_issue_fails(self):
        p = check_pr.evaluate("Depends on: rmx-lt/x#1", WIKI, {("x", 1): None})
        self.assertEqual(len(p), 1)
        self.assertIn("rmx-lt/x#1", p[0])

    def test_dep_unmerged_fails(self):
        pr = {"merged": False, "base": {"ref": "development"}}
        p = check_pr.evaluate("Depends on: rmx-lt/x#1", WIKI, {("x", 1): pr})
        self.assertEqual(len(p), 1)
        self.assertIn("rmx-lt/x#1", p[0])

    def test_dep_production_fails(self):
        pr = {"merged": True, "base": {"ref": "production"}}
        p = check_pr.evaluate("Depends on: rmx-lt/x#1", WIKI, {("x", 1): pr})
        self.assertEqual(len(p), 1)
        self.assertIn("rmx-lt/x#1", p[0])

    def test_dep_merged_development_passes(self):
        self.assertEqual(
            check_pr.evaluate("Depends on: rmx-lt/x#1", WIKI, {("x", 1): MERGED_DEV}), []
        )

    def test_malformed_dep_reported(self):
        p = check_pr.evaluate("Depends on: foo", WIKI, {})
        self.assertEqual(len(p), 1)
        self.assertIn("foo", p[0])

    def test_none_body(self):
        self.assertEqual(len(check_pr.evaluate(None, CODE, {})), 1)


if __name__ == "__main__":
    unittest.main()
