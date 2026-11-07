"""Weekly drift scan across the rmx-lt repos.

On each repo's development branch: the caller workflow matches the canonical
file (tools/drift/callers/), rulesets and has_wiki match tools/rulesets, and
README.md and LICENSE exist. The GitHub wiki tip must be a "Publish wiki from"
commit, so a direct edit shows up until the next publish overwrites it.

Default prints findings and exits 2 when there are any (0 when in sync,
1 on a gh error). --update-issue opens or replaces one issue, and closes it
when the scan is clean. Creating that issue with a PAT (not GITHUB_TOKEN)
lets the repo's rmx.yml add it to the project.

Needs a gh login that can read rulesets (Administration) on every repo and,
with --update-issue, open issues on rmx-lt/blade-of-grass. Spec:
https://github.com/rmx-lt/blade-of-grass/issues/32
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULESETS = HERE.parent / "rulesets"
sys.path.insert(0, str(RULESETS))

import apply  # noqa: E402

ORG = apply.ORG
HOME = apply.WIKI_REPO
WIKI_GIT = "https://github.com/rmx-lt/blade-of-grass.wiki.git"
ISSUE_REPO = "rmx-lt/blade-of-grass"
ISSUE_TITLE = "Drift: rmx-lt repos are out of sync"
PUBLISH_PREFIX = "Publish wiki from"
MARKER = "<!-- drift-scan -->"
FILES = ("LICENSE", "README.md")
CALLER = ".github/workflows/rmx.yml"
HOME_USES = (
    "uses: ./.github/workflows/add-to-project.yml",
    "uses: ./.github/workflows/wiki-check.yml",
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def gh_plain(args, stdin=None):
    """apply.gh, with color codes removed. CLICOLOR_FORCE makes gh color JSON."""
    return ANSI.sub("", apply.gh(args, stdin))


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def load_templates(directory: Path | None = None) -> dict[str, str]:
    directory = directory or (HERE / "callers")
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.yml"))}


def fetch_text(gh, repo: str, path: str) -> str | None:
    try:
        return gh([
            "api", "-H", "Accept: application/vnd.github.raw",
            f"repos/{ORG}/{repo}/contents/{path}?ref=development",
        ])
    except apply.GhError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return None
        raise


def check_caller(repo: str, text: str | None, templates: dict[str, str]) -> list[str]:
    if text is None:
        return [f"{repo}: {CALLER} missing on development"]
    norm = normalize_text(text)
    if repo == HOME:
        missing = [needle for needle in HOME_USES if needle not in norm]
        if missing:
            return [f"{repo}: {CALLER} does not call {', '.join(missing)}"]
        return []
    kind = "dot-github" if repo == ".github" else "component"
    if norm != normalize_text(templates[kind]):
        return [f"{repo}: {CALLER} differs from tools/drift/callers/{kind}.yml"]
    return []


def check_files(repo: str, present: dict[str, bool]) -> list[str]:
    return [f"{repo}: {name} missing on development"
            for name in FILES if not present.get(name)]


def check_rules(repo: str, current: list[dict], has_wiki: bool,
                shared: list[dict], ci: dict) -> list[str]:
    lines = [f"{repo}: ruleset {action} {name}"
             for action, name, _body, _rid in apply.plan(repo, current, apply.desired(repo, shared, ci))]
    want_wiki = repo == HOME
    if bool(has_wiki) != want_wiki:
        lines.append(f"{repo}: has_wiki {str(bool(has_wiki)).lower()} -> {str(want_wiki).lower()}")
    return lines


def check_wiki(commits: list[tuple[str, str]] | None, error: str | None) -> list[str]:
    if error:
        return [f"GitHub wiki: unreadable ({error})"]
    if not commits:
        return ["GitHub wiki: no commits"]
    if commits[0][1].startswith(PUBLISH_PREFIX):
        return []
    after = []
    for sha, subject in commits:
        if subject.startswith(PUBLISH_PREFIX):
            return [f"GitHub wiki: {len(after)} commit(s) after the last publish", *after]
        after.append(f"{sha[:7]} {subject}")
    return ["GitHub wiki: no publish commit in the fetched history", *after]


def collect(gh, templates: dict[str, str], shared: list[dict], ci: dict,
            wiki: tuple[list[tuple[str, str]] | None, str | None]) -> list[str]:
    repos = sorted(r["name"] for r in json.loads(gh([
        "repo", "list", ORG, "--no-archived", "--limit", "200", "--json", "name"]) or "[]"))
    findings: list[str] = []
    for repo in repos:
        caller = fetch_text(gh, repo, CALLER)
        present = {name: fetch_text(gh, repo, name) is not None for name in FILES}
        current = apply.current_rulesets(gh, repo)
        meta = json.loads(gh(["api", f"repos/{ORG}/{repo}"]) or "null")
        findings += check_caller(repo, caller, templates)
        findings += check_files(repo, present)
        findings += check_rules(repo, current, bool(meta.get("has_wiki")), shared, ci)
    findings += check_wiki(*wiki)
    return findings


def issue_body(findings: list[str]) -> str:
    items = "\n".join(f"- {line}" for line in findings)
    return (
        f"{MARKER}\n"
        "The weekly drift scan found differences. The next run replaces this body.\n\n"
        "## Drift\n"
        f"{items}\n\n"
        "## Notes\n"
        "Checked by `tools/drift/scan.py` "
        "([blade-of-grass#32](https://github.com/rmx-lt/blade-of-grass/issues/32)). "
        "Fix the repo, or change the definition in blade-of-grass "
        "(`tools/rulesets/`, `tools/drift/callers/`) and apply it.\n"
    )


def _open_drift_issues(gh) -> list[int]:
    listing = json.loads(gh([
        "issue", "list", "--repo", ISSUE_REPO, "--state", "open",
        "--search", f'in:title "{ISSUE_TITLE}"',
        "--json", "number,title", "--limit", "20",
    ]) or "[]")
    return sorted(i["number"] for i in listing if i.get("title") == ISSUE_TITLE)


def update_issue(findings: list[str], gh) -> str:
    numbers = _open_drift_issues(gh)
    if not findings:
        if not numbers:
            return "in sync"
        for number in numbers:
            gh(["issue", "comment", str(number), "--repo", ISSUE_REPO,
                "--body", "Drift scan is clean. Closing."])
            gh(["issue", "close", str(number), "--repo", ISSUE_REPO,
                "--reason", "completed"])
        return "closed " + ", ".join(f"#{n}" for n in numbers)
    body = issue_body(findings)
    if not numbers:
        created = gh(["issue", "create", "--repo", ISSUE_REPO, "--title", ISSUE_TITLE,
                      "--type", "Task", "--body", body]).strip()
        return f"created {created}"
    primary = numbers[0]
    gh(["issue", "edit", str(primary), "--repo", ISSUE_REPO, "--body", body])
    for number in numbers[1:]:
        gh(["issue", "comment", str(number), "--repo", ISSUE_REPO,
            "--body", f"Duplicate drift issue. The scan updates #{primary}."])
        gh(["issue", "close", str(number), "--repo", ISSUE_REPO, "--reason", "not planned"])
    return f"updated #{primary}"


def fetch_wiki_commits() -> tuple[list[tuple[str, str]] | None, str | None]:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    url = WIKI_GIT
    if token:
        url = f"https://x-access-token:{token}@github.com/rmx-lt/blade-of-grass.wiki.git"
    with tempfile.TemporaryDirectory() as directory:
        cloned = subprocess.run(
            ["git", "clone", "--depth", "50", "--quiet", url, directory],
            capture_output=True, text=True, encoding="utf-8")
        if cloned.returncode != 0:
            detail = (cloned.stderr or cloned.stdout or "git clone failed").strip()
            if token:
                detail = detail.replace(token, "***")
            line = detail.splitlines()[-1] if detail else "git clone failed"
            return None, line
        logged = subprocess.run(
            ["git", "-C", directory, "log", "-50", "--format=%H%x1f%s"],
            capture_output=True, text=True, encoding="utf-8", check=True)
    commits = []
    for line in logged.stdout.splitlines():
        sha, sep, subject = line.partition("\x1f")
        if sep:
            commits.append((sha, subject))
    return commits, None


def main(argv: list[str] | None = None, gh=gh_plain,
         wiki: tuple[list[tuple[str, str]] | None, str | None] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-issue", action="store_true",
                        help="open, update, or close the drift issue")
    args = parser.parse_args(argv)
    try:
        templates = load_templates()
        shared = json.loads((RULESETS / "shared.json").read_text(encoding="utf-8"))
        ci = json.loads((RULESETS / "ci.json").read_text(encoding="utf-8"))
        findings = collect(gh, templates, shared, ci,
                           wiki if wiki is not None else fetch_wiki_commits())
        if findings:
            print("\n".join(findings))
        else:
            print("in sync")
        if args.update_issue:
            print(update_issue(findings, gh))
    except apply.GhError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
