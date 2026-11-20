// Testbench for examples/selftest/selftest.v (Icarus Verilog, from OSS CAD Suite):
//   iverilog -g2012 -o sim/selftest.vvp sim/tb_selftest.v examples/selftest/selftest.v rtl/uart_tx.v
//   vvp -n sim/selftest.vvp
// Checks: switches reach the LEDs, the button decoder, and one full UART
// banner received by a 115200-baud receiver model.
`timescale 1ns/1ps
module tb;
    reg clk = 1'b0;
    always #18.518 clk = ~clk;                 // 27 MHz

    reg  [7:0] s = 8'h5A, b = 8'h00;
    reg        pir = 1'b0;
    wire [7:0] led;
    wire da, db, dc, dd, de, df, dg, dp, d1, d2, d3, d4, bz, tx;

    top dut (.clk(clk), .s(s), .b(b), .pir(pir), .led(led),
             .disp_a(da), .disp_b(db), .disp_c(dc), .disp_d(dd), .disp_e(de), .disp_f(df),
             .disp_g(dg), .disp_dp(dp), .disp_1(d1), .disp_2(d2), .disp_3(d3), .disp_4(d4),
             .buzzer(bz), .uart_tx(tx));

    localparam real BIT_NS = 1.0e9 / 115200.0;
    localparam [8*17-1:0] EXPECT = {"DevChipBoard OK", 8'h0D, 8'h0A};
    reg [7:0] c;
    integer k, n = 0, errors = 0;

    initial begin
        #1 b = 8'h01; #1 b = 8'h00;             // make the combinational decoder evaluate
        #10;
        if (led !== 8'h5A) begin $display("FAIL: led=%h, expected 5A", led); errors = errors + 1; end
        if (dut.which !== 4'd8) begin $display("FAIL: no button should read 8"); errors = errors + 1; end
        b = 8'b0000_1000; #10;
        if (dut.which !== 4'd3) begin $display("FAIL: b3 decode"); errors = errors + 1; end
        b = 8'h00;
    end

    initial begin                               // UART receiver model
        forever begin
            @(negedge tx);
            #(BIT_NS * 1.5);
            for (k = 0; k < 8; k = k + 1) begin c[k] = tx; #(BIT_NS); end
            if (tx !== 1'b1) begin $display("FAIL: stop bit"); errors = errors + 1; end
            if (c !== EXPECT[8*(16-n) +: 8]) begin
                $display("FAIL: char %0d = %h, expected %h", n, c, EXPECT[8*(16-n) +: 8]);
                errors = errors + 1;
            end
            n = n + 1;
            if (n == 17) begin
                if (errors == 0) $display("PASS: LEDs, buttons and UART banner OK");
                else             $display("FAILED with %0d error(s)", errors);
                $finish;
            end
        end
    end

    initial begin #5_000_000; $display("FAIL: timeout (got %0d chars)", n); $finish; end
endmodule
