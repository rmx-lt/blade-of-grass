# Mower-Protocol

The contract between the mower and the server: MQTT topics and payloads, commands, job and border transfer, corrections, and the link between the mower's two boards. The server ([Server-App](Server-App)), the gateway firmware ([Mower-Gateway](Mower-Gateway)), the autopilot firmware ([Mower-Autopilot](Mower-Autopilot)) and the device simulator are written against this page.

**Contract version: 0.1.**

**Status:** this page is the target. The gateway and the server run an older subset today (unprefixed `status`, `cmd`, `cmd/ack`, `firmware` and `fw/…` topics, described in [Mower-Gateway-Server-Contract](Mower-Gateway-Server-Contract)); the autopilot has no code. The work is tracked in [blade-of-grass#6](https://github.com/rmx-lt/blade-of-grass/issues/6).

## Contents

1. [Roles](#1-roles)
2. [Version](#2-version)
3. [Topics](#3-topics)
4. [Common rules](#4-common-rules)
5. [Commands and acks](#5-commands-and-acks)
6. [Gateway topics](#6-gateway-topics)
7. [Autopilot state, telemetry and events](#7-autopilot-state-telemetry-and-events)
8. [Autopilot commands](#8-autopilot-commands)
9. [Live driving](#9-live-driving)
10. [Border recording](#10-border-recording)
11. [Jobs](#11-jobs)
12. [Chunk transfer](#12-chunk-transfer)
13. [Corrections (NTRIP)](#13-corrections-ntrip)
14. [Board link (UART)](#14-board-link-uart)
15. [Monitor](#15-monitor)
16. [Metrics](#16-metrics)

## 1. Roles

| Part | Role |
|---|---|
| **Server** (rmx-server-app) | Owns maps and planning. Plans every path, keeps the draft border during recording, sends commands, stores telemetry. The only publisher of commands. |
| **Gateway** (T-SIM7600 board) | Communications only: LTE, MQTT, the NTRIP client, later a local link (Wi-Fi or Bluetooth). Its only hardware connection besides the modem is the UART to the autopilot. It never reads autopilot payloads. |
| **Autopilot** (ESP32-P4 board) | Everything about the mower: positioning (RTK GNSS), drive motors, blade, battery. Its only connection to the outside is the UART to the gateway. It holds no map and goes only where it is told. |

Hardware the contract assumes: drive motors with encoders, blade motor(s) with an encoder, battery voltage and current, an RTK GNSS receiver with one antenna. There is no dock and there are no safety sensors, so the contract has no docking and no safety rules beyond the live-driving timeout (§9). The modem's own GNSS is not used.

## 2. Version

- The version is `major.minor`. Each side reports the version it implements in its retained state message (`protocol`, §6.2 and §7.1). Other messages carry no version.
- A minor version only adds: new topics, new commands, new optional fields. Receivers ignore fields and events they do not know and answer an unknown command with `unknown_cmd`.
- A major version may change or remove anything. While the major version is 0, a minor version may too.
- When a board reports a `protocol` the server does not support, the server shows that and sends that board no command except `ota`.
- Version 1 is the fully operational mower.

## 3. Topics

A device's name is the CN of its client certificate ([Device-CA](Device-CA)): 1–32 characters of `[A-Za-z0-9_-]`. The broker forces the MQTT client id to the name and limits each device to `mower/<name>/#`, plus read access to `mower/status/server`. `status` cannot be a device name, because of that shared topic.

Every device topic names its source: `mower/<name>/gateway/…` or `mower/<name>/autopilot/…`.

| Topic | Direction | QoS | Retained | Payload | § |
|---|---|---|---|---|---|
| `mower/status/server` | server → all | 1 | yes | `online` / `offline` (server's last will) | |
| `mower/<name>/gateway/status` | up | 1 | yes | `online` / `offline` (gateway's last will) | 6.1 |
| `mower/<name>/gateway/state` | up | 1 | yes | JSON | 6.2 |
| `mower/<name>/gateway/telemetry` | up | 0 | no | JSON | 6.3 |
| `mower/<name>/gateway/monitor` | up | 0 | no | JSON samples | 15 |
| `mower/<name>/gateway/metrics/<part>` | up | 1 | yes | JSON catalogue | 16 |
| `mower/<name>/gateway/cmd` | down | 1 | no | JSON command | 5, 6.4 |
| `mower/<name>/gateway/cmd/ack` | up | 1 | no | JSON ack | 5 |
| `mower/<name>/gateway/fw/req`, `…/chunk`, `…/res` | up, down, down | 1 | no | chunk transfer | 12 |
| `mower/<name>/autopilot/state` | up | 1 | yes | JSON | 7.1 |
| `mower/<name>/autopilot/telemetry` | up | 0 | no | JSON | 7.2 |
| `mower/<name>/autopilot/event` | up | 1 | no | JSON | 7.3 |
| `mower/<name>/autopilot/cmd` | down | 1 | no | JSON command | 5, 8 |
| `mower/<name>/autopilot/cmd/ack` | up | 1 | no | JSON ack | 5 |
| `mower/<name>/autopilot/drive` | down | 0 | no | JSON setpoint | 9 |
| `mower/<name>/autopilot/recording` | up | 1 | no | JSON points | 10 |
| `mower/<name>/autopilot/monitor` | up | 0 | no | JSON samples | 15 |
| `mower/<name>/autopilot/metrics/<part>` | up | 1 | yes | JSON catalogue | 16 |
| `mower/<name>/autopilot/job/req`, `…/chunk`, `…/res` | up, down, down | 1 | no | chunk transfer | 11, 12 |
| `mower/<name>/autopilot/fw/req`, `…/chunk`, `…/res` | up, down, down | 1 | no | chunk transfer | 12 |

"Up" is device → server, "down" is server → device.

The gateway publishes and subscribes the `autopilot/…` topics on the autopilot's behalf (§14) and passes payloads through unchanged.

**MQTT connection.** The gateway and the server connect with a clean session, so nothing published while a side was offline is delivered later. The gateway's keep-alive is 15 s.

## 4. Common rules

- JSON payloads on MQTT are one UTF-8 object, at most **4096 bytes**. Unknown fields are ignored. The limit is for messages, not for files (§11, §12).
- An **id** (command id, session, job, request id) is 1–64 characters of `[A-Za-z0-9_-]`.
- **Position** is latitude and longitude in degrees with 8 decimals, as the RTK receiver reports them (with LitPOS corrections that is the ETRS89 frame, a few decimetres from the WGS84 of satellite imagery). A point is the array `[lat, lon]`. Each side converts to metres internally; no local coordinate system is shared.
- **Units:** metres, seconds, m/s, rad/s, volts, amperes, watts. Headings are degrees clockwise from true north, 0–360.
- Only the status, state and metric catalogue topics are retained.
- **The mower supplies finished values.** Anything computed from measurements (battery level, power) is computed on the mower and sent; the server stores and shows what it gets and holds no formulas or constants about the mower's hardware. Which values a board measures, their units, ranges and warning levels come from the board's own catalogue (§16), not from this page.

### 4.1 Time and boot

- **Time** is Unix time in seconds; `time` fields may carry a fraction (`1794650000.25`). `expires_at` is a whole number.
- The gateway sets its clock from network time (SNTP) after it connects and keeps it within 0.1 s. The autopilot takes its time from the gateway's heartbeat (§14.4). The server uses network time too.
- A board whose clock is not set yet still sends its messages, with `time: null`.
- **`boot`** is a board's boot counter: a whole number that grows by one every time the board starts, kept across restarts. It is not a time. It is in state, telemetry and events. A new `boot` value tells the server that the board restarted: its counters (§16.3) start again from 0 and its open commands are gone (§5).

### 4.2 Server link

Both boards act on whether the server can be reached. It is defined once, here:

- The **server link is up** when the gateway's MQTT connection is up **and** the retained `mower/status/server` says `online`. A server that has crashed while the broker still runs therefore counts as down.
- The gateway tells the autopilot both facts in every heartbeat (§14.4). For the autopilot the link is also down while the board link is down.
- The **server link is lost** when it has been down for 10 s without a break. Shorter drops change nothing.
- When the link comes up (also the first time after a boot), each board publishes its state and its metric catalogue again (§6.2, §7.1, §16.1).

What a board does when the link is lost is in §7.1 (autopilot) and §15 (monitor streams).

### 4.3 Reliable messages

Commands, acks, state, events, recorded points, catalogues and chunk requests are **reliable**: QoS 1 on MQTT, and acknowledged and resent on the board link (§14.2). Telemetry, monitor samples and live-driving setpoints are not: a lost one is simply gone.

Reliable does not mean guaranteed. A reliable message is still lost when the gateway restarts with it in hand, or when the mower is offline longer than the gateway's queue holds (§14.2). Each flow says how it recovers: commands by the server's resend (§5), recorded points by visible gaps (§10), chunks by the requester's retry (§12), state by publishing again when the link comes up (§4.2).

## 5. Commands and acks

The same envelope is used for `gateway/cmd` and `autopilot/cmd`. Only the server publishes commands.

```jsonc
// command
{ "id": "c-8f2a", "cmd": "follow", "expires_at": 1794650060, "points": [[54.68712345, 25.27965432]] }

// ack: accepted (long-running commands only)
{ "id": "c-8f2a", "cmd": "follow", "ok": true, "state": "accepted", "time": 1794650001.10 }
// ack: final, success
{ "id": "c-8f2a", "cmd": "follow", "ok": true, "state": "done", "result": {}, "time": 1794650041.72 }
// ack: final, failure
{ "id": "c-8f2a", "cmd": "follow", "ok": false, "state": "failed", "error": "no_fix", "message": "No fixed RTK solution", "time": 1794650020.03 }
```

| Field | Rule |
|---|---|
| `id` | Required. An id (§4), unique per command. |
| `cmd` | Required. The command name. Its parameters are further fields of the same object. |
| `expires_at` | Optional. The command is refused with `expired` when the time is past, and with `no_clock` when the receiver's clock is not set. |

Acks:

- Every command gets exactly **one final ack**: `state: "done"` or `state: "failed"`. A long-running command (marked in §6.4 and §8) first gets an ack with `state: "accepted"`.
- `result` is an object and may be present on any ack, also on a failure. `message` is text for people; programs read `error` and `result`.
- A long-running command that is ended by `stop` gets the final ack `cancelled`. One that ends because the autopilot enters `fault` gets the fault code as its `error` (§7.1).
- Acks never carry secrets.

Lost acks and repeats:

- A receiver remembers every command id for at least **2 minutes**, with the last ack it sent for it. When the same id arrives again it does not run the command again: it sends that last ack again (`accepted` while the command still runs, the final ack afterwards).
- When the server gets no ack within 5 s, it sends the command again **with the same id**, up to 3 times. After that the outcome is unknown and the server reads it from the board's state.
- When a board's `boot` value changes, the server treats every open command of that board as failed.

Error codes shared by both receivers:

| `error` | When |
|---|---|
| `bad_request` | Not a command object, or a parameter is missing or invalid |
| `unknown_cmd` | The command name is not known |
| `expired` | `expires_at` is past |
| `no_clock` | `expires_at` is set and the clock is not |
| `busy` | A firmware update is running on that board (§6.4, §8) |
| `wrong_mode` | The command is not allowed in the current mode (autopilot) |
| `cancelled` | A long-running command was ended by `stop` |
| `failed` | Anything else; `message` says what |

Commands may define more codes; they are listed with the command.

## 6. Gateway topics

### 6.1 `gateway/status`

Plain text `online` or `offline`, retained. `online` is published after every connect; `offline` is the last will. It says whether the mower is reachable.

### 6.2 `gateway/state`

Retained. Published when the server link comes up (§4.2) and when a field changes.

```json
{
  "protocol": "0.1",
  "boot": 212,
  "firmware": "0.4.0",
  "previous": "0.3.2",
  "partition": "ota_0",
  "autopilot_link": "up",
  "ntrip": "streaming",
  "operator": "24601",
  "time": 1794650000
}
```

| Field | Type | Values |
|---|---|---|
| `protocol` | string | Contract version the gateway implements |
| `boot` | number | Boot counter (§4.1) |
| `firmware` | string | Running version |
| `previous` | string or null | The version that ran before the last update; null if there was none |
| `partition` | string | The running slot |
| `autopilot_link` | string | `up`, `down` (no heartbeat, §14.4) or `incompatible` (the autopilot speaks another link version) |
| `ntrip` | string | `off` (no settings), `waiting` (no position from the autopilot yet), `connecting`, `streaming`, `error` |
| `operator` | string or null | Network code of the mobile operator in use; null before registration |
| `time` | number or null | When the message was made (§4.1) |

### 6.3 `gateway/telemetry`

The gateway's measurements: signal, its own load, and how much mobile data the mower uses and for what. All of them are metrics from the gateway's catalogue (§16). Besides `metrics`, the message has only `time` and `boot` (§4.1).

```json
{
  "time": 1794650000, "boot": 212,
  "metrics": {
    "signal.rssi": -71,
    "link.crc_errors": 0, "link.dropped": 0,
    "system.cpu": 37, "system.memory.free": 143000, "system.memory.pct": 56, "system.nvs.pct": 34,
    "usage.total.up": 5210000, "usage.total.down": 9120000,
    "usage.ntrip.up": 41000, "usage.ntrip.down": 2816000,
    "usage.mqtt.up.autopilot/telemetry": 1480000,
    "usage.mqtt.up.autopilot/monitor": 912000,
    "usage.mqtt.down.autopilot/job/chunk": 187000,
    "usage.mqtt.down.autopilot/drive": 310000
  }
}
```

Each metric is sent at the period its catalogue entry names (60 s for most gateway metrics).

**Data usage.** Every byte passes through the gateway, so it does the counting:

| Metric | Meaning |
|---|---|
| `usage.total.up`, `usage.total.down` | Bytes on the LTE connection, as counted on the network interface. This is what the SIM's allowance is charged for |
| `usage.ntrip.up`, `usage.ntrip.down` | The caster connection: positions sent, corrections received |
| `usage.mqtt.up.<topic>`, `usage.mqtt.down.<topic>` | One topic's bytes. The topic is named without `mower/<name>/`; a topic outside the device's own tree keeps its full name (`mower/status/server`). Whole MQTT packets are counted (header, topic and payload) |

- "Up" is mower → network, "down" is network → mower.
- They are counters (§16.3): bytes since boot, charted as a rate. The per-topic counters are a family (§16.2): a topic appears once it has carried data.
- `total` is larger than `ntrip` plus the topics: the rest is encryption, connection set-up and keep-alive overhead, which the app shows as "other".
- Maps and paths are the `autopilot/job/…` topics, firmware the `…/fw/…` topics, fast charts the `…/monitor` topics.
- For a live view finer than a minute, the same counters can be sampled on demand (§15).
- The gateway counts sizes only; it still does not read autopilot payloads.

### 6.4 Gateway commands

| `cmd` | Parameters | Result | Notes |
|---|---|---|---|
| `ping` | | `{"pong": "<name>"}` | |
| `restart` | | | Acks, then restarts |
| `ota` | `version` (string), optional `file` (string), optional `size` (number, bytes) | `{"version", "previous", "partition"}` | Long-running firmware update, §6.5 |
| `ntrip_set` | `host` (string), `port` (number), `mountpoint`, `user`, `password` (strings) | | Stores the caster settings on the gateway and reconnects with them at once (§13). Whether they work shows in `gateway/state` (`ntrip`) |
| `ntrip_clear` | | | Removes them; corrections stop |
| `autopilot_reset` | | | Pulses the autopilot's reset line. `failed` when the line is not wired |
| `monitor_start`, `monitor_stop` | as in §15 | | Fast sampling of gateway values, on demand |

A gateway restart or update takes the mower offline, which pauses a running job (§7.1). The server sends `restart` and `ota` to the gateway only while the autopilot is `idle`.

### 6.5 Firmware update

`ota` works the same way on both boards (the gateway here, the autopilot in §8):

1. The board acks `accepted` and downloads the image over its `fw/…` topics (§12). `file` defaults to `<version>.bin`.
2. It checks the image (its signature, its version against `version`, and `size` when given), then restarts into it. The command id is kept across the restart.
3. When the new image runs and has reached the server, it confirms itself and sends the final ack `done` with the result `{"version", "previous", "partition"}`.
4. If the new image does not get that far, the board starts the old image again and sends the final ack `failed` with the error `rolled_back`.

While an update runs, the board answers every other command with `busy`, except `stop` (autopilot only, which cancels the update before the restart) and `monitor_start` / `monitor_stop`.

| `error` | When |
|---|---|
| `same_version` | That version is already running |
| `download_failed` | The download did not complete (§12) |
| `bad_image` | The image is not valid: wrong project, version or signature |
| `bad_size` | `size` was given and does not match |
| `low_signal` | The signal is too weak to start (gateway) |
| `rolled_back` | The new image started but did not confirm; the old one runs again |

## 7. Autopilot state, telemetry and events

### 7.1 `autopilot/state`

Retained. Published when the server link comes up (§4.2) and when a field changes. It changes on transitions only; progress is in telemetry.

The server treats this message as out of date while `gateway/status` is `offline` or the gateway's `autopilot_link` is not `up`.

```json
{
  "protocol": "0.1",
  "boot": 57,
  "firmware": "0.1.0",
  "previous": null,
  "partition": "ota_0",
  "mode": "job",
  "paused": null,
  "job": "j-2031",
  "recording": null,
  "fault": null,
  "time": 1794650000.00
}
```

| Field | Type | Values |
|---|---|---|
| `protocol`, `boot`, `firmware`, `previous`, `partition`, `time` | | As in `gateway/state` (§6.2) |
| `mode` | string | See the table below |
| `paused` | string or null | In `job` mode: null while driving, or why the path stands still: `command`, `link` or `fix` |
| `job` | string or null | The job id while a job runs; null for a `follow` path and outside `job` mode |
| `recording` | string or null | The session id in `recording` mode |
| `fault` | object or null | `{"code", "message"}` in `fault` mode |

| `mode` | Meaning |
|---|---|
| `idle` | Stopped, blade off |
| `manual` | Follows the live-driving stream (§9) |
| `recording` | As `manual`, and streams border points (§10) |
| `job` | Downloads and follows a path: a job (§11) or a `follow` command |
| `fault` | Stopped, blade off, refuses motion |

Which command is allowed in which mode, and where it leads, is one table in §8.

**Blade.** The blade runs only after an explicit instruction: the `blade` command in `manual` and `recording`, or a path that says so (`follow` with `blade: true`, a job segment with `blade: true`). It switches off on every mode change, on `stop`, whenever a path is paused, on a live-driving timeout (§9) and when the server link is lost. It never switches on again by itself, except when a path that was paused for the fix continues.

**Fix.** Following a path needs a fixed RTK solution (`rtk_fixed`):

- `follow` and `job_start` are refused with `no_fix` without one.
- When the fix drops below `rtk_fixed` during a path, the autopilot keeps going for a short time that it sets itself (a few seconds). Then it pauses the path (`paused: "fix"`) and publishes the event `job_paused`.
- When `rtk_fixed` returns it continues by itself and publishes `job_resumed`.

**Losing the server link** (§4.2). The mower does not work on its own without the server:

- In `job` mode the autopilot pauses (`paused: "link"`) and publishes the event `job_paused`. It stays paused when the link returns; the server continues it with `resume`. A path that was paused for the fix becomes paused for the link.
- In `recording` it stops recording and goes to `manual`, as after `record_stop`, and publishes the event `recording_stopped` (§10).
- In `manual`, live driving has already stopped by its own timeout (§9).

**Faults.** The autopilot enters `fault` from any mode when it detects one of these: `motor_stall`, `blade_stall`, `battery_low` (below its critical level), `internal`. It publishes the event `fault`, and a long-running command that was running gets the fault code as its final error. `clear_fault` returns to `idle`; while the cause is still there it fails with the fault code and the mode stays `fault`.

### 7.2 `autopilot/telemetry`

Every value the autopilot measures or computes, position included, is a metric from its catalogue (§16). Besides `metrics`, the message has only `time` and `boot` (§4.1).

```json
{
  "time": 1794650000.25, "boot": 57,
  "metrics": {
    "position.lat": 54.68712345, "position.lon": 25.27965432,
    "position.heading": 271.5, "position.speed": 0.42,
    "gnss.fix": 4, "gnss.sats": 24, "gnss.accuracy": 0.014, "gnss.correction_age": 1.2,
    "job.point": 412,
    "battery.v": 25.3, "battery.a": 4.1, "battery.power": 103.7, "battery.pct": 78,
    "drive.left.speed": 0.41, "drive.right.speed": 0.43, "drive.left.rpm": 52, "drive.right.rpm": 55,
    "blade.on": true, "blade.rpm": 2900
  }
}
```

- A message is sent whenever at least one metric is due, and holds the metrics that are due: each is sent at the period its catalogue entry names, so slow ones (the board's load, every 10 s) are not in every message.
- In `idle` every metric's period is stretched to at least 10 s.
- Metrics that belong together (the position metrics) have the same period and come from the same measurement.
- A value that is not known is `null` (the position without a fix, the job point outside a job).

The server needs a few values to draw the map, run jobs and fill the app's fixed indicators. It asks for them by **key** (§16.4), and the catalogue says which metric answers each key; the metric names themselves are the board's choice.

### 7.3 `autopilot/event`

Things that happen without a command. Command results are acks, not events.

```json
{ "time": 1794650020.03, "boot": 57, "seq": 14, "event": "fault", "code": "motor_stall", "message": "Left wheel does not turn" }
```

Every event has `time`, `boot` and `seq`. `seq` counts the events since boot, from 0. The server drops an event whose `boot` and `seq` it has already seen.

| `event` | Extra fields | When |
|---|---|---|
| `boot` | `firmware` (string), `reason` (string) | The autopilot started |
| `fault` | `code` (string), `message` (string) | Entered `fault` (§7.1) |
| `fault_cleared` | | Left `fault` |
| `fix_lost` | `fix` (string: a fix name from §16.4) | The fix dropped below `rtk_fixed` |
| `fix_regained` | `fix` (string) | The fix returned to `rtk_fixed` |
| `drive_timeout` | | The live-driving stream timed out (§9) |
| `job_paused` | `reason` (string: `link` or `fix`) | The autopilot paused a path by itself (§7.1) |
| `job_resumed` | `reason` (string: `fix`) | The autopilot continued a path by itself |
| `recording_stopped` | `reason` (string: `link`), `session` (string), `index` (number) | Recording ended because the server link was lost; `index` is the number of points taken, as in the result of `record_stop` |
| `battery_low` | `v` (number) | The battery fell below the autopilot's warning level. The `battery_low` fault follows at a lower, critical level |

## 8. Autopilot commands

This table is the autopilot's whole state machine. A command sent in a mode that is not listed for it fails with `wrong_mode`.

| `cmd` | Parameters | Allowed in | Ends in | Long-running | Notes |
|---|---|---|---|---|---|
| `stop` | | any | `idle`; `fault` stays `fault` | | Motors and blade off. Ends a running path, recording or update |
| `manual_start` | | `idle` | `manual` | | |
| `manual_stop` | | `manual` | `idle` | | |
| `blade` | `on` (bool) | `manual`, `recording` | unchanged | | §7.1, Blade |
| `follow` | `points`, optional `reverse` (bool), `blade` (bool), `speed` (number) | `idle`, `manual` | `job`, then back to the mode it came from | yes | Drives through 1–100 points in order; one point is "go to". `reverse: true` drives backwards without turning round. `blade` is off unless given. Error: `no_fix` |
| `record_start` | `session`, optional `spacing` (number, metres) | `idle`, `manual` | `recording` | | §10 |
| `record_stop` | | `recording` | `manual` | | Result `{"index": <points taken>}` (§10) |
| `job_start` | `job`, `size` (number), `sha256` (string), optional `from_point` (number) | `idle` | `job`, then `idle` | yes | Downloads and runs a job (§11). Errors: `no_fix`, `download_failed`, `bad_job` |
| `pause` | | `job` | `job` | | The path stands still, blade off (`paused: "command"`). `done` also when already paused |
| `resume` | | `job` | `job` | | Continues a path paused by `command` or `link`. `done` also when not paused. Error: `no_fix` without a fixed solution |
| `clear_fault` | | `fault` | `idle` | | §7.1, Faults |
| `monitor_start` | `session`, `metrics`, `rate`, optional `hold` | any | unchanged | | §15 |
| `monitor_stop` | optional `session` | any | unchanged | | §15 |
| `ota` | as for the gateway (§6.4) | `idle` | `idle` | yes | Firmware update over `autopilot/fw/…`, §6.5 |
| `restart` | | `idle`, `fault` | | | Acks, then restarts |

- `speed` is a limit in m/s; the autopilot also has its own maximum and uses the lower.
- A path that ends by itself gets the final ack `done`; one ended by `stop` gets `cancelled`; one ended by a fault gets the fault code.
- `stop` is accepted in every mode.

## 9. Live driving

The server publishes setpoints on `autopilot/drive` about 10 times per second while the user drives. QoS 0, no acks.

```json
{ "seq": 1041, "time": 1794650000.25, "v": 0.5, "w": -0.2 }
```

| Field | Meaning |
|---|---|
| `seq` | Counter that grows by one per setpoint. A setpoint with a `seq` not above the last applied one is dropped |
| `time` | When the server sent it. A setpoint more than 1 s old is dropped (messages delivered in a burst after a stall). The autopilot skips this check while its clock is not set |
| `v` | Forward speed, m/s; negative is backwards |
| `w` | Turn rate, rad/s; positive turns left |

- Setpoints are applied only in `manual` and `recording`; elsewhere they are ignored.
- The autopilot forgets the last applied `seq` each time it enters `manual` or `recording` and after a timeout, so the next setpoint is applied whatever its `seq`. The server may start counting anywhere.
- **Timeout:** with no valid setpoint for **0.5 s** the autopilot stops the motors and the blade, stays in its mode, and publishes the event `drive_timeout` once for that stop. The next valid setpoint moves it again.
- The autopilot clamps `v` and `w` to its limits.

The same commands and setpoints will be used on a local link (gateway Wi-Fi or Bluetooth); that transport is not part of version 0.1.

## 10. Border recording

The user drives the mower along a border; the autopilot streams the points and the server keeps the draft border and shows it live. The border and every edit of it belong to the server.

**Sessions.** Every `record_start` opens a new session with a new session id chosen by the server, and optionally the spacing in metres (default 0.1). One border can be made of several sessions; the server joins them.

**Points.** The autopilot takes the first point at once, and then one each time it has moved `spacing` from the last one, while its fix is `rtk_fixed` or `rtk_float`. With a worse fix it takes none. Points are numbered from 0 within the session. It publishes them in batches on `autopilot/recording`, at most once per second and at most 50 points per message:

```json
{ "session": "r-17", "index": 120, "fix": "rtk_fixed", "time": 1794650000.25,
  "points": [[54.68712345, 25.27965432], [54.68712431, 25.27965440]] }
```

- `index` is the number of the first point in the message.
- `fix` is the worst fix of the batch, as a string: `rtk_fixed` or `rtk_float`. The server takes both into the border and marks the float points.
- `time` is when the message was made.

**Ending.** On `record_stop` the autopilot publishes every point it still holds and then acks with `{"index": n}`, where `n` is the number of points taken in the session. The server has the whole session when it holds the points 0 to `n − 1`.

**What the server does with what arrives:**

- A point number it already holds in that session is a repeat: ignored.
- A missing range is a gap. Lost points are not sent again; the server shows the gap, and the user can rewind past it and drive it again.

**Rewind** is done by the server with existing commands:

1. `record_stop`, and wait until the whole session has arrived.
2. `follow` along the last points in reverse order with `reverse: true`. A `follow` takes at most 100 points (10 m at the default spacing), so a longer rewind is several commands.
3. Cut those points from the draft.
4. `record_start` with a new session.

**Losing the server link** stops recording (§7.1): the session ends as after `record_stop`, and the event `recording_stopped` reports the number of points. Nothing is recorded while offline. Points taken before the loss arrive if the link returns while the gateway still holds them (§14.2). The user continues with a new session.

## 11. Jobs

A job is a path planned by the server: segments of points, each with the blade on or off. The autopilot downloads it as a file and follows it.

1. The server sends `job_start` with the job id, the file's `size` in bytes and its `sha256` (64 lower-case hex characters).
2. The autopilot acks `accepted`, enters `job` mode with the job id in its state, and downloads the file `<job>.json` over `autopilot/job/…` (§12). It may skip the download when it still holds a file with that hash.
3. It checks the file against `size` and `sha256` from the command and parses it. A mismatch or a file it cannot use ends the command with `bad_job`; a download that does not complete, with `download_failed`.
4. It drives to the starting point with the blade off, then follows the segments in order.
5. The final ack is `done` with `{"points": n}`, where `n` is the number of points in the job, and the mode returns to `idle`.

Pauses (by command, lost link or lost fix, §7.1) also apply during the download: it waits and then continues.

**Point numbers.** The points of a job are numbered from 0 in file order through all segments. Every point counts, also a segment's first point when it repeats the last point of the segment before.

- The metric linked to the key `job.point` (§16.4) is the number of the last point reached; null before the first one.
- `from_point` is the number of the first point to drive to; it defaults to 0. To continue a job after a failure or a `stop`, the server sends `job_start` again with `from_point` set to the last point reached plus one.

The job file is JSON, at most 1 MiB:

```json
{
  "job": "j-2031",
  "speed": 0.5,
  "segments": [
    { "blade": false, "points": [[54.68712345, 25.27965432], [54.68713001, 25.27966010]] },
    { "blade": true,  "points": [[54.68713001, 25.27966010], [54.68719876, 25.27966020]] }
  ]
}
```

- `job` is the job id and must equal the id in the command.
- `speed` is a limit in m/s, as for `follow` (§8).
- There is at least one segment, and every segment has at least one point.

The server checks every job against the map's zones before sending it: the autopilot has no map to check against.

## 12. Chunk transfer

Firmware images and job files are downloaded as binary chunks over MQTT, pulled by the board that needs them. This section is the whole definition; the server's implementation is described in [Server-App](Server-App#firmware-over-mqtt).

Three topic sets use it. In each, the board publishes requests on `req`, and the server answers with a binary chunk on `chunk` or a JSON error on `res`:

| Topics | Who asks | Files | File name |
|---|---|---|---|
| `gateway/fw/req`, `chunk`, `res` | Gateway | Signed gateway images | `<version>.bin` |
| `autopilot/fw/req`, `chunk`, `res` | Autopilot | Signed autopilot images | `<version>.bin` |
| `autopilot/job/req`, `chunk`, `res` | Autopilot | Job files | `<job>.json` |

The server keeps the three sets of files apart: a request on one topic set can only reach that set's files. A file name is 1–128 characters of `[A-Za-z0-9._-]`, never a path. A firmware image is at most 32 MiB, a job file 1 MiB.

### 12.1 Request

```json
{ "request_id": "c0", "file": "1.2.3.bin", "chunk": 0 }
```

| Field | Rule |
|---|---|
| `request_id` | An id (§4), new for every request |
| `file` | The file name |
| `chunk` | The chunk number, from 0 |

### 12.2 Chunk

The answer is one binary MQTT payload: a 64-byte header, then the chunk's bytes. Integers are little-endian.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | Magic `RMFW` (bytes `52 4D 46 57`) |
| 4 | 1 | Header version, `1` |
| 5 | 1 | Flags, `1` |
| 6 | 2 | Header length, `64` |
| 8 | 4 | Chunk number |
| 12 | 4 | Number of chunks in the file |
| 16 | 4 | File size, in bytes |
| 20 | 2 | Chunk length: how many bytes follow the header |
| 22 | 2 | Reserved, `0` |
| 24 | 8 | The first 8 bytes of SHA-256 over the `request_id` |
| 32 | 32 | SHA-256 of the whole file, raw bytes |
| 64 | chunk length | The chunk |

- A chunk is **4096 bytes**; only the last one of a file is shorter. An empty file is one chunk of length 0.
- Every chunk carries the file's size, chunk count and hash, so a download can start or continue at any chunk.
- The board drops a chunk whose fixed fields are wrong, whose length does not fit the payload, or whose request-id hash is not that of its open request.

### 12.3 Errors

```json
{ "request_id": "c3", "error": { "code": "not_found", "message": "no such file" } }
```

| `code` | When |
|---|---|
| `bad_request` | Not a request, a file name that is not allowed, or a chunk number past the end |
| `not_found` | No such file in that set |
| `internal` | The server could not read the file, or it is too large |

`request_id` is empty when the request's own id was missing or not valid.

### 12.4 Flow

- A board has **one request open per topic set**. The server answers requests on different sets side by side.
- The board waits **10 s** for the answer. Then it asks for the same chunk again with a new `request_id`, up to 5 times in a row. After that, or on an error answer, the download has failed and the command that started it ends with `download_failed`.
- When the whole file is there, the board compares its SHA-256 with the one in the chunks.
- The server runs one download per mower at a time where it can: the LTE modem carries about 11 KB/s in total (§15).

## 13. Corrections (NTRIP)

The RTK receiver needs a correction stream from an NTRIP caster. The NTRIP client runs on the gateway, with its own TCP connection to the caster over LTE. Corrections do not pass through MQTT or the server, so positioning keeps working while the server is down.

- **Settings** (host, port, mount point, user, password) are stored on the gateway and set with the gateway command `ntrip_set` (§6.4). They survive restarts, so the server sends them once per gateway and again when they change. The password is never reported back.
- **Position to the caster:** the autopilot sends its GGA sentence to the gateway every 10 s (§14.3); the gateway forwards it to the caster. A network caster such as LitPOS needs it to keep sending corrections. A GGA sentence without a position does not count: the client stays in `waiting` until the first one with a position.
- **Corrections to the receiver:** the gateway forwards the caster's bytes to the autopilot unchanged (§14.3), which feeds them to the receiver.
- **Reporting:** the gateway reports the client's state in `gateway/state` (`ntrip`); the autopilot reports the result in telemetry (`gnss.fix`, `gnss.correction_age`).

## 14. Board link (UART)

The wiring is in [Mower-Hardware](Mower-Hardware). 921600 baud, 8N1, RTS/CTS flow control. **Not verified on hardware yet.**

### 14.1 Frames

A frame is `type` (1 byte), `body`, and a CRC-16 (CCITT-FALSE: polynomial `0x1021`, initial value `0xFFFF`) over type and body, little-endian. The frame is COBS-encoded and ends with one `0x00` byte. The largest frame is 4608 bytes before encoding; the largest one this page produces is a relayed chunk, about 4200 bytes. A frame with a bad CRC or an unknown type is dropped and counted (metric `link.crc_errors` on each board).

| Type | Name | Direction | Body |
|---|---|---|---|
| `0x01` | PUBLISH | autopilot → gateway | A message to publish (§14.2) |
| `0x02` | MESSAGE | gateway → autopilot | A received message (§14.2) |
| `0x03` | SUBSCRIBE | autopilot → gateway | Topics the autopilot wants (§14.2) |
| `0x04` | CORRECTIONS | gateway → autopilot | Raw bytes from the caster |
| `0x05` | GGA | autopilot → gateway | One NMEA GGA sentence, ASCII |
| `0x06` | HEARTBEAT | both | §14.4 |
| `0x07` | ACK | both | The sequence number of a reliable frame (1 byte) |

### 14.2 Relayed messages

PUBLISH and MESSAGE share one body:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Flags: bit 0 retain, bits 1–2 QoS (0 or 1) |
| 1 | 1 | Sequence number: 1–255 for a reliable frame (QoS 1), 0 otherwise |
| 2 | 1 | Topic length `n`, at most 64 |
| 3 | `n` | Topic, ASCII, **without** the `mower/<name>/autopilot/` prefix (for example `telemetry`, `cmd/ack`) |
| 3 + `n` | rest | Payload, unchanged |

The gateway adds the prefix when it publishes and removes it when it delivers, so the autopilot can only use its own topics. It does not read or change the payload.

**Reliable frames.** QoS 1 messages and SUBSCRIBE are acknowledged on the link:

- Each direction sends one reliable frame at a time and numbers them 1, 2, … 255, 1, …
- The receiver answers every reliable frame it gets with an ACK carrying its number. A frame with the same number as the last one it took is a repeat: acknowledged again, not passed on.
- A sender that gets no ACK within 200 ms sends the frame again, up to 5 times. Then it drops the frame and counts it (metric `link.dropped`).
- Other frames (QoS 0 messages, corrections, heartbeats, ACKs) are sent in between and never acknowledged.

**SUBSCRIBE** body: a sequence number (1 byte), then one or more entries of QoS (1 byte), topic length (1 byte), topic (without the prefix; no wildcards). The gateway replaces the previous list with it and subscribes again after every MQTT reconnect. The autopilot sends its list after it starts, and again whenever the gateway's heartbeat asks for it (§14.4). Version 0.1's list is `cmd`, `drive`, `job/chunk`, `job/res`, `fw/chunk`, `fw/res`.

**When a side is unreachable:**

- While MQTT is disconnected, the gateway keeps reliable messages from the autopilot for up to **60 s** and up to **64 KB**; beyond either limit it drops the oldest and counts them (`link.dropped`). Other messages are dropped at once.
- While the board link is down, the gateway drops messages for the autopilot and counts them. A command lost this way gets no ack, and the server sends it again (§5).

### 14.3 Correction frames

CORRECTIONS frames carry the caster's bytes in order, split wherever the gateway likes; the autopilot passes them to the receiver as a stream. GGA frames carry one sentence each, every 10 s.

### 14.4 Heartbeat

Both boards send a HEARTBEAT every second. A board treats the link as down when it starts, as up from the first heartbeat it receives, and as down again after 3 s without one.

Gateway → autopilot:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Link version, `1` |
| 1 | 1 | Flags: bit 0 MQTT connected, bit 1 server online (`mower/status/server`), bit 2 corrections streaming, bit 3 clock valid, bit 4 subscriptions needed |
| 2 | 4 | Unix time, seconds (little-endian; 0 when the clock is not valid) |
| 6 | 2 | Milliseconds |

Autopilot → gateway:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Link version, `1` |
| 1 | 1 | Reserved, `0` |

- **Server link.** Bits 0 and 1 together are the server link of §4.2. The autopilot applies the 10 s rule to them itself.
- **Subscriptions needed.** The gateway sets bit 4 from its start until it has received a SUBSCRIBE. The autopilot sends its list whenever it sees the bit set, so a gateway that restarted gets the list again even if the link never looked down.
- **Clock.** The autopilot sets its clock from the heartbeat whenever bit 3 is set.
- **Link version.** A board that receives a link version it does not know keeps the link down; the gateway reports `autopilot_link: "incompatible"` (§6.2).

## 15. Monitor

Telemetry is at most once per second from the autopilot (§7.2) and mostly once per minute from the gateway (§6.3). For values that change fast (battery voltage and current, wheel and blade speed, data usage) the user can ask for a short, fast stream of chosen values, for example to watch a chart. It runs beside any mode and changes nothing about how the mower drives. It is never stored on the mower and never sent unless asked for.

Both boards offer it, each for its own values, with the same commands and the same message: the autopilot on `autopilot/cmd` and `autopilot/monitor`, the gateway on `gateway/cmd` and `gateway/monitor`. The two are independent, each with its own streams and budget.

**Start.** `monitor_start` on the board's `cmd` topic:

```json
{ "id": "c-91b0", "cmd": "monitor_start", "session": "m-3", "metrics": ["battery.v", "battery.a"], "rate": 100, "hold": 10 }
```

| Field | Rule |
|---|---|
| `session` | An id (§4) chosen by the server |
| `metrics` | One or more metric names from the board's catalogue (§16). A member of a family is named in full (`usage.mqtt.up.autopilot/telemetry`); the family name with `*` is not accepted |
| `rate` | Samples per second. It must be one of the `rates` of every metric asked for |
| `hold` | Seconds the stream runs without being extended; default 10, at most 60 |

Any number of streams run side by side, each with its own session, metrics, rate and hold. The only limit is the total: the sum of `metrics × rate` over all running streams may not exceed the board's **budget**: 400 values per second on the autopilot and 100 on the gateway in version 0.1. Every `monitor_start` ack reports it in its `result`, on success and on failure, so the app can show what is left. From the autopilot:

```json
{ "id": "c-91b0", "cmd": "monitor_start", "ok": true, "state": "done", "result": { "budget": 400, "used": 200 }, "time": 1794650012.01 }
```

Errors: `bad_request` for an unknown metric, a rate a metric does not offer, or for a running session id with different metrics or rate; `over_budget` when the stream does not fit.

**Keeping it alive.** The stream ends by itself `hold` seconds after the last `monitor_start`. While the user is watching, the server sends `monitor_start` again with the same session (and a new command id) every few seconds; that extends the stream without restarting the sample index. A stream also ends on `monitor_stop`, and every stream of a board ends when the server link is lost (§4.2). Nothing is kept back for later.

- `monitor_stop` with a session that is not running is `done`.
- A session id may be used again after its stream has ended; the sample index starts from 0.

**Data.** The board publishes each stream's samples on its `monitor` topic, QoS 0, one message per stream every 0.2 s (or every sample, when samples are further apart than that):

```json
{ "session": "m-3", "index": 1200, "time": 1794650012.000, "rate": 100,
  "metrics": ["battery.v", "battery.a"],
  "samples": [[25.31, 4.10], [25.30, 4.12], [25.30, 4.15]] }
```

- `index` is the number of the first sample in the message, counted from 0 within the session, so a lost message shows as a gap.
- `time` is when the first sample was taken; sample `k` of the message was taken at `time + k / rate`.
- Each sample is an array with one value per metric, in the order of `metrics`.

Counters (data usage) are sent as the running count, not as a rate, exactly as in telemetry. A monitor stream is itself traffic and shows up in the usage counters.

The budgets exist because of bandwidth: 400 values per second are about 3 KB/s, on top of telemetry and corrections, and the LTE modem's serial link carries about 11 KB/s.

## 16. Metrics

What a board measures is not fixed by this page. Each board publishes a **catalogue** of its metrics; telemetry (§6.3, §7.2) and monitor streams (§15) carry values by the names in it. The server stores every metric as a time series by name, and the app builds its charts, units, ranges and warning colours from the catalogue. A new metric is a firmware change only.

Every measured or computed value is a metric, and every metric is in the catalogue. What the server itself depends on is a short list of **keys** (§16.4): the server's side of the interface. A catalogue entry may name the key its metric answers. A metric without a key is only stored and shown.

State (§6.2, §7.1), events (§7.3) and recorded border points (§10) are not metrics: they are not measurements over time but facts, so they keep their own reliable messages (§4.3).

### 16.1 Catalogue topics

`gateway/metrics/<part>` and `autopilot/metrics/<part>`, retained, QoS 1. A board publishes its catalogue when the server link comes up (§4.2).

The catalogue is split into parts so that each message fits 4096 bytes; normally one part per group, where a metric's group is its name up to the first dot (`battery`, `drive`, `system`, `usage`). A part name is 1–32 characters of `[a-z0-9_-]`. The part `index` lists the others:

```json
{ "revision": 12, "parts": ["battery", "drive", "blade", "position", "gnss", "job", "system"] }
```

```json
{
  "revision": 12,
  "label": "Battery",
  "metrics": [
    { "name": "battery.v", "label": "Battery voltage", "description": "Voltage measured at the battery terminals.",
      "unit": "V", "kind": "gauge", "type": "number", "period": 1, "rates": [10, 20, 50, 100], "chart": true,
      "min": 18, "max": 29.4, "low": 21, "decimals": 2 },
    { "name": "battery.pct", "key": "battery.level", "label": "Battery level", "description": "Charge left, estimated by the autopilot.",
      "unit": "%", "kind": "gauge", "type": "number", "period": 10, "rates": [], "chart": true,
      "min": 0, "max": 100, "low": 20, "decimals": 0 }
  ]
}
```

- `revision` is a whole number the board changes whenever its catalogue changes. The index and every part carry it.
- The server uses a board's catalogue once it holds the index and every part the index lists, all with the index's revision. Until then it keeps the catalogue it had. Retained parts that the index does not list are ignored, so a part that a newer firmware no longer has does no harm.
- `label` in a part is the display name of its group.

### 16.2 Entry fields

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | The id used in telemetry and monitor requests: parts of `[a-z0-9_]` joined by dots; the first part is the group. Stable: a name never changes its meaning |
| `key` | no | The server key this metric answers (§16.4) |
| `label` | yes | Display name, English |
| `description` | yes | One or two sentences for a tooltip, English |
| `unit` | yes | The unit as the app shows it, free text: `V`, `A`, `W`, `%`, `rpm`, `m/s`, `°C`, `B`, `dBm`, `degrees`; empty for none |
| `kind` | yes | `gauge` or `counter` (§16.3) |
| `type` | yes | `number`, `bool` or `enum` |
| `period` | yes | Seconds between values in telemetry outside `idle` (in `idle`: at least 10 s, §7.2); `0` means the metric is not in telemetry, only in monitor streams |
| `rates` | yes | Monitor rates the metric offers, samples per second; empty when it cannot be monitored |
| `chart` | yes | `true` or `false`: whether the app offers the metric in its chart picker (a latitude is not something to chart). It limits nothing else: the metric is still sent, stored and usable through its key |
| `min`, `max` | no | Expected range, for chart axes and gauges |
| `low`, `high` | no | Warning levels: the app marks a value below `low` or above `high`. For display only; the board raises its own events and faults (§7.3) |
| `decimals` | no | Digits after the decimal point to show |
| `values` | for `enum` | The names of the values, in order; the metric's value is an index into this list, from 0 |

**Families.** A name ending in `.*` describes a set of metrics that share everything but the last part, which is only known while running: the gateway's `usage.mqtt.up.*` covers one counter per MQTT topic (`usage.mqtt.up.autopilot/telemetry`). Only that last part may contain any characters but a dot. A member appears in telemetry once it has data, and the app lists the members it has seen.

### 16.3 Gauges and counters

- A **gauge** is a value at a moment (a voltage, a speed). It is charted as it is.
- A **counter** only grows: it counts something since the board started (bytes sent, dropped frames). It is charted as its rate of change, in its unit per second. A new `boot` value in the telemetry message (§4.1) means every counter started again from 0. Because a counter carries the whole count, a lost message loses nothing.
- A counter that has not changed since it was last sent may be left out of a telemetry message.

### 16.4 Keys

The list of values the server and the app use by themselves. It is the interface a mower has to satisfy: for every key, one metric of the mower names it in its catalogue entry (`key`). The list is kept short; a key is added only when the server or the app starts to depend on a value.

| Key | Type, unit | The server or app uses it for |
|---|---|---|
| `position.lat` | number, degrees | The mower on the map (§4) |
| `position.lon` | number, degrees | The mower on the map (§4) |
| `position.heading` | number, degrees | The mower's direction on the map. The receiver has one antenna, so the heading comes from movement and is null while it is not known (standing still) |
| `gnss.fix` | enum: `none`, `single`, `dgps`, `rtk_float`, `rtk_fixed` (values 0–4) | Whether the position can be trusted |
| `job.point` | number | Job progress and where to continue (§11) |
| `battery.level` | number, % | The battery indicator |
| `blade.on` | bool | The blade indicator |
| `signal.strength` | number, dBm | The signal indicator |

Rules:

- A key is linked by exactly one metric of the mower, on either board.
- The metric has the key's type and unit; the server converts nothing. For an enum key, the metric's `values` are the key's values in the same order.
- Metrics whose keys belong together (`position.lat`, `position.lon`, `position.heading`, `gnss.fix`) have the same period and come from the same measurement.
- The server reads the links from the catalogues it uses (§16.1). A key that no metric links, or that more than one links, counts as not linked: the app reports it, and what depends on it is not shown.

### 16.5 Metrics of version 0.1 firmware

For orientation: the catalogue a board publishes is what counts, and the server never reads this table. Ranges, warning levels and decimals are set in the firmware. Period is seconds between values in telemetry; rates are samples per second on demand (§15); chart says whether the app offers the metric in its chart picker.

| Board | Name | Key | Type | Unit | Kind | Period | Monitor rates | Chart |
|---|---|---|---|---|---|---|---|---|
| Autopilot | `position.lat` | `position.lat` | number | degrees | gauge | 1 | 10 | no |
| Autopilot | `position.lon` | `position.lon` | number | degrees | gauge | 1 | 10 | no |
| Autopilot | `position.heading` | `position.heading` | number | degrees | gauge | 1 | 10 | no |
| Autopilot | `position.alt` | | number | m | gauge | 1 | 10 | yes |
| Autopilot | `position.speed` | | number | m/s | gauge | 1 | 10 | yes |
| Autopilot | `gnss.fix` | `gnss.fix` | enum | | gauge | 1 | 10 | yes |
| Autopilot | `gnss.sats` | | number | | gauge | 1 | | yes |
| Autopilot | `gnss.accuracy` | | number | m | gauge | 1 | 10 | yes |
| Autopilot | `gnss.correction_age` | | number | s | gauge | 1 | | yes |
| Autopilot | `job.point` | `job.point` | number | | gauge | 1 | | no |
| Autopilot | `battery.v` | | number | V | gauge | 1 | 10, 20, 50, 100 | yes |
| Autopilot | `battery.a` | | number | A | gauge | 1 | 10, 20, 50, 100 | yes |
| Autopilot | `battery.power` | | number | W | gauge | 1 | 10, 20, 50, 100 | yes |
| Autopilot | `battery.pct` | `battery.level` | number | % | gauge | 10 | | yes |
| Autopilot | `drive.left.speed`, `drive.right.speed` | | number | m/s | gauge | 1 | 10, 20, 50, 100 | yes |
| Autopilot | `drive.left.rpm`, `drive.right.rpm` | | number | rpm | gauge | 1 | 10, 20, 50, 100 | yes |
| Autopilot | `blade.on` | `blade.on` | bool | | gauge | 1 | | no |
| Autopilot | `blade.rpm` | | number | rpm | gauge | 1 | 10, 20, 50, 100 | yes |
| Autopilot | `system.psram.free` | | number | B | gauge | 10 | 10 | yes |
| Autopilot | `system.psram.pct` | | number | % | gauge | 10 | 10 | yes |
| Gateway | `signal.rssi` | `signal.strength` | number | dBm | gauge | 60 | 1, 2, 5, 10 | yes |
| Gateway | `usage.total.up`, `usage.total.down` | | number | B | counter | 60 | 1, 2, 5, 10 | yes |
| Gateway | `usage.ntrip.up`, `usage.ntrip.down` | | number | B | counter | 60 | 1, 2, 5, 10 | yes |
| Gateway | `usage.mqtt.up.*`, `usage.mqtt.down.*` | | number | B | counter | 60 | 1, 2, 5, 10 | yes |
| Both | `link.crc_errors`, `link.dropped` | | number | frames | counter | 10 / 60 | | yes |
| Both | `system.cpu`, `system.core0`, `system.core1` | | number | % | gauge | 10 / 60 | 1 / 1, 2, 5, 10 | yes |
| Both | `system.memory.free`, `system.memory.min_free`, `system.memory.largest` | | number | B | gauge | 10 / 60 | 10 / 1, 2, 5, 10 | yes |
| Both | `system.memory.pct` | | number | % | gauge | 10 / 60 | 10 / 1, 2, 5, 10 | yes |
| Both | `system.nvs.pct` | | number | % | gauge | 10 / 60 | | yes |
| Autopilot | `system.temperature` | | number | °C | gauge | 10 | 10 | yes |

Where a row is for both boards, the first period and rates are the autopilot's, the second the gateway's.

- Processor load is read at most once per second on the autopilot: reading it briefly stops the task scheduler, which the board that drives the motors should not do often.
- `system.temperature` is the autopilot's only: the gateway's chip has no usable temperature sensor.
- These boards have no disk. Their storage is flash: the settings area (`system.nvs.pct`) today, and one more metric per file system if a board gets one.
