# ChipLoader protocol

"ChipLoader" is the small Linux computer on the DevChipBoard v2.2 that programs
the FPGA. The ChipInventor web page talks to it through the browser's Web Serial
API. This document describes that protocol as re-implemented in
[`devchiplib/chiploader.py`](../devchiplib/chiploader.py), for interoperability.

## Transport
| Property | Value |
|---|---|
| USB device | Silicon Labs CP2105 (VID 10C4, PID EA70) |
| Port | Interface 0, which Windows calls *"Enhanced COM Port"* |
| Serial settings | 115200 baud, 8N1, no flow control |
| Framing | KISS |

Bytes sent without KISS framing are ignored, so ChipLoader looks dead to a
normal serial terminal at every baud rate.

## KISS framing
```
0xC0 <channel byte> <payload, escaped> 0xC0
escape: 0xC0 -> 0xDB 0xDC     0xDB -> 0xDB 0xDD
```
The channel byte holds the channel number directly. Channel 99 doesn't fit the
4-bit port field of standard KISS, so this is a variant of the format.

| Channel | No. | Direction | Content |
|---|---|---|---|
| PROTO  | 0  | both | Control messages (ASCII) |
| FILE   | 1  | host to board | Raw file bytes, written to `/tmp/pack.fs.gz` |
| STDOUT | 2  | board to host | Text output. Each character arrives as its own frame, padded with a NUL byte. Shell commands are echoed as `$> <cmd>\r\n`. |
| STDERR | 3  | board to host | Error text |
| SHELL  | 99 | host to board | A command line run by the board's shell, as root |

## Messages
| Host to board (PROTO) | Board reply | Meaning |
|---|---|---|
| `HOST_QUERY` | `DEVICE_VERSION 1000` | Handshake |
| `TRANSFER_BEGIN` | (none) | The next FILE frame is one chunk |
| `TRANSFER_DONE` | `CHECKSUM <md5>` | MD5 of the assembled `/tmp/pack.fs.gz` |
| `FLASH_BEGIN <args>` | Output on STDOUT/STDERR, then `FLASH_DONE <exit code>` | Gunzips to `/tmp/pack.fs` and runs `openFPGALoader <args> /tmp/pack.fs` |
| `SERIAL_BEGIN` / `SERIAL_CLOSE` | (not observed) | The web page's "user serial" toggle. Unused by this tool. |

## Upload sequence (as the web page does it)
```
for each chunk of at most 131071 bytes of the gzipped bitstream:
    PROTO  "TRANSFER_BEGIN"
    FILE   <chunk>                                         -> /tmp/pack.fs.gz
    SHELL  "cat /tmp/pack.fs.gz >> /tmp/pack2.fs.gz"
SHELL  "mv /tmp/pack2.fs.gz /tmp/pack.fs.gz"
PROTO  "TRANSFER_DONE"                                      <- "CHECKSUM <md5>"
PROTO  "FLASH_BEGIN  -c dirtyJtag -m"                       <- output..., "FLASH_DONE 0"
```
### Framing quirk and recovery
ChipLoader's frame parser keeps state across messages and does not treat `0xC0`
the way standard KISS does:
- **What breaks it:** a stray `0xC0`, or a client that dies in the middle of a
  message, leaves the parser out of step.
- **What that looks like:** every later well-formed message is silently ignored,
  so the board seems dead.
- **What fixes it:** one extra `0xC0` brings it back.

`devchip.py` handles this automatically. If `HOST_QUERY` gets no answer within
1.5 s, it alternates plain and `0xC0`-prefixed queries (up to 6 attempts).

This was measured on hardware:
- **Recovery** from stray bytes, from cut-off frames and from cut-off escape
  sequences took at most 3 attempts.
- **Killed uploads:** uploads killed halfway with `kill -9` were followed by
  successful connections every time.

Unplugging the board, which restarts ChipLoader, is only a last resort.

`devchip.py` makes three changes to the upload sequence itself:
- It first runs `rm -f /tmp/pack2.fs.gz`, so a previously interrupted upload can't get mixed into the new one.
- It refuses to program if the MD5 doesn't match.
- It only ever sends these fixed commands, plus the read-only diagnostics of `devchip.py info`.

The gzip member is named `pack.fs`, which is also what the web server produces.

## openFPGALoader arguments
The web page's script lists several presets:
- `--board tangnano9k`
- `-c libgpiod --pins 106:104:105:103`, labelled "Tang Primer 20K"
- `-c dirtyJtag`
- `-m` (SRAM) and `-f` (flash)

On the DevChipBoard v2.2, the GPIO preset fails with *"no device found"*. The
working cable is **`-c dirtyJtag`**: ChipLoader's `lsusb` shows a DirtyJTAG adapter
(`1209:c0ca`) connected to its USB host port, and that adapter is wired to the
FPGA's JTAG pins.

## Other operations used by devchip.py
These go through the SHELL channel, as fixed command strings:

| Purpose | Command |
|---|---|
| Restart the FPGA from flash | `openFPGALoader -c dirtyJtag -r` |
| Write a raw flash image (restore) | `openFPGALoader -c dirtyJtag --external-flash -f --file-type bin /tmp/devchip_image.bin` |
| Diagnostics | `uname -a`, `openFPGALoader --Version`, `lsusb`, `df -h /tmp`, `openFPGALoader -c dirtyJtag --detect` |

Notes on openFPGALoader v0.11 with this chip:
- **Raw `.bin` images** are rejected ("incompatible file format") unless `--external-flash` is given.
- **`--dump-flash` is not supported** for Gowin devices. `devchip.py flash backup` reads
  the flash with its own read-only FPGA design instead.

## Observed ChipLoader environment
```
Linux chiploader 6.4.16-chiploader armv5tejl   (ARM926EJ-S, ~57 MB RAM)
Buildroot 2023.11
/usr/bin/chiploader -n        (the protocol daemon)
openFPGALoader v0.11.0
/tmp is tmpfs, 28 MB
```
The web page also sets the board's status LEDs (`/sys/class/leds/licheepi:*:usr`)
when it closes. The LED names suggest a Lichee Pi-family board design.
