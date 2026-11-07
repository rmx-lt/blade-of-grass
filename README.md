# Blade of Grass

An open source **robotic lawn mower** project: the mower, a cloud server it talks to, and a client app to watch and control it.

This is the **meta repository**. The project lives on GitHub:

- **[Wiki](https://github.com/rmx-lt/blade-of-grass/wiki)**: overview, architecture, and the docs of every component (server, app probe, gateway probe), written in each repo's `wiki/` folder, rules: [Wiki-Policy](https://github.com/rmx-lt/blade-of-grass/wiki/Wiki-Policy).
- **[Project board](https://github.com/orgs/rmx-lt/projects/1)**: what is done, in progress, next and planned, as issues across all repos.

## Repos

| Part | Repo | What it is |
|---|---|---|
| **rmx-server** | [rmx-server-infra](https://github.com/rmx-lt/rmx-server-infra) | Server infrastructure: hardened Ubuntu VPS, Docker Compose, Caddy, Mosquitto |
| | [rmx-server-app](https://github.com/rmx-lt/rmx-server-app) | Production app: Go backend (telemetry, TimescaleDB, REST/WebSocket API) and React/TypeScript frontend to monitor and control the mower |
| | [rmx-server-app-probe](https://github.com/rmx-lt/rmx-server-app-probe) | Learning / diagnostic Go service that rehearses the app stack end to end |
| **rmx-mower** | [rmx-mower-autopilot](https://github.com/rmx-lt/rmx-mower-autopilot) | Mower firmware on the ESP32-P4 board: sensors, motion, blade, safety |
| | [rmx-mower-gateway](https://github.com/rmx-lt/rmx-mower-gateway) | Gateway firmware: the mower's LTE link to the server |
| | [rmx-mower-gateway-probe](https://github.com/rmx-lt/rmx-mower-gateway-probe) | Learning / diagnostic firmware for the mower's LTE link |

## Local layout

The component repos are cloned inside this one (`.gitignore` excludes their folders):

```
blade-of-grass/            ← this repo
├── rmx-server/
│   ├── rmx-server-infra/
│   ├── rmx-server-app/
│   └── rmx-server-app-probe/
└── rmx-mower/
    ├── rmx-mower-gateway/
    ├── rmx-mower-gateway-probe/
    └── rmx-mower-autopilot/
```

## License

Code and documentation are licensed under [Apache-2.0](LICENSE).
