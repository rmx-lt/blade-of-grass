"""Build the GitHub wiki from the wiki/ folders of the rmx-lt repos.

Pure functions over a source tree SRC/<repo>/<branch>/wiki/*.md; no network.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
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
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


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
            if entry.is_symlink():
                problems.append(f"{where}: symlinks are not allowed in wiki/")
                continue
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
            try:
                dev_text = _read(entry)
                prod_text = _read(prod) if prod.is_file() and not prod.is_symlink() else None
            except UnicodeDecodeError:
                problems.append(f"{where}: not valid UTF-8")
                continue
            pages[name] = Page(name=name, repo=repo, dev_text=dev_text, prod_text=prod_text)
    if problems:
        raise BuildError(problems)
    return pages


def _banner(repo: str) -> str:
    return (
        "> **Not yet in production.** This page has changes merged into `development` "
        "that are not deployed yet: "
        f"[diff](https://github.com/rmx-lt/{repo}/compare/production...development).\n\n"
    )


FOOTER = (
    "Generated from the `wiki/` folders of the rmx-lt repos. Do not edit here: "
    "changes go through PRs, see [Wiki-Policy](Wiki-Policy).\n"
)


def render(pages: dict[str, Page]) -> dict[str, str]:
    files: dict[str, str] = {}
    if "_Footer" in pages:
        raise BuildError(["page _Footer clashes with the generated footer"])
    for name, page in pages.items():
        text = page.dev_text.replace("\r\n", "\n")
        prod = None if page.prod_text is None else page.prod_text.replace("\r\n", "\n")
        if not name.startswith("_") and prod != text:
            text = _banner(page.repo) + text
        files[f"{name}.md"] = text
    files["_Footer.md"] = FOOTER
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "config.json")
    args = ap.parse_args(argv)
    out = args.out.resolve()
    src = args.src.resolve()
    cwd = Path.cwd().resolve()
    for other in (cwd, src):
        if out == other or out in other.parents:
            print(f"error: --out {args.out} must not be the working directory, "
                  "--src, or an ancestor of either", file=sys.stderr)
            return 1
    if out.exists() and not out.is_dir():
        print(f"error: --out {args.out} exists and is not a directory", file=sys.stderr)
        return 1
    try:
        config = load_config(args.config)
        files = render(collect(args.src, config))
    except BuildError as e:
        for problem in e.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for fname, content in files.items():
        with open(out / fname, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
