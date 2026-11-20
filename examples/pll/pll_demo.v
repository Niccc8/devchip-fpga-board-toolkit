// pll_demo.v - run logic from a PLL clock (135 MHz, 5x the board clock).
//   python devchip.py run examples/pll/pll_demo.v examples/pll/pll_135mhz.v rtl/uart_tx.v --freq 135
// pll_135mhz.v was generated with:  python devchip.py pll 135 --name pll_135mhz
//
// LED0 = PLL locked. LED1 blinks at 1 Hz (counted at 135 MHz).
// uart_tx sends "PLL 135 MHz OK" once per second at 115200 baud; the baud
// divider is computed for 135 MHz, so readable text on the PC proves the PLL
// really runs at 135 MHz.
module top (
    input  wire       clk,
    output wire [1:0] led,
    output wire       uart_tx
);
    wire fast, lock;
    pll_135mhz u_pll (.clkin(clk), .clkout(fast), .lock(lock));

    reg [27:0] tick = 28'd0;
    reg        blink = 1'b0;
    always @(posedge fast)
        if (!lock) tick <= 28'd0;
        else if (tick == 28'd134_999_999) begin tick <= 28'd0; blink <= ~blink; end
        else tick <= tick + 28'd1;

    assign led = {blink, lock};

    localparam integer N = 16;
    wire [8*N-1:0] msg = {"PLL 135 MHz OK", 8'h0D, 8'h0A};
    reg  [4:0] idx = 5'd0;
    reg        sending = 1'b0, start = 1'b0;
    wire       busy;
    always @(posedge fast) begin
        start <= 1'b0;
        if (!sending) begin
            if (lock && tick == 28'd0) begin sending <= 1'b1; idx <= 5'd0; end
        end else if (!busy && !start) begin
            if (idx == N) sending <= 1'b0;
            else          start   <= 1'b1;
        end
        if (start) idx <= idx + 5'd1;
    end

    uart_tx #(.DIV(1172)) u_tx (.clk(fast), .data(msg[8*(N-1-idx) +: 8]), .start(start),
                               .busy(busy), .tx(uart_tx));   // 135e6 / 115200 = 1171.9
endmodule
