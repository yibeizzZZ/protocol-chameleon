// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// A byte-completion rule selects both the next state and the byte to shift.
// Bit launch remains a single registered operation in either program profile.
module spi_target (
    input  wire       clk, rst_n, enter,
    input  wire       start_byte_program,
    input  wire [15:0] byte_rule,
    output wire [2:0] byte_state,
    input  wire       strobe, control,
    input  wire [7:0] host_byte,
    input  wire       cs_n, sclk, mosi,
    input  wire       bank_enable, bank_id,
    output wire       frame_start, frame_end, byte_valid, partial_byte,
    output wire [7:0] observed_byte,
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
  reg active, loaded_profile, addr_pending;
  reg [1:0] read_addr;
  reg [2:0] bit_index;
  reg [3:0] state;  // addresses 0..7, 8 means quiet until deselect
  reg [6:0] rx_shift;
  reg [7:0] tx_shift;

  wire clock_edge = sclk_sync != sclk_prev;
  // CPHA=0 samples the leading edge; CPHA=1 samples the trailing edge.
  wire sample_level = ~(mode[1] ^ mode[0]);
  wire sample_edge = clock_edge && sclk_sync == sample_level;
  assign byte_in = {rx_shift, sync_pins[0]};
  localparam [3:0] END_FRAME = 0, MATCH = 1, READ_INDEX = 2, READ_FIXED = 3,
                   COMMIT = 4, LITERAL = 5, IF_SEEN = 6, ADVANCE = 7;
  localparam [3:0] QUIET = 8;
  assign byte_state = state[2:0];

  // The M5 frame is the default program for this same byte interpreter.
  reg [15:0] default_rule;
  always @* begin
    case (state)
      0: default_rule = {MATCH,      4'd2, 8'hA6}; // mismatch -> state 1 (end)
      2: default_rule = {READ_INDEX, 4'd3, 8'd0};
      3: default_rule = {COMMIT,     4'd1, 8'd0};
      default: default_rule = 0;
    endcase
  end
  wire [15:0] rule = loaded_profile ? byte_rule : default_rule;
  wire [3:0] op = (state[3] || rule[11]) ? END_FRAME : rule[15:12];
  wire [3:0] target = {1'b0, rule[10:8]};
  wire [7:0] arg = rule[7:0];
  wire [1:0] logical_addr = (op == READ_INDEX) ? byte_in[1:0] : arg[1:0];
  wire [1:0] addr = bank_enable ? {bank_id, logical_addr[0]} : logical_addr;
  wire [7:0] read_value = status_value[addr] & ~(seen[addr] ? clear_mask[addr] : 8'h00);
  wire complete_byte = active && !cs_sync && sample_edge && bit_index == 3'd7;
  assign frame_start = selected && !active && cs_prev && !cs_sync;
  assign frame_end = selected && active && cs_sync;
  assign byte_valid = complete_byte;
  assign partial_byte = bit_index != 0;
  assign observed_byte = byte_in;
  wire complete_read = complete_byte && op == COMMIT && addr_pending;
  // Raw deselect releases the pad without waiting for the system clock.
  assign miso_oe = active && !cs_n;

  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      selected <= 0;
      loaded_profile <= 0;
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
      selected <= enter || start_byte_program;
      loaded_profile <= start_byte_program;
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
      state <= 0;
      bit_index <= 0;
      addr_pending <= 0;
      read_addr <= 0;
      rx_shift <= 0;
      tx_shift <= 0;
      miso <= 0;
    end else if (cs_prev && !cs_sync) begin
      active <= 1;
    end else if (active && sample_edge) begin
      rx_shift <= byte_in[6:0];
      bit_index <= bit_index + 1'b1;
      if (complete_byte) begin
        state <= target;
        tx_shift <= 0;
        case (op)
          MATCH: if (byte_in != arg) state <= state + 1'b1;
          READ_INDEX, READ_FIXED: begin
            if (op == READ_INDEX && byte_in[7:2] != 0) begin
              state <= QUIET;
              addr_pending <= 0;
            end else begin
              tx_shift <= read_value;
              read_addr <= addr;
              addr_pending <= 1;
            end
          end
          COMMIT: addr_pending <= 0;
          LITERAL: tx_shift <= arg;
          IF_SEEN: if (!seen[addr]) state <= state + 1'b1;
          ADVANCE: state <= target;
          default: begin
            state <= QUIET;
            addr_pending <= 0;
          end
        endcase
      end
    end else if (active && clock_edge && !sample_edge) begin
      // The next bit is already selected before its launch edge arrives.
      miso <= tx_shift[7];
      tx_shift <= {tx_shift[6:0], 1'b0};
    end
  end
endmodule
