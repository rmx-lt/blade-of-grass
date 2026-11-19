# Pipelines

What runs in GitHub Actions across the rmx-lt repos, when, and why it is set up this way. Details of each repo's own checks and deploy are on its page: [Server-App](Server-App), [Server-Infra](Server-Infra).

## 1. Where the workflow files live

GitHub runs only the workflows in a repo's own `.github/workflows/`. So every repo keeps thin **trigger files** there: they say *when* something runs and call a shared **reusable workflow** (`on: workflow_call`) for *what* runs.

The reusable workflows live in blade-of-grass, next to the `tools/` they run (`tools/wiki/`, `tools/drift/`). Callers pin them to `@development`, so a change merged there reaches every repo at once.

They are not in `rmx-lt/.github`: that would separate the workflows from their code, and org-wide required workflows need a paid plan (the org is on Free). `rmx-lt/.github` holds only community defaults (the PR template).

**Naming:** reusable workflows start with `reusable-`. They never run on their own, and blade-of-grass needs caller and callee side by side (`wiki-check.yml` calls `reusable-wiki-check.yml`). Every workflow file starts with a header comment: what it does, when it runs, why.

The canonical trigger files for the other repos are in blade-of-grass `tools/drift/callers/split/`. The weekly drift scan reports any repo whose copy differs (§6).

## 2. Workflows per repo

All triggers are on the `development` branch unless stated.

### Every repo

| Workflow | Runs when | Does |
|---|---|---|
| `add-to-project` | an issue is opened, reopened or transferred | adds it to the [project board](https://github.com/orgs/rmx-lt/projects/1) (the board's own auto-add covers one repo on our plan); fields are set by hand |
| `wiki-check` | a PR to `development` is opened, edited or pushed | checks the PR body rules of [Wiki-Policy](Wiki-Policy) §4–5 (`Wiki:`, `Depends on:`) and that the PR links at least one issue, all of them open |

### Component repos (rmx-server-app, rmx-server-infra, rmx-mower-autopilot, rmx-mower-gateway)

| Workflow | Runs when | Does |
|---|---|---|
| `wiki-dispatch` | a push to `development` changes `wiki/` | asks blade-of-grass to republish the wiki |

`rmx-lt/.github` has no `wiki/` folder, so no `wiki-dispatch`.

### rmx-server-app

| Workflow | Runs when | Does |
|---|---|---|
| `CI` (`ci.yml`) | PRs to and pushes to `development` | Go checks and unit tests, client checks and build, integration tests, Docker image build (never pushed) |
| `Deploy` (`deploy.yml`) | a push to `production` outside `wiki/`; by hand | builds and pushes the image to GHCR, deploys it to the VPS |

### rmx-server-infra

| Workflow | Runs when | Does |
|---|---|---|
| `ci` | PRs to and pushes to `development` | playbook syntax and lint, vault encrypted, database backup/restore round trip, the whole server built from empty in a container |
| `deploy` | a push to `production` outside `wiki/`; by hand | encrypted backup, `ansible --check --diff`, apply, smoke test from outside |

### rmx-mower-autopilot, rmx-mower-gateway

Only the trigger files above. Firmware is built and flashed on the PC, not in Actions.

### blade-of-grass

| Workflow | Runs when | Does |
|---|---|---|
| `add-to-project`, `wiki-check` | as for every repo | call the reusable workflows next to them; `wiki-check` runs the checker from the PR itself, so a change to it is tested by its own PR |
| `reusable-add-to-project`, `reusable-wiki-check`, `reusable-wiki-dispatch` | only when called | the shared workflows (§1) |
| `wiki-publish` | PRs that touch `wiki/` or `tools/wiki/` (build only); pushes to `development` and `production`; weekly; by hand; the `wiki-publish` dispatch | builds the GitHub wiki from every repo's `wiki/`; only a `development` run publishes |
| `drift-scan` | weekly; by hand | §6 |

No `wiki-dispatch` here: `wiki-publish` already runs on every push.

## 3. When CI runs

CI (rmx-server-app, rmx-server-infra) runs on **PRs to `development`** and on **pushes to `development`**, and nowhere else.

- **The PR run** is the gate before merge, and what Auto-fix reacts to.
- **The push run** tests the merge commit in the background (nobody waits for it), keeps the caches on `development` warm (§5), and leaves check results on the `development` tip.
- **The `development` → `production` PR** has that tip as its head, so its required checks are already green. There is no run on PRs to `production` or on pushes to `production`.
- **Superseded runs are cancelled:** a newer commit on the same PR, or a newer push to `development`, cancels the older run. Only the latest tip matters.
- **No path filters on CI.** A filtered-out commit would have no results, and if it were the `development` tip it would block the production PR.

## 4. Deploys

Merging to `development` deploys nothing. Merging a `development` → `production` PR deploys rmx-server-app and rmx-server-infra:

1. The PR passes because the tip already has green checks (§3).
2. The push to `production` starts `deploy.yml` in each repo, unless the change is wiki-only.
3. Each deploy runs one at a time in the `production` environment and is never cancelled halfway. It runs no tests of its own.

What each deploy does, its secrets and rollback: [Server-App](Server-App), [Server-Infra](Server-Infra). A manual run (workflow_dispatch) redeploys; from any branch other than `production` it does nothing.

## 5. Required checks and caches

Required checks come from branch rulesets defined in blade-of-grass `tools/rulesets/` and applied to each repo (organization rulesets need a paid plan):

| Check | Where | Branches |
|---|---|---|
| `wiki-check / check` | every repo | `development` |
| `Go (fmt, vet, staticcheck, unit tests)`, `Client (eslint, tsc, bun test, build)`, `Integration tests (TimescaleDB + Mosquitto)`, `Docker image` | rmx-server-app | `development`, `production` |
| `check`, `db-roundtrip`, `container` | rmx-server-infra | `development`, `production` |

`wiki-check / check` is the caller job `wiki-check` plus the reusable job `check`, so trigger files keep the job ID `wiki-check`. PRs to `production` are not wiki-checked: their changes were checked on the way into `development`.

**Linked issues.** The PR's linked issues are its closing references (`Closes #<n>` or a link set in the PR sidebar) plus the issues on `Refs <issue>` lines (`#<n>`, `rmx-lt/<repo>#<n>` or the issue URL), used when the issue stays open after merge. `Part of <epic>` does not count. The check fails when there is no linked issue or one is closed: a PR linked to a closed issue moves it back to In Progress on the board, so reopen the issue first. A sidebar link, or an issue closed after the last run, is only seen on the next push or edit of the PR body.

Caches (rmx-server-app only): Go modules and build (`setup-go`), Bun packages (`actions/cache`, keyed on `web/bun.lock`), Docker layers (`type=gha`, shared by CI and deploy). A PR run can read caches saved on `development`, which is why the push run keeps them warm.

## 6. Drift scan

`drift-scan` (weekly, Monday) runs `tools/drift/scan.py`. It opens or updates one issue in blade-of-grass when a repo's trigger files differ from the canonical copies, an old `rmx.yml` is still there, a ruleset or `has_wiki` differs from `tools/rulesets/`, `LICENSE` or `README.md` is missing, or the GitHub wiki has direct edits. It closes the issue when the scan is clean.
