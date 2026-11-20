"""Identify the DevChipBoard's accelerometer and print live X/Y/Z readings.
Needs examples/accelerometer/accel_bridge.v loaded first (see its header).

    python examples/accelerometer/accel.py [--port COMx] [--seconds 10]
"""
import argparse
import os
import struct
import sys
import time

import serial

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from devchiplib.flashtool import find_fpga_uart  # noqa: E402


class Bridge:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=1)
        time.sleep(0.1)
        self.s.reset_input_buffer()

    def xfer(self, data):
        data = bytes(data)
        self.s.write(b"T" + bytes([len(data)]) + data)
        r = self.s.read(1 + len(data))
        if len(r) != 1 + len(data) or r[0:1] != b"T":
            raise IOError(f"bridge did not answer (got {r!r}); is accel_bridge.v loaded?")
        return r[1:]


# (name, id-read transaction, expected id byte position, expected values)
CHIPS = [
    ("ADXL345",            [0x80, 0x00],       1, {0xE5}),
    ("ADXL362",            [0x0B, 0x00, 0x00], 2, {0xAD}),
    ("LIS3DH / LIS2DH12",  [0x8F, 0x00],       1, {0x33}),
    ("LIS3DSH",            [0x8F, 0x00],       1, {0x3F}),
    ("LIS2DW12",           [0x8F, 0x00],       1, {0x44}),
    ("LSM6DS3 / LSM6DSL",  [0x8F, 0x00],       1, {0x69, 0x6A}),
    ("MPU-6000/6500/9250", [0xF5, 0x00],       1, {0x68, 0x70, 0x71, 0x73}),
    ("ICM-20948",          [0x80, 0x00],       1, {0xEA}),
    ("BMI160",             [0x80, 0x00],       1, {0xD1}),
    ("BMA250 / BMA280",    [0x80, 0x00],       1, {0xF9, 0xFA, 0xFB}),
]


def identify(b):
    b.xfer([0xFF, 0x00])                       # dummy transaction (wakes BMI160-style SPI)
    seen = {}
    for name, txn, pos, ids in CHIPS:
        val = b.xfer(txn)[pos]
        seen[bytes(txn).hex()] = val
        if val in ids:
            return name, val
    raise IOError("no known accelerometer answered; raw replies: "
                  + ", ".join(f"{k}->{v:02X}" for k, v in seen.items()))


def setup_and_reader(b, name):
    """Enable measurement; return a function giving (x, y, z) in g."""
    if name == "ADXL345":
        b.xfer([0x31, 0x08])                   # DATA_FORMAT: full resolution, +-2 g
        b.xfer([0x2D, 0x08])                   # POWER_CTL: measure
        return lambda: tuple(v * 0.0039 for v in struct.unpack("<hhh", b.xfer([0xF2] + [0] * 6)[1:]))
    if name == "ADXL362":
        b.xfer([0x0A, 0x2D, 0x02])             # POWER_CTL: measurement mode
        return lambda: tuple(v * 0.001 for v in struct.unpack("<hhh", b.xfer([0x0B, 0x0E] + [0] * 6)[2:]))
    if name.startswith(("LIS3DH", "LIS3DSH", "LIS2DW")):
        b.xfer([0x20, 0x57])                   # CTRL_REG1: 100 Hz, X/Y/Z on
        b.xfer([0x23, 0x88])                   # CTRL_REG4: block update, high resolution, +-2 g
        return lambda: tuple((v >> 4) * 0.001 for v in struct.unpack("<hhh", b.xfer([0xE8] + [0] * 6)[1:]))
    if name.startswith("MPU"):
        b.xfer([0x6B, 0x00])                   # PWR_MGMT_1: wake up
        time.sleep(0.05)
        return lambda: tuple(v / 16384 for v in struct.unpack(">hhh", b.xfer([0xBB] + [0] * 6)[1:]))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="CP2105 Standard port (default: auto)")
    ap.add_argument("--seconds", type=float, default=10)
    a = ap.parse_args()
    b = Bridge(a.port or find_fpga_uart())
    name, chip_id = identify(b)
    print(f"accelerometer: {name} (ID 0x{chip_id:02X})")
    read = setup_and_reader(b, name)
    if not read:
        print("identified, but no reader implemented for this part yet")
        return
    time.sleep(0.1)
    end = time.time() + a.seconds
    while time.time() < end:
        x, y, z = read()
        print(f"  x={x:+.2f} g  y={y:+.2f} g  z={z:+.2f} g   |g|={(x*x + y*y + z*z) ** 0.5:.2f}")
        time.sleep(0.25)


if __name__ == "__main__":
    main()
