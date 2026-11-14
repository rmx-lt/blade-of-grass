# Mower hardware

How the mower's electronics split into boards. **Status: design only, not built** (decided 2026-10-22). Building the link: [rmx-mower-gateway#40](https://github.com/rmx-lt/rmx-mower-gateway/issues/40).

## Two boards

| Board | Owns | Firmware repo |
|---|---|---|
| LilyGo T-SIM7600 (ESP32 + SIM7600G-H) | Communications only: LTE, MQTT over TLS, the NTRIP client, the link to the server. No hardware connection to anything but the P4 | [rmx-mower-gateway](https://github.com/rmx-lt/rmx-mower-gateway) ([Mower-Gateway](Mower-Gateway)) |
| Guition JC-ESP32P4-M3-DEV (ESP32-P4 + C6) | positioning (RTK GNSS), motors, blade, battery, **safety** | [rmx-mower-autopilot](https://github.com/rmx-lt/rmx-mower-autopilot) |

Safety lives on the P4: it stops by itself when the link to the modem board or the server's command acks are lost (see [Home](Home), architecture).

## The link

UART with RTS/CTS. Frames are COBS + CRC-16; the frame types and what they carry (relayed MQTT messages as JSON, the correction stream, a heartbeat) are in [Protocol](Protocol) §14.

| T-SIM7600 | Signal | P4 board (JP1) |
|---|---|---|
| GPIO23 | UART2 TX → RX | GPIO33 |
| GPIO19 | UART2 RX ← TX | GPIO32 |
| GPIO18 | RTS → CTS | GPIO47 |
| GPIO22 | CTS ← RTS | GPIO46 |
| GPIO21 | reset (optional, open-drain) | CHIP_PU (solder to the RST button pad) |
| GND | | GND |

P4 firmware updates go over this link into the P4's OTA slot, with rollback.

## Why not the other options

- **SDIO / ESP-Hosted:** the classic ESP32's SDIO slave pins are fixed (2, 4, 12, 13, 14, 15); on the T-SIM7600 GPIO4 is PWRKEY and GPIO12 the LED. The P4's SDIO is already used by its C6.
- **RMII Ethernet:** the ESP32's RMII needs GPIO25–27, which drive the modem.
- **SPI / CAN:** possible, but more work for no gain. The real bottleneck is the modem's own UART (115200 baud, no flow control, about 11 KB/s).
- **ROM flashing of the P4 from the modem board:** the P4 board's CH340C owns UART0, BOOT and CHIP_PU.

## Useful components

- `espressif/eppp_link`: PPP/TUN between two ESPs over UART/SPI/SDIO/Ethernet (measured 2 Mbit/s TCP over UART at 3 Mbaud). The option if the P4 ever needs its own sockets.
- `espressif/esp-serial-flasher`: flashes an ESP32-P4 over UART from another MCU (needs UART0 + BOOT + EN).

## More

Board pinouts and the full lesson are in the private ESP knowledge hub (`jRmx0/esp-knowledge`, local `C:\Repos\esp-knowledge`): `boards/t-sim7600.md`, `boards/jc-esp32p4-m3-dev.md`, `lessons/2026-10-22-modem-to-p4-link.md`. Board facts that are reusable beyond this project go there; mower-specific decisions go here.
