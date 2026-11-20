// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module uart_tx #(
    parameter integer CLOCKS_PER_BIT = 434  // Positive number of clk cycles
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,  // One-cycle request; accepted while idle
    input  wire [7:0] data,
    output wire       tx,
    output wire       busy,
    output reg        done
);
  localparam integer COUNT_WIDTH = CLOCKS_PER_BIT > 1 ? $clog2(CLOCKS_PER_BIT) : 1;
  localparam [COUNT_WIDTH-1:0] BIT_RELOAD = CLOCKS_PER_BIT - 1;
  reg [COUNT_WIDTH-1:0] ticks_left;
  reg [3:0] bits_left;
  reg [9:0] frame;

  assign tx = frame[0];
  assign busy = bits_left != 0;

  always @(posedge clk) begin
    if (!rst_n) begin
      frame      <= 10'h3ff;
      bits_left  <= 4'd0;
      ticks_left <= 0;
      done       <= 1'b0;
    end else begin
      done <= 1'b0;
      if (!busy) begin
        if (start) begin
          frame      <= {1'b1, data, 1'b0};  // Stop, data, start; LSB exits first
          bits_left  <= 4'd10;
          ticks_left <= BIT_RELOAD;
        end
      end else if (ticks_left == 0) begin
        frame      <= {1'b1, frame[9:1]};
        bits_left  <= bits_left - 1'b1;
        ticks_left <= BIT_RELOAD;
        done       <= bits_left == 4'd1;
      end else begin
        ticks_left <= ticks_left - 1'b1;
      end
    end
  end
endmodule
