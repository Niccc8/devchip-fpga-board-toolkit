// blinky.v - the smallest useful design: an 8-bit binary counter on the LEDs.
//   python devchip.py run examples/blinky/blinky.v
// LED0 toggles about every 0.6 s; LED7 about every 80 s.
module top (
    input  wire       clk,        // 27 MHz board clock
    output wire [7:0] led         // led[0] -> board location led0 ... led[7] -> led7
);
    reg [31:0] count = 32'd0;
    always @(posedge clk) count <= count + 32'd1;
    assign led = count[31:24];
endmodule
