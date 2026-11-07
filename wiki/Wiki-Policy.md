# Wiki Policy

How documentation is written and kept in every repo of the project. This page is the only place the rules are written; READMEs and CLAUDE.md files link here.

## 1. Where things go

| What | Where |
|---|---|
| Knowledge: how it works, current state, decisions, how-tos | `wiki/` pages |
| Tasks and open questions | Issues, on the [Blade of Grass project](https://github.com/orgs/rmx-lt/projects/1) |
| Purpose, wiki link, quickstart commands, license | `README.md` |
| Instructions for agents only, plus a link to this page | `CLAUDE.md` |
| ESP facts reusable beyond this project (boards, chips, ESP-IDF, lessons) | The `esp-knowledge` hub |
| Pointer from code to a page | Code comment `wiki <Page> §N` |

## 2. Current state only

Pages describe how things are now. History lives in git, PRs and issues. There are no changelog pages and no "open items" sections: an open item is an issue, and the page links it.

## 3. Where pages live

Every repo keeps its pages in its own `wiki/` folder. They change only by PR.

The GitHub wiki is a generated mirror, built from the `development` branch of every repo. Direct edits there are overwritten on the next publish and reported.

A page that differs between `development` and `production` gets a banner "Not yet in production" with a link to the diff. It means the described change is merged but not deployed.

A repo owns the pages whose names start with its prefix (the repo name without `rmx-`, words capitalised). The longest matching prefix wins: `Server-App-Probe-X` belongs to rmx-server-app-probe, not rmx-server-app. Pages with no repo prefix belong to blade-of-grass.

| Page name starts with | Owner repo |
|---|---|
| `Server-Infra` | rmx-server-infra |
| `Server-App` | rmx-server-app |
| `Server-App-Probe` | rmx-server-app-probe |
| `Mower-Autopilot` | rmx-mower-autopilot |
| `Mower-Gateway` | rmx-mower-gateway |
| `Mower-Gateway-Probe` | rmx-mower-gateway-probe |
| anything else (`Home`, `_Sidebar`, `Wiki-Policy`, `Mower-Hardware`, protocol, architecture) | blade-of-grass |

## 4. When a PR must change `wiki/`

A PR changes `wiki/` when it changes something a page describes:

- behaviour
- protocol or API
- configuration or environment
- ports
- deploy or rebuild steps
- server state
- hardware facts
- a decision

Otherwise the PR body says `Wiki: none: <reason>`. Allowed reasons: refactor, tests, undocumented CI internals, dependency bump without behaviour change, typo.

The `wiki-check` workflow enforces this on PRs into `development`. A PR that changes files outside `wiki/` and none inside needs the `Wiki: none:` line with a non-empty reason. PRs from `development` into `production` are not checked: their changes were checked on the way into `development`.

## 5. Cross-repo dependencies

Declare them both ways:

- "Blocked by" on the issues.
- `Depends on: rmx-lt/<repo>#<PR>` in the PR body.

The check blocks the merge until every dependency is merged into `development`.

## 6. Conventions

- Every repo has a landing page, listed in `_Sidebar` and in `Home`.
- Sections are numbered where code cites them (`wiki <Page> §N`).
- Hardware facts say what was verified and when.
- Links use the wiki syntax `[text](Page-Name)`.
- The wiki is public. No secrets or personal data: passwords, tokens, keys, IMEI/ICCID/IMSI, home IPs, personal names or emails.
