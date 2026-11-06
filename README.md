# Blade of Grass

An open source **robotic lawn mower** project: the mower, a cloud server it talks to, and a client app to watch and control it.

This is the **meta repository**. The project lives on GitHub:

- **[Wiki](https://github.com/rmx-lt/blade-of-grass/wiki)**: overview, architecture, and the docs of every component (server, backend probe, modem probe).
- **[Project board](https://github.com/orgs/rmx-lt/projects/1)**: what is done, in progress, next and planned, as issues across all repos.

## Repos

| Part | Repo | What it is |
|---|---|---|
| **rmx-server** | [rmx-vps](https://github.com/rmx-lt/rmx-vps) | Server infrastructure: hardened Ubuntu VPS, Docker Compose, Caddy, Mosquitto |
| | [rmx-backend-probe](https://github.com/rmx-lt/rmx-backend-probe) | Learning / diagnostic Go service that rehearses the backend stack end to end |
| | [rmx-backend](https://github.com/rmx-lt/rmx-backend) | Production Go backend: telemetry, TimescaleDB, REST/WebSocket API |
| **rmx-mower** | [rmx-mower](https://github.com/rmx-lt/rmx-mower) | Mower firmware |
| | [rmx-mower-modem-probe](https://github.com/rmx-lt/rmx-mower-modem-probe) | Learning / diagnostic firmware for the mower's LTE link |
| **rmx-client** | [rmx-client](https://github.com/rmx-lt/rmx-client) | Client app to monitor and control the mower |

## Local layout

The component repos are cloned inside this one (`.gitignore` excludes their folders); the wiki is cloned next to it:

```
blade-of-grass.wiki/       ← the wiki (git clone https://github.com/rmx-lt/blade-of-grass.wiki.git)
blade-of-grass/            ← this repo
├── rmx-server/
│   ├── rmx-vps/
│   ├── rmx-backend-probe/
│   └── rmx-backend/
├── rmx-mower/
│   ├── rmx-mower-modem/
│   └── rmx-mower-modem-probe/
└── rmx-client/
```
