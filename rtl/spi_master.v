// spi_master.v - one-byte SPI master, MSB first, SPI mode 0 or mode 3.
//   SCLK = clk / (2 * HALF).  Pulse `start` (while !busy) with `tx`;
//   `rx` holds the received byte once `busy` falls. Chip select is the caller's job.
// Modes 0 and 3 both sample on the rising edge and shift on the falling edge;
// they differ only in the idle level (CPOL). A byte is always 16 clock edges.
module spi_master #(
    parameter integer HALF = 16,       // 27 MHz / 32 = 844 kHz
    parameter         CPOL = 1'b1      // 1 = mode 3 (idle high), 0 = mode 0 (idle low)
) (
    input  wire       clk,
    input  wire       start,
    input  wire [7:0] tx,
    output reg  [7:0] rx = 8'd0,
    output reg        busy = 1'b0,
    output reg        sclk = CPOL,
    output reg        mosi = 1'b0,
    input  wire       miso
);
    reg [1:0]  ms = 2'b00;                 // MISO synchronizer
    always @(posedge clk) ms <= {ms[0], miso};

    reg [15:0] cnt = 16'd0;
    reg [4:0]  toggles = 5'd0;             // 16 per byte
    reg [3:0]  sampled = 4'd0;             // rising edges seen
    reg [7:0]  txsh = 8'd0;

    always @(posedge clk) begin
        if (!busy) begin
            sclk <= CPOL;
            if (start) begin
                busy    <= 1'b1;
                txsh    <= {tx[6:0], 1'b0};
                mosi    <= tx[7];          // set up before the first sampling edge
                cnt     <= 16'd0;
                toggles <= 5'd0;
                sampled <= 4'd0;
            end
        end else if (cnt == HALF - 1) begin
            cnt  <= 16'd0;
            sclk <= ~sclk;
            if (!sclk) begin                               // rising edge: sample
                rx      <= {rx[6:0], ms[1]};
                sampled <= sampled + 4'd1;
            end else if (sampled != 4'd0 && sampled != 4'd8) begin   // falling: shift
                mosi <= txsh[7];
                txsh <= {txsh[6:0], 1'b0};
            end
            toggles <= toggles + 5'd1;
            if (toggles == 5'd15) busy <= 1'b0;
        end else begin
            cnt <= cnt + 16'd1;
        end
    end
endmodule
