"""Derive board/pins.csv from a ChipInventor-generated .cst file.

ChipInventor's "Associate Pins" dialog writes constraints that use Gowin's
internal pad names (e.g. IOL45B). This script translates them to package
balls (e.g. E8) using the Apicula chip database and adds the per-pin
direction / safety metadata used by devchip.py.

How the source .cst was obtained is described in docs/JOURNEY.md (map every
location once with tools/pinmap/map_all.v, then download the design archive;
the file is design/pinData/fpga_*.cst).

Needs Apicula (bundled with OSS CAD Suite):
    python tools/cloudcst_to_pins.py path/to/fpga_XXXX.cst -o board/pins.csv
Run it with the OSS CAD Suite python (oss-cad-suite/lib/python3), or any
python where `pip install apycula` has been done.
"""
import argparse
import csv
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
try:
    import apycula
    from apycula import chipdb
except ImportError:
    sys.exit("apycula not found: run with the OSS CAD Suite python or `pip install apycula`")

# Balls that Sipeed's own reference constraints declare as LVCMOS15 (1.5 V bank).
LOW_VOLTAGE_BALLS = {"E8", "E9", "T2", "T3", "T4"}


def classify(loc):
    """Board-level knowledge, verified on hardware unless noted."""
    if loc == "clk":
        return "in", "clock", "", "27 MHz oscillator on the Tang Primer 20K module"
    if loc == "uart_rx":
        return "in", "uart", "", "FPGA receives from PC (CP2105 Standard port)"
    if loc == "uart_tx":
        return "out", "uart", "", "FPGA sends to PC (CP2105 Standard port)"
    if re.fullmatch(r"led[0-7]", loc):
        return "out", "led", "high", "LED on when driven 1"
    if re.fullmatch(r"s[0-7]", loc):
        return "in", "switch", "high", "slide switch reads 1 when on"
    if re.fullmatch(r"b[0-7]", loc):
        return "in", "button", "high", "push button reads 1 while pressed"
    if loc == "pir":
        return "in", "pir", "high", "PIR motion sensor; ~4 s lockout after each trigger"
    if loc == "buzzer":
        return "out", "buzzer", "high", "drive a square wave (e.g. 2 kHz) for a tone"
    if re.fullmatch(r"disp_[1-4]", loc):
        return "out", "7seg", "high", "digit enable (1 = digit on); multiplex the 4 digits"
    if re.fullmatch(r"disp_(a|b|c|d|e|f|g|dp)", loc):
        return "out", "7seg", "high", "segment (1 = lit), shared by all 4 digits"
    if loc == "acc_cs":
        return "out", "accel", "", "LIS3DH accelerometer chip select (active low), SPI mode 3"
    if loc == "acc_sclk":
        return "out", "accel", "", "LIS3DH SPI clock (idle high, mode 3)"
    if loc == "acc_mosi":
        return "out", "accel", "", "LIS3DH SPI data in"
    if loc == "acc_miso":
        return "in", "accel", "", "LIS3DH SPI data out (ID register 0x0F reads 0x33)"
    if re.fullmatch(r"pmod[01]_[0-7]", loc):
        return "io", "pmod", "", "PMOD connector, free for user"
    if loc in ("d5", "d7", "f6", "f7"):        # measured: pulled high weakly on the carrier
        return "io", "header", "", "2x20 header, free for user; weakly pulled high on the carrier (reads 1 when undriven)"
    if re.fullmatch(r"[cdef][0-7]", loc):
        return "io", "header", "", "2x20 header, free for user"
    return "io", "other", "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cst", nargs="+")
    ap.add_argument("-o", "--out", default="pins.csv")
    a = ap.parse_args()

    db = chipdb.load_chipdb(os.path.join(os.path.dirname(apycula.__file__), "GW2A-18C.msgpack.xz"))
    pkg = db.pinout["GW2A-18C"]["PBGA256"]
    io2ball = {v[0]: (ball, v[1]) for ball, v in pkg.items()}

    loc_re = re.compile(r'IO_LOC\s+"([^"]+)"\s+(\S+?);')
    pull_re = re.compile(r'IO_PORT\s+"([^"]+)".*PULL_MODE=(\w+)')
    locs, pulls = {}, {}
    for path in a.cst:
        for line in open(path, encoding="utf-8", errors="replace"):
            m = loc_re.search(line)
            if m:
                locs[m.group(1)] = m.group(2)
            m = pull_re.search(line)
            if m:
                pulls[m.group(1)] = m.group(2)

    rows = []
    for loc, io in locs.items():
        if io not in io2ball:
            sys.exit(f"{loc}: unknown Gowin pad {io}")
        ball, funcs = io2ball[io]
        direction, group, active, note = classify(loc)
        rows.append({
            "location": loc, "ball": ball, "gowin_io": io, "direction": direction,
            "group": group, "active": active, "pull": pulls.get(loc, ""),
            "vccio": "1.5" if ball in LOW_VOLTAGE_BALLS else "3.3",
            "special": " ".join(funcs), "notes": note,
        })
    order = ["clock", "uart", "led", "switch", "button", "7seg", "buzzer", "pir",
             "accel", "pmod", "header", "other"]
    rows.sort(key=lambda r: (order.index(r["group"]), r["location"]))
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {a.out}: {len(rows)} pins")


if __name__ == "__main__":
    main()
