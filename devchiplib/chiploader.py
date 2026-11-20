"""Client for "ChipLoader", the Linux programmer built into the DevChipBoard.

Protocol (re-implemented for interoperability; see docs/PROTOCOL.md):
  * CP2105 "Enhanced" COM port, 115200 8N1.
  * KISS framing: 0xC0 <channel byte> <escaped payload> 0xC0.
  * Channels: PROTO 0, FILE 1, STDOUT 2, STDERR 3, SHELL 99.
  * HOST_QUERY -> DEVICE_VERSION <n>
  * per <=131071-byte chunk: TRANSFER_BEGIN, FILE <chunk>,
    SHELL "cat /tmp/pack.fs.gz >> /tmp/pack2.fs.gz"
    then SHELL "mv /tmp/pack2.fs.gz /tmp/pack.fs.gz", TRANSFER_DONE -> CHECKSUM <md5>
  * FLASH_BEGIN <openFPGALoader args> -> output on STDOUT/STDERR, FLASH_DONE <exit>

Safety: only fixed command strings are ever sent: the upload commands above,
the read-only diagnostics in INFO_COMMANDS, `openFPGALoader -c dirtyJtag -r`
(restart from flash) and the raw-image flash write used by `flash restore`
(devchiplib/flashtool.py). No user input reaches the board's shell.
"""
import hashlib
import os
import re
import sys
import time

FEND, FESC, TFEND, TFESC = 0xC0, 0xDB, 0xDC, 0xDD
PROTO, FILE, STDOUT, STDERR, SHELL = 0, 1, 2, 3, 99
CHUNK = 131071
BAUD = 115200
TESTED_VERSIONS = {"1000"}     # ChipLoader firmware versions this tool was tested with
CP2105_VID, CP2105_PID = 0x10C4, 0xEA70

# openFPGALoader arguments. The DevChipBoard's ChipLoader reaches the FPGA's
# JTAG through an on-board DirtyJTAG adapter (USB 1209:c0ca).
CABLE = "-c dirtyJtag"
ARGS_SRAM = f"{CABLE} -m"        # volatile: lost at power-off
ARGS_FLASH = f"{CABLE} -f"       # persistent: written to the module's SPI flash

INFO_COMMANDS = [
    "uname -a",
    "openFPGALoader --Version",
    "lsusb",
    "df -h /tmp",
    f"openFPGALoader {CABLE} --detect",
]


class ChipLoaderError(Exception):
    pass


def _echo(raw):
    """Print board output without ever failing on the console's encoding."""
    text = raw.decode("utf-8", "replace")
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace"))
    sys.stdout.flush()


def kiss_frame(channel, data):
    if isinstance(data, str):
        data = data.encode()
    out = bytearray([FEND, channel])
    for b in data:
        if b == FEND:
            out += bytes([FESC, TFEND])
        elif b == FESC:
            out += bytes([FESC, TFESC])
        else:
            out.append(b)
    out.append(FEND)
    return bytes(out)


def find_port():
    """Return the CP2105 interface that carries ChipLoader (interface 0, 'Enhanced')."""
    from serial.tools import list_ports
    cps = [p for p in list_ports.comports() if p.vid == CP2105_VID and p.pid == CP2105_PID]
    if not cps:
        raise ChipLoaderError(
            "No DevChipBoard found (CP2105 USB 10C4:EA70). Check the USB cable and that the "
            "Silicon Labs CP210x driver is installed.")
    enhanced = [p for p in cps if "enhanced" in (p.description or "").lower()]
    if len(enhanced) == 1:
        return enhanced[0].device
    iface0 = [p for p in cps if (p.location or "").endswith(".0") or (p.location or "").endswith(":1.0")]
    if len(iface0) == 1:
        return iface0[0].device
    raise ChipLoaderError(
        "Could not tell which CP2105 port is ChipLoader; pass --port. Candidates: "
        + ", ".join(f"{p.device} ({p.description})" for p in cps))


