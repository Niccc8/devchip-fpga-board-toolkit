// pir_monitor.v - watch the PIR motion sensor.
//   python devchip.py run examples/pir_monitor/pir_monitor.v rtl/uart_tx.v
// LED0 = PIR output, LED1 = inverted. Every 100 ms the level is sent as '0'/'1'
// on uart_tx (CP2105 Standard port, 115200 8N1) so it can be logged on the PC.
// Expect: high for several seconds after motion, then a ~4 s lockout low.
module top (
    input  wire       clk,
    input  wire       pir,
    output wire [1:0] led,
    output wire       uart_tx
);
    reg [1:0] sync = 2'b00;                  // two-flop synchronizer
    always @(posedge clk) sync <= {sync[0], pir};
    wire p = sync[1];

    assign led = {~p, p};

    reg [21:0] t = 22'd0;                    // 2_700_000 cycles = 100 ms
    reg        start = 1'b0;
    wire       busy;
    always @(posedge clk) begin
        start <= 1'b0;
        if (t == 22'd2_699_999) begin
            t <= 22'd0;
            if (!busy) start <= 1'b1;
        end else
            t <= t + 22'd1;
    end

    uart_tx #(.DIV(234)) u_tx (.clk(clk), .data(p ? "1" : "0"), .start(start),
                              .busy(busy), .tx(uart_tx));
endmodule
