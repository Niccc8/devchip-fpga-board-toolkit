# From subscription to self-hosted: how this was figured out

This is the end-to-end record of how the ChipInventor DevChipBoard v2.2 was made
usable without the ChipInventor platform. It covers each step, what it showed,
and the dead ends, because they explain *why* the tool works the way it does.
All work was done on Windows 11 with the board connected over a normal USB cable.

**Contents**
1. [Starting point](#1-starting-point)
2. [Identify the hardware](#2-identify-the-hardware)
3. [Listen to the serial ports: silence](#3-listen-to-the-serial-ports-silence)
4. [Watch the website program the board](#4-watch-the-website-program-the-board)
5. [Download the design archive](#5-download-the-design-archive)
6. [Rebuild locally, translate pin names](#6-rebuild-locally-translate-pin-names)
7. [The full pin map in one pass](#7-the-full-pin-map-in-one-pass)
8. [The ChipLoader protocol](#8-the-chiploader-protocol)
9. [First local flash: the wrong cable](#9-first-local-flash-the-wrong-cable)
10. [Verify every peripheral](#10-verify-every-peripheral)
11. [The boot flash: backup, write, restore](#11-the-boot-flash-backup-write-restore)
12. [Clocks: PLL generation](#12-clocks-pll-generation)
13. [From scripts to a tool](#13-from-scripts-to-a-tool)
14. [Lessons](#lessons)

---

## 1. Starting point
- **The hardware:** a DevChipBoard v2.2 carrier with a removable **Sipeed Tang
  Primer 20K** module (Gowin GW2A-LV18PG256C8/I7), won together with a one-year
  subscription to ChipInventor's cloud EDA platform.
- **The question:** can the board still be used when the subscription ends?
- **The problem:** the board's schematic and programming method are not published.

## 2. Identify the hardware
- **The module.** Photos identified the module as a Tang Primer 20K. Sipeed documents
  its 27 MHz oscillator on ball H11, its DDR3 and its SPI flash.
- **The USB chip.** Windows saw an unknown USB device `10C4:EA70`, which is a
  **Silicon Labs CP2105** dual USB-UART.
  - The CP2105 cannot do JTAG.
  - So *something else* on the carrier must program the FPGA.
- **The driver.** With the CP210x driver installed, two ports appeared:
  *Enhanced COM Port* (COM3) and *Standard COM Port* (COM4).

## 3. Listen to the serial ports: silence
- We listened passively on both ports at many baud rates, and sent newlines.
  We got **zero bytes**, including in a 10-minute recording across power cycles
  while every switch and button was pressed.
- **The factory demo** in flash runs anyway: **B0** counts a `MM.SS` timer up on
  the 7-segment display, and **B1** counts it down. It simply doesn't use the UART.

**Conclusion:** whatever programs the board only speaks when spoken to in its own protocol.

## 4. Watch the website program the board
ChipInventor's *Prototype* page uses the browser's **Web Serial** API.
- Connecting to the **Enhanced** port prints `ChipLoader is Ready`. The Standard
  port prints `FPGA not found`.
- The flash log shows **Linux shell commands** (`cat /tmp/pack.fs.gz >> …`, `mv …`),
  then openFPGALoader output. So there is a small **Linux computer** on the
  carrier that receives a gzipped Gowin bitstream (`pack.fs`) and runs
  openFPGALoader.

Two pitfalls on the website:
1. **An ASIC project has no FPGA bitstream.** Uploading one fails with `Transfer Failed`.
2. **Use 1-bit ports in *Associate Pins*.** A bus such as `sw[7:0]` is mapped as a
   whole to a single location, and place and route fails (`Unconstrained IO`).

With Input Pin `sw0` mapped to `s0` and Output pin `ld0` mapped to `led0`, the
first flash worked: S0 switched LED0.

## 5. Download the design archive
The project download (`.tar.gz`) contains:
- **`hdl.v`:** the block diagram as Verilog. The wrapper module is always named `top`.
- **`pinData/fpga_*.cst`:** the pin constraints, using **Gowin internal pad names**
  (`IOL45B`) instead of ball names.
- **`text.txt`:** despite the name, the **gzipped bitstream**.
- **Logs.** They show the cloud runs **Yosys** (`synth_gowin -noalu -top top`),
  then **nextpnr-himbaechel** for `GW2A-LV18PG256C8/I7`, then gowin_pack.

The cloud uses the open-source flow that anyone can install.

## 6. Rebuild locally, translate pin names
- **Rebuilding:** with OSS CAD Suite, the same `hdl.v` and `.cst` produce a valid
  bitstream with the same structure. It isn't byte-identical, because the tool
  versions are newer.
- **Translating pad names:** Apicula's chip database maps Gowin pad names to balls
  (`IOL45B` is **E8**, `IOT54A` is **P15**). Constraints written with ball names
  give exactly the same bitstream as constraints written with pad names, which
  confirms the translation.

## 7. The full pin map in one pass
To read the whole map at once:
1. Write [tools/pinmap/map_all.v](../tools/pinmap/map_all.v): a module with 93
   *input* ports, one per location name. Inputs-only means nothing can be driven.
2. Import it as a custom block, with an Input Pin per port.
3. Map each port to the same-named location, then **Save**.
4. Download the archive. Its `.cst` is the complete pin map.

**Pitfall:** the first attempt named the module `top`. The website's wrapper is
also `top`, so the design contained itself and **Yosys crashed** while working
out the hierarchy. Any other module name works.

**Sanity checks:**
- No duplicate pins.
- `clk` landed on **H11**, the module's oscillator.
- Related signals sit on A/B pad pairs.
- Both PMOD connectors follow the same pattern.

**Findings:**
- **The UART is on N8/L9.**
- **Some pins double as configuration pins:** `acc_miso` is on RECONFIG_N,
  `acc_cs` on READY, and a few header/PMOD pins on the slave-SPI pins. These
  need "use as GPIO" options in the bitstream.
- **Five balls are on a 1.5 V bank:** `s0`, `s1`, and header `c6`, `e6`, `e7`.

[tools/cloudcst_to_pins.py](../tools/cloudcst_to_pins.py) turns the `.cst` into
[board/pins.csv](../board/pins.csv).

## 8. The ChipLoader protocol
- Plain text sent to COM3, at any baud rate, got no reply.
- The browser's developer tools (search for `ChipLoader`) led to the page's
  publicly served script. It describes the protocol:
  - **115200 baud with KISS framing**
  - channels for control, file data, output and a shell
  - the `HOST_QUERY`, `TRANSFER_*`, `CHECKSUM` and `FLASH_*` messages
  - chunked uploads

  See [PROTOCOL.md](PROTOCOL.md).
- **The handshake works:** sending a KISS-framed `HOST_QUERY` returned
  `DEVICE_VERSION 1000`.
- **ChipLoader's environment:** read-only commands showed Buildroot Linux on an
  ARM926, `openFPGALoader v0.11.0`, and a 28 MB `/tmp`.
- **Uploads are verified:** an upload's MD5 matched the local file.

## 9. First local flash: the wrong cable
- **First try:** the script's "Tang Primer 20K" preset is
  `-c libgpiod --pins 106:104:105:103`. It failed with *"no device found"*.
- **The clue:** `lsusb` on ChipLoader listed `1209:c0ca`, a **DirtyJTAG** adapter.
  JTAG on this board goes through that adapter.
- **The fix:** with **`-c dirtyJtag -m`**, a locally built bitstream loaded and
  openFPGALoader exited with 0. The board was now programmable from a laptop.

This also explained a failed website flash, *"No cable or board specified"*:
the page had run openFPGALoader without a cable argument.

## 10. Verify every peripheral
| Peripheral | How it was verified |
|---|---|
| Switches, LEDs, buttons, 7-segment, buzzer | [selftest](../examples/selftest/selftest.v), checked by eye. All active-high. |
| `uart_tx` | The self-test banner arrived on **COM4 (Standard port)**. That also confirms the 27 MHz clock. |
| `uart_rx` | Thousands of command bytes reached the flash reader correctly at 921,600 baud (section 11) |
| PIR | [pir_monitor](../examples/pir_monitor/pir_monitor.v) logged 20 transitions in 3 minutes. Each low period was 3.4–4.3 s, the sensor's lockout time. "Always on" just meant it kept seeing people nearby. |
| Accelerometer (4 pins) | [UART-to-SPI bridge](../examples/accelerometer/). The ID register read **0x33**, which makes it an **ST LIS3DH** (or the compatible LIS2DH12). It reads +1.0 g on Z when lying flat. |
| 48 PMOD/header pins | [pin_tester](../examples/pin_tester/): with pull-ups **48/48 read 1**. With pull-downs **44/48 read 0**; the other four (`d5`, `d7`, `f6`, `f7`) are weakly pulled high on the carrier (see section 13). A pin wired to anything else on the board would fail one of the two. Connector positions follow ChipInventor's mapping; touching a pin with a GND wire while `pin_tester.py` runs names it, for anyone who wants to confirm a position. |

## 11. The boot flash: backup, write, restore
- **openFPGALoader 0.11 can't read Gowin flash** (*"dump flash not supported"*).
  A backup needed another route.
- **The flash pins.** Apicula lists the GW2A's configuration flash pins: MCLK L10,
  MCS_N M9, MI P10 and MO R10. No board peripheral uses them.
- **A read-only reader.** [flash_reader.v](../devchiplib/hdl/flash_reader.v) is loaded
  into SRAM and reads the flash directly.
  - It can only issue *read ID* (0x9F) and *read data* (0x03). Without
    *write enable* (0x06), a flash chip ignores every erase or write.
  - It streams the data over the Standard port at 921,600 baud, in 64 KiB blocks,
    each with a CRC-16. Simulated first against a model of the flash chip.
- **The chip:** JEDEC ID `0B 40 17`, an XTX part of **8 MB**. The factory image
  uses 888 KB of it.
- **The backup:** 8 MB at about 80 KiB/s, with every block CRC-checked. Reading the
  used region a second time matched exactly.
- **Persistent writes:** `openFPGALoader -c dirtyJtag -f` wrote the self-test, and
  the FPGA booted it from flash. Reading the flash back matched the bitstream byte
  for byte (577,178 bytes). openFPGALoader reported the same chip ID as our
  reader, which cross-checks both.
- **Restoring:** openFPGALoader 0.11 accepts a raw image for this chip only with
  `--external-flash -f --file-type bin`. Written that way, the factory image read
  back with an identical SHA-256, and `openFPGALoader -r` booted the timer demo again.

## 12. Clocks: PLL generation
- **The search:** `devchip.py pll` searches the Gowin rPLL's divider settings
  (IDIV, FBDIV, ODIV) for the requested frequency. It keeps the internal oscillator
  inside the datasheet range (500–1250 MHz) and the comparison frequency at 3 MHz
  or more.
- **The example:** [pll_demo](../examples/pll/pll_demo.v) runs at 135 MHz, and its
  UART baud divider is computed for 135 MHz. Readable text on the PC therefore
  proves the generated PLL runs at the requested frequency.

## 13. From scripts to a tool
The one-off scripts became `devchip.py`, modelled on how vendor FPGA tools behave:
- projects, defines and include paths
- per-build reports: utilization, timing, latches, warnings
- simulation
- PLL generation
- flash backup, verify and restore
- `doctor` for environment checks

Its safety rules:
- **Pin direction check:** never drive a pin the board drives.
- **Bitstream check:** the device ID must be the GW2A-18.
- **Verified uploads:** the MD5 must match, or nothing is programmed.
- **Confirmation before writing flash.**
- **Configuration pins** are released only when a design uses them.
- **JTAG is never released.**
- **Fixed commands only:** nothing typed by the user reaches ChipLoader's shell.

During testing, one problem appeared. A crash on the PC in the middle of an
upload left ChipLoader ignoring every message, and only unplugging the board
helped.
- **The cause:** controlled byte patterns showed that ChipLoader's frame parser
  keeps state across messages. A stray `0xC0`, or a message cut off halfway,
  leaves it out of step until it sees one more `0xC0`.
- **The fix:** the tool now detects an unanswered query and re-synchronises the
  board by itself.
- **The check:** uploads were killed halfway (`kill -9`), and the very next
  command connected normally every time.

The header test also found four pins that read 1 even with the FPGA's pull-down:
`d5`, `d7`, `f6` and `f7`. Three experiments narrowed it down:
1. **Not strongly driven:** pulling each low for 1 µs at 4 mA showed the FPGA
   overrides them easily.
2. **Weakly held:** once released, they rise slowly.
3. **Not the Lichee's UART lines:** sending bytes on them left the Lichee's UART
   counters unchanged.

They are weakly pulled high somewhere on the carrier, and are documented as such.

## Lessons
- **Cloud EDA platforms often wrap open-source tools.** Their logs and downloads
  tell you which ones.
- **A silent serial port may only need framing.** Read the client that normally
  talks to it.
- **Presets can be wrong for your board.** `lsusb` on the programmer showed the
  real JTAG path.
- **Map pins through the vendor's own tool, using inputs only,** instead of
  driving unknown pins.
- **Before any destructive test, build the backup and the verification first:**
  read back, compare, restore, compare again.