class ChipLoader:
    def __init__(self, port=None, echo=True):
        import serial
        self.port = port or find_port()
        try:
            self.ser = serial.Serial(self.port, BAUD, timeout=0.05)
        except serial.SerialException as e:
            raise ChipLoaderError(
                f"Cannot open {self.port}: {e}\nOnly one program can use the port: close the "
                "ChipInventor web page (or any serial monitor) and try again.")
        self.ser.reset_input_buffer()
        self.echo = echo
        dbg = os.environ.get("DEVCHIP_DEBUG_LOG")     # raw traffic log for troubleshooting
        self._dbg = open(dbg, "ab") if dbg else None
        self.frames = []
        self._cur, self._esc, self._inside = bytearray(), False, False

    # -- context manager --
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass
        if self._dbg:
            self._dbg.close()

    def _log(self, tag, data):
        if self._dbg:
            line = "%s %.3f %s" % (tag.decode(), time.time(), data[:256].hex())
            self._dbg.write(line.encode() + bytes([10]))

    # -- framing --
    def _send(self, channel, data):
        import serial
        frame = kiss_frame(channel, data)
        # 10 bits per byte on the wire; allow 2x margin + 5 s for the OS / USB
        self.ser.write_timeout = len(frame) * 10 / BAUD * 2 + 5
        self._log(b">", frame)
        try:
            self.ser.write(frame)
            self.ser.flush()
        except serial.SerialException as e:
            raise ChipLoaderError(f"serial write failed ({e}). Was the board unplugged?")

    def _ingest(self, raw):
        for b in raw:
            if b == FEND:
                if self._inside and self._cur:
                    ch, msg = self._cur[0], bytes(self._cur[1:])
                    if ch != PROTO:
                        msg = msg.replace(b"\x00", b"")    # device pads text with NULs
                    self.frames.append((ch, msg))
                    if self.echo and ch in (STDOUT, STDERR):
                        _echo(msg)
                self._cur, self._inside = bytearray(), True
            elif self._esc:
                self._cur.append(FEND if b == TFEND else FESC if b == TFESC else b)
                self._esc = False
            elif b == FESC:
                self._esc = True
            elif self._inside:
                self._cur.append(b)

    def _read(self):
        import serial
        try:
            data = self.ser.read(4096)
            if data:
                self._log(b"<", data)
            return data
        except serial.SerialException as e:
            raise ChipLoaderError(f"serial read failed ({e}). Was the board unplugged?")

    def _pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self._ingest(self._read())

    def _wait_proto(self, prefix, timeout):
        end = time.time() + timeout
        while time.time() < end:
            self._ingest(self._read())
            for i, (ch, msg) in enumerate(self.frames):
                if ch == PROTO and msg.startswith(prefix.encode()):
                    del self.frames[: i + 1]
                    return msg.decode("utf-8", "replace")
        return None

    # -- protocol --
    def query(self, timeout=1.5, attempts=6):
        """Handshake. ChipLoader's frame parser keeps state across messages: a
        stray 0xC0 (e.g. from a client that died mid-message) leaves it out of
        step, and every later message is ignored. A single extra 0xC0 brings it
        back, so unanswered queries alternate plain / 0xC0-prefixed attempts.
        (Measured on hardware: recovers from stray bytes, cut-off frames and
        cut-off escapes within 3 attempts.)"""
        for i in range(attempts):
            if i % 2 == 1:
                self.ser.write(bytes([FEND]))
                self._log(b">", bytes([FEND]))
            self._send(PROTO, "HOST_QUERY")
            msg = self._wait_proto("DEVICE_VERSION", timeout)
            if msg:
                return msg.split(" ", 1)[1].strip() if " " in msg else "?"
        raise ChipLoaderError(
            f"No answer from ChipLoader on {self.port}. Close the ChipInventor web page and any "
            "serial monitor. If it still does not answer, unplug the board for a few seconds "
            "and plug it back in (this restarts ChipLoader).")

    def info(self, wait=3.0):
        for cmd in INFO_COMMANDS:
            self._send(SHELL, cmd)
            self._pump(wait)

    def transfer(self, gz_bytes, timeout=60.0, chunk=CHUNK):
        """Upload a gzipped bitstream; returns after verifying the device MD5."""
        if not gz_bytes or gz_bytes[:2] != b"\x1f\x8b":
            raise ChipLoaderError("transfer() expects gzip data")
        # start from a clean state in case an earlier upload was interrupted
        self._send(SHELL, "rm -f /tmp/pack2.fs.gz")
        self._pump(0.3)
        for i in range(0, len(gz_bytes), chunk):
            self._send(PROTO, "TRANSFER_BEGIN")
            self._send(FILE, gz_bytes[i:i + chunk])
            self._send(SHELL, "cat /tmp/pack.fs.gz >> /tmp/pack2.fs.gz")
            self._pump(0.3)
        self._send(SHELL, "mv /tmp/pack2.fs.gz /tmp/pack.fs.gz")
        self._send(PROTO, "TRANSFER_DONE")
        msg = self._wait_proto("CHECKSUM", timeout)
        if not msg:
            raise ChipLoaderError("no CHECKSUM reply after upload")
        device = msg.split(" ", 1)[1].strip().lower() if " " in msg else ""
        local = hashlib.md5(gz_bytes).hexdigest()
        if device != local:
            raise ChipLoaderError(f"upload corrupted: board md5 {device or '?'} != local {local}. "
                                  "Nothing was programmed. Try again.")
        return local

    def run_fixed(self, cmd, timeout=120.0):
        """Run one of this module's fixed commands on ChipLoader; return its exit code."""
        marker = "DEVCHIP_EXIT="
        start = len(self.frames)
        self._send(SHELL, f"{cmd}; echo {marker}$?")
        end = time.time() + timeout
        while time.time() < end:
            self._pump(0.5)
            text = "".join(m.decode("utf-8", "replace") for c, m in self.frames[start:]
                           if c in (STDOUT, STDERR))
            m = re.search(marker + r"(\d+)", text)    # the echoed command shows "$?", not digits
            if m:
                return int(m.group(1))
        raise ChipLoaderError(f"no exit status within {timeout:.0f} s")

    def reset_fpga(self):
        """Reconfigure the FPGA from its flash (as at power-up)."""
        return self.run_fixed(f"openFPGALoader {CABLE} -r", timeout=60)

    def program(self, persistent=False, timeout=300.0):
        """Run openFPGALoader on the board. Returns its exit code."""
        args = ARGS_FLASH if persistent else ARGS_SRAM
        self._send(PROTO, f"FLASH_BEGIN  {args}")
        msg = self._wait_proto("FLASH_DONE", timeout)
        if not msg:
            raise ChipLoaderError(f"no FLASH_DONE within {timeout:.0f} s")
        try:
            return int(msg.split()[1])
        except (IndexError, ValueError):
            raise ChipLoaderError(f"unexpected reply: {msg!r}")
