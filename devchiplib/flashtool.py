"""Back up, verify and restore the FPGA's boot flash (the design that runs at
power-up), which openFPGALoader 0.11 on ChipLoader cannot read back.

Reading: a small read-only design (hdl/flash_reader.v) is loaded into SRAM.
It reads the flash chip directly and streams it to the PC over the CP2105
Standard port, 64 KiB at a time, each block protected by a CRC-16 and
retried on error. It cannot write to the flash (see the HDL header).

Restoring: the image is uploaded to ChipLoader and written with
`openFPGALoader -c dirtyJtag -f --file-type bin`, then read back and compared.
"""
import binascii
import gzip
import hashlib
import json
import os
import time

from .chiploader import CABLE, CP2105_PID, CP2105_VID

HDL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hdl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READER_SOURCES = [os.path.join(HDL, "flash_reader.v"),
                  os.path.join(ROOT, "rtl", "uart_rx.v"),
                  os.path.join(ROOT, "rtl", "uart_tx.v")]
# Tang Primer 20K configuration-flash pins (MSPI). Only the reader may use them.
READER_PINS = {"flash_cs_n": "M9", "flash_clk": "L10", "flash_mosi": "R10", "flash_miso": "P10"}
READER_BAUD = 921600
BLOCK = 64 * 1024

VENDORS = {0xEF: "Winbond", 0xC8: "GigaDevice", 0x68: "Boya", 0x20: "XMC/Micron",
           0x0B: "XTX", 0x85: "Puya", 0x9D: "ISSI", 0xC2: "Macronix", 0x1C: "EON"}


class FlashError(Exception):
    pass


def find_fpga_uart():
    """The CP2105 interface wired to the FPGA's uart_rx/uart_tx (interface 1, 'Standard')."""
    from serial.tools import list_ports
    cps = [p for p in list_ports.comports() if p.vid == CP2105_VID and p.pid == CP2105_PID]
    std = [p for p in cps if "standard" in (p.description or "").lower()]
    if len(std) == 1:
        return std[0].device
    iface1 = [p for p in cps if (p.location or "").endswith(".1")]
    if len(iface1) == 1:
        return iface1[0].device
    raise FlashError("could not find the CP2105 Standard port; pass --uart-port")


def build_reader(out, oss=None, log=print):
    from .toolchain import build
    return build(READER_SOURCES, out, top="top", oss=oss, log=log,
                 _internal=READER_PINS, _flags=("mspi",))


class Reader:
    def __init__(self, port):
        import serial
        try:
            self.ser = serial.Serial(port, READER_BAUD, timeout=2)
        except serial.SerialException as e:
            raise FlashError(f"cannot open {port}: {e}")
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def _exact(self, n):
        data = self.ser.read(n)
        if len(data) != n:
            raise FlashError(f"timeout: expected {n} bytes, got {len(data)}")
        return data

    def jedec(self):
        for _ in range(3):
            self.ser.reset_input_buffer()
            self.ser.write(b"I")
            try:
                r = self._exact(4)
            except FlashError:
                continue
            if r[0:1] == b"I":
                return r[1], r[2], r[3]
        raise FlashError("flash reader does not answer (is it loaded?)")

    def read_block(self, addr, n, retries=4):
        cmd = b"R" + addr.to_bytes(3, "big") + n.to_bytes(3, "big")
        for attempt in range(retries):
            self.ser.reset_input_buffer()
            self.ser.write(cmd)
            try:
                hdr = self._exact(1)
                data = self._exact(n)
                crc = int.from_bytes(self._exact(2), "big")
            except FlashError:
                time.sleep(0.5)
                continue
            if hdr == b"R" and binascii.crc_hqx(data, 0xFFFF) == crc:
                return data
            time.sleep(0.2)
        raise FlashError(f"block at 0x{addr:06X} failed {retries} times")

    def read(self, start, length, progress=None):
        out = bytearray()
        addr = start
        while addr < start + length:
            n = min(BLOCK, start + length - addr)
            out += self.read_block(addr, n)
            addr += n
            if progress:
                progress(addr - start, length)
        return bytes(out)


def describe(jid):
    m, t, c = jid
    size = (1 << c) if 16 <= c <= 28 else None
    return VENDORS.get(m, f"vendor 0x{m:02X}"), size


def used_length(image, align=4096):
    """Bytes up to the last non-erased (non-0xFF) byte, rounded up."""
    end = len(image.rstrip(b"\xff"))
    return min(len(image), ((end + align - 1) // align) * align)


def save_backup(path, image, jid):
    with open(path, "wb") as f:
        f.write(image)
    meta = {"jedec": "%02X %02X %02X" % jid, "size": len(image),
            "used": used_length(image), "sha256": hashlib.sha256(image).hexdigest(),
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(path + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def write_image(cl, image):
    """Write a raw flash image at offset 0 through ChipLoader. Returns the exit code.
    openFPGALoader 0.11 accepts raw .bin images for this chip only with --external-flash."""
    if not image or len(image) > 8 * 1024 * 1024:
        raise FlashError("flash image must be 1 byte .. 8 MiB")
    cl.transfer(gzip.compress(image, mtime=0))            # MD5-verified -> /tmp/pack.fs.gz
    return cl.run_fixed("gunzip -c /tmp/pack.fs.gz > /tmp/devchip_image.bin && "
                        f"openFPGALoader {CABLE} --external-flash -f --file-type bin "
                        "/tmp/devchip_image.bin; rc=$?; rm -f /tmp/devchip_image.bin; (exit $rc)",
                        timeout=600)


def fs_to_image(fs_data):
    """Gowin .fs text -> the bytes it occupies in flash (verified on hardware)."""
    out = bytearray()
    for ln in fs_data.decode("ascii", "replace").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("//"):
            out += int(ln, 2).to_bytes(len(ln) // 8, "big")
    return bytes(out)
