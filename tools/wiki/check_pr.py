"""wiki-check: PR body rules from Wiki-Policy sections 4-5.

Pure rules (wiki_reason, parse_depends, evaluate) plus a thin `gh api` wrapper (main).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

ORG = "rmx-lt"
WIKI_NONE = re.compile(r"^Wiki:[ \t]*none:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
DEPENDS = re.compile(r"^Depends on:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
DEP_ITEM = re.compile(rf"^{ORG}/([A-Za-z0-9_-][A-Za-z0-9._-]*)#(\d+)$")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _clean(body: str | None) -> str:
    return COMMENT.sub("", (body or "").replace("\r", ""))


def escape_cmd(msg: str) -> str:
    """Escape a workflow-command message (::error::...)."""
    return msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def wiki_reason(body: str) -> str | None:
    m = WIKI_NONE.search(_clean(body))
    if not m:
        return None
    reason = m.group(1).strip()
    return None if re.fullmatch(r"<[^>]*>", reason) else reason


def parse_depends(body: str) -> tuple[list[tuple[str, int]], list[str]]:
    deps: list[tuple[str, int]] = []
    problems: list[str] = []
    for m in DEPENDS.finditer(_clean(body)):
        items = [i.strip() for i in m.group(1).split(",") if i.strip()]
        if not items:
            problems.append("empty Depends on line")
        for item in items:
            d = DEP_ITEM.match(item)
            if d:
                deps.append((d.group(1), int(d.group(2))))
            else:
                problems.append(f"Depends on: '{item}' is not of the form {ORG}/<repo>#<n>")
    return deps, problems


def evaluate(
    body: str, files: list[str], deps: dict[tuple[str, int], dict | None]
) -> list[str]:
    body = body or ""
    problems: list[str] = []
    wiki_changed = any(f.startswith("wiki/") for f in files)
    code_changed = any(not f.startswith("wiki/") for f in files)
    if code_changed and not wiki_changed and wiki_reason(body) is None:
        problems.append(
            "Code changed without a wiki change: add a 'Wiki: none: <reason>' line "
            "to the PR body or change a page under wiki/ (Wiki-Policy sections 4-5)"
        )
    parsed, bad = parse_depends(body)
    problems.extend(bad)
    for repo, n in parsed:
        ref = f"{ORG}/{repo}#{n}"
        pr = deps.get((repo, n))
        if pr is None:
            problems.append(f"Depends on {ref}: not found or not a pull request")
        elif not pr.get("merged"):
            problems.append(f"Depends on {ref}: not merged yet")
        elif (pr.get("base") or {}).get("ref") != "development":
            problems.append(
                f"Depends on {ref}: merged into '{(pr.get('base') or {}).get('ref')}', "
                "not 'development'"
            )
    return problems


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True, encoding="utf-8")


def _changed_files(repo: str, pr: int) -> list[str]:
    r = _gh(f"repos/{repo}/pulls/{pr}/files", "--paginate", "--jq", ".[].filename")
    if r.returncode != 0:
        raise RuntimeError(f"cannot list files of {repo}#{pr}: {r.stderr.strip()}")
    return [line for line in r.stdout.splitlines() if line]



def _pr_body(repo: str, pr: int) -> str:
    r = _gh(f"repos/{repo}/pulls/{pr}", "--jq", ".body")
    if r.returncode != 0:
        raise RuntimeError(f"cannot read {repo}#{pr}: {r.stderr.strip()}")
    return r.stdout


def _lookup(repo: str, n: int) -> dict | None:
    r = _gh(f"repos/{ORG}/{repo}/pulls/{n}")
    if r.returncode == 0:
        return json.loads(r.stdout)
    if "404" in r.stderr or "Not Found" in r.stderr:
        return None
    raise RuntimeError(f"cannot look up {ORG}/{repo}#{n}: {r.stderr.strip()}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    args = ap.parse_args(argv)
    try:
        body = _pr_body(args.repo, args.pr)
        files = _changed_files(args.repo, args.pr)
        parsed, _ = parse_depends(body)
        deps = {key: _lookup(*key) for key in dict.fromkeys(parsed)}
    except RuntimeError as e:
        print(f"::error::{escape_cmd(str(e))}")
        return 1
    problems = evaluate(body, files, deps)
    for p in problems:
        print(f"::error::{escape_cmd(p)}")
    if problems:
        return 1
    print("wiki-check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
