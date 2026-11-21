/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_forg_protocol_chameleon (
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
  wire start_byte_program;
  wire [2:0] byte_state;
  wire [15:0] byte_rule;
  wire annotated, logical_transactions, logical_end, byte_start;
  wire [5:0] byte_annotation;
  wire [4:0] fields;
  wire [7:0] observed_reply;
  wire trial_selected, bank_enable, bank_id;
  wire [1:0] status_mode;
  wire [3:0] model_param;
  wire [15:0] program_operands;
  wire frame_start, frame_end, byte_valid, partial_byte;
  wire [7:0] observed_byte, trial_outputs;
  wire uart_host = !engine_selected && !spi_selected;
  wire [3:0] engine_out, engine_oe, engine_samples;
  serial_config settings (
    .clk(clk), .rst_n(rst_n), .write(strobe && config_mode && uart_host),
    .command(ui_in), .enter_engine(enter_engine), .enter_spi(enter_spi),
    .bit_reload(bit_reload), .seven_bits(seven_bits), .two_stops(two_stops)
  );

  spi_target peripheral (
    .clk(clk), .rst_n(rst_n), .enter(enter_spi), .selected(spi_selected),
    .start_byte_program(start_byte_program), .byte_state(byte_state), .byte_rule(byte_rule),
    .annotated(annotated), .byte_annotation(byte_annotation), .miso_pad(uio_in[7]),
    .logical_transactions(logical_transactions), .logical_end(logical_end), .byte_start(byte_start),
    .fields(fields), .observed_reply(observed_reply),
    .strobe(strobe && !trial_selected), .control(config_mode), .host_byte(ui_in),
    .cs_n(uio_in[4] && (!trial_selected || uio_in[1])), .sclk(uio_in[5]), .mosi(uio_in[6]),
    .bank_enable(bank_enable), .bank_id(bank_id), .status_mode(status_mode),
    .model_param(model_param), .program_operands(program_operands),
    .frame_start(frame_start), .frame_end(frame_end), .byte_valid(byte_valid),
    .partial_byte(partial_byte), .observed_byte(observed_byte),
    .miso(miso), .miso_oe(miso_oe)
  );

  trial_checker trials (
    .clk(clk), .rst_n(rst_n), .spi_selected(spi_selected),
    .strobe(strobe), .control(config_mode), .host_byte(ui_in),
    .cs_n({uio_in[1], uio_in[4]}), .frame_start(frame_start), .frame_end(frame_end),
    .byte_valid(byte_valid), .partial_byte(partial_byte), .observed_byte(observed_byte),
    .selected(trial_selected), .bank_enable(bank_enable), .bank_id(bank_id),
    .logical_transactions(logical_transactions), .logical_end(logical_end), .byte_start(byte_start),
    .fields(fields), .observed_reply(observed_reply),
    .outputs(trial_outputs), .status_mode(status_mode), .model_param(model_param),
    .program_operands(program_operands)
  );

  protocol_engine engine (
    .clk(clk), .rst_n(rst_n), .enter(enter_engine),
    .strobe(strobe), .control(config_mode), .host_byte(ui_in),
    .pins_in(uio_in[7:4]), .selected(engine_selected), .running(engine_running),
    .start_byte_program(start_byte_program), .byte_state(byte_state), .byte_rule(byte_rule),
    .samples(engine_samples), .pins_out(engine_out), .pins_oe(engine_oe),
    .annotated(annotated), .byte_annotation(byte_annotation)
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
    .clk(clk), .rst_n(rst_n), .rx(trial_selected || uio_in[1]),
    .bit_reload(bit_reload), .seven_bits(seven_bits), .two_stops(two_stops),
    .data(rx_data), .valid(rx_valid), .framing_error(rx_error)
  );

  assign uo_out  = trial_selected ? trial_outputs :
                   {engine_selected ? engine_samples : rx_data[7:4], rx_valid, done, busy, tx};
  wire [3:0] upper_out = spi_selected ? {miso, 3'b0} :
                         engine_selected ? engine_out : rx_data[3:0];
  wire [3:0] upper_oe = spi_selected ? {miso_oe, 3'b0} :
                        engine_selected ? engine_oe : 4'b1111;
  assign uio_out = {upper_out, 1'b0,
                    engine_selected ? engine_running : rx_error, 2'b0};
  assign uio_oe  = {upper_oe, 4'b0100};

  wire _unused = &{ena, uio_in[2], 1'b0};

endmodule
