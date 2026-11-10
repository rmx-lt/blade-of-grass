import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402

CONFIG = build.load_config(Path(__file__).resolve().parent / "config.json")
P = CONFIG["prefixes"]
HOME = CONFIG["home_repo"]


def write(root: Path, repo: str, branch: str, name: str, text: str) -> None:
    d = root / repo / branch / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(text.encode("utf-8"))


class OwnerTest(unittest.TestCase):
    def test_owner_longest_prefix(self):
        nested = {**P, "rmx-server-app-x": "Server-App-X"}
        self.assertEqual(build.owner("Server-App-X-Y", nested, HOME), "rmx-server-app-x")
        self.assertEqual(build.owner("Server-App-Y", nested, HOME), "rmx-server-app")
        self.assertEqual(build.owner("Server-App", P, HOME), "rmx-server-app")
        self.assertEqual(build.owner("Server-Infra-Ansible", P, HOME), "rmx-server-infra")
        self.assertEqual(build.owner("Home", P, HOME), "blade-of-grass")
        self.assertEqual(build.owner("Server-Applause", P, HOME), "blade-of-grass")


class CollectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.src = Path(self._tmp.name)

    def test_collect_reads_dev_and_prod(self):
        write(self.src, HOME, "development", "Home.md", "a\r\nb\r\n")
        write(self.src, HOME, "production", "Home.md", "old\r\n")
        write(self.src, HOME, "development", "New.md", "new\n")
        pages = build.collect(self.src, CONFIG)
        self.assertEqual(set(pages), {"Home", "New"})
        self.assertEqual(pages["Home"].repo, HOME)
        self.assertEqual(pages["Home"].dev_text, "a\nb\n")
        self.assertEqual(pages["Home"].prod_text, "old\n")
        self.assertIsNone(pages["New"].prod_text)

    def test_missing_wiki_folders_are_empty(self):
        (self.src / "rmx-server-infra" / "development").mkdir(parents=True)
        (self.src / "rmx-server-app").mkdir()
        self.assertEqual(build.collect(self.src, CONFIG), {})

    def test_page_in_wrong_repo(self):
        write(self.src, "rmx-server-app", "development", "Server-Infra.md", "x\n")
        with self.assertRaises(build.BuildError) as cm:
            build.collect(self.src, CONFIG)
        joined = "\n".join(cm.exception.problems)
        self.assertIn("Server-Infra", joined)
        self.assertIn("rmx-server-infra", joined)

    def test_non_md_and_subfolder_rejected(self):
        write(self.src, HOME, "development", "img.png", "x")
        (self.src / HOME / "development" / "wiki" / "sub").mkdir()
        with self.assertRaises(build.BuildError) as cm:
            build.collect(self.src, CONFIG)
        self.assertEqual(len(cm.exception.problems), 2)

    def test_symlink_rejected(self):
        write(self.src, HOME, "development", "Real.md", "x\n")
        wiki = self.src / HOME / "development" / "wiki"
        try:
            os.symlink(wiki / "Real.md", wiki / "Link.md")
            os.symlink(wiki, wiki / "LinkDir", target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("symlinks not available")
        with self.assertRaises(build.BuildError) as cm:
            build.collect(self.src, CONFIG)
        joined = "\n".join(cm.exception.problems)
        self.assertIn("Link.md", joined)
        self.assertIn("LinkDir", joined)
        self.assertIn("symlink", joined)

    def test_invalid_utf8_is_a_problem(self):
        d = self.src / HOME / "development" / "wiki"
        d.mkdir(parents=True)
        (d / "Bad.md").write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(build.BuildError) as cm:
            build.collect(self.src, CONFIG)
        self.assertIn("Bad.md", "\n".join(cm.exception.problems))

    def test_bom_dropped(self):
        d = self.src / HOME / "development" / "wiki"
        d.mkdir(parents=True)
        (d / "Home.md").write_bytes(b"\xef\xbb\xbf# Home\n")
        self.assertEqual(build.collect(self.src, CONFIG)["Home"].dev_text, "# Home\n")


def banner(repo: str) -> str:
    return (
        "> **Not yet in production.** This page has changes merged into `development` "
        "that are not deployed yet: "
        f"[diff](https://github.com/rmx-lt/{repo}/compare/production...development).\n\n"
    )


FOOTER = (
    "Generated from the `wiki/` folders of the rmx-lt repos. Do not edit here: "
    "changes go through PRs, see [Wiki-Policy](Wiki-Policy).\n"
)


def P_(name, repo, dev, prod):
    return build.Page(name=name, repo=repo, dev_text=dev, prod_text=prod)


class RenderTest(unittest.TestCase):
    def test_banner_only_when_dev_differs(self):
        pages = {
            "Same": P_("Same", HOME, "x\n", "x\n"),
            "Diff": P_("Diff", HOME, "new\n", "old\n"),
            "Fresh": P_("Fresh", "rmx-server-app", "new\n", None),
            "_Sidebar": P_("_Sidebar", HOME, "new\n", "old\n"),
            "Eol": P_("Eol", HOME, "a\n", "a\r\n"),
        }
        pages["Fresh"].name = "Server-App-Fresh"
        pages["Server-App-Fresh"] = pages.pop("Fresh")
        files, _ = build.render(pages, CONFIG)
        self.assertEqual(files["Same.md"], "x\n")
        self.assertEqual(files["Diff.md"], banner(HOME) + "new\n")
        self.assertEqual(files["Server-App-Fresh.md"], banner("rmx-server-app") + "new\n")
        self.assertEqual(files["_Sidebar.md"], "new\n")
        self.assertEqual(files["Eol.md"], "a\n")

    def test_stubs(self):
        pages = {"Server-Infra": P_("Server-Infra", "rmx-server-infra", "x\n", "x\n")}
        files, warnings = build.render(pages, CONFIG)
        self.assertEqual(files["Server.md"], "This page moved to [Server-Infra](Server-Infra).\n")
        self.assertEqual(len(CONFIG["stubs"]), 24)
        for old in CONFIG["stubs"]:
            self.assertIn(old + ".md", files)
        self.assertEqual(len(warnings), 23)
        self.assertTrue(any("Server-Infra-Ansible" in w for w in warnings))
        self.assertFalse(any(w.endswith(": Server-Infra") for w in warnings))

    def test_stub_collision(self):
        pages = {"Server": P_("Server", HOME, "x\n", "x\n")}
        with self.assertRaises(build.BuildError) as cm:
            build.render(pages, CONFIG)
        self.assertIn("Server", "\n".join(cm.exception.problems))

    def test_footer(self):
        files, _ = build.render({}, CONFIG)
        self.assertEqual(files["_Footer.md"], FOOTER)
        with self.assertRaises(build.BuildError):
            build.render({"_Footer": P_("_Footer", HOME, "x\n", "x\n")}, CONFIG)


class MainTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.src = self.root / "src"
        self.out = self.root / "out"
        self.cfg = Path(__file__).resolve().parent / "config.json"

    def run_main(self):
        return build.main(["--src", str(self.src), "--out", str(self.out), "--config", str(self.cfg)])

    def test_main_writes_out_and_exit_codes(self):
        write(self.src, HOME, "development", "Home.md", "h\n")
        write(self.src, HOME, "production", "Home.md", "h\n")
        self.out.mkdir()
        (self.out / "stale.md").write_text("old", encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        expected = {"Home.md", "_Footer.md"} | {s + ".md" for s in CONFIG["stubs"]}
        self.assertEqual({p.name for p in self.out.iterdir()}, expected)
        self.assertEqual((self.out / "Home.md").read_bytes(), b"h\n")
        # invalid tree: out untouched
        write(self.src, HOME, "development", "img.png", "x")
        self.assertEqual(self.run_main(), 1)
        self.assertEqual({p.name for p in self.out.iterdir()}, expected)

    def test_main_creates_out(self):
        self.src.mkdir()
        self.assertEqual(self.run_main(), 0)
        self.assertTrue((self.out / "_Footer.md").is_file())

    def test_out_overlapping_src_refused(self):
        write(self.src, HOME, "development", "Home.md", "h\n")
        page = self.src / HOME / "development" / "wiki" / "Home.md"
        work = self.root / "work"  # a throwaway cwd, never the real repo
        work.mkdir()
        old = os.getcwd()
        os.chdir(work)
        self.addCleanup(os.chdir, old)
        for out in (self.src, self.root, self.src / "..", work, Path(".")):
            rc = build.main(["--src", str(self.src), "--out", str(out), "--config", str(self.cfg)])
            self.assertEqual(rc, 1, out)
        self.assertEqual(page.read_bytes(), b"h\n")

    def test_out_is_a_file_refused(self):
        self.src.mkdir()
        self.out.write_text("x", encoding="utf-8")
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "x")


if __name__ == "__main__":
    unittest.main()
