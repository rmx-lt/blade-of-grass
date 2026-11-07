"""Apply the shared branch rulesets (shared.json, ci.json) to every rmx-lt repo.

Organization rulesets need GitHub Team, so each repo gets the same definitions
through `gh`. Default is a dry run; --apply writes. Needs a `gh` login with
`repo` and `admin:org`. Exit codes: 0 in sync (or applied), 1 gh error,
2 dry run found differences.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

ORG = "rmx-lt"
WIKI_REPO = "blade-of-grass"
HERE = Path(__file__).resolve().parent
IGNORED = ("id", "node_id", "source", "source_type", "_links", "created_at",
           "updated_at", "current_user_can_bypass")


class GhError(Exception):
    pass


def gh(args: list[str], stdin: str | None = None) -> str:
    try:
        p = subprocess.run(["gh", *args], input=stdin, capture_output=True,
                           text=True, encoding="utf-8")
    except FileNotFoundError:
        raise GhError("gh not found") from None
    if p.returncode != 0:
        raise GhError(f"gh {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def normalize(ruleset: dict) -> dict:
    r = copy.deepcopy(ruleset)
    for k in IGNORED:
        r.pop(k, None)
    r["rules"] = sorted(r.get("rules", []), key=lambda rule: rule["type"])
    return r


def desired(repo: str, shared: list[dict], ci: dict) -> list[dict]:
    return [copy.deepcopy(r) for r in [*shared, *ci.get(repo, [])]]


def plan(repo: str, current: list[dict], wanted: list[dict]) -> list[tuple[str, str, dict | None]]:
    have = {}
    for r in current:
        have.setdefault(r["name"], r)
    want_names = {w["name"] for w in wanted}
    actions: list[tuple[str, str, dict | None]] = []
    for w in wanted:
        if w["name"] not in have:
            actions.append(("create", w["name"], w))
        elif normalize(have[w["name"]]) != normalize(w):
            actions.append(("update", w["name"], w))
    for r in current:
        if r["name"] not in want_names:
            actions.append(("delete", r["name"], None))
    return actions


def _json(run, args: list[str]):
    return json.loads(run(args) or "null")


def current_rulesets(run, repo: str) -> list[dict]:
    listing = _json(run, ["api", f"repos/{ORG}/{repo}/rulesets"])
    return [_json(run, ["api", f"repos/{ORG}/{repo}/rulesets/{r['id']}"]) for r in listing]


def main(argv: list[str] | None = None, gh=gh) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--repo", help="only this repo")
    args = ap.parse_args(argv)
    shared = json.loads((HERE / "shared.json").read_text(encoding="utf-8"))
    ci = json.loads((HERE / "ci.json").read_text(encoding="utf-8"))
    differences = False
    try:
        repos = sorted(r["name"] for r in _json(gh, [
            "repo", "list", ORG, "--no-archived", "--limit", "200", "--json", "name"]))
        if args.repo:
            repos = [r for r in repos if r == args.repo]
        for repo in repos:
            current = current_rulesets(gh, repo)
            actions = plan(repo, current, desired(repo, shared, ci))
            want_wiki = repo == WIKI_REPO
            has_wiki = bool(_json(gh, ["api", f"repos/{ORG}/{repo}"]).get("has_wiki"))
            wiki_change = has_wiki != want_wiki
            if not actions and not wiki_change:
                print(f"{repo}: in sync")
                continue
            ids = {r["name"]: r["id"] for r in current}
            for action, name, body in actions:
                print(f"{repo}: {action} {name}")
                if args.apply:
                    base = f"repos/{ORG}/{repo}/rulesets"
                    payload = json.dumps(body) if body is not None else None
                    if action == "create":
                        gh(["api", "-X", "POST", base, "--input", "-"], payload)
                    elif action == "update":
                        gh(["api", "-X", "PUT", f"{base}/{ids[name]}", "--input", "-"], payload)
                    else:
                        gh(["api", "-X", "DELETE", f"{base}/{ids[name]}"])
            if wiki_change:
                print(f"{repo}: has_wiki {str(has_wiki).lower()} -> {str(want_wiki).lower()}")
                if args.apply:
                    gh(["repo", "edit", f"{ORG}/{repo}", f"--enable-wiki={str(want_wiki).lower()}"])
            differences = True
    except GhError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2 if differences and not args.apply else 0


if __name__ == "__main__":
    sys.exit(main())
