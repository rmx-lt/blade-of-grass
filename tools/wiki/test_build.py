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
        self.assertEqual(build.owner("Server-App-Probe-X", P, HOME), "rmx-server-app-probe")
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


if __name__ == "__main__":
    unittest.main()
