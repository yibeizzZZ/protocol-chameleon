// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Two host writes describe a frame. Only the second write changes live settings.
module serial_config (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        write,
    input  wire [7:0]  command,
    output wire        enter_engine,
    output wire        enter_spi,
    output reg  [11:0] bit_reload,
    output reg         seven_bits,
    output reg         two_stops
);
  localparam [11:0] DEFAULT_RELOAD = 12'd433;  // 434 clocks, 115200 baud at 50 MHz
  reg [6:0] timing_low;
  wire [11:0] requested_reload = {command[6:2], timing_low};
  // This pair previously requested an invalid one-clock UART period.
  assign enter_engine = write && timing_low == 7'd0 && command == 8'h83;
  assign enter_spi = write && timing_low == 7'd0 && command == 8'h82;

  always @(posedge clk) begin
    if (!rst_n) begin
      timing_low <= DEFAULT_RELOAD[6:0];
      bit_reload <= DEFAULT_RELOAD;
      seven_bits <= 1'b0;
      two_stops  <= 1'b0;
    end else if (write) begin
      if (!command[7]) begin
        timing_low <= command[6:0];
      end else if (requested_reload >= 12'd7) begin
        bit_reload <= requested_reload;
        seven_bits <= command[0];
        two_stops  <= command[1];
      end
    end
  end
endmodule
