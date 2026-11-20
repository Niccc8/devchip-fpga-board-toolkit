// Testbench for examples/whack_a_led/whack_a_led.v (fast clock: 1 ms = 20 cycles)
//   python devchip.py sim examples/whack_a_led/whack_a_led.v --tb sim/tb_whack_a_led.v
`timescale 1ns/1ps
module tb;
  reg clk=0; always #5 clk=~clk;
  reg [7:0] b=0, s=0; reg pir=0;
  wire [7:0] led; wire a,bb,c,d,e,f,g,dp,d1,d2,d3,d4,bz;
  top #(.MS_DIV(20)) dut(.clk(clk),.b(b),.s(s),.pir(pir),.led(led),.disp_a(a),.disp_b(bb),.disp_c(c),.disp_d(d),
    .disp_e(e),.disp_f(f),.disp_g(g),.disp_dp(dp),.disp_1(d1),.disp_2(d2),.disp_3(d3),.disp_4(d4),.buzzer(bz));
  localparam MS = 20*10;  // ns per ms
  task press(input [7:0] m); begin b=m; #(MS*10); b=0; #(MS*10); end endtask
  integer i, err=0;
  initial begin
    #(MS*20);
    if (dut.st!==0) begin $display("FAIL not idle"); err=err+1; end
    pir=1; #(MS*10); if (dut.hey==0) begin $display("FAIL no HEY"); err=err+1; end pir=0;
    press(8'h04);                                  // start
    if (dut.st!==1) begin $display("FAIL not counting st=%0d", dut.st); err=err+1; end
    wait(dut.st==3);                               // PLAY
    for (i=0;i<5;i=i+1) begin wait(dut.st==3); #(MS*5); press(led); end
    if (dut.score!==16'h0005) begin $display("FAIL score %h", dut.score); err=err+1; end
    if (dut.window>=2000) begin $display("FAIL window not shrinking"); err=err+1; end
    wait(dut.st==3); #(MS*5); press(~led & 8'hFF & (led==8'h01 ? 8'h02 : 8'h01));   // wrong button
    if (dut.lives!==2) begin $display("FAIL wrong press lives=%0d", dut.lives); err=err+1; end
    wait(dut.st==5);                               // two timeouts -> game over
    wait(dut.st==0);
    if (dut.best!==16'h0005) begin $display("FAIL best %h", dut.best); err=err+1; end
    if (err==0) $display("PASS whack: idle/HEY, start, countdown, 5 hits, speed-up, wrong press, timeouts, game over, high score");
    $finish;
  end
  initial begin #(MS*60000); $display("FAIL timeout st=%0d", dut.st); $finish; end
endmodule
