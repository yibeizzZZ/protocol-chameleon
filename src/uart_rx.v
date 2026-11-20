// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module uart_rx (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx,
    input  wire [11:0] bit_reload,
    input  wire       seven_bits,
    input  wire       two_stops,
    output reg  [7:0] data,
    output reg        valid,
    output reg        framing_error
);
  localparam [2:0] IDLE = 3'd0, START = 3'd1, DATA = 3'd2,
                   STOP = 3'd3, WAIT_HIGH = 3'd4;

  reg rx_meta, rx_sync;
  reg [2:0] state;
  reg [11:0] frame_reload, ticks_left;
  reg frame_seven_bits, extra_stop_pending;
  reg [2:0] bit_index;
  reg [7:0] shift_reg;

  // Only the second stage drives the receiver logic.
  always @(posedge clk) begin
    if (!rst_n) begin
      rx_meta <= 1'b1;
      rx_sync <= 1'b1;
    end else begin
      rx_meta <= rx;
      rx_sync <= rx_meta;
    end
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      state         <= IDLE;
      ticks_left    <= 0;
      frame_reload  <= 0;
      frame_seven_bits <= 1'b0;
      extra_stop_pending <= 1'b0;
      bit_index     <= 0;
      shift_reg     <= 0;
      data          <= 0;
      valid         <= 1'b0;
      framing_error <= 1'b0;
    end else begin
      valid         <= 1'b0;
      framing_error <= 1'b0;
      case (state)
        IDLE: if (!rx_sync) begin
          // Snapshot the settings before sampling even the start bit.
          frame_reload       <= bit_reload;
          frame_seven_bits   <= seven_bits;
          extra_stop_pending <= two_stops;
          ticks_left <= bit_reload >> 1;
          state      <= START;
        end

        START: if (ticks_left == 0) begin
          // Confirm the start bit at its midpoint before collecting data.
          state      <= rx_sync ? IDLE : DATA;
          ticks_left <= frame_reload;
          bit_index  <= 0;
        end else ticks_left <= ticks_left - 1'b1;

        DATA: if (ticks_left == 0) begin
          shift_reg  <= {rx_sync, shift_reg[7:1]};
          ticks_left <= frame_reload;
          bit_index  <= bit_index + 1'b1;
          if (bit_index == (frame_seven_bits ? 3'd6 : 3'd7))
            state <= STOP;
        end else ticks_left <= ticks_left - 1'b1;

        STOP: if (ticks_left == 0) begin
          if (!rx_sync) begin
            framing_error <= 1'b1;
            state         <= WAIT_HIGH;
          end else if (extra_stop_pending) begin
            extra_stop_pending <= 1'b0;
            ticks_left <= frame_reload;
          end else begin
            data  <= frame_seven_bits ? {1'b0, shift_reg[7:1]} : shift_reg;
            valid <= 1'b1;
            state <= IDLE;
          end
        end else ticks_left <= ticks_left - 1'b1;

        // A continuous low line reports one bad frame. Rearm on release.
        WAIT_HIGH: if (rx_sync) state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end
endmodule
