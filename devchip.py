#!/usr/bin/env python3
"""devchip - build, simulate and program the ChipInventor DevChipBoard v2.2
(Sipeed Tang Primer 20K, Gowin GW2A-18C) from your own computer.

Typical use:
  python devchip.py run examples/blinky/blinky.v           build + load into SRAM
  python devchip.py new myproj && cd myproj && python ../devchip.py run
  python devchip.py doctor                                 check tools + board

SRAM loads are temporary (gone at power-off). --persistent writes the boot
flash; back it up first with `devchip.py flash backup`.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time

from devchiplib import __version__, board, flashtool, pll
from devchiplib.bitstream import BitstreamError, check_fs, read_fs, to_gzip
from devchiplib.chiploader import TESTED_VERSIONS, ChipLoader, ChipLoaderError
from devchiplib.toolchain import BOARD_CLOCK_MHZ, BuildError, build, tool_env, tool_versions

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_FILE = "devchip.json"


class CliError(Exception):
    pass


# ----------------------------------------------------------------------------- helpers
def say(msg=""):
    print(msg, flush=True)


def check_version(ver):
    if ver not in TESTED_VERSIONS:
        say(f"[!!] ChipLoader v{ver} has not been tested with this tool "
            f"(tested: {', '.join(sorted(TESTED_VERSIONS))}). Prefer SRAM loads until verified.")


def connect(port):
    cl = ChipLoader(port)
    ver = cl.query()
    say(f"[ok] ChipLoader v{ver} on {cl.port}")
    check_version(ver)
    return cl


def confirm(question, assume_yes):
    if assume_yes:
        return True
    try:
        return input(f"  {question} Type YES to continue: ").strip() == "YES"
    except EOFError:
        return False


def load_project(a):
    """Fill sources/top/defines/... from devchip.json when no sources were given."""
    if getattr(a, "sources", None):
        return a
    pdir = a.project or "."
    pfile = os.path.join(pdir, PROJECT_FILE)
    if not os.path.isfile(pfile):
        raise CliError(f"no source files given and no {PROJECT_FILE} in {os.path.abspath(pdir)}")
    with open(pfile, encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise CliError(f"{pfile}: {e}")
    rel = lambda p: os.path.normpath(os.path.join(pdir, p))   # noqa: E731
    a.sources = [rel(s) for s in cfg.get("sources", [])]
    if not a.sources:
        raise CliError(f"{pfile}: 'sources' is empty")
    a.top = a.top or cfg.get("top", "top")
    a.defines = (a.defines or []) + cfg.get("defines", [])
    a.includes = (a.includes or []) + [rel(i) for i in cfg.get("includes", [])]
    a.cst = a.cst or (rel(cfg["constraints"]) if cfg.get("constraints") else None)
    a.freq = a.freq or cfg.get("freq_mhz")
    if a.out == "build" and pdir != ".":
        a.out = os.path.join(pdir, "build")
    if hasattr(a, "tb") and not a.tb and cfg.get("testbench"):
        a.tb = rel(cfg["testbench"])
    say(f"[..] project {os.path.abspath(pfile)}")
    return a


def do_build(a):
    load_project(a)
    return build(a.sources, a.out, top=a.top or "top", oss=a.oss, log=say,
                 defines=a.defines or [], includes=a.includes or [], user_cst=a.cst,
                 freq=a.freq or BOARD_CLOCK_MHZ, seed=a.seed)


def do_load(a, fs_path):
    data = read_fs(fs_path)
    check_fs(data)                               # only GW2A-18 bitstreams
    if a.persistent and not confirm(
            "--persistent replaces the design the board boots at power-up "
            "(back it up first with `devchip.py flash backup`).", a.yes):
        say("aborted - nothing was sent to the board")
        return 1
    with connect(a.port) as cl:
        say(f"[..] uploading {len(to_gzip(data))} bytes")
        md5 = cl.transfer(to_gzip(data))
        say(f"[ok] upload verified (md5 {md5})")
        say(f"[..] programming {'SPI flash (persistent)' if a.persistent else 'SRAM (until power-off)'}")
        code = cl.program(persistent=a.persistent)
    say()
    if code != 0:
        say(f"[FAIL] openFPGALoader exit code {code} (see output above)")
        return 1
    if a.persistent and a.verify:
        say("[..] verifying flash contents")
        image = flashtool.fs_to_image(data)
        r = open_reader(a)
        try:
            got = read_with_progress(r, 0, len(image))
        finally:
            r.close()
        boot_from_flash(a)                       # run the freshly written design again
        if got != image:
            say("[FAIL] flash read-back differs from the bitstream")
            return 1
        say(f"[ok] flash verified ({len(image)} bytes) and FPGA restarted from flash")
    say("[ok] done")
    return 0


def open_reader(a):
    """Build (cached per build dir) and load the read-only flash reader; return a Reader."""
    out = os.path.join(getattr(a, "out", "build"), "flash_reader")
    fs = flashtool.build_reader(out, oss=getattr(a, "oss", None), log=lambda m: None)
    with ChipLoader(a.port, echo=False) as cl:
        cl.query()
        cl.transfer(to_gzip(read_fs(fs)))
        if cl.program() != 0:
            raise ChipLoaderError("could not load the flash reader")
    time.sleep(0.5)
    r = flashtool.Reader(a.uart_port or flashtool.find_fpga_uart())
    r.jedec()                                    # proves the reader is alive
    return r


def read_with_progress(r, start, length):
    t0 = time.time()

    def prog(done, total):
        rate = done / max(time.time() - t0, 1e-3) / 1024
        sys.stdout.write(f"\r      {done // 1024:>5} / {total // 1024} KiB  ({rate:.0f} KiB/s)")
        sys.stdout.flush()
    data = r.read(start, length, prog)
    say()
    return data


def boot_from_flash(a):
    with ChipLoader(a.port, echo=False) as cl:
        cl.query()
        return cl.reset_fpga()


# ----------------------------------------------------------------------------- commands
def cmd_new(a):
    d = a.name
    if os.path.exists(d):
        raise CliError(f"{d} already exists")
    os.makedirs(os.path.join(d, "src"))
    with open(os.path.join(d, "src", "top.v"), "w", encoding="utf-8") as f:
        f.write("""// top.v - port names are DevChipBoard locations (python devchip.py pins)
