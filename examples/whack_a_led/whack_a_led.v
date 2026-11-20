// WHACK-A-LED - a tiny arcade game for the DevChipBoard v2.2
//   python devchip.py run examples/whack_a_led/whack_a_led.v
//   idle   : LEDs sweep, display alternates "PLAY" / high score.
//            walk past the board -> PIR -> "HEY" + chirp
//   start  : press any button -> 3, 2, 1, GO
//   play   : one LED lights; press its button (b0..b7) before it goes out.
//            you get 2 s for the first LED (1.2 s in hard mode); each hit = +1 score and
//            ~3% less time next round (never below 0.4 s). wrong button or too slow = -1 life.
//            score on the display, lives on the decimal points (3 lives)
//   over   : score blinks, sad sound, back to idle (high score kept)
//   s0 = hard mode (faster start), s7 = mute
module top #(
    parameter integer MS_DIV = 27000          // clock cycles per millisecond (27 MHz)
) (
    input  wire       clk,
    input  wire [7:0] b,
    input  wire [7:0] s,
    input  wire       pir,
    output reg  [7:0] led,
    output wire       disp_a, disp_b, disp_c, disp_d, disp_e, disp_f, disp_g, disp_dp,
    output wire       disp_1, disp_2, disp_3, disp_4,
    output wire       buzzer
);
    // ---------------- 1 ms tick ----------------
    reg [15:0] div = 0;
    reg        ms  = 0;
    always @(posedge clk) begin
        ms <= 1'b0;
        if (div == MS_DIV - 1) begin div <= 0; ms <= 1'b1; end
        else div <= div + 1'b1;
    end

    // ---------------- inputs: sync, debounce, edges ----------------
    reg [7:0] bq0 = 0, bq1 = 0, bsa = 0, bsb = 0, bdb = 0, bdb_d = 0;
    reg [2:0] pq = 0;
    always @(posedge clk) begin
        bq0 <= b; bq1 <= bq0;
        pq  <= {pq[1:0], pir};
        if (ms) begin
            bsa <= bq1; bsb <= bsa;
            bdb <= (bsa == bsb) ? bsb : bdb;   // stable for 2 ms
        end
        bdb_d <= bdb;
    end
    wire [7:0] press  = bdb & ~bdb_d;          // one-cycle pulse per press
    wire       anyp   = |press;
    wire       pir_up = pq[1] & ~pq[2];

    // ---------------- random numbers (LFSR runs every clock) ----------------
    reg [15:0] lfsr = 16'hACE1;
    always @(posedge clk) lfsr <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};

    // ---------------- sound ----------------
    reg [16:0] half = 17'd6750, tcnt = 0;
    reg [9:0]  snd_ms = 0;
    reg        tone = 0;
    reg        play_req = 0;
    reg [16:0] req_half = 0;
    reg [9:0]  req_ms = 0;
    always @(posedge clk) begin
        if (play_req) begin half <= req_half; snd_ms <= req_ms; tcnt <= 0; end
        else begin
            if (ms && snd_ms != 0) snd_ms <= snd_ms - 1'b1;
            if (tcnt >= half) begin tcnt <= 0; tone <= ~tone; end
            else tcnt <= tcnt + 1'b1;
        end
    end
    assign buzzer = (snd_ms != 0) & tone & ~s[7];

    // ---------------- 7-segment letters / digits ({g,f,e,d,c,b,a}) ----------------
    localparam [6:0] L_P = 7'b1110011, L_L = 7'b0111000, L_A = 7'b1110111, L_Y = 7'b1101110,
                     L_H = 7'b1110110, L_E = 7'b1111001, L_G = 7'b0111101, L_O = 7'b0111111,
                     L_I = 7'b0000110, L_d = 7'b1011110, L_BL = 7'b0000000;
    function [6:0] num(input [3:0] v);
        case (v)
            4'd0: num = 7'b0111111; 4'd1: num = 7'b0000110; 4'd2: num = 7'b1011011;
            4'd3: num = 7'b1001111; 4'd4: num = 7'b1100110; 4'd5: num = 7'b1101101;
            4'd6: num = 7'b1111101; 4'd7: num = 7'b0000111; 4'd8: num = 7'b1111111;
            default: num = 7'b1101111;
        endcase
    endfunction

    // BCD +1 on a 4-digit score
    function [15:0] bcd_inc(input [15:0] x);
        reg [15:0] y; begin
            y = x;
            if (y[3:0] != 9) y[3:0] = y[3:0] + 1;
            else begin y[3:0] = 0;
                if (y[7:4] != 9) y[7:4] = y[7:4] + 1;
                else begin y[7:4] = 0;
                    if (y[11:8] != 9) y[11:8] = y[11:8] + 1;
                    else begin y[11:8] = 0; if (y[15:12] != 9) y[15:12] = y[15:12] + 1; end
                end
            end
            bcd_inc = y;
        end
    endfunction

    // ---------------- game state ----------------
    localparam S_IDLE = 3'd0, S_COUNT = 3'd1, S_NEW = 3'd2, S_PLAY = 3'd3, S_GAP = 3'd4, S_OVER = 3'd5;
    reg [2:0]  st = S_IDLE;
    reg [15:0] t = 0;              // ms timer within a state
    reg [15:0] window = 2000;      // ms allowed per mole
    reg [2:0]  mole = 0;
    reg [1:0]  lives = 3;
    reg [1:0]  cnt = 3;
    reg [15:0] score = 0, best = 0;
    reg [15:0] hey = 0;            // ms left of the "HEY" greeting
    reg [15:0] anim = 0;           // free-running ms counter for animations
    reg        newbest = 0;

    task sound(input [16:0] h, input [9:0] d);
        begin play_req <= 1'b1; req_half <= h; req_ms <= d; end
    endtask

    always @(posedge clk) begin
        play_req <= 1'b0;
        if (ms) begin
            anim <= anim + 1'b1;
            if (hey != 0) hey <= hey - 1'b1;
            t <= t + 1'b1;
        end

        case (st)
            S_IDLE: begin
                if (pir_up && hey == 0) begin hey <= 16'd1500; sound(17'd4500, 10'd90); end
                if (anyp) begin
                    st <= S_COUNT; t <= 0; cnt <= 3; score <= 0; lives <= 3; newbest <= 0;
                    window <= s[0] ? 16'd1200 : 16'd2000;
                    sound(17'd13500, 10'd120);
                end
            end
            S_COUNT: if (ms && t == 16'd999) begin
                t <= 0;
                if (cnt == 0) st <= S_NEW;
                else begin
                    cnt <= cnt - 1'b1;
                    if (cnt == 1) sound(17'd5400, 10'd350);      // GO!
                    else          sound(17'd13500, 10'd120);
                end
            end
            S_NEW: begin
                mole <= (lfsr[2:0] == mole) ? lfsr[2:0] + 3'd1 : lfsr[2:0];
                t <= 0; st <= S_PLAY;
            end
            S_PLAY: begin
                if (anyp) begin
                    if (press == (8'b1 << mole)) begin
                        score <= bcd_inc(score);
                        sound(17'd6750 - {9'd0, score[3:0], 4'd0}, 10'd60);   // pitch rises a little
                        window <= (window > 16'd420) ? window - (window >> 5) : 16'd400;
                        t <= 0; st <= S_GAP;
                    end else begin
                        lives <= lives - 1'b1; t <= 0;
                        sound(17'd45000, 10'd250);
                        st <= (lives == 1) ? S_OVER : S_GAP;
                    end
                end else if (t >= window) begin
                    lives <= lives - 1'b1; t <= 0;
                    sound(17'd45000, 10'd250);
                    st <= (lives == 1) ? S_OVER : S_GAP;
                end
            end
            S_GAP: if (ms && t == 16'd300) st <= S_NEW;
            S_OVER: begin
                if (t == 16'd0 && ms) begin
                    sound(17'd67500, 10'd700);
                    if (score > best) begin best <= score; newbest <= 1'b1; end
                end
                if (ms && t == 16'd4000) begin st <= S_IDLE; t <= 0; end
            end
            default: st <= S_IDLE;
        endcase
    end

    // ---------------- LEDs ----------------
    wire [2:0] sweep_pos = anim[9:7];
    wire       sweep_dir = anim[10];
    always @* begin
        case (st)
            S_IDLE:  led = 8'b1 << (sweep_dir ? 3'd7 - sweep_pos : sweep_pos);
            S_COUNT: led = (cnt == 0) ? 8'hFF : (cnt == 3) ? 8'h18 : (cnt == 2) ? 8'h3C : 8'h7E;
            S_PLAY:  led = 8'b1 << mole;
            S_OVER:  led = {8{anim[7]}} & (newbest ? 8'hFF : 8'h81);
            default: led = 8'h00;
        endcase
    end

    // ---------------- display content ----------------
    reg [6:0] d0, d1, d2, d3;       // left to right
    reg [3:0] dps;                  // decimal points, left to right
    wire      show_best = anim[11] & (best != 0);
    always @* begin
        dps = 4'b0000;
        {d0, d1, d2, d3} = {L_BL, L_BL, L_BL, L_BL};
        case (st)
            S_IDLE:
                if (hey != 0)        {d0, d1, d2, d3} = {L_H, L_E, L_Y, L_BL};
                else if (show_best)  {d0, d1, d2, d3} = {L_H, L_I, num(best[7:4]), num(best[3:0])};
                else                 {d0, d1, d2, d3} = {L_P, L_L, L_A, L_Y};
            S_COUNT:
                if (cnt == 0)        {d0, d1, d2, d3} = {L_BL, L_G, L_O, L_BL};
                else                 {d0, d1, d2, d3} = {L_BL, L_BL, num({2'b0, cnt}), L_BL};
            S_OVER:
                if (anim[8])         {d0, d1, d2, d3} = {num(score[15:12]), num(score[11:8]), num(score[7:4]), num(score[3:0])};
                else                 {d0, d1, d2, d3} = {L_d, L_E, L_A, L_d};
            default: begin
                {d0, d1, d2, d3} = {num(score[15:12]), num(score[11:8]), num(score[7:4]), num(score[3:0])};
                dps = (lives == 3) ? 4'b1110 : (lives == 2) ? 4'b1100 : (lives == 1) ? 4'b1000 : 4'b0000;
            end
        endcase
    end

    // ---------------- multiplexing (~200 Hz per digit) ----------------
    reg [16:0] scan = 0;
    always @(posedge clk) scan <= scan + 1'b1;
    wire [1:0] dig = scan[16:15];
    wire [6:0] seg = (dig == 0) ? d0 : (dig == 1) ? d1 : (dig == 2) ? d2 : d3;
    assign {disp_g, disp_f, disp_e, disp_d, disp_c, disp_b, disp_a} = seg;
    assign disp_dp = dps[3 - dig];
    assign disp_1 = (dig == 2'd0);
    assign disp_2 = (dig == 2'd1);
    assign disp_3 = (dig == 2'd2);
    assign disp_4 = (dig == 2'd3);
endmodule
