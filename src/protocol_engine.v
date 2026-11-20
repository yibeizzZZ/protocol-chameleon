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
    input  wire [2:0] byte_state,
    output wire [15:0] byte_rule,
    output wire [5:0] byte_annotation,
    output reg        annotated,
    output wire       start_byte_program,
    output reg        selected,
    output reg        running,
    output reg  [3:0] samples,
    output reg  [3:0] pins_out,
    output reg  [3:0] pins_oe
);
  localparam [7:0] EXIT = 8'h00, CLEAR = 8'h01, RUN = 8'h02, STOP = 8'h03;
  localparam [7:0] RUN_TIMED = 8'h05;
  localparam [3:0] DRIVE = 4'h1, DIR = 4'h2, SAMPLE = 4'h3, DELAY = 4'h5,
                   JUMP_ONE = 4'h6, JUMP = 4'h7, RISE = 4'h8, FALL = 4'h9;

  // Only the loaded prefix is executable. No reset network on program storage.
  // Both interpreters fetch from the same 128 bits. GPIO mode reads either
  // byte; the serial shifter needs the entire state rule at a byte boundary.
  reg [7:0] even_code [0:7];
  reg [7:0] odd_code [0:7];
  reg [5:0] annotations [0:7];
  reg field_pending;
  reg [3:0] field_index; // 0..7: byte annotations. 8..12: timed GPIO settings.
  reg [4:0] length, pc;
  reg [7:0] delay_left;
  reg timed, sample_pending;
  reg [1:0] lane;
  reg [7:0] low_reload, high_reload;
  reg [6:0] checkpoint_a, checkpoint_b; // enable and six-bit slot address
  reg [5:0] branch_slot;
  wire [2:0] fetch_addr = selected ? pc[3:1] : byte_state;
  wire [7:0] even_byte = even_code[fetch_addr];
  wire [7:0] odd_byte = odd_code[fetch_addr];
  wire [7:0] instruction = pc[0] ? odd_byte : even_byte;
  wire [1:0] low_enables = instruction[{lane, 1'b0} +: 2];
  wire [5:0] slot = {pc[3:0], lane};
  wire state_loaded = {1'b0, byte_state} < length[4:1];
  assign byte_rule = state_loaded ? {even_byte, odd_byte} : 16'd0;
  assign byte_annotation = state_loaded ? annotations[byte_state] : 6'd0;
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
  assign start_byte_program = command_write && host_byte == 8'h04 &&
                              !running && length != 0 && !length[0];
  wire data_write = selected && strobe && !control && !running;
  wire append = data_write && !field_pending && length < 5'd16;
  wire annotate = data_write && field_pending && !field_index[3] && field_index < length[4:1];
  wire select_timing = host_byte >= 8'h20 && host_byte <= 8'h24;

  always @(posedge clk) begin
    if (!rst_n || enter || (command_write && !running && host_byte == CLEAR)) begin
      field_pending <= 0;
      annotated <= 0;
      low_reload <= 1;
      high_reload <= 1;
      checkpoint_a <= 0;
      checkpoint_b <= 0;
      branch_slot <= 0;
    end else if (selected && !running && strobe) begin
      field_pending <= control && (host_byte[7:3] == 5'b00010 || select_timing);
      if (control) field_index <= {select_timing, host_byte[2:0]};
      if (data_write && field_pending) begin
        case (field_index)
          8: low_reload <= host_byte == 0 ? 8'd1 : host_byte;
          9: high_reload <= host_byte == 0 ? 8'd1 : host_byte;
          10: checkpoint_a <= host_byte[6:0];
          11: checkpoint_b <= host_byte[6:0];
          12: branch_slot <= host_byte[5:0];
          default: begin end
        endcase
      end
      if (annotate) annotated <= 1;
    end
  end

  always @(posedge clk) begin
    if (rst_n && append) begin
      if (length[0]) odd_code[length[3:1]] <= host_byte;
      else begin
        even_code[length[3:1]] <= host_byte;
        annotations[length[3:1]] <= 0;
      end
    end
    if (rst_n && annotate) annotations[field_index[2:0]] <= host_byte[5:0];
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      selected   <= 1'b0;
      running    <= 1'b0;
      length     <= 0;
      pc         <= 0;
      delay_left <= 0;
      timed      <= 0;
      lane       <= 0;
      sample_pending <= 0;
      samples    <= 0;
      pins_out   <= 0;
      pins_oe    <= 0;
    end else if (!selected) begin
      if (enter) begin
        selected <= 1'b1;
        length   <= 0;
        samples  <= 0;
      end
    end else if ((command_write && host_byte == EXIT) || start_byte_program) begin
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
      else if (command_write && (host_byte == RUN || host_byte == RUN_TIMED) && length != 0) begin
        running    <= 1'b1;
        timed      <= host_byte == RUN_TIMED;
        lane       <= 0;
        sample_pending <= 0;
        pc         <= 0;
        delay_left <= 0;
        // The timed-mode sentinel distinguishes one sample from two in readback.
        samples    <= {3'b000, host_byte == RUN_TIMED};
        pins_out   <= 0;
        pins_oe    <= 0;
      end
    end else if (delay_left != 0) begin
      delay_left <= delay_left - 1'b1;
      // Resolve the branch one clock before the next mask goes to the pads.
      if (timed && sample_pending && delay_left == 1) begin
        samples <= {samples[2:0], pin_sync[1]};
        if (pin_sync[1]) {pc, lane} <= {1'b0, branch_slot};
      end
    end else if (pc >= length) begin
      running <= 1'b0;
      pins_oe <= 0;
    end else if (timed) begin
      // RUN cleared the output latches. Only enabled pins pull the wire low.
      pins_oe <= {2'b00, low_enables};
      delay_left <= low_enables[0] ? low_reload : high_reload;
      sample_pending <= checkpoint_a == {1'b1, slot} || checkpoint_b == {1'b1, slot};
      {pc, lane} <= {pc, lane} + 1'b1;
    end else begin
      pc <= pc + 1'b1;
      case (opcode)
        DRIVE: pins_out <= operand;
        DIR:   pins_oe <= operand;
        SAMPLE: samples <= {samples[2:0], input_bit};
        DELAY: delay_left <= {4'b0, operand};
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
