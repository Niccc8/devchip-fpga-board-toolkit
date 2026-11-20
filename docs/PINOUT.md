# DevChipBoard v2.2 pinout

Generated from [`board/pins.csv`](../board/pins.csv) by `python devchip.py gen`.
Location names are the ones ChipInventor's *Associate Pins* dialog uses, so
designs and constraints are interchangeable with the website.

- **Dir** is from the FPGA's point of view. `in` pins are driven by the board:
  never drive them from your design (devchip.py refuses to build that).
- **VCCIO 1.5 V** pins (E8, E9, T2, T3, T4) are on a 1.5 V bank according to
  Sipeed's reference constraints. Do not connect 3.3 V or 5 V signals to header
  pins `c6`, `e6`, `e7`.
- **Config function** pins are released as normal I/O automatically, only
  when your design uses them.
- The 2x20 header also carries GND, 3.3 V and **5 V** supply pins (see the board
  image in the README). Never connect a supply pin to a signal pin.
- Hardware checks: on-board I/O, both UART directions and the accelerometer (SPI ID
  register) were exercised directly. The 48 PMOD/header pins were checked to be
  free and responsive with pull-up/pull-down read-back; their connector positions
  follow ChipInventor's own mapping. To confirm a position yourself, run
  examples/pin_tester and touch the pin with a wire from GND.

