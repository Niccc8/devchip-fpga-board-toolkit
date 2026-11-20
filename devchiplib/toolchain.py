"""Open-source build flow (Yosys -> nextpnr-himbaechel -> gowin_pack) with
board-safety checks and a build report. Mirrors what ChipInventor's cloud runs."""
import json
import os
import re
import shutil
import subprocess
import time

from . import board
from .bitstream import check_fs, read_fs

DEVICE = "GW2A-LV18PG256C8/I7"
FAMILY = "GW2A-18C"
BOARD_CLOCK_MHZ = 27.0
TOOLS = ("yosys", "nextpnr-himbaechel", "gowin_pack")

# I/O attributes a user constraint file may set (locations always come from board/pins.csv)
USER_ATTRS = {
    "PULL_MODE": {"UP", "DOWN", "NONE", "KEEPER"},
    "DRIVE": {"4", "8", "12", "16", "24"},
    "OPEN_DRAIN": {"ON", "OFF"},
    "HYSTERESIS": {"NONE", "H2L", "L2H", "HIGH"},
    "IO_TYPE": {"LVCMOS33", "LVCMOS25", "LVCMOS18", "LVCMOS15", "LVCMOS12", "LVTTL33",
                "LVDS25", "LVDS25E", "SSTL15", "SSTL18_I", "SSTL25_I", "SSTL33_I"},
    "SLEW_RATE": {"SLOW", "FAST"},
}


class BuildError(Exception):
    pass


# ----------------------------------------------------------------------------- tools
def tool_env(oss=None):
    """Return (env, {tool: full path}). Uses --oss, else $OSS_CAD_SUITE, else PATH."""
    env = os.environ.copy()
    oss = oss or env.get("OSS_CAD_SUITE")
    if oss:
        if not os.path.isdir(oss):
            raise BuildError(f"OSS CAD Suite directory not found: {oss}")
        extra = [os.path.join(oss, "bin"), os.path.join(oss, "lib")]
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    found = {t: shutil.which(t, path=env["PATH"]) for t in TOOLS}
    missing = [t for t, p in found.items() if not p]
    if missing:
        raise BuildError(
            "Missing tools: " + ", ".join(missing) + ".\nInstall OSS CAD Suite "
            "(https://github.com/YosysHQ/oss-cad-suite-build/releases), then set "
            "OSS_CAD_SUITE=<install dir> or pass --oss <install dir>.")
    return env, found


def tool_versions(oss=None):
    env, exe = tool_env(oss)
    out = {}
    for name, args in (("yosys", ["-V"]), ("nextpnr-himbaechel", ["--version"])):
        try:
            r = subprocess.run([exe[name]] + args, env=env, capture_output=True, text=True, timeout=60)
            out[name] = (r.stdout or r.stderr).strip().splitlines()[0]
        except Exception as e:                       # noqa: BLE001 - report, don't crash
            out[name] = f"error: {e}"
    out["gowin_pack"] = exe["gowin_pack"]
    return out


