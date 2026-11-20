/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_example (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // The parallel data and send strobe are synchronous to clk.
  reg send_prev;
  always @(posedge clk) begin
    if (!rst_n)
      send_prev <= 1'b0;
    else
      send_prev <= uio_in[0];
  end

  localparam integer CLOCKS_PER_BIT = 434;
  wire tx, busy, done;
  uart_tx #(.CLOCKS_PER_BIT(CLOCKS_PER_BIT)) transmitter (
    .clk(clk), .rst_n(rst_n),
    .start(uio_in[0] && !send_prev), .data(ui_in),
    .tx(tx), .busy(busy), .done(done)
  );

  wire [7:0] rx_data;
  wire rx_valid, rx_error;
  uart_rx #(.CLOCKS_PER_BIT(CLOCKS_PER_BIT)) receiver (
    .clk(clk), .rst_n(rst_n), .rx(uio_in[1]),
    .data(rx_data), .valid(rx_valid), .framing_error(rx_error)
  );

  assign uo_out  = {rx_data[7:4], rx_valid, done, busy, tx};
  assign uio_out = {rx_data[3:0], 1'b0, rx_error, 2'b0};
  assign uio_oe  = 8'b1111_0100;

  wire _unused = &{ena, uio_in[7:2], 1'b0};

endmodule
