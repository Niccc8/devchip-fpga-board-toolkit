"""Board pin database (board/pins.csv) and constraint generation."""
import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINS_CSV = os.path.join(ROOT, "board", "pins.csv")

# Configuration-function pins that need a "release as GPIO" option.
# Keys are names from the 'special' column (Apicula chip database).
RELEASE_FLAGS = {
    "SSPI_CS_N": "sspi", "SCLK": "sspi", "SI": "sspi", "SO": "sspi",
    "READY": "ready",
    "RECONFIG_N": "reconfign",
    "DONE": "done",
}
# Pins that must never be used by user logic on this board.
FORBIDDEN_SPECIAL = {"TCK", "TMS", "TDI", "TDO",          # JTAG: programming path
                     "MCLK", "MCS_N", "MI", "MO"}         # boot-flash SPI


class Pin:
    def __init__(self, row):
        self.location = row["location"]
        self.ball = row["ball"]
        self.gowin_io = row["gowin_io"]
        self.direction = row["direction"]      # in / out / io (from the board's point of view of the FPGA)
        self.group = row["group"]
        self.active = row["active"]
        self.pull = row["pull"]
        self.vccio = row["vccio"]
        self.special = row["special"].split() if row["special"] else []
        self.notes = row["notes"]

    def release_flags(self):
        return {RELEASE_FLAGS[s] for s in self.special if s in RELEASE_FLAGS}

    def forbidden(self):
        return [s for s in self.special if s in FORBIDDEN_SPECIAL]


def load_pins(path=PINS_CSV):
    with open(path, newline="", encoding="utf-8") as f:
        pins = [Pin(r) for r in csv.DictReader(f)]
    names = [p.location for p in pins]
    balls = [p.ball for p in pins]
    if len(set(names)) != len(names) or len(set(balls)) != len(balls):
        raise ValueError(f"{path}: duplicate location or ball")
    return {p.location: p for p in pins}


def resolve_bit(pins, port, index=None):
    """Map an HDL port (or one bit of a bus port) to a board pin.
    Scalar 'led0' -> led0. Bus 'led[3]' -> led3; 'pmod0[2]' -> pmod0_2."""
    if index is None:
        return pins.get(port)
    for cand in (f"{port}{index}", f"{port}_{index}"):
        if cand in pins:
            return pins[cand]
    return None


def cst_lines(name, pin):
    out = [f'IO_LOC  "{name}" {pin.ball};']
    attrs = []
    if pin.pull:
        attrs.append(f"PULL_MODE={pin.pull}")
    if attrs:
        out.append(f'IO_PORT "{name}" {" ".join(attrs)};')
    return out


def full_cst(pins):
    """Constraint file with every board location (for reference / other tools)."""
    lines = [
        "// DevChipBoard v2.2 + Sipeed Tang Primer 20K (GW2A-LV18PG256C8/I7)",
        "// GENERATED from board/pins.csv by `python devchip.py gen` - do not edit.",
        "// Port names = ChipInventor location names. Inputs/outputs: see pins.csv.",
        "// Balls E8 E9 T2 T3 T4 (s0 s1 c6 e6 e7) are on a 1.5 V bank.",
    ]
    for p in pins.values():
        lines += [ln + f"   // {p.direction} {p.group} {' '.join(p.special)}".rstrip()
                  if ln.startswith("IO_LOC") else ln for ln in cst_lines(p.location, p)]
    return "\n".join(lines) + "\n"


def pinout_md(pins):
    rows = ["| Location | Ball | Dir | Active | Pull | VCCIO | Config function | Notes |",
            "|---|---|---|---|---|---|---|---|"]
    for p in pins.values():
        rows.append(f"| `{p.location}` | {p.ball} | {p.direction} | {p.active or '-'} | "
                    f"{p.pull or '-'} | {p.vccio} V | {' '.join(p.special) or '-'} | {p.notes} |")
    head = ("# DevChipBoard v2.2 pinout\n\n"
            "Generated from [`board/pins.csv`](../board/pins.csv) by `python devchip.py gen`.\n"
            "Location names are the ones ChipInventor's *Associate Pins* dialog uses, so\n"
            "designs and constraints are interchangeable with the website.\n\n"
            "- **Dir** is from the FPGA's point of view. `in` pins are driven by the board:\n"
            "  never drive them from your design (devchip.py refuses to build that).\n"
            "- **VCCIO 1.5 V** pins (E8, E9, T2, T3, T4) are on a 1.5 V bank according to\n"
            "  Sipeed's reference constraints. Do not connect 3.3 V or 5 V signals to header\n"
            "  pins `c6`, `e6`, `e7`.\n"
            "- **Config function** pins are released as normal I/O automatically, only\n"
            "  when your design uses them.\n"
            "- The 2x20 header also carries GND, 3.3 V and **5 V** supply pins (see the board\n"
            "  image in the README). Never connect a supply pin to a signal pin.\n"
            "- Hardware checks: on-board I/O, both UART directions and the accelerometer (SPI ID\n"
            "  register) were exercised directly. The 48 PMOD/header pins were checked to be\n"
            "  free and responsive with pull-up/pull-down read-back; their connector positions\n"
            "  follow ChipInventor's own mapping. To confirm a position yourself, run\n"
            "  examples/pin_tester and touch the pin with a wire from GND.\n\n")
    bus = ("\n## Bus ports\n\nA bus port is split into board locations automatically:\n"
           "`led[7:0]` -> `led0`..`led7`, `s[7:0]`, `b[7:0]`, `c[7:0]`..`f[7:0]`,\n"
           "`pmod0[7:0]` -> `pmod0_0`..`pmod0_7`. 7-segment pins are scalar\n"
           "(`disp_a`..`disp_g`, `disp_dp`, `disp_1`..`disp_4`).\n")
    return head + "\n".join(rows) + "\n" + bus
