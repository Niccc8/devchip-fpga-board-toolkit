// accel_bridge.v - UART-to-SPI bridge for the on-board accelerometer.
//   python devchip.py run examples/accelerometer/accel_bridge.v rtl/uart_rx.v rtl/uart_tx.v rtl/spi_master.v
//   python examples/accelerometer/accel.py          (identifies the chip, prints X/Y/Z)
//
// Protocol (CP2105 Standard port, 115200 8N1):
//   'T' n b1..bn  ->  'T' r1..rn     one SPI transaction (CS low for all n bytes), 1 <= n <= 255
// SPI mode 3 at ~844 kHz, which every common accelerometer supports.
// LED0 lights during a transaction.
module top (
    input  wire clk,
    input  wire uart_rx,
    output wire uart_tx,
    output reg  acc_cs = 1'b1,
    output wire acc_sclk,
    output wire acc_mosi,
    input  wire acc_miso,
    output wire led0
);
    wire [7:0] rx_data;  wire rx_valid;
    reg  [7:0] tx_data = 8'd0;  reg tx_start = 1'b0;  wire tx_busy;
    uart_rx #(.DIV(234)) u_rx (.clk(clk), .rx(uart_rx), .data(rx_data), .valid(rx_valid));
    uart_tx #(.DIV(234)) u_tx (.clk(clk), .data(tx_data), .start(tx_start), .busy(tx_busy), .tx(uart_tx));

    reg  [7:0] spi_tx = 8'd0;  reg spi_go = 1'b0;
    wire [7:0] spi_rx;  wire spi_busy;
    spi_master #(.HALF(16), .CPOL(1'b1)) u_spi (.clk(clk), .start(spi_go), .tx(spi_tx), .rx(spi_rx),
        .busy(spi_busy), .sclk(acc_sclk), .mosi(acc_mosi), .miso(acc_miso));

    localparam S_IDLE = 3'd0, S_LEN = 3'd1, S_BYTE = 3'd2, S_SPI = 3'd3, S_SEND = 3'd4, S_END = 3'd5;
    reg [2:0] st = S_IDLE;
    reg [7:0] left = 8'd0;
    reg [7:0] gap = 8'd0;
    assign led0 = ~acc_cs;

    // one-byte holding register so no host byte is lost while the FSM is busy
    reg [7:0] pend = 8'd0;
    reg       pend_v = 1'b0;
    wire      take = pend_v && (st == S_IDLE || st == S_LEN || st == S_BYTE);
    always @(posedge clk)
        if (rx_valid)  begin pend <= rx_data; pend_v <= 1'b1; end
        else if (take) pend_v <= 1'b0;

    always @(posedge clk) begin
        spi_go   <= 1'b0;
        tx_start <= 1'b0;
        case (st)
            S_IDLE: if (take && pend == "T") st <= S_LEN;
            S_LEN:  if (take) begin
                if (pend == 8'd0) st <= S_IDLE;
                else begin
                    left <= pend; acc_cs <= 1'b0;
                    tx_data <= "T"; tx_start <= 1'b1;
                    st <= S_BYTE;
                end
            end
            S_BYTE: if (take) begin                 // next byte to shift out
                spi_tx <= pend; spi_go <= 1'b1; st <= S_SPI;
            end
            S_SPI:  if (!spi_go && !spi_busy && !tx_busy && !tx_start) begin
                tx_data <= spi_rx; tx_start <= 1'b1;
                left <= left - 8'd1;
                st <= S_SEND;
            end
            S_SEND: if (!tx_start) begin
                if (left == 8'd0) begin gap <= 8'd0; st <= S_END; end
                else st <= S_BYTE;
            end
            S_END: begin                           // hold CS high briefly between transactions
                acc_cs <= 1'b1;
                gap <= gap + 8'd1;
                if (gap == 8'd200) st <= S_IDLE;
            end
            default: st <= S_IDLE;
        endcase
    end
endmodule
