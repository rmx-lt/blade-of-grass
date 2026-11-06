# Blade of Grass — notes for agents

Applies to this repo and every component repo cloned inside it (`rmx-server/*`, `rmx-mower/*`, `rmx-client`). Component repos may add their own `CLAUDE.md`.

## Where things live

- **Code:** the repos of the GitHub organization `rmx-lt` (all public).
- **Knowledge:** the wiki of this repo, https://github.com/rmx-lt/blade-of-grass/wiki. Local clone `C:\Projects\blade-of-grass\blade-of-grass.wiki` (`git pull` before reading, commit and push after editing). Pages: `Home`, `Server*`, `Backend-Probe`, `Modem-*`; the sidebar lists them all. Code comments cite pages as "wiki Server §N".
- **ESP hardware facts** reusable beyond this project (boards, chips, ESP-IDF, lessons): the private hub `C:\Repos\esp-knowledge` (`jRmx0/esp-knowledge`), read its `INDEX.md` before firmware or board work. Mower-specific hardware decisions: wiki `Mower-Hardware`.
- **Work:** issues in the matching repo, on the org project **Blade of Grass** (`gh project … 1 --owner rmx-lt`, https://github.com/orgs/rmx-lt/projects/1). Use the `planning-work-in-github-issues` skill.

## Project board

| Field | Values |
|---|---|
| Status | Backlog (not scheduled), Todo (next up), In Progress, Done |
| Priority | High, Medium, Low |
| Area | Firmware, Modem, Backend, Client, Infra, Docs |

Issue types: Task, Bug, Feature, and Epic for parent issues that group sub-issues. Cross-cutting work (protocol, docs) goes in this repo's issues.

## Rules

- Never commit or write to the wiki: passwords, tokens, private keys, IMEI/ICCID/IMSI, home IPs, personal emails or names. The wiki is public.
- Server changes get a dated entry on the wiki page `Server-Changelog` (what, why, backup, undo).
- Branches in every rmx-lt repo: `feat/<issue#>-slug` → PR → `development` (default) → PR → `production`. Feature branches are deleted on merge; there is no `main`.
- Merging to `production` deploys: rmx-vps (playbook) and rmx-backend-probe (probe image) go to the VPS. Merging to `development` deploys nothing.
