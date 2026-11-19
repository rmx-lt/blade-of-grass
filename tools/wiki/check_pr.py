"""wiki-check: PR body rules from Wiki-Policy sections 4-5, and the linked issue rule.

Every PR links at least one issue (a closing reference or a `Refs <issue>` line) and
every linked issue is open (rmx-lt/blade-of-grass#81).

Pure rules (wiki_reason, parse_depends, parse_refs, evaluate, check_issues) plus a
thin `gh api` wrapper (main).
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
REFS = re.compile(r"^Refs:?[ \t]+(.*)$", re.IGNORECASE | re.MULTILINE)
REF_ITEM = re.compile(
    r"https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)"
    r"|(?<![\w/])([\w.-]+/[\w.-]+)#(\d+)"
    r"|(?<![\w/#])#(\d+)"
)


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


def parse_refs(body: str, repo: str) -> tuple[list[tuple[str, int]], list[str]]:
    """Issues named on `Refs` lines, as (owner/name, number); bare #n is in `repo`."""
    refs: list[tuple[str, int]] = []
    problems: list[str] = []
    for m in REFS.finditer(_clean(body)):
        items = REF_ITEM.findall(m.group(1))
        if not items:
            problems.append(f"Refs line names no issue: '{m.group(1).strip()}'")
        for url_repo, url_n, short_repo, short_n, bare_n in items:
            if url_repo:
                refs.append((url_repo, int(url_n)))
            elif short_repo:
                refs.append((short_repo, int(short_n)))
            else:
                refs.append((repo, int(bare_n)))
    return refs, problems


def check_issues(linked: dict[tuple[str, int], str | None]) -> list[str]:
    """linked: (owner/name, n) -> 'open' / 'closed', or None when not an issue."""
    if not linked:
        return [
            "No linked issue: link the open issue this PR belongs to ('Closes #<n>', "
            "or a 'Refs <issue>' line when the issue stays open after merge). If the "
            "work belongs to a closed issue, reopen it first"
        ]
    problems: list[str] = []
    for (repo, n), state in linked.items():
        ref = f"{repo}#{n}"
        if state is None:
            problems.append(f"Linked {ref}: not found or not an issue")
        elif state != "open":
            problems.append(
                f"Linked issue {ref} is closed: reopen it first (a PR linked to a closed "
                "issue moves it back to In Progress on the board)"
            )
    return problems


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


def _closing_issues(repo: str, pr: int) -> dict[tuple[str, int], str]:
    """Closing references: `Closes` keywords and links set in the PR sidebar."""
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$pr:Int!){repository(owner:$owner,name:$name)"
        "{pullRequest(number:$pr){closingIssuesReferences(first:50)"
        "{nodes{number state repository{nameWithOwner}}}}}}"
    )
    r = _gh(
        "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}",
        "-F", f"pr={pr}",
        "--jq", ".data.repository.pullRequest.closingIssuesReferences.nodes",
    )
    if r.returncode != 0:
        raise RuntimeError(f"cannot read the linked issues of {repo}#{pr}: {r.stderr.strip()}")
    return {
        (i["repository"]["nameWithOwner"], i["number"]): i["state"].lower()
        for i in json.loads(r.stdout or "[]")
    }


def _issue_state(repo: str, n: int) -> str | None:
    r = _gh(f"repos/{repo}/issues/{n}")
    if r.returncode == 0:
        issue = json.loads(r.stdout)
        return None if "pull_request" in issue else issue["state"]
    if "404" in r.stderr or "Not Found" in r.stderr:
        return None
    raise RuntimeError(f"cannot look up {repo}#{n}: {r.stderr.strip()}")


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
        linked: dict[tuple[str, int], str | None] = _closing_issues(args.repo, args.pr)
        refs, ref_problems = parse_refs(body, args.repo)
        for key in refs:
            if key not in linked:
                linked[key] = _issue_state(*key)
    except RuntimeError as e:
        print(f"::error::{escape_cmd(str(e))}")
        return 1
    problems = evaluate(body, files, deps) + ref_problems + check_issues(linked)
    for p in problems:
        print(f"::error::{escape_cmd(p)}")
    if problems:
        return 1
    print("wiki-check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
