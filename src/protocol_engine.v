// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module protocol_engine (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       enter,
    input  wire       strobe,
    input  wire       control,
    input  wire [7:0] host_byte,
    input  wire [3:0] pins_in,
    output reg        selected,
    output reg        running,
    output reg  [3:0] samples,
    output reg  [3:0] pins_out,
    output reg  [3:0] pins_oe
);
  localparam [7:0] EXIT = 8'h00, CLEAR = 8'h01, RUN = 8'h02, STOP = 8'h03;
  localparam [3:0] DRIVE = 4'h1, DIR = 4'h2, SAMPLE = 4'h3, DELAY = 4'h5,
                   JUMP_ONE = 4'h6, JUMP = 4'h7, RISE = 4'h8, FALL = 4'h9;

  // Only the loaded prefix is executable. No reset network on program storage.
  reg [7:0] code_mem [0:15];
  reg [4:0] length, pc;
  reg [3:0] delay_left;
  wire [7:0] instruction = code_mem[pc[3:0]];
  wire [3:0] opcode = instruction[7:4];
  wire [3:0] operand = instruction[3:0];

  reg [3:0] pin_meta, pin_sync, pin_previous;
  always @(posedge clk) begin
    if (!rst_n) begin
      pin_meta     <= 0;
      pin_sync     <= 0;
      pin_previous <= 0;
    end else begin
      pin_meta     <= pins_in;
      pin_sync     <= pin_meta;
      pin_previous <= pin_sync;
    end
  end

  wire input_bit = pin_sync[operand[1:0]];
  wire clock_bit = pin_sync[operand[3:2]];
  wire previous_clock = pin_previous[operand[3:2]];
  wire matched_edge = (clock_bit != previous_clock) && (clock_bit == (opcode == RISE));
  wire command_write = selected && strobe && control;
  wire append = selected && strobe && !control && !running && length < 5'd16;

  always @(posedge clk) begin
    if (rst_n && append)
      code_mem[length[3:0]] <= host_byte;
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      selected   <= 1'b0;
      running    <= 1'b0;
      length     <= 0;
      pc         <= 0;
      delay_left <= 0;
      samples    <= 0;
      pins_out   <= 0;
      pins_oe    <= 0;
    end else if (!selected) begin
      if (enter) begin
        selected <= 1'b1;
        length   <= 0;
        samples  <= 0;
      end
    end else if (command_write && host_byte == EXIT) begin
      selected <= 1'b0;
      running  <= 1'b0;
      pins_oe  <= 0;
    end else if (command_write && host_byte == STOP) begin
      running <= 1'b0;
      pins_oe <= 0;
    end else if (!running) begin
      if (append)
        length <= length + 1'b1;
      else if (command_write && host_byte == CLEAR)
        length <= 0;
      else if (command_write && host_byte == RUN && length != 0) begin
        running    <= 1'b1;
        pc         <= 0;
        delay_left <= 0;
        samples    <= 0;
        pins_out   <= 0;
        pins_oe    <= 0;
      end
    end else if (delay_left != 0) begin
      delay_left <= delay_left - 1'b1;
    end else if (pc >= length) begin
      running <= 1'b0;
      pins_oe <= 0;
    end else begin
      pc <= pc + 1'b1;
      case (opcode)
        DRIVE: pins_out <= operand;
        DIR:   pins_oe <= operand;
        SAMPLE: samples <= {samples[2:0], input_bit};
        DELAY: delay_left <= operand;
        JUMP_ONE: if (samples[0]) pc <= {1'b0, operand};
        JUMP: pc <= {1'b0, operand};
        RISE, FALL: begin
          if (matched_edge)
            samples <= {samples[2:0], input_bit};
          else
            pc <= pc;
        end
        default: begin // HALT and reserved opcodes
          running <= 1'b0;
          pins_oe <= 0;
        end
      endcase
    end
  end
endmodule
