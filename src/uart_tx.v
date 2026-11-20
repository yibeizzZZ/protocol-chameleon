// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module uart_tx (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,  // One-cycle request; accepted while idle
    input  wire [7:0] data,
    input  wire [11:0] bit_reload,
    input  wire       seven_bits,
    input  wire       two_stops,
    output wire       tx,
    output wire       busy,
    output reg        done
);
  reg [11:0] frame_reload, ticks_left;
  reg [3:0] bits_left;
  reg [9:0] frame;

  assign tx = frame[0];
  assign busy = bits_left != 0;

  always @(posedge clk) begin
    if (!rst_n) begin
      frame      <= 10'h3ff;
      bits_left  <= 4'd0;
      ticks_left <= 0;
      frame_reload <= 0;
      done       <= 1'b0;
    end else begin
      done <= 1'b0;
      if (!busy) begin
        if (start) begin
          // Shifting in ones also supplies the optional second stop bit.
          frame        <= {1'b1, (seven_bits | data[7]), data[6:0], 1'b0};
          bits_left    <= (seven_bits ? 4'd9 : 4'd10) + two_stops;
          frame_reload <= bit_reload;
          ticks_left   <= bit_reload;
        end
      end else if (ticks_left == 0) begin
        frame      <= {1'b1, frame[9:1]};
        bits_left  <= bits_left - 1'b1;
        ticks_left <= frame_reload;
        done       <= bits_left == 4'd1;
      end else begin
        ticks_left <= ticks_left - 1'b1;
      end
    end
  end
endmodule
