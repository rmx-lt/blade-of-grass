# Protocol

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

Hardware the contract assumes: drive motors with encoders, blade motor(s) with an encoder, battery voltage and current, an RTK GNSS receiver. There is no dock and there are no safety sensors, so the contract has no docking and no safety rules beyond the live-driving timeout (§9). The modem's own GNSS is not used.

## 2. Version

- The version is `major.minor`. Each side reports the version it implements in its retained state message (`protocol`, §6.2 and §7.1). Other messages carry no version.
- A minor version only adds: new topics, new commands, new optional fields. Receivers ignore fields and events they do not know and answer an unknown command with `unknown_cmd`.
- A major version may change or remove anything. While the major version is 0, a minor version may too.
- Version 1 is the fully operational mower.

## 3. Topics

A device's name is the CN of its client certificate ([Device-CA](Device-CA)): 1–32 characters of `[A-Za-z0-9_-]`. The broker forces the MQTT client id to the name and limits each device to `mower/<name>/#`, plus read access to `mower/status/server`.

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

"Up" is device → server, "down" is server → device. `status` and `events` cannot be device names.

The gateway publishes and subscribes the `autopilot/…` topics on the autopilot's behalf (§14) and passes payloads through unchanged.

## 4. Common rules

- JSON payloads are one UTF-8 object, at most **4096 bytes**. Unknown fields are ignored.
- **Time** is Unix time in seconds; `time` fields may carry a fraction (`1794650000.25`). `expires_at` is a whole number.
- **Position** is latitude and longitude in degrees with 8 decimals, as the RTK receiver reports them (with LitPOS corrections that is the ETRS89 frame, a few decimetres from the WGS84 of satellite imagery). A point is the array `[lat, lon]`. Each side converts to metres internally; no local coordinate system is shared.
- **Units:** metres, seconds, m/s, rad/s, volts, amperes, watts. Headings are degrees clockwise from true north, 0–360.
- Only the status, state and metric catalogue topics are retained.
- **The mower supplies finished values.** Anything computed from measurements (battery level, power) is computed on the mower and sent; the server stores and shows what it gets and holds no formulas or constants about the mower's hardware. Which values a board measures, their units, ranges and warning levels come from the board's own catalogue (§16), not from this page.

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
{ "id": "c-8f2a", "cmd": "follow", "ok": false, "error": "no_fix", "message": "RTK fix lost", "time": 1794650020.03 }
```

| Field | Rule |
|---|---|
| `id` | Required. 1–64 of `[A-Za-z0-9_-]`, unique per command. |
| `cmd` | Required. The command name. Its parameters are further fields of the same object. |
| `expires_at` | Optional. The command is refused with `expired` when the time is past, and with `no_clock` when the receiver's clock is not set. |

- Every command gets exactly **one final ack**: `ok: true` with `state: "done"`, or `ok: false`. A long-running command (marked in §6.4 and §8) first gets an ack with `state: "accepted"`.
- A long-running command that is replaced or stopped ends with `ok: false`, `error: "cancelled"`.
- **Duplicates:** the receiver remembers at least the last 8 ids. A repeated id (QoS 1 redelivery) is ignored without a second ack.
- Acks never carry secrets.

Error codes shared by both receivers:

| `error` | When |
|---|---|
| `bad_request` | Not a command object, or a parameter is missing or invalid |
| `unknown_cmd` | The command name is not known |
| `expired` | `expires_at` is past |
| `no_clock` | `expires_at` is set and the clock is not |
| `busy` | Another command of the same kind is running |
| `wrong_mode` | The command is not allowed in the current mode (autopilot) |
| `cancelled` | A long-running command was stopped or replaced |
| `failed` | Anything else; `message` says what |

Commands may define more codes; they are listed with the command.

## 6. Gateway topics

### 6.1 `gateway/status`

Plain text `online` or `offline`, retained. `online` is published after every connect; `offline` is the last will. It says whether the mower is reachable.

### 6.2 `gateway/state`

Retained. Published after every connect and when a field changes.

```json
{
  "protocol": "0.1",
  "firmware": "0.4.0",
  "previous": "0.3.2",
  "partition": "ota_0",
  "autopilot_link": "up",
  "ntrip": "streaming",
  "operator": "24601",
  "time": 1794650000
}
```

| Field | Values |
|---|---|
| `protocol` | Contract version the gateway implements |
| `firmware`, `previous`, `partition` | Running version, the version before the last update, the running slot |
| `autopilot_link` | `up` / `down` (heartbeat on the board link, §14.4) |
| `ntrip` | `off` (no settings), `waiting` (no position from the autopilot yet), `connecting`, `streaming`, `error` |
| `operator` | Network code of the mobile operator in use |

### 6.3 `gateway/telemetry`

The gateway's measurements: signal, its own load, and how much mobile data the mower uses and for what. All of them are metrics from the gateway's catalogue (§16); the message has no other fields than `time` and `boot`.

```json
{
  "time": 1794650000, "boot": 1794563600,
  "metrics": {
    "signal.rssi": -71,
    "link.crc_errors": 0,
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

`boot` is when the gateway started. Each metric is sent at the period its catalogue entry names (60 s for most gateway metrics).

**Data usage.** Every byte passes through the gateway, so it does the counting:

| Metric | Meaning |
|---|---|
| `usage.total.up`, `usage.total.down` | Bytes on the LTE connection, as counted on the network interface. This is what the SIM's allowance is charged for |
| `usage.ntrip.up`, `usage.ntrip.down` | The caster connection: positions sent, corrections received |
| `usage.mqtt.up.<topic>`, `usage.mqtt.down.<topic>` | One topic's bytes, the topic named without `mower/<name>/`. Whole MQTT packets are counted (header, topic and payload) |

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
| `status` | | uptime, signal, heap, clock, link and NTRIP state | Never returns the NTRIP password |
| `restart` | | | Acks, then restarts |
| `ota` | `version`, optional `file`, `size` | `{"version", "previous", "partition"}` | Long-running. Downloads `gateway/fw/…` (§12). Errors: `same_version`, `bad_image`, `bad_size`, `download_failed`, `low_signal`, `not_found` |
| `ntrip_set` | `host`, `port`, `mountpoint`, `user`, `password` | | Stores the caster settings on the gateway (§13) |
| `ntrip_clear` | | | Removes them; corrections stop |
| `autopilot_reset` | | | Pulses the autopilot's reset line, if wired |
| `monitor_start`, `monitor_stop` | as in §15 | | Fast sampling of gateway values, on demand |

## 7. Autopilot state, telemetry and events

### 7.1 `autopilot/state`

Retained. Published when a field changes and every time the gateway reports the server link up (§14.4). It changes on transitions only; progress is in telemetry.

```json
{
  "protocol": "0.1",
  "firmware": "0.1.0",
  "mode": "job",
  "paused": false,
  "job": "j-2031",
  "recording": null,
  "fault": null,
  "time": 1794650000.00
}
```

| `mode` | Meaning | Leaves by |
|---|---|---|
| `idle` | Stopped, blade off | `manual_start`, `record_start`, `job_start`, `follow` |
| `manual` | Follows the live-driving stream (§9) | `manual_stop`, `stop`, `record_start` |
| `recording` | As `manual`, and streams border points (§10) | `record_stop` (to `manual`), `stop` |
| `job` | Follows a path: a job (§11) or a `follow` command | Path finished, `stop`; `pause` / `resume` set `paused` |
| `fault` | Stopped, blade off, refuses motion | `clear_fault` (to `idle`) |

`job` is the job id (null for a `follow` path and outside `job` mode), `recording` the session id, `fault` an object `{"code", "message"}`.

`stop` is accepted in every mode and from every source, ends in `idle` (or stays in `fault`), and switches the motors and the blade off.

Fault codes: `no_fix` (RTK fix lost while following a path, longer than the autopilot tolerates), `motor_stall`, `blade_stall`, `battery_low`, `internal`.

**Losing the server link.** The link counts as lost when the gateway has reported MQTT disconnected for 10 s, or the board link is down (§14.4). The mower does not work on its own without the server:

- In `job` mode the autopilot pauses (`paused: true`, blade off) and publishes the event `job_paused`. It stays paused when the link returns; the server continues it with `resume`.
- In `recording` it stops recording and goes to `manual`, as after `record_stop`, and publishes the event `recording_stopped` (§10).
- Live driving has already stopped by its own timeout (§9).

### 7.2 `autopilot/telemetry`

Every value the autopilot measures or computes, position included, is a metric from its catalogue (§16). The message has no other fields than `time` and `boot` (when the autopilot started).

```json
{
  "time": 1794650000.25, "boot": 1794563700,
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
- Metrics that belong together (the position metrics) have the same period and come from the same measurement.
- In `idle` the autopilot sends no metric more often than every 10 s.
- A value that is not known is `null` (the position without a fix, `job.point` outside a job).

The server needs a few values to draw the map, run jobs and fill the app's fixed indicators. It asks for them by **key** (§16.4), and the catalogue says which metric answers each key; the metric names themselves are the board's choice.

### 7.3 `autopilot/event`

Things that happen without a command. Command results are acks, not events.

```json
{ "time": 1794650020.03, "event": "fault", "code": "no_fix", "message": "RTK fix lost" }
```

| `event` | Extra fields | When |
|---|---|---|
| `boot` | `firmware`, `reason` | The autopilot started |
| `fault` | `code`, `message` | Entered `fault` |
| `fault_cleared` | | Left `fault` |
| `fix_lost`, `fix_regained` | `fix` | The fix dropped below or returned to `rtk_fixed` |
| `drive_timeout` | | The live-driving stream timed out (§9) |
| `job_paused` | `reason`: `link` | A path was paused because the server link was lost (§7.1) |
| `recording_stopped` | `reason`: `link`, `session`, `index` | Recording ended because the server link was lost; `index` is the next index, as in the result of `record_stop` |
| `battery_low` | `v` | Battery below the autopilot's warning level |

## 8. Autopilot commands

| `cmd` | Parameters | Allowed in | Long-running | Notes |
|---|---|---|---|---|
| `stop` | | any | | Motors and blade off, ends in `idle`. Cancels a running path |
| `manual_start` | | `idle` | | Enters `manual` |
| `manual_stop` | | `manual` | | Returns to `idle` |
| `blade` | `on` | `manual`, `recording` | | In `job` mode the path sets the blade |
| `follow` | `points`, optional `reverse`, `blade`, `speed` | `idle`, `manual` | yes | Drives through 1–100 points in order; one point is "go to". `reverse: true` drives backwards without turning round. `blade` defaults to off. Enters `job`, then returns to the mode it came from. Errors: `no_fix` |
| `record_start` | `session`, `index`, optional `spacing` | `idle`, `manual` | | Enters `recording` (§10) |
| `record_stop` | | `recording` | | Returns to `manual`. Result `{"index": <next index>}` |
| `job_start` | `job`, `size`, `sha256`, optional `from_point` | `idle` | yes | Downloads and runs a job (§11). Errors: `download_failed`, `bad_job`, `no_fix` |
| `pause`, `resume` | | `job` | | Stops and continues the path; the blade is off while paused |
| `clear_fault` | | `fault` | | Returns to `idle` |
| `monitor_start` | `session`, `metrics`, `rate`, optional `hold` | any | | Starts or extends fast sampling (§15) |
| `monitor_stop` | optional `session` | any | | Ends that stream, or every stream when `session` is absent |
| `ota` | `version`, optional `file`, `size` | `idle` | yes | Updates the autopilot firmware over `autopilot/fw/…` (§12), with rollback |
| `restart` | | `idle`, `fault` | | |

`speed` is a limit in m/s; the autopilot also has its own maximum and uses the lower.

## 9. Live driving

The server publishes setpoints on `autopilot/drive` about 10 times per second while the user drives. QoS 0, no acks.

```json
{ "seq": 1041, "time": 1794650000.25, "v": 0.5, "w": -0.2 }
```

| Field | Meaning |
|---|---|
| `seq` | Counter that grows by one per setpoint within a session. A setpoint with a `seq` not above the last applied one is dropped |
| `time` | When the server sent it. A setpoint more than 1 s old is dropped (messages delivered in a burst after a stall) |
| `v` | Forward speed, m/s; negative is backwards |
| `w` | Turn rate, rad/s; positive turns left |

- Setpoints are applied only in `manual` and `recording`; elsewhere they are ignored.
- **Timeout:** with no valid setpoint for **0.5 s** the autopilot stops the motors, stays in its mode, and publishes the event `drive_timeout` once. The next valid setpoint moves it again.
- The autopilot clamps `v` and `w` to its limits.

The same commands and setpoints will be used on a local link (gateway Wi-Fi or Bluetooth); that transport is not part of version 0.1.

## 10. Border recording

The user drives the mower along a border; the autopilot streams the points and the server keeps the draft border and shows it live. The border and every edit of it belong to the server.

`record_start` carries the session id, the index the next point gets, and optionally the spacing in metres (default 0.1). In `recording` the autopilot takes a point each time it has moved `spacing` from the last one, while its fix is `rtk_fixed` or `rtk_float`, and publishes them in batches on `autopilot/recording`, at most once per second and at most 50 points per message:

```json
{ "session": "r-17", "index": 120, "fix": "rtk_fixed", "time": 1794650000.25,
  "points": [[54.68712345, 25.27965432], [54.68712431, 25.27965440]] }
```

- `index` is the index of the first point in the message; indexes are continuous within a session, so the server sees a gap.
- `fix` is the worst fix of the batch: `rtk_fixed` or `rtk_float`. The server takes both into the border and marks the float points. With a worse fix no points are taken.
- When the server link is lost, recording stops (§7.1). Points taken before that still arrive; nothing is recorded while offline. The user continues with a new `record_start` for the same session and the next index.

**Rewind** is done by the server with existing commands: `record_stop`, then `follow` along the last recorded points in reverse order with `reverse: true`, then `record_start` with the same session and the index of the first removed point. The server cuts the removed points from its draft.

## 11. Jobs

A job is a path planned by the server: segments of points, each with the blade on or off. The autopilot downloads it as a file and follows it.

1. The server sends `job_start` with the job id, the file's `size` in bytes and its `sha256` (64 hex characters).
2. The autopilot acks `accepted` and downloads the file over `autopilot/job/…` (§12), asking for the file named by the job id.
3. It checks the size and hash, then follows the segments in order. State shows `mode: "job"` and the job id; telemetry shows the metric linked to the key `job.point` (§16.4).
4. The final ack is `done` with `{"points": <count>}`, or a failure. After a failure or a `stop`, the server can send `job_start` again with `from_point` to continue.

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

A job id is 1–64 of `[A-Za-z0-9_-]`. The server checks every job against the map's zones before sending it: the autopilot has no map to check against.

## 12. Chunk transfer

Firmware images and job files are downloaded as binary chunks on the MQTT connection, pulled by the receiver one request at a time. The same mechanism serves three topic sets:

| Topics | Who asks | Files |
|---|---|---|
| `gateway/fw/req`, `chunk`, `res` | Gateway | Signed gateway images, `<version>.bin` |
| `autopilot/fw/req`, `chunk`, `res` | Autopilot | Signed autopilot images, `<version>.bin` |
| `autopilot/job/req`, `chunk`, `res` | Autopilot | Job files, named by the job id |

The server keeps the three sets of files apart: a request on one topic set can only reach that set's files.

The request JSON, the 64-byte chunk header (`RMFW`), the info reply and the error codes are specified in [Server-App, Firmware over MQTT](Server-App#firmware-over-mqtt). A chunk is 4096 bytes by default, so a chunk message is larger than the 4096-byte JSON limit of §4; the board link carries it (§14.2).

## 13. Corrections (NTRIP)

The RTK receiver needs a correction stream from an NTRIP caster. The NTRIP client runs on the gateway, with its own TCP connection to the caster over LTE. Corrections do not pass through MQTT or the server, so positioning keeps working while the server is down.

- **Settings** (host, port, mount point, user, password) are stored on the gateway and set with the gateway command `ntrip_set` (§6.4). The password is never reported back.
- **Position to the caster:** the autopilot sends its GGA sentence to the gateway every 10 s (§14.3); the gateway forwards it to the caster. A network caster such as LitPOS needs it to keep sending corrections.
- **Corrections to the receiver:** the gateway forwards the caster's bytes to the autopilot unchanged (§14.3), which feeds them to the receiver.
- **Reporting:** the gateway reports the client's state in `gateway/state` (`ntrip`); the autopilot reports the result in telemetry (`gnss.fix`, `gnss.correction_age`).

## 14. Board link (UART)

The wiring is in [Mower-Hardware](Mower-Hardware). 921600 baud, 8N1, RTS/CTS flow control. **Not verified on hardware yet.**

### 14.1 Frames

A frame is `type` (1 byte), `body`, and a CRC-16 (CCITT-FALSE: polynomial `0x1021`, initial value `0xFFFF`) over type and body, little-endian. The frame is COBS-encoded and ends with one `0x00` byte. The largest frame is 4608 bytes before encoding. A frame with a bad CRC or an unknown type is dropped and counted.

| Type | Name | Direction | Body |
|---|---|---|---|
| `0x01` | PUBLISH | autopilot → gateway | A message to publish (§14.2) |
| `0x02` | MESSAGE | gateway → autopilot | A received message (§14.2) |
| `0x03` | SUBSCRIBE | autopilot → gateway | Topics the autopilot wants (§14.2) |
| `0x04` | CORRECTIONS | gateway → autopilot | Raw bytes from the caster |
| `0x05` | GGA | autopilot → gateway | One NMEA GGA sentence, ASCII |
| `0x06` | HEARTBEAT | both | §14.4 |

### 14.2 Relayed messages

PUBLISH and MESSAGE share one body:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Flags: bit 0 retain, bits 1–2 QoS (0 or 1) |
| 1 | 1 | Topic length `n` |
| 2 | `n` | Topic, ASCII, **without** the `mower/<name>/autopilot/` prefix (for example `telemetry`, `cmd/ack`) |
| 2 + `n` | rest | Payload, unchanged |

- The gateway adds the prefix when it publishes and removes it when it delivers, so the autopilot can only use its own topics. It does not read or change the payload.
- **SUBSCRIBE** body: one or more entries of QoS (1 byte), topic length (1 byte), topic (without the prefix; MQTT wildcards allowed). The autopilot sends its whole list each time the heartbeat shows the link has come up; the gateway replaces the previous list and subscribes again after every MQTT reconnect. Version 0.1's list is `cmd`, `drive`, `job/chunk`, `job/res`, `fw/chunk`, `fw/res`.
- While MQTT is disconnected the gateway queues QoS 1 messages up to its memory limit and drops QoS 0 messages. The autopilot knows the connection state from the heartbeat.

### 14.3 Correction frames

CORRECTIONS frames carry the caster's bytes in order, split wherever the gateway likes; the autopilot passes them to the receiver as a stream. GGA frames carry one sentence each, every 10 s while the receiver has a position.

### 14.4 Heartbeat

Both boards send a HEARTBEAT every second. A board that receives none for 3 s treats the link as down.

Gateway → autopilot:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Link version, `1` |
| 1 | 1 | Flags: bit 0 MQTT connected, bit 1 server online (`mower/status/server`), bit 2 corrections streaming, bit 3 clock valid |
| 2 | 4 | Unix time, seconds (little-endian; 0 when the clock is not valid) |
| 6 | 2 | Milliseconds |

Autopilot → gateway:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Link version, `1` |
| 1 | 1 | Flags: bit 0 ready (subscriptions sent) |

The autopilot may set its clock from the heartbeat until the receiver gives it time. When bit 0 of the gateway's flags goes from 0 to 1 the autopilot republishes its state (§7.1) and its metric catalogue (§16.1).

## 15. Monitor

Telemetry is at most once per second from the autopilot (§7.2) and mostly once per minute from the gateway (§6.3). For values that change fast (battery voltage and current, wheel and blade speed, data usage) the user can ask for a short, fast stream of chosen values, for example to watch a chart. It runs beside any mode and changes nothing about how the mower drives. It is never stored on the mower and never sent unless asked for.

Both boards offer it, each for its own values, with the same commands and the same message: the autopilot on `autopilot/cmd` and `autopilot/monitor`, the gateway on `gateway/cmd` and `gateway/monitor`. The two are independent, each with its own streams and budget.

**Start.** `monitor_start` on the board's `cmd` topic:

```json
{ "id": "c-91b0", "cmd": "monitor_start", "session": "m-3", "metrics": ["battery.v", "battery.a"], "rate": 100, "hold": 10 }
```

| Field | Rule |
|---|---|
| `session` | Id chosen by the server, 1–64 of `[A-Za-z0-9_-]` |
| `metrics` | One or more metric names from the board's catalogue (§16) |
| `rate` | Samples per second. It must be one of the `rates` of every metric asked for |
| `hold` | Seconds the stream runs without being extended; default 10, at most 60 |

Any number of streams run side by side, each with its own session, metrics, rate and hold. The only limit is the total: the sum of `metrics × rate` over all running streams may not exceed the board's **budget**: 400 values per second on the autopilot and 100 on the gateway in version 0.1. The ack's result reports it, so the app can show what is left:

```json
{ "id": "c-91b0", "cmd": "monitor_start", "ok": true, "state": "done", "result": { "budget": 400, "used": 200 }, "time": 1794650012.01 }
```

Errors: `bad_request` for an unknown metric, a rate a metric does not offer, or for a running session id with different metrics or rate (use a new session); `over_budget` when the stream does not fit, with `budget` and `used` in the message.

**Keeping it alive.** The stream ends by itself `hold` seconds after the last `monitor_start`. While the user is watching, the server sends `monitor_start` again with the same session (and a new command id) every few seconds; that extends the stream without restarting the sample index. A stream also ends on `monitor_stop`, and every stream ends at once when the gateway reports the server link down (§14.4). Nothing is kept back for later.

**Data.** The board publishes each stream's samples on its `monitor` topic, QoS 0, one message per stream every 0.2 s (the gateway: every second):

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

State (§6.2, §7.1), events (§7.3) and recorded border points (§10) are not metrics: they are not measurements over time but facts that must arrive, so they keep their own messages with guaranteed delivery.

### 16.1 Catalogue topics

`gateway/metrics/<part>` and `autopilot/metrics/<part>`, retained, QoS 1. A board publishes its catalogue after boot and again when the server link comes up. The catalogue is split into parts so that each message fits 4096 bytes; normally one part per group, where a metric's group is its name up to the first dot (`battery`, `drive`, `system`, `usage`). The server joins all parts. A board removes a part by publishing an empty retained message on its topic.

```json
{
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

`label` at the top is the display name of the part's group.

### 16.2 Entry fields

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | The id used in telemetry and monitor requests. Lower-case parts joined by dots; the first part is the group. Stable: a name never changes its meaning |
| `key` | no | The server key this metric answers (§16.4) |
| `label` | yes | Display name, English |
| `description` | yes | One or two sentences for a tooltip, English |
| `unit` | yes | Unit as shown: `V`, `A`, `W`, `%`, `rpm`, `m/s`, `°C`, `B`, `dBm`; empty for none |
| `kind` | yes | `gauge` or `counter` (§16.3) |
| `type` | yes | `number`, `bool` or `enum` |
| `period` | yes | Seconds between values in telemetry; `0` means the metric is not in telemetry, only in monitor streams |
| `rates` | yes | Monitor rates the metric offers, samples per second; empty when it cannot be monitored |
| `chart` | yes | `true` or `false`: whether the app offers the metric in its chart picker (a latitude is not something to chart). Always stated; there is no default. It limits nothing else: the metric is still sent, stored and usable through its key |
| `min`, `max` | no | Expected range, for chart axes and gauges |
| `low`, `high` | no | Warning levels: the app marks a value below `low` or above `high`. For display only; the board raises its own events and faults (§7.3) |
| `decimals` | no | Digits after the decimal point to show |
| `values` | for `enum` | The names of the values, in order; the metric's value is an index into this list, from 0 |

**Families.** A name ending in `.*` describes a set of metrics that share everything but the last part, which is only known while running: the gateway's `usage.mqtt.up.*` covers one counter per MQTT topic (`usage.mqtt.up.autopilot/telemetry`). The last part may contain any characters but a dot. A member appears in telemetry once it has data, and the app lists the members it has seen.

### 16.3 Gauges and counters

- A **gauge** is a value at a moment (a voltage, a speed). It is charted as it is.
- A **counter** only grows: it counts something since the board's boot (bytes sent, dropped frames). It is charted as its rate of change, in its unit per second. The `boot` field of the telemetry message says when counting started; a new `boot` value means every counter started again from 0. Because a counter carries the whole count, a lost message loses nothing.
- A counter that has not changed since it was last sent may be left out of a telemetry message.

### 16.4 Keys

The list of values the server and the app use by themselves. It is the interface a mower has to satisfy: for every key, one metric of the mower names it in its catalogue entry (`key`). The list is kept short; a key is added only when the server or the app starts to depend on a value.

| Key | Type, unit | The server or app uses it for |
|---|---|---|
| `position.lat` | number, degrees | The mower on the map (§4) |
| `position.lon` | number, degrees | The mower on the map (§4) |
| `position.heading` | number, degrees | The mower's direction on the map. The receiver has one antenna, so the heading comes from movement and is null while it is not known (standing still) |
| `gnss.fix` | enum: `none`, `single`, `dgps`, `rtk_float`, `rtk_fixed` (values 0–4) | Whether the position can be trusted |
| `job.point` | number | Job progress and where to resume: the index of the last point reached, counted through the whole job; null outside a job. The job itself is named in state (§7.1) |
| `battery.level` | number, % | The battery indicator |
| `blade.on` | bool | The blade indicator |
| `signal.strength` | number, dBm | The signal indicator |

Rules:

- A key is linked by exactly one metric of the mower, on either board.
- The metric has the key's type and unit; the server converts nothing. For an enum key, the metric's `values` are the key's values in the same order.
- Metrics whose keys belong together (`position.lat`, `position.lon`, `position.heading`, `gnss.fix`) have the same period and come from the same measurement.
- The server reads the links from the catalogue. A key that no metric links is reported in the app, and what depends on it is not shown.

### 16.5 Metrics of version 0.1 firmware

For orientation: the catalogue a board publishes is what counts. Ranges, warning levels and decimals are set in the firmware. Period is seconds between values in telemetry; rates are samples per second on demand (§15); chart says whether the app offers the metric in its chart picker.

| Board | Name | Key | Type | Unit | Kind | Period | Monitor rates | Chart |
|---|---|---|---|---|---|---|---|---|
| Autopilot | `position.lat` | `position.lat` | number | degrees | gauge | 1 | 10 | no |
| Autopilot | `position.lon` | `position.lon` | number | degrees | gauge | 1 | 10 | no |
| Autopilot | `position.heading` | `position.heading` | number | degrees | gauge | 1 | 10 | no |
| Autopilot | `position.alt` | | number | m | gauge | 0 | 10 | yes |
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
| Gateway | `link.crc_errors` | | number | frames | counter | 60 | | yes |
| Gateway | `usage.total.up`, `usage.total.down` | | number | B | counter | 60 | 1, 2, 5, 10 | yes |
| Gateway | `usage.ntrip.up`, `usage.ntrip.down` | | number | B | counter | 60 | 1, 2, 5, 10 | yes |
| Gateway | `usage.mqtt.up.*`, `usage.mqtt.down.*` | | number | B | counter | 60 | 1, 2, 5, 10 | yes |
| Both | `system.cpu`, `system.core0`, `system.core1` | | number | % | gauge | 10 / 60 | 10 / 1, 2, 5, 10 | yes |
| Both | `system.memory.free`, `system.memory.min_free`, `system.memory.largest` | | number | B | gauge | 10 / 60 | 10 / 1, 2, 5, 10 | yes |
| Both | `system.memory.pct` | | number | % | gauge | 10 / 60 | 10 / 1, 2, 5, 10 | yes |
| Both | `system.nvs.pct` | | number | % | gauge | 10 / 60 | | yes |
| Both | `system.temperature` | | number | °C | gauge | 10 / 60 | 10 / 1, 2, 5, 10 | yes |

Where a row is for both boards, the first period and rates are the autopilot's, the second the gateway's. `system.temperature` exists only where the chip has a usable sensor.

These boards have no disk. Their storage is flash: the settings area (`system.nvs.pct`) today, and one more metric per file system if a board gets one.
