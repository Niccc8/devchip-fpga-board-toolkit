// 8N1 UART receiver, samples in the middle of each bit.
module uart_rx #(
    parameter integer DIV = 234
) (
    input  wire       clk,
    input  wire       rx,
    output reg  [7:0] data  = 8'd0,
    output reg        valid = 1'b0   // 1-cycle pulse
);
    reg [2:0]  sync = 3'b111;
    always @(posedge clk) sync <= {sync[1:0], rx};
    wire r = sync[2];

    reg        busy = 1'b0;
    reg [15:0] cnt  = 16'd0;
    reg [3:0]  bitn = 4'd0;
    reg [7:0]  sh   = 8'd0;

    always @(posedge clk) begin
        valid <= 1'b0;
        if (!busy) begin
            if (!r) begin                // falling edge = start bit
                busy <= 1'b1;
                cnt  <= DIV / 2;         // first sample lands mid start bit
                bitn <= 4'd0;
            end
        end else if (cnt == DIV - 1) begin
            cnt <= 16'd0;
            if (bitn == 4'd0) begin
                if (r) busy <= 1'b0;     // glitch, not a real start bit
                bitn <= 4'd1;
            end else if (bitn <= 4'd8) begin
                sh   <= {r, sh[7:1]};
                bitn <= bitn + 4'd1;
            end else begin               // stop bit
                busy <= 1'b0;
                if (r) begin
                    data  <= sh;
                    valid <= 1'b1;
                end
            end
        end else begin
            cnt <= cnt + 16'd1;
        end
    end
endmodule
