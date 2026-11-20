"""Companion to pin_tester.v: show the level of all 48 PMOD/header pins.

    python examples/pin_tester/pin_tester.py               # live: prints every change
    python examples/pin_tester/pin_tester.py --expect 1    # one-shot check: all pins must read 1
    python examples/pin_tester/pin_tester.py --expect 0    # (use with pull_down.cst)
"""
import argparse
import os
import sys
import time

import serial

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from devchiplib.flashtool import find_fpga_uart  # noqa: E402

GROUPS = ["c", "d", "e", "f", "pmod0_", "pmod1_"]
NAMES = [f"{g}{i}" for g in GROUPS for i in range(8)]


def levels(body):
    """{name: 0/1} from the 6 data bytes (each byte MSB = bit 7)."""
    out = {}
    for g, byte in zip(GROUPS, body):
        for i in range(8):
            out[f"{g}{i}"] = (byte >> i) & 1
    return out


def read_frame(ser, timeout=3):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        buf += ser.read(64)
        i = buf.find(b"\xA5\x5A")
        if i >= 0 and len(buf) >= i + 9:
            body, chk = buf[i + 2:i + 8], buf[i + 8]
            x = 0
            for b in body:
                x ^= b
            if x == chk:
                return levels(body)
            buf = buf[i + 2:]
    raise IOError("no frames from pin_tester.v (is it loaded?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--expect", type=int, choices=(0, 1))
    ap.add_argument("--seconds", type=float, default=600)
    a = ap.parse_args()
    ser = serial.Serial(a.port or find_fpga_uart(), 115200, timeout=0.1)
    ser.reset_input_buffer()

    if a.expect is not None:
        lv = read_frame(ser)
        bad = [n for n in NAMES if lv[n] != a.expect]
        print(f"{48 - len(bad)}/48 pins read {a.expect}" + (f"; NOT: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    prev = read_frame(ser)
    low = [n for n in NAMES if not prev[n]]
    print("ready. pins low now:", ", ".join(low) or "none")
    end = time.time() + a.seconds
    while time.time() < end:
        lv = read_frame(ser)
        for n in NAMES:
            if lv[n] != prev[n]:
                print(f"{time.strftime('%H:%M:%S')}  {n:<8} -> {'LOW (touched)' if lv[n] == 0 else 'high'}",
                      flush=True)
        prev = lv


if __name__ == "__main__":
    main()
