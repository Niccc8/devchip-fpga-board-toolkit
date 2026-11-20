// selftest.v - exercises every on-board peripheral of the DevChipBoard v2.2.
//   python devchip.py run examples/selftest/selftest.v rtl/uart_tx.v
//
//   s[7:0]  -> led[7:0]             each switch lights its LED
//   b0..b7  -> 7-segment            holding a button shows "b" + its number, else "----"
//   pir     -> decimal point        lit while the PIR reports motion
//   b7      -> buzzer               ~2 kHz tone while held
//   uart_tx -> "DevChipBoard OK"    once per second, 115200 8N1, on the CP2105
//                                   *Standard* port (the one ChipLoader does not use)
// All on-board I/O is active-high (verified on hardware).
module top (
    input  wire       clk,
    input  wire [7:0] s,
    input  wire [7:0] b,
    input  wire       pir,
    output wire [7:0] led,
    output wire       disp_a, disp_b, disp_c, disp_d, disp_e, disp_f, disp_g, disp_dp,
    output wire       disp_1, disp_2, disp_3, disp_4,
    output wire       buzzer,
    output wire       uart_tx
);
    // ---------------- switches -> LEDs ----------------
    assign led = s;

    // ---------------- which button is held (highest wins) ----------------
    reg [3:0] which;                 // 0..7 = button index, 8 = none
    integer i;
    always @* begin
        which = 4'd8;
        for (i = 0; i < 8; i = i + 1)
            if (b[i]) which = i[3:0];
    end

    // ---------------- 7-segment, multiplexed (~1.6 kHz per digit) ----------------
    reg [16:0] scan = 17'd0;
    always @(posedge clk) scan <= scan + 17'd1;
    wire [1:0] digit = scan[16:15];

    function [6:0] hexseg(input [3:0] v);   // {g,f,e,d,c,b,a}, 1 = lit
        case (v)
            4'h0: hexseg = 7'b0111111; 4'h1: hexseg = 7'b0000110;
            4'h2: hexseg = 7'b1011011; 4'h3: hexseg = 7'b1001111;
            4'h4: hexseg = 7'b1100110; 4'h5: hexseg = 7'b1101101;
            4'h6: hexseg = 7'b1111101; 4'h7: hexseg = 7'b0000111;
            4'h8: hexseg = 7'b1111111; 4'h9: hexseg = 7'b1101111;
            4'hA: hexseg = 7'b1110111; 4'hB: hexseg = 7'b1111100;
            4'hC: hexseg = 7'b0111001; 4'hD: hexseg = 7'b1011110;
            4'hE: hexseg = 7'b1111001; default: hexseg = 7'b1110001;
        endcase
    endfunction

    reg [6:0] seg;
    always @* begin
        if (which == 4'd8)      seg = 7'b1000000;          // "-"
        else if (digit == 2'd0) seg = hexseg(4'hB);         // "b"
        else if (digit == 2'd3) seg = hexseg(which);        // button number
        else                    seg = 7'b0000000;
    end
    assign {disp_g, disp_f, disp_e, disp_d, disp_c, disp_b, disp_a} = seg;
    assign disp_dp = (digit == 2'd3) & pir;
    assign disp_1  = (digit == 2'd0);
    assign disp_2  = (digit == 2'd1);
    assign disp_3  = (digit == 2'd2);
    assign disp_4  = (digit == 2'd3);

    // ---------------- buzzer: scan[12] is a square wave of 27 MHz / 2^13 = ~3.3 kHz ----------------
    assign buzzer = b[7] & scan[12];

    // ---------------- UART banner once per second ----------------
    localparam integer MSG_LEN = 17;
    wire [8*MSG_LEN-1:0] msg = {"DevChipBoard OK", 8'h0D, 8'h0A};
    reg  [24:0] tick = 25'd0;
    reg  [4:0]  idx  = 5'd0;
    reg         sending = 1'b0, start = 1'b0;
    wire        busy;
    wire [7:0]  ch = msg[8*(MSG_LEN-1-idx) +: 8];

    always @(posedge clk) begin
        start <= 1'b0;
        tick  <= (tick == 25'd26_999_999) ? 25'd0 : tick + 25'd1;
        if (!sending) begin
            if (tick == 25'd0) begin sending <= 1'b1; idx <= 5'd0; end
        end else if (!busy && !start) begin
            if (idx == MSG_LEN) sending <= 1'b0;
            else                start   <= 1'b1;
        end
        if (start) idx <= idx + 5'd1;
    end

    uart_tx #(.DIV(234)) u_tx (.clk(clk), .data(ch), .start(start), .busy(busy), .tx(uart_tx));
endmodule