def _run(cmd, env, log_path):
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    with open(log_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if proc.returncode != 0:
        errors = [ln for ln in text.splitlines() if re.search(r"\b(ERROR|Error)\b", ln)]
        tail = "\n".join((errors or text.splitlines())[-20:])
        raise BuildError(f"{os.path.basename(cmd[0])} failed (exit {proc.returncode}). "
                         f"Full log: {log_path}\n{tail}")
    return text


# ----------------------------------------------------------------------------- ports / pins
def _top_ports(syn_json, top):
    with open(syn_json, encoding="utf-8") as f:
        mods = json.load(f)["modules"]
    if top not in mods:
        raise BuildError(f"top module '{top}' not found (have: {', '.join(sorted(mods))})")
    return [(name, p["direction"], len(p["bits"]), p.get("offset", 0), p.get("upto", 0))
            for name, p in mods[top]["ports"].items()]


def map_ports(ports, pins, internal=None):
    """Return (cst_lines, release_flags, notes, used{location: port}) or raise
    BuildError listing every problem. `internal` maps extra port names to balls
    for the tool's own designs only (not reachable from the command line)."""
    errors, notes, cst, used, flags = [], [], [], {}, set()
    internal = internal or {}
    for name, direction, width, offset, upto in ports:
        if name in internal and width == 1:
            cst.append(f'IO_LOC  "{name}" {internal[name]};')
            continue
        if upto and width > 1:
            errors.append(f"port '{name}' uses an ascending range ([lo:hi]); declare it as [hi:lo]")
            continue
        for i in range(width):
            if width == 1:
                pin, label = pins.get(name), name
            else:
                idx = offset + i                    # yosys lists bits LSB first
                pin, label = board.resolve_bit(pins, name, idx), f"{name}[{idx}]"
            if pin is None:
                errors.append(f"port '{label}' does not match any board location "
                              "(see docs/PINOUT.md or `python devchip.py pins`)")
                continue
            if pin.location in used:
                errors.append(f"board pin {pin.location} used twice ('{used[pin.location]}' and '{label}')")
                continue
            used[pin.location] = label
            if pin.forbidden():
                errors.append(f"{label} -> {pin.location} is a reserved pin ({', '.join(pin.forbidden())})")
            if pin.direction == "in" and direction in ("output", "inout"):
                errors.append(
                    f"'{label}' is an {direction}, but {pin.location} ({pin.group}) is driven by the "
                    "board. Driving it could short the FPGA pin against the board; make it an input.")
            if pin.direction == "out" and direction == "input":
                notes.append(f"'{label}' reads {pin.location}, which is a board output ({pin.group}).")
            if pin.vccio == "1.5" and pin.group in ("header", "pmod"):
                notes.append(f"'{label}' -> {pin.location} (ball {pin.ball}) is on a 1.5 V bank: "
                             "never connect 3.3 V / 5 V signals to it.")
            for fl in sorted(pin.release_flags()):
                flags.add(fl)
                notes.append(f"{pin.location} doubles as config pin ({' '.join(pin.special)}); "
                             f"released as GPIO ({fl}).")
            cst += board.cst_lines(label, pin)
    if errors:
        raise BuildError("Pin check failed, nothing was built:\n  - " + "\n  - ".join(errors))
    return cst, flags, notes, used


def parse_user_cst(path, port_bits):
    """Validate a user constraint file: only IO_PORT attribute lines for ports
    that exist. Returns {port_bit: {attr: value}}."""
    attrs = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, raw in enumerate(f, 1):
            line = raw.split("//", 1)[0].strip()
            if not line:
                continue
            m = re.fullmatch(r'IO_PORT\s+"([^"]+)"\s+(.*?);?', line)
            if not m:
                raise BuildError(f"{path}:{n}: only IO_PORT lines are allowed (pin locations come "
                                 f"from board/pins.csv): {raw.strip()}")
            port = m.group(1)
            if port not in port_bits:
                raise BuildError(f"{path}:{n}: '{port}' is not a port bit of this design")
            for kv in m.group(2).split():
                if "=" not in kv:
                    raise BuildError(f"{path}:{n}: bad attribute '{kv}'")
                k, v = kv.split("=", 1)
                k, v = k.upper(), v.upper()
                if k not in USER_ATTRS:
                    raise BuildError(f"{path}:{n}: attribute {k} is not allowed "
                                     f"(allowed: {', '.join(sorted(USER_ATTRS))})")
                if v not in USER_ATTRS[k]:
                    raise BuildError(f"{path}:{n}: {k}={v} is not allowed "
                                     f"({k} may be {', '.join(sorted(USER_ATTRS[k]))})")
                attrs.setdefault(port, {})[k] = v
    return attrs


def merge_cst(cst_lines, user_attrs):
    """Combine generated IO_LOC/IO_PORT lines with user attributes (user wins)."""
    gen = {}
    locs = []
    for ln in cst_lines:
        m = re.match(r'IO_PORT\s+"([^"]+)"\s+(.*);', ln)
        if m:
            gen[m.group(1)] = dict(kv.split("=", 1) for kv in m.group(2).split())
        else:
            locs.append(ln)
    for port, a in user_attrs.items():
        gen.setdefault(port, {}).update(a)
    ports = [f'IO_PORT "{p}" ' + " ".join(f"{k}={v}" for k, v in a.items()) + ";"
             for p, a in gen.items() if a]
    return locs + ports


# ----------------------------------------------------------------------------- reports
def parse_utilisation(text):
    res = {}
    for m in re.finditer(r"Info:\s+(\w+):\s+(\d+)/\s*(\d+)\s+(\d+)%", text):
        res[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return res


def parse_fmax(text):
    """Last reported Fmax per clock: {clock: (mhz, target_mhz, ok)}."""
    out = {}
    for m in re.finditer(r"Max frequency for clock\s+'([^']+)':\s+([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)", text):
        out[m.group(1)] = (float(m.group(2)), float(m.group(4)), m.group(3) == "PASS")
    return out


def _count(pattern, text):
    return len(re.findall(pattern, text, flags=re.MULTILINE))


SHOW = ["LUT4", "DFF", "ALU", "MUX2_LUT5", "RAM16SDP4", "BSRAM", "MULT18X18", "MULT9X9",
        "MULTALU18X18", "ALU54D", "rPLL", "IOB", "IOLOGICI", "IOLOGICO", "BUFG", "OSC"]


def write_report(path, info):
    lines = ["devchip build report", "=" * 60]
    for k in ("top", "sources", "device", "duration"):
        lines.append(f"{k:<10}: {info[k]}")
    lines += ["", "Resources", "-" * 60]
    for k in SHOW:
        if k in info["util"] and (info["util"][k][0] or k in ("LUT4", "DFF", "IOB")):
            u, t = info["util"][k]
            lines.append(f"  {k:<14} {u:>7} / {t:<7} {100.0 * u / t:5.1f} %")
    lines += ["", "Timing", "-" * 60]
    if info["fmax"]:
        for clk, (mhz, tgt, ok) in info["fmax"].items():
            lines.append(f"  {clk:<40} {mhz:8.2f} MHz  (target {tgt:.2f})  {'PASS' if ok else 'FAIL'}")
    else:
        lines.append("  no clocked logic")
    lines += ["", "Diagnostics", "-" * 60,
              f"  yosys warnings   : {info['yosys_warnings']}",
              f"  latches inferred : {info['latches']}",
              f"  nextpnr warnings : {info['pnr_warnings']}"]
    lines += ["", "Pins", "-" * 60] + [f"  {p:<12} <- {loc}" for loc, p in sorted(info["used"].items(), key=lambda x: x[1])]
    if info["notes"]:
        lines += ["", "Notes", "-" * 60] + [f"  - {n}" for n in info["notes"]]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return lines


# ----------------------------------------------------------------------------- build
_UNSAFE = re.compile(r'["\r\n;]')                 # would break / extend the Yosys command line
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_DEFINE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(=[A-Za-z0-9_.+\-']*)?")


def build(sources, outdir, top="top", oss=None, log=print, defines=(), includes=(),
          user_cst=None, freq=BOARD_CLOCK_MHZ, seed=None, _internal=None, _flags=()):
    t0 = time.time()
    # ---- validate everything before starting any tool ----
    if not _IDENT.fullmatch(top):
        raise BuildError(f"invalid top module name: {top!r}")
    if not sources:
        raise BuildError("no source files given")
    for p in list(sources) + list(includes) + [outdir] + ([user_cst] if user_cst else []):
        if _UNSAFE.search(p):
            raise BuildError(f"path contains a character the build cannot handle (\" ; newline): {p!r}")
    for d in defines:
        if not _DEFINE.fullmatch(d):
            raise BuildError(f"invalid define: {d!r} (use NAME or NAME=VALUE)")
    for s in sources:
        if not os.path.isfile(s):
            raise BuildError(f"source not found: {s}")
    for i in includes:
        if not os.path.isdir(i):
            raise BuildError(f"include directory not found: {i}")
    if user_cst and not os.path.isfile(user_cst):
        raise BuildError(f"constraint file not found: {user_cst}")
    if not (1.0 <= float(freq) <= 500.0):
        raise BuildError(f"--freq {freq} MHz is outside 1..500")

    env, exe = tool_env(oss)
    pins = board.load_pins()
    os.makedirs(outdir, exist_ok=True)
    paths = {k: os.path.join(outdir, v) for k, v in (
        ("syn", "syn.json"), ("pnr", "pnr.json"), ("cst", "board.cst"), ("fs", "pack.fs"),
        ("report", "report.txt"))}
    for p in paths.values():                         # never load or read a leftover file
        if os.path.exists(p):
            os.remove(p)

    # ---- 1. synthesis ----
    opts = "".join(f" -D{d}" for d in defines) + "".join(f' -I"{i}"' for i in includes)
    reads = "; ".join(f'read_verilog{" -sv" if s.endswith(".sv") else ""}{opts} "{s}"' for s in sources)
    log("[1/4] yosys: synthesis")
    ytext = _run([exe["yosys"], "-p", f"{reads}; synth_gowin -noalu -top {top} -json \"{paths['syn']}\""],
                 env, os.path.join(outdir, "yosys.log"))
    latches = _count(r"Latch inferred for signal", ytext)
    if latches:
        log(f"      WARNING: {latches} latch(es) inferred (incomplete if/case in combinational logic)")

    # ---- 2. pins ----
    log("[2/4] pin safety check")
    ports = _top_ports(paths["syn"], top)
    cst, flags, notes, used = map_ports(ports, pins, _internal)
    flags |= set(_flags)
    if "jtag" in flags:
        raise BuildError("refusing to release the JTAG pins")
    if user_cst:
        bits = {n if w == 1 else f"{n}[{off + i}]" for n, _, w, off, _ in ports for i in range(w)}
        cst = merge_cst(cst, parse_user_cst(user_cst, bits))
    for n in notes:
        log(f"      note: {n}")
    with open(paths["cst"], "w", encoding="utf-8") as f:
        f.write("// generated by devchip.py for this build\n" + "\n".join(cst) + "\n")

    # ---- 3. place and route ----
    log("[3/4] nextpnr: place and route")
    pnr_cmd = [exe["nextpnr-himbaechel"], "--json", paths["syn"], "--write", paths["pnr"],
               "--device", DEVICE, "--vopt", f"family={FAMILY}", "--vopt", f"cst={paths['cst']}",
               "--freq", str(freq)]
    if seed is not None:
        pnr_cmd += ["--seed", str(int(seed))]
    if "sspi" in flags:
        pnr_cmd += ["--vopt", "sspi_as_gpio"]
    ptext = _run(pnr_cmd, env, os.path.join(outdir, "nextpnr.log"))
    fmax = parse_fmax(ptext)
    for clk, (mhz, tgt, ok) in fmax.items():
        if not ok:
            log(f"      WARNING: clock {clk} reaches only {mhz:.1f} MHz (target {tgt:.1f} MHz); "
                "the design may misbehave in hardware")

    # ---- 4. bitstream ----
    log("[4/4] gowin_pack: bitstream")
    pack_cmd = [exe["gowin_pack"], "-d", FAMILY, "-o", paths["fs"]]
    pack_cmd += [f"--{fl}_as_gpio" for fl in sorted(flags)]
    _run(pack_cmd + [paths["pnr"]], env, os.path.join(outdir, "gowin_pack.log"))
    check_fs(read_fs(paths["fs"]))

    info = {"top": top, "sources": " ".join(os.path.basename(s) for s in sources),
            "device": DEVICE, "duration": f"{time.time() - t0:.1f} s",
            "util": parse_utilisation(ptext), "fmax": fmax, "used": used, "notes": notes,
            "latches": latches, "yosys_warnings": _count(r"^Warning:", ytext),
            "pnr_warnings": _count(r"^Warning:", ptext)}
    report = write_report(paths["report"], info)
    summary = [ln for ln in report if ln.startswith("  ") and ("%" in ln or "MHz" in ln)]
    for ln in summary:
        log("     " + ln)
    log(f"      ok: {paths['fs']}  (report: {paths['report']})")
    return paths["fs"]
