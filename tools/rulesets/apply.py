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
    for rule in r["rules"]:
        params = rule.get("parameters")
        if isinstance(params, dict) and isinstance(params.get("required_status_checks"), list):
            params["required_status_checks"] = sorted(
                params["required_status_checks"], key=lambda c: c.get("context", ""))
    return r


def prune(have, want):
    """Drop dict keys of `have` that `want` does not define (GitHub fills defaults).
    Lists of equal length are pruned elementwise; others are kept so they differ."""
    if isinstance(have, dict) and isinstance(want, dict):
        return {k: prune(v, want[k]) for k, v in have.items() if k in want}
    if isinstance(have, list) and isinstance(want, list) and len(have) == len(want):
        return [prune(h, w) for h, w in zip(have, want)]
    return have


def desired(repo: str, shared: list[dict], ci: dict) -> list[dict]:
    return [copy.deepcopy(r) for r in [*shared, *ci.get(repo, [])]]


def plan(repo: str, current: list[dict], wanted: list[dict]) -> list[tuple[str, str, dict | None, int | None]]:
    """Actions as (verb, name, body, id of the existing ruleset or None)."""
    have: dict[str, dict] = {}
    actions: list[tuple[str, str, dict | None, int | None]] = []
    extras = []
    for r in current:
        if r["name"] in have:
            extras.append(r)
        else:
            have[r["name"]] = r
    want_names = {w["name"] for w in wanted}
    for w in wanted:
        h = have.get(w["name"])
        if h is None:
            actions.append(("create", w["name"], w, None))
        else:
            nw = normalize(w)
            if prune(normalize(h), nw) != nw:
                actions.append(("update", w["name"], w, h.get("id")))
    for r in current:
        if r["name"] not in want_names or r in extras:
            actions.append(("delete", r["name"], None, r.get("id")))
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
            for action, name, body, rid in actions:
                print(f"{repo}: {action} {name}")
                if args.apply:
                    base = f"repos/{ORG}/{repo}/rulesets"
                    payload = json.dumps(body) if body is not None else None
                    if action == "create":
                        gh(["api", "-X", "POST", base, "--input", "-"], payload)
                    elif action == "update":
                        gh(["api", "-X", "PUT", f"{base}/{rid}", "--input", "-"], payload)
                    else:
                        gh(["api", "-X", "DELETE", f"{base}/{rid}"])
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
