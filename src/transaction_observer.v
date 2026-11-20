// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Assemble wire observations. This module has no expected values, event
// quotas or verdict input. A marked byte closes and belongs to the record.
module transaction_observer (
    input wire clk, rst_n, running, logical_transactions, logical_end,
    input wire frame_start, frame_end, byte_start, byte_valid, partial_byte,
    input wire [4:0] fields,
    input wire [7:0] mosi_byte, miso_byte,
    output wire txn_start, txn_end, truncated,
    output wire [3:0] length, present,
    output wire [7:0] tag, cmd, addr, data
);
  reg in_logical, completed_in_frame;
  reg [3:0] count, captured;
  reg [7:0] saved_tag, saved_cmd, saved_addr, saved_data;

  assign txn_start = logical_transactions ? byte_start && !in_logical : frame_start;
  assign txn_end = logical_transactions ? logical_end : frame_end;
  assign truncated = frame_end && (partial_byte ||
                    (logical_transactions ? in_logical || !completed_in_frame : count < 2));

  // Legacy records take command/address from the first two MOSI bytes.
  wire [3:0] roles = logical_transactions ? fields[4:1] :
                     {1'b0, count == 0, count == 1, 1'b0};
  wire [3:0] capture = {4{byte_valid}} & roles;
  assign length = byte_valid && count < 10 ? count + 1'b1 : count;
  assign present = captured | capture;
  assign tag  = capture[3] ? mosi_byte : saved_tag;
  assign cmd  = capture[2] ? mosi_byte : saved_cmd;
  assign addr = capture[1] ? mosi_byte : saved_addr;
  assign data = capture[0] ? (fields[0] ? miso_byte : mosi_byte) : saved_data;

  always @(posedge clk) begin
    if (!rst_n || !running || frame_start || frame_end)
      completed_in_frame <= 0;
    else if (txn_end)
      completed_in_frame <= 1;

    if (!rst_n || !running || frame_start || frame_end || txn_end) begin
      in_logical <= 0;
      count <= 0;
      captured <= 0;
      saved_tag <= 0;
      saved_cmd <= 0;
      saved_addr <= 0;
      saved_data <= 0;
    end else begin
      if (byte_start) in_logical <= 1;
      if (byte_valid) begin
        count <= length;
        captured <= present;
        saved_tag <= tag;
        saved_cmd <= cmd;
        saved_addr <= addr;
        saved_data <= data;
      end
    end
  end
endmodule
