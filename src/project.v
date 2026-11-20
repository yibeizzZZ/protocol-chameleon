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

  wire strobe = uio_in[0] && !send_prev;
  wire config_mode = uio_in[3];
  wire [11:0] bit_reload;
  wire seven_bits, two_stops;
  wire enter_engine, engine_selected, engine_running;
  wire enter_spi, spi_selected, miso, miso_oe;
  wire uart_host = !engine_selected && !spi_selected;
  wire [3:0] engine_out, engine_oe, engine_samples;
  serial_config settings (
    .clk(clk), .rst_n(rst_n), .write(strobe && config_mode && uart_host),
    .command(ui_in), .enter_engine(enter_engine), .enter_spi(enter_spi),
    .bit_reload(bit_reload), .seven_bits(seven_bits), .two_stops(two_stops)
  );

  spi_target peripheral (
    .clk(clk), .rst_n(rst_n), .enter(enter_spi), .selected(spi_selected),
    .strobe(strobe), .control(config_mode), .host_byte(ui_in),
    .cs_n(uio_in[4]), .sclk(uio_in[5]), .mosi(uio_in[6]),
    .miso(miso), .miso_oe(miso_oe)
  );

  protocol_engine engine (
    .clk(clk), .rst_n(rst_n), .enter(enter_engine),
    .strobe(strobe), .control(config_mode), .host_byte(ui_in),
    .pins_in(uio_in[7:4]), .selected(engine_selected), .running(engine_running),
    .samples(engine_samples), .pins_out(engine_out), .pins_oe(engine_oe)
  );

  wire tx, busy, done;
  uart_tx transmitter (
    .clk(clk), .rst_n(rst_n),
    .start(strobe && !config_mode && uart_host), .data(ui_in),
    .bit_reload(bit_reload), .seven_bits(seven_bits), .two_stops(two_stops),
    .tx(tx), .busy(busy), .done(done)
  );

  wire [7:0] rx_data;
  wire rx_valid, rx_error;
  uart_rx receiver (
    .clk(clk), .rst_n(rst_n), .rx(uio_in[1]),
    .bit_reload(bit_reload), .seven_bits(seven_bits), .two_stops(two_stops),
    .data(rx_data), .valid(rx_valid), .framing_error(rx_error)
  );

  assign uo_out  = {engine_selected ? engine_samples : rx_data[7:4], rx_valid, done, busy, tx};
  wire [3:0] upper_out = spi_selected ? {miso, 3'b0} :
                         engine_selected ? engine_out : rx_data[3:0];
  wire [3:0] upper_oe = spi_selected ? {miso_oe, 3'b0} :
                        engine_selected ? engine_oe : 4'b1111;
  assign uio_out = {upper_out, 1'b0,
                    engine_selected ? engine_running : rx_error, 2'b0};
  assign uio_oe  = {upper_oe, 4'b0100};

  wire _unused = &{ena, uio_in[2], 1'b0};

endmodule
