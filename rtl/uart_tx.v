// 8N1 UART transmitter. DIV = clk_hz / baud (27 MHz / 115200 = 234).
module uart_tx #(
    parameter integer DIV = 234
) (
    input  wire       clk,
    input  wire [7:0] data,
    input  wire       start,   // 1-cycle pulse while !busy
    output reg        busy = 1'b0,
    output reg        tx   = 1'b1
);
    reg [8:0]  shreg = 9'h1FF;   // {stop, data[7:0]}, shifted out LSB first
    reg [3:0]  nbits = 4'd0;
    reg [15:0] cnt   = 16'd0;

    always @(posedge clk) begin
        if (!busy) begin
            tx <= 1'b1;
            if (start) begin
                shreg <= {1'b1, data};
                tx    <= 1'b0;          // start bit
                busy  <= 1'b1;
                cnt   <= 16'd0;
                nbits <= 4'd0;
            end
        end else if (cnt == DIV - 1) begin
            cnt <= 16'd0;
            if (nbits == 4'd9) begin    // stop bit finished
                busy <= 1'b0;
                tx   <= 1'b1;
            end else begin
                tx    <= shreg[0];
                shreg <= {1'b1, shreg[8:1]};
                nbits <= nbits + 4'd1;
            end
        end else begin
            cnt <= cnt + 16'd1;
        end
    end
endmodule
