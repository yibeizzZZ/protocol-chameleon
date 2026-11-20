// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Four read-to-clear status registers. SPI inputs are oversampled by clk.
// Frame: A6, register address, readback (all MSB first, one frame per CS).
module spi_target (
    input  wire       clk, rst_n, enter,
    input  wire       strobe, control,
    input  wire [7:0] host_byte,
    input  wire       cs_n, sclk, mosi,
    output reg        selected,
    output reg        miso,
    output wire       miso_oe
);
  (* async_reg = "true" *) reg [2:0] meta, sync_pins;
  reg cs_prev, sclk_prev;
  wire cs_sync = sync_pins[2];
  wire sclk_sync = sync_pins[1];
  wire [7:0] byte_in;
  always @(posedge clk) begin
    if (!rst_n) begin
      meta <= 3'b100;
      sync_pins <= 3'b100;
      {cs_prev, sclk_prev} <= 2'b10;
    end else begin
      meta <= {cs_n, sclk, mosi};
      sync_pins <= meta;
      {cs_prev, sclk_prev} <= sync_pins[2:1];
    end
  end

  reg [1:0] mode;
  reg [7:0] status_value [0:3];
  reg [7:0] clear_mask [0:3];
  reg [3:0] seen;
  reg cfg_pending, cfg_mask;
  reg [1:0] cfg_addr;
  reg active, command_ok, read_ok;
  reg [1:0] read_addr;
  reg [4:0] count;
  reg [6:0] rx_shift;
  reg [7:0] tx_shift;

  wire clock_edge = sclk_sync != sclk_prev;
  // CPHA=0 samples the leading edge; CPHA=1 samples the trailing edge.
  wire sample_level = ~(mode[1] ^ mode[0]);
  wire sample_edge = clock_edge && sclk_sync == sample_level;
  assign byte_in = {rx_shift, sync_pins[0]};
  wire [1:0] addr = byte_in[1:0];
  wire [7:0] read_value = status_value[addr] & ~(seen[addr] ? clear_mask[addr] : 8'h00);
  wire complete_read = active && !cs_sync && sample_edge && count == 5'd23 && read_ok;
  // Raw deselect releases the pad without waiting for the system clock.
  assign miso_oe = active && !cs_n;

  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      selected <= 0;
      mode <= 0;
      seen <= 0;
      cfg_pending <= 0;
      cfg_mask <= 0;
      cfg_addr <= 0;
      for (i = 0; i < 4; i = i + 1) begin
        status_value[i] <= 0;
        clear_mask[i] <= 0;
      end
    end else if (!selected) begin
      selected <= enter;
      cfg_pending <= 0;
    end else if (strobe && control && host_byte == 0) begin
      selected <= 0;
      cfg_pending <= 0;
    end else if (strobe && cs_sync && !active) begin
      if (control) begin
        cfg_pending <= host_byte[7:3] == 5'b00100; // 20..27
        cfg_mask <= host_byte[2];
        cfg_addr <= host_byte[1:0];
        if (host_byte[7:2] == 6'h04) mode <= host_byte[1:0];
        if (host_byte == 8'h01) seen <= 0;
      end else if (cfg_pending) begin
        if (cfg_mask) clear_mask[cfg_addr] <= host_byte;
        else status_value[cfg_addr] <= host_byte;
        seen[cfg_addr] <= 0;
        cfg_pending <= 0;
      end
    end else if (complete_read) begin
      seen[read_addr] <= 1'b1;
    end
  end

  always @(posedge clk) begin
    if (!rst_n || !selected || cs_sync) begin
      active <= 0;
      count <= 0;
      command_ok <= 0;
      read_ok <= 0;
      read_addr <= 0;
      rx_shift <= 0;
      tx_shift <= 0;
      miso <= 0;
    end else if (cs_prev && !cs_sync) begin
      active <= 1;
    end else if (active && sample_edge && count < 5'd24) begin
      rx_shift <= byte_in[6:0];
      count <= count + 1'b1;
      if (count == 5'd7)
        command_ok <= byte_in == 8'hA6;
      if (count == 5'd15) begin
        read_ok <= command_ok && byte_in[7:2] == 0;
        read_addr <= addr;
        tx_shift <= (command_ok && byte_in[7:2] == 0) ? read_value : 8'h00;
      end
    end else if (active && clock_edge && !sample_edge) begin
      // The next bit is already selected before its launch edge arrives.
      miso <= tx_shift[7];
      tx_shift <= {tx_shift[6:0], 1'b0};
    end
  end
endmodule
