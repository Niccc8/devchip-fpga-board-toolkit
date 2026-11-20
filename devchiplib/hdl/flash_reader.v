// flash_reader.v - READ-ONLY access to the Tang Primer 20K's configuration
// SPI flash, used by `devchip.py flash backup` / `flash verify`.
//
// Safety: this design can only ever issue the SPI flash commands 0x9F (read
// JEDEC ID) and 0x03 (read data). It never sends 0x06 (write enable), which
// every erase/program command requires, so it cannot modify the flash.
//
// Host protocol on uart_rx/uart_tx (CP2105 Standard port, BAUD below, 8N1):
//   'I'                  -> 'I' id0 id1 id2
//   'R' a2 a1 a0 n2 n1 n0 -> 'R' <n bytes from address a> crc_hi crc_lo
//                          (CRC-16/CCITT-FALSE over the n data bytes; n >= 1)
// LED0 lights while a read is in progress.
module top #(
    parameter integer DIV = 29          // 27 MHz / 29 = 931 kbaud (921600 -1.0%)
) (
    input  wire clk,
    input  wire uart_rx,
    output wire uart_tx,
    output reg  flash_cs_n = 1'b1,
    output reg  flash_clk  = 1'b0,
    output reg  flash_mosi = 1'b0,
    input  wire flash_miso,
    output wire led0
);
    // ---------------- UART ----------------
    wire [7:0] rx_data;
    wire       rx_valid;
    reg  [7:0] tx_data  = 8'd0;
    reg        tx_start = 1'b0;
    wire       tx_busy;
    uart_rx #(.DIV(DIV)) u_rx (.clk(clk), .rx(uart_rx), .data(rx_data), .valid(rx_valid));
    uart_tx #(.DIV(DIV)) u_tx (.clk(clk), .data(tx_data), .start(tx_start), .busy(tx_busy), .tx(uart_tx));

    // ---------------- SPI byte engine, mode 0, SCLK = clk/4 ----------------
    reg  [7:0] spi_tx = 8'd0, spi_rx = 8'd0;
    reg        spi_go = 1'b0, spi_busy = 1'b0;
    reg  [1:0] phase = 2'd0;
    reg  [2:0] bitn  = 3'd0;
    reg  [1:0] miso_s = 2'b00;
    always @(posedge clk) miso_s <= {miso_s[0], flash_miso};

    always @(posedge clk) begin
        if (!spi_busy) begin
            flash_clk <= 1'b0;
            if (spi_go) begin
                spi_busy <= 1'b1;
                phase    <= 2'd0;
                bitn     <= 3'd7;
            end
        end else begin
            phase <= phase + 2'd1;
            case (phase)
                2'd0: begin flash_clk <= 1'b0; flash_mosi <= spi_tx[bitn]; end
                2'd1: flash_clk <= 1'b1;                       // rising edge: flash samples MOSI
                2'd2: ;                                        // MISO stable since last falling edge
                2'd3: begin
                    spi_rx[bitn] <= miso_s[1];
                    flash_clk    <= 1'b0;
                    if (bitn == 3'd0) spi_busy <= 1'b0;
                    else              bitn <= bitn - 3'd1;
                end
            endcase
        end
    end

    // ---------------- CRC-16/CCITT-FALSE ----------------
    function [15:0] crc_byte(input [15:0] c, input [7:0] d);
        integer k;
        reg [15:0] x;
        begin
            x = c ^ {d, 8'h00};
            for (k = 0; k < 8; k = k + 1)
                x = x[15] ? {x[14:0], 1'b0} ^ 16'h1021 : {x[14:0], 1'b0};
            crc_byte = x;
        end
    endfunction

    // ---------------- command FSM ----------------
    localparam S_IDLE = 4'd0, S_ARGS = 4'd1, S_SPI = 4'd2, S_SPIW = 4'd3,
               S_TX = 4'd4, S_TXW = 4'd5, S_NEXT = 4'd6;
    reg [3:0]  st = S_IDLE;
    reg [7:0]  cmd = 8'd0;
    reg [2:0]  argn = 3'd0;
    reg [47:0] args = 48'd0;
    reg [23:0] remain = 24'd0;
    reg [15:0] crc = 16'hFFFF;
    reg [2:0]  hdr = 3'd0;          // header bytes still to send on SPI
    reg [1:0]  trailer = 2'd0;      // 0: data phase, 1: crc_hi, 2: crc_lo
    reg        reading = 1'b0;

    assign led0 = reading;

    always @(posedge clk) begin
        spi_go   <= 1'b0;
        tx_start <= 1'b0;
        case (st)
            S_IDLE: if (rx_valid) begin
                cmd <= rx_data;
                if (rx_data == "I") begin
                    flash_cs_n <= 1'b0;
                    spi_tx <= 8'h9F; spi_go <= 1'b1; hdr <= 3'd0;
                    remain <= 24'd3; crc <= 16'hFFFF; trailer <= 2'd0;
                    tx_data <= "I"; tx_start <= 1'b1;
                    st <= S_SPIW;
                end else if (rx_data == "R") begin
                    argn <= 3'd0; st <= S_ARGS;
                end
            end
            S_ARGS: if (rx_valid) begin
                args <= {args[39:0], rx_data};
                if (argn == 3'd5) begin
                    remain  <= {args[15:0], rx_data};
                    flash_cs_n <= 1'b0;
                    spi_tx  <= 8'h03; spi_go <= 1'b1; hdr <= 3'd3;
                    crc <= 16'hFFFF; trailer <= 2'd0; reading <= 1'b1;
                    tx_data <= "R"; tx_start <= 1'b1;
                    st <= S_SPIW;
                end
                argn <= argn + 3'd1;
            end
            // wait for the current SPI byte; send address bytes, then data bytes
            S_SPIW: if (!spi_go && !spi_busy) begin
                if (hdr != 3'd0) begin
                    case (hdr)
                        3'd3: spi_tx <= args[47:40];
                        3'd2: spi_tx <= args[39:32];
                        default: spi_tx <= args[31:24];
                    endcase
                    hdr <= hdr - 3'd1; spi_go <= 1'b1;
                end else st <= S_SPI;
            end
            S_SPI: begin                    // clock in one data byte
                spi_tx <= 8'h00; spi_go <= 1'b1; st <= S_TX;
            end
            S_TX: if (!spi_go && !spi_busy && !tx_busy && !tx_start) begin
                tx_data  <= spi_rx; tx_start <= 1'b1;
                crc      <= crc_byte(crc, spi_rx);
                remain   <= remain - 24'd1;
                st       <= S_NEXT;
            end
            S_NEXT: if (!tx_busy && !tx_start) begin
                if (remain != 24'd0) st <= S_SPI;
                else if (cmd == "R" && trailer == 2'd0) begin
                    flash_cs_n <= 1'b1;
                    tx_data <= crc[15:8]; tx_start <= 1'b1; trailer <= 2'd1;
                end else if (cmd == "R" && trailer == 2'd1) begin
                    tx_data <= crc[7:0]; tx_start <= 1'b1; trailer <= 2'd2;
                end else begin
                    flash_cs_n <= 1'b1; reading <= 1'b0; st <= S_IDLE;
                end
            end
            default: st <= S_IDLE;
        endcase
    end
endmodule