module top (
    input  wire       clk,        // 27 MHz
    input  wire [7:0] s,          // slide switches
    input  wire [7:0] b,          // push buttons
    output wire [7:0] led
);
    reg [24:0] count = 25'd0;
    always @(posedge clk) count <= count + 25'd1;
    assign led = s ^ {8{count[24] & b[0]}};   // switches on LEDs; hold B0 to blink them
endmodule
""")
    with open(os.path.join(d, PROJECT_FILE), "w", encoding="utf-8") as f:
        json.dump({"top": "top", "sources": ["src/top.v"], "defines": [], "includes": [],
                   "constraints": None, "freq_mhz": BOARD_CLOCK_MHZ, "testbench": None}, f, indent=2)
        f.write("\n")
    tool = os.path.join(ROOT, "devchip.py")
    rel = os.path.relpath(tool)
    say(f"created {d}/ (src/top.v, {PROJECT_FILE}). Build and load with:\n"
        f"  python {rel if rel.count('..') <= 2 else tool} run --project {d}")
    return 0


def cmd_build(a):
    do_build(a)
    return 0


def cmd_run(a):
    return do_load(a, do_build(a))


def cmd_load(a):
    return do_load(a, a.bitstream)


def cmd_sim(a):
    load_project(a)
    env, _ = tool_env(a.oss)
    iverilog = shutil.which("iverilog", path=env["PATH"])
    vvp = shutil.which("vvp", path=env["PATH"])
    if not iverilog or not vvp:
        raise CliError("iverilog/vvp not found (they ship with OSS CAD Suite)")
    files = ([a.tb] if a.tb else []) + list(a.sources)
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, "sim.vvp")
    cmd = [iverilog, "-g2012", "-o", out] + [f"-D{d}" for d in (a.defines or [])] + \
          [f"-I{i}" for i in (a.includes or [])] + files
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        return r.returncode
    return subprocess.run([vvp, "-n", out], env=env, cwd=a.out).returncode


def cmd_reset(a):
    with connect(a.port) as cl:
        code = cl.reset_fpga()
    say(f"[{'ok' if code == 0 else 'FAIL'}] FPGA reloaded from flash")
    return 0 if code == 0 else 1


def cmd_flash(a):
    if a.action in ("id", "backup"):
        if a.action == "backup" and os.path.exists(a.file) and not a.force:
            raise CliError(f"{a.file} exists (use --force to overwrite)")
        say("[..] loading the read-only flash reader into SRAM")
        r = open_reader(a)
        try:
            jid = r.jedec()
            vendor, size = flashtool.describe(jid)
            say(f"[ok] flash JEDEC ID {jid[0]:02X} {jid[1]:02X} {jid[2]:02X}: {vendor}, "
                f"{size // (1024 * 1024) if size else '?'} MiB")
            if a.action == "backup":
                size = a.size or size
                if not size:
                    raise CliError("unknown flash size; pass --size")
                say(f"[..] reading {size // 1024} KiB (CRC-checked blocks)")
                image = read_with_progress(r, 0, size)
                used = flashtool.used_length(image)
                say(f"[..] reading the used {used // 1024} KiB again to confirm")
                if read_with_progress(r, 0, used) != image[:used]:
                    raise CliError("the two reads disagree; backup NOT saved")
        finally:
            r.close()
        boot_from_flash(a)
        if a.action == "backup":
            meta = flashtool.save_backup(a.file, image, jid)
            say(f"[ok] saved {a.file} ({size} bytes, {meta['used']} in use, "
                f"sha256 {meta['sha256'][:16]}...) and {a.file}.json")
        say("[ok] the board runs its flash design again")
        return 0

    with open(a.file, "rb") as f:
        image = f.read()
    used = flashtool.used_length(image)
    if used == 0:
        raise CliError(f"{a.file} is empty or all 0xFF")
    if a.action == "verify":
        r = open_reader(a)
        try:
            got = read_with_progress(r, 0, used)
        finally:
            r.close()
        boot_from_flash(a)
        ok = got == image[:used]
        say(f"[{'ok' if ok else 'FAIL'}] flash {'matches' if ok else 'DIFFERS from'} {a.file} "
            f"({used} bytes compared)")
        return 0 if ok else 1

    if a.action == "restore":
        if not confirm(f"This rewrites the boot flash with {a.file} ({used} bytes).", a.yes):
            say("aborted - nothing was written")
            return 1
        with connect(a.port) as cl:
            say(f"[..] writing {used} bytes (takes about a minute)")
            code = flashtool.write_image(cl, image[:used])
        if code != 0:
            say(f"[FAIL] openFPGALoader exit code {code}")
            return 1
        say("[..] verifying")
        r = open_reader(a)
        try:
            ok = read_with_progress(r, 0, used) == image[:used]
        finally:
            r.close()
        boot_from_flash(a)
        say(f"[{'ok' if ok else 'FAIL'}] restore {'verified' if ok else 'VERIFY FAILED'}; "
            "the FPGA booted from flash")
        return 0 if ok else 1
    raise CliError(f"unknown flash action {a.action}")


def cmd_pll(a):
    p = pll.solve(a.mhz)
    name = a.name or f"pll_{str(round(p['out_mhz'], 3)).replace('.', 'p')}mhz"
    text = pll.wrapper(name, p)
    path = a.output or f"{name}.v"
    if os.path.exists(path) and not a.force:
        raise CliError(f"{path} exists (use --force)")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    err = (p["out_mhz"] - a.mhz) / a.mhz * 100
    say(f"wrote {path}: {p['out_mhz']:.6f} MHz ({err:+.3f} %), IDIV={p['IDIV_SEL']} "
        f"FBDIV={p['FBDIV_SEL']} ODIV={p['ODIV_SEL']}, VCO {p['vco_mhz']:.1f} MHz")
    say(f"build with --freq {p['out_mhz']:.3f} so timing is checked at the new clock")
    return 0


def cmd_pins(a):
    pins = board.load_pins()
    say(f"{'location':<10} {'ball':<5} {'dir':<4} {'group':<7} notes")
    for p in pins.values():
        say(f"{p.location:<10} {p.ball:<5} {p.direction:<4} {p.group:<7} {p.notes}")
    return 0


def cmd_gen(a):
    pins = board.load_pins()
    targets = {os.path.join(ROOT, "board", "devchipboard_v2.2.cst"): board.full_cst(pins),
               os.path.join(ROOT, "docs", "PINOUT.md"): board.pinout_md(pins)}
    for path, text in targets.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        say(f"wrote {os.path.relpath(path, ROOT)}")
    return 0


def cmd_info(a):
    with connect(a.port) as cl:
        say()
        cl.info()
    say()
    return 0


def cmd_doctor(a):
    ok = True
    say(f"devchip      {__version__}")
    say(f"python       {platform.python_version()} ({platform.system()} {platform.release()})")
    try:
        import serial
        say(f"pyserial     {serial.__version__}")
    except ImportError:
        say("pyserial     MISSING  ->  pip install -r requirements.txt")
        ok = False
    try:
        for k, v in tool_versions(a.oss).items():
            say(f"{k:<12} {v}")
    except BuildError as e:
        say(f"tools        MISSING  -> {e}")
        ok = False
    try:
        from serial.tools import list_ports
        ports = [p for p in list_ports.comports() if p.vid == 0x10C4 and p.pid == 0xEA70]
        for p in ports:
            say(f"port         {p.device}: {p.description}")
        if not ports:
            say("board        NOT FOUND (USB data cable? CP210x driver?)")
            ok = False
        else:
            with ChipLoader(a.port, echo=False) as cl:
                ver = cl.query()
                say(f"chiploader   v{ver} on {cl.port}")
                check_version(ver)
                det = cl.run_fixed("openFPGALoader -c dirtyJtag --detect > /dev/null 2>&1", timeout=30)
                say(f"jtag         {'GW2A-18C detected' if det == 0 else 'FPGA NOT detected'}")
                ok &= det == 0
            say(f"fpga uart    {flashtool.find_fpga_uart()}")
    except (ChipLoaderError, flashtool.FlashError) as e:
        say(f"board        ERROR: {e}")
        ok = False
    say("\n" + ("all good" if ok else "problems found (see above)"))
    return 0 if ok else 1


# ----------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="devchip", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"devchip {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    def common(p, port=True, tools=True):
        if port:
            p.add_argument("--port", help="ChipLoader port (default: auto-detect)")
            p.add_argument("--uart-port", help="FPGA UART port (default: auto-detect)")
        if tools:
            p.add_argument("--oss", help="OSS CAD Suite directory (or set OSS_CAD_SUITE)")
            p.add_argument("--out", default="build", help="build directory (default: build)")

    def design(p):
        p.add_argument("sources", nargs="*", help="Verilog files (default: from devchip.json)")
        p.add_argument("--project", help=f"directory containing {PROJECT_FILE}")
        p.add_argument("--top", help="top module (default: top)")
        p.add_argument("-D", dest="defines", action="append", metavar="NAME[=VAL]", help="Verilog define")
        p.add_argument("-I", dest="includes", action="append", metavar="DIR", help="include directory")
        p.add_argument("--cst", help="extra constraints: IO_PORT attributes only")
        p.add_argument("--freq", type=float, help=f"clock target in MHz (default {BOARD_CLOCK_MHZ:g})")
        p.add_argument("--seed", type=int, help="place-and-route seed")

    def loading(p):
        p.add_argument("--persistent", action="store_true", help="write the boot flash instead of SRAM")
        p.add_argument("--verify", action="store_true", help="with --persistent: read the flash back")
        p.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    p = sub.add_parser("new", help="create a project folder")
    p.add_argument("name")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("build", help="synthesize, check pins, place & route, pack")
    design(p); common(p, port=False)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("run", help="build, then load")
    design(p); common(p); loading(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("load", help="load a .fs bitstream")
    p.add_argument("bitstream")
    common(p); loading(p)
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("sim", help="simulate with Icarus Verilog")
    design(p); common(p, port=False)
    p.add_argument("--tb", help="testbench file (default: from devchip.json)")
    p.set_defaults(func=cmd_sim)

    p = sub.add_parser("reset", help="reload the FPGA from its flash (like power-up)")
    common(p, tools=False)
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("flash", help="boot flash: id | backup FILE | verify FILE | restore FILE")
    p.add_argument("action", choices=["id", "backup", "verify", "restore"])
    p.add_argument("file", nargs="?")
    p.add_argument("--size", type=int, help="bytes to back up (default: whole chip)")
    p.add_argument("--force", action="store_true", help="overwrite an existing backup file")
    p.add_argument("--yes", action="store_true")
    common(p)
    p.set_defaults(func=cmd_flash)

    p = sub.add_parser("pll", help="generate an rPLL wrapper for a frequency")
    p.add_argument("mhz", type=float)
    p.add_argument("--name")
    p.add_argument("-o", "--output")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_pll)

    sub.add_parser("pins", help="list board pin names").set_defaults(func=cmd_pins)
    sub.add_parser("gen", help="regenerate board/*.cst and docs/PINOUT.md").set_defaults(func=cmd_gen)

    p = sub.add_parser("info", help="ChipLoader diagnostics")
    common(p, tools=False)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("doctor", help="check Python, tools, drivers and board")
    common(p)
    p.set_defaults(func=cmd_doctor)

    a = ap.parse_args(argv)
    if a.cmd == "flash" and a.action != "id" and not a.file:
        ap.error(f"flash {a.action} needs a FILE")
    if getattr(a, "verify", False) and not getattr(a, "persistent", False):
        ap.error("--verify is only meaningful with --persistent")
    try:
        return a.func(a) or 0
    except (BuildError, ChipLoaderError, BitstreamError, flashtool.FlashError,
            pll.PllError, CliError, OSError) as e:
        sys.stdout.flush()
        print(f"\nerror: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        sys.stdout.flush()
        print("\ninterrupted. Running the command again is safe: SRAM loads can always be "
              "repeated, and an interrupted flash write is fixed by writing again "
              "(JTAG always stays available).", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
