// pin_tester.v - read all 48 PMOD / 2x20-header pins and stream them to the PC.
// Every pin is an INPUT, so nothing is ever driven onto the connectors.
//
//   python devchip.py run examples/pin_tester/pin_tester.v rtl/uart_tx.v --cst examples/pin_tester/pull_up.cst
//   python examples/pin_tester/pin_tester.py
//
// With pull_up.cst every free pin reads 1. Touch a pin with a jumper wire
// connected to GND and pin_tester.py names the pin that went low: that is how
// each connector position was checked against its location name.
// (GND is safe on every pin, including the 1.5 V ones c6/e6/e7.)
//
// Frame, every ~20 ms on uart_tx (115200 8N1):
//   0xA5 0x5A  c  d  e  f  pmod0  pmod1  xor-of-the-6-bytes
module top (
    input  wire       clk,
    input  wire [7:0] c, d, e, f,
    input  wire [7:0] pmod0, pmod1,
    output wire       uart_tx,
    output wire       led0
);
    reg [47:0] s1 = 48'd0, s2 = 48'd0;            // synchronizers
    always @(posedge clk) begin
        s1 <= {c, d, e, f, pmod0, pmod1};
        s2 <= s1;
    end

    reg [19:0] t = 20'd0;                          // 20 ms at 27 MHz = 540000
    reg [3:0]  idx = 4'd0;
    reg        sending = 1'b0, start = 1'b0;
    reg [47:0] snap = 48'd0;
    wire       busy;
    wire [7:0] x = snap[47:40] ^ snap[39:32] ^ snap[31:24] ^ snap[23:16] ^ snap[15:8] ^ snap[7:0];
    reg  [7:0] ch;
    always @* case (idx)
        4'd0: ch = 8'hA5;          4'd1: ch = 8'h5A;
        4'd2: ch = snap[47:40];    4'd3: ch = snap[39:32];
        4'd4: ch = snap[31:24];    4'd5: ch = snap[23:16];
        4'd6: ch = snap[15:8];     4'd7: ch = snap[7:0];
        default: ch = x;
    endcase

    always @(posedge clk) begin
        start <= 1'b0;
        t <= (t == 20'd539_999) ? 20'd0 : t + 20'd1;
        if (!sending) begin
            if (t == 20'd0) begin sending <= 1'b1; idx <= 4'd0; snap <= s2; end
        end else if (!busy && !start) begin
            if (idx == 4'd9) sending <= 1'b0;
            else             start   <= 1'b1;
        end
        if (start) idx <= idx + 4'd1;
    end

    assign led0 = ~&s2;                            // lights while any pin reads 0
    uart_tx #(.DIV(234)) u_tx (.clk(clk), .data(ch), .start(start), .busy(busy), .tx(uart_tx));
endmodule
