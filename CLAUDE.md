# Blade of Grass — notes for agents

Applies to this repo and every component repo cloned inside it (`rmx-server/*`, `rmx-mower/*`). Component repos may add their own `CLAUDE.md`.

## Where things live

- **Code:** the repos of the GitHub organization `rmx-lt` (all public).
- **Knowledge:** the wiki, https://github.com/rmx-lt/blade-of-grass/wiki. Pages live in the owning repo's `wiki/` folder and change by PR. Read [Wiki-Policy](https://github.com/rmx-lt/blade-of-grass/wiki/Wiki-Policy) (local `wiki/Wiki-Policy.md`) before writing docs. The GitHub wiki is generated from these folders by the `wiki-publish` workflow; never edit it directly. Code comments cite pages as "wiki `<Page>` §N".
- **ESP hardware facts** reusable beyond this project (boards, chips, ESP-IDF, lessons): the private hub `C:\Repos\esp-knowledge` (`jRmx0/esp-knowledge`), read its `INDEX.md` before firmware or board work. Mower-specific hardware decisions: wiki `Mower-Hardware`.
- **Work:** issues in the matching repo, on the org project **Blade of Grass** (`gh project … 1 --owner rmx-lt`, https://github.com/orgs/rmx-lt/projects/1). Use the `planning-work-in-github-issues` skill. Every issue gets all of the board's fields filled; read the fields and their options from the board (`gh project field-list 1 --owner rmx-lt`), not from docs. Use the org's issue types, Epic for parents. Cross-cutting work (protocol, docs) goes in this repo's issues.

## Shared tooling

This repo holds the tooling for all rmx-lt repos:

- **Shared workflows** in `.github/workflows/`: `add-to-project` (adds new issues to the board; fields stay manual), `wiki-check` (PR body rules), `wiki-dispatch` (triggers `wiki-publish` on wiki changes). Each repo calls them from its own `rmx.yml`, pinned to `@development`.
- **`tools/rulesets/apply.py`**: one branch-ruleset definition applied to every repo (dry run by default).
- **`tools/drift/scan.py`**: weekly `drift-scan` workflow; opens or updates one issue when a repo drifts (callers, rulesets, wiki, LICENSE, README).
- **`tools/wiki/`**: the wiki builder and the PR checker behind `wiki-publish` and `wiki-check`.
- The org repo `rmx-lt/.github` holds the shared PR template.

## Rules

- Never commit or write to the wiki: passwords, tokens, private keys, IMEI/ICCID/IMSI, home IPs, personal emails or names. The wiki is public; see Wiki-Policy.
- Branches in every rmx-lt repo: `feat/<issue#>-slug` → PR → `development` (default) → PR → `production`. Feature branches are deleted on merge; there is no `main`.
- Merging to `production` deploys: rmx-server-infra (playbook) and rmx-server-app (backend image) go to the VPS. Merging to `development` deploys nothing.