| Location | Ball | Dir | Active | Pull | VCCIO | Config function | Notes |
|---|---|---|---|---|---|---|---|
| `clk` | H11 | in | - | - | 3.3 V | GCLKT_0 | 27 MHz oscillator on the Tang Primer 20K module |
| `uart_rx` | N8 | in | - | - | 3.3 V | - | FPGA receives from PC (CP2105 Standard port) |
| `uart_tx` | L9 | out | - | - | 3.3 V | - | FPGA sends to PC (CP2105 Standard port) |
| `led0` | P15 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led1` | P16 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led2` | N15 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led3` | N16 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led4` | N14 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led5` | L16 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led6` | L14 | out | high | - | 3.3 V | - | LED on when driven 1 |
| `led7` | K15 | out | high | - | 3.3 V | GCLKC_1 | LED on when driven 1 |
| `s0` | E8 | in | high | DOWN | 1.5 V | LPLL2_C_IN | slide switch reads 1 when on |
| `s1` | E9 | in | high | DOWN | 1.5 V | - | slide switch reads 1 when on |
| `s2` | J11 | in | high | DOWN | 3.3 V | - | slide switch reads 1 when on |
| `s3` | L12 | in | high | DOWN | 3.3 V | - | slide switch reads 1 when on |
| `s4` | A9 | in | high | DOWN | 3.3 V | GCLKT_7 | slide switch reads 1 when on |
| `s5` | C9 | in | high | DOWN | 3.3 V | GCLKC_7 | slide switch reads 1 when on |
| `s6` | E14 | in | high | DOWN | 3.3 V | - | slide switch reads 1 when on |
| `s7` | D16 | in | high | DOWN | 3.3 V | - | slide switch reads 1 when on |
| `b0` | L13 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b1` | H15 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b2` | G16 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b3` | H14 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b4` | H16 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b5` | J15 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b6` | K16 | in | high | - | 3.3 V | - | push button reads 1 while pressed |
| `b7` | K14 | in | high | - | 3.3 V | GCLKT_1 | push button reads 1 while pressed |
| `disp_1` | K13 | out | high | - | 3.3 V | - | digit enable (1 = digit on); multiplex the 4 digits |
| `disp_2` | K12 | out | high | - | 3.3 V | - | digit enable (1 = digit on); multiplex the 4 digits |
| `disp_3` | K11 | out | high | - | 3.3 V | - | digit enable (1 = digit on); multiplex the 4 digits |
| `disp_4` | H13 | out | high | - | 3.3 V | - | digit enable (1 = digit on); multiplex the 4 digits |
| `disp_a` | P7 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_b` | L8 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_c` | D11 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_d` | E10 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_dp` | D10 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_e` | R7 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_f` | M6 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `disp_g` | F10 | out | high | - | 3.3 V | - | segment (1 = lit), shared by all 4 digits |
| `buzzer` | J12 | out | high | - | 3.3 V | - | drive a square wave (e.g. 2 kHz) for a tone |
| `pir` | R16 | in | high | DOWN | 3.3 V | - | PIR motion sensor; ~4 s lockout after each trigger |
| `acc_cs` | A13 | out | - | - | 3.3 V | READY | LIS3DH accelerometer chip select (active low), SPI mode 3 |
| `acc_miso` | B10 | in | - | - | 3.3 V | RECONFIG_N | LIS3DH SPI data out (ID register 0x0F reads 0x33) |
| `acc_mosi` | G11 | out | - | - | 3.3 V | - | LIS3DH SPI data in |
| `acc_sclk` | H12 | out | - | - | 3.3 V | - | LIS3DH SPI clock (idle high, mode 3) |
| `pmod0_0` | T9 | io | - | - | 3.3 V | DIN CLKHOLD_N | PMOD connector, free for user |
| `pmod0_1` | T8 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod0_2` | T7 | io | - | - | 3.3 V | GCLKT_3 | PMOD connector, free for user |
| `pmod0_3` | T6 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod0_4` | P8 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod0_5` | R8 | io | - | - | 3.3 V | GCLKC_3 | PMOD connector, free for user |
| `pmod0_6` | P6 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod0_7` | T10 | io | - | - | 3.3 V | SI D2 | PMOD connector, free for user |
| `pmod1_0` | R13 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_1` | R12 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_2` | R11 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_3` | P11 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_4` | P13 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_5` | T12 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_6` | T11 | io | - | - | 3.3 V | - | PMOD connector, free for user |
| `pmod1_7` | P9 | io | - | - | 3.3 V | DOUT WE_N | PMOD connector, free for user |
| `c0` | A14 | io | - | - | 3.3 V | LPLL1_C_FB | 2x20 header, free for user |
| `c1` | C12 | io | - | - | 3.3 V | LPLL1_T_IN | 2x20 header, free for user |
| `c2` | A12 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `c3` | B11 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `c4` | C10 | io | - | - | 3.3 V | SCLK | 2x20 header, free for user |
| `c5` | D7 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `c6` | T3 | io | - | - | 1.5 V | - | 2x20 header, free for user |
| `c7` | T5 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `d0` | N7 | io | - | - | 3.3 V | RPLL2_C_FB | 2x20 header, free for user |
| `d1` | R9 | io | - | - | 3.3 V | FASTRD_N D3 | 2x20 header, free for user |
| `d2` | E15 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `d3` | A15 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `d4` | G15 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `d5` | J14 | io | - | - | 3.3 V | - | 2x20 header, free for user; weakly pulled high on the carrier (reads 1 when undriven) |
| `d6` | T15 | io | - | - | 3.3 V | RPLL1_T_IN | 2x20 header, free for user |
| `d7` | F13 | io | - | - | 3.3 V | - | 2x20 header, free for user; weakly pulled high on the carrier (reads 1 when undriven) |
| `e0` | B14 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `e1` | B13 | io | - | - | 3.3 V | LPLL1_T_FB | 2x20 header, free for user |
| `e2` | B12 | io | - | - | 3.3 V | LPLL1_C_IN | 2x20 header, free for user |
| `e3` | C11 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `e4` | A11 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `e5` | C7 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `e6` | T2 | io | - | - | 1.5 V | - | 2x20 header, free for user |
| `e7` | T4 | io | - | - | 1.5 V | - | 2x20 header, free for user |
| `f0` | N6 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `f1` | N9 | io | - | - | 3.3 V | SSPI_CS_N D0 | 2x20 header, free for user |
| `f2` | F16 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `f3` | D14 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `f4` | F14 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `f5` | G14 | io | - | - | 3.3 V | - | 2x20 header, free for user |
| `f6` | J16 | io | - | - | 3.3 V | - | 2x20 header, free for user; weakly pulled high on the carrier (reads 1 when undriven) |
| `f7` | G12 | io | - | - | 3.3 V | - | 2x20 header, free for user; weakly pulled high on the carrier (reads 1 when undriven) |

## Bus ports

A bus port is split into board locations automatically:
`led[7:0]` -> `led0`..`led7`, `s[7:0]`, `b[7:0]`, `c[7:0]`..`f[7:0]`,
`pmod0[7:0]` -> `pmod0_0`..`pmod0_7`. 7-segment pins are scalar
(`disp_a`..`disp_g`, `disp_dp`, `disp_1`..`disp_4`).
