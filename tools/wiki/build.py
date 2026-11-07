"""Build the GitHub wiki from the wiki/ folders of the rmx-lt repos.

Pure functions over a source tree SRC/<repo>/<branch>/wiki/*.md; no network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

BRANCHES = ("development", "production")


class BuildError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class Page:
    name: str
    repo: str
    dev_text: str
    prod_text: str | None


def load_config(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def owner(page: str, prefixes: dict[str, str], home_repo: str) -> str:
    best_repo, best_len = home_repo, -1
    for repo, prefix in prefixes.items():
        if (page == prefix or page.startswith(prefix + "-")) and len(prefix) > best_len:
            best_repo, best_len = repo, len(prefix)
    return best_repo


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def collect(src: Path, config: dict) -> dict[str, Page]:
    src = Path(src)
    home = config["home_repo"]
    prefixes = config["prefixes"]
    problems: list[str] = []
    pages: dict[str, Page] = {}
    for repo in [home, *prefixes]:
        wiki = src / repo / "development" / "wiki"
        if not wiki.is_dir():
            continue
        for entry in sorted(wiki.iterdir()):
            where = f"{repo}/development/wiki/{entry.name}"
            if entry.is_dir():
                problems.append(f"{where}: subfolders are not allowed in wiki/")
                continue
            if entry.suffix != ".md":
                problems.append(f"{where}: only .md files are allowed in wiki/")
                continue
            name = entry.stem
            expected = owner(name, prefixes, home)
            if expected != repo:
                problems.append(f"{where}: page {name} belongs in repo {expected}")
                continue
            prod = src / repo / "production" / "wiki" / entry.name
            pages[name] = Page(
                name=name,
                repo=repo,
                dev_text=_read(entry),
                prod_text=_read(prod) if prod.is_file() else None,
            )
    if problems:
        raise BuildError(problems)
    return pages
