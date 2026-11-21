// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// The policy runs between checker trials. No host handshake on the loop path.
module feedback_policy (
    input wire clk, rst_n, selected, trial_running, strobe, control,
    input wire [7:0] host_byte,
    input wire [2:0] verdict,
    input wire [1:0] source_mask,
    input wire [15:0] stamp,
    output wire busy, start_trial,
    output wire [7:0] issue_a, issue_b,
    output wire [1:0] status_mode,
    output wire [3:0] model_param,
    output reg [3:0] page
);
  localparam IDLE=2'd0, START=2'd1, WAIT_RESULT=2'd2;
  reg [1:0] state, profile, initial_profile, last_index;
  reg [2:0] count, previous, older;
  assign busy = state != IDLE;
  assign start_trial = state == START;

  reg [5:0] condition [0:3]; // enable, exact source (3=both), current verdict
  reg [5:0] history [0:3];   // older and previous verdict predicates
  reg [2:0] action [0:3];    // stop, next profile
  reg [7:0] time_a [0:3], time_b [0:3];
  reg [1:0] modes [0:3];
  reg [3:0] params [0:3];
  reg [3:0] match_source;
  assign issue_a = time_a[profile];
  assign issue_b = time_b[profile];
  assign status_mode = busy ? modes[profile] : 2'b00;
  assign model_param = params[profile];

  reg pending;
  reg [7:0] selector;
  wire [1:0] index = selector[3:2];
  wire configure = selected && !busy && !trial_running && strobe;
  wire run = configure && control && host_byte == 8'h34;
  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      pending <= 0;
      selector <= 0;
      initial_profile <= 0;
      last_index <= 0;
      match_source <= 0;
      for (i=0; i<4; i=i+1) begin
        condition[i] <= 0;
        history[i] <= 0;
        action[i] <= 0;
        time_a[i] <= 0;
        time_b[i] <= 0;
        modes[i] <= 0;
        params[i] <= 0;
      end
    end else if (configure) begin
      pending <= control && (host_byte == 8'h51 || host_byte[7:5] == 3'b011);
      if (control) selector <= host_byte;
      else if (pending) begin
        if (selector == 8'h51) begin
          initial_profile <= host_byte[3:2];
          last_index <= host_byte[1:0];
        end else if (selector[4]) begin
          case (selector[1:0])
            0: time_a[index] <= host_byte;
            1: time_b[index] <= host_byte;
            2: modes[index] <= host_byte[1:0];
            3: params[index] <= host_byte[3:0];
          endcase
        end else begin
          case (selector[1:0])
            0: begin
              condition[index] <= host_byte[5:0];
              match_source[index] <= host_byte[6];
            end
            1: history[index] <= host_byte[5:0];
            2: action[index] <= host_byte[2:0];
            default: ;
          endcase
        end
      end
    end
  end

  // In a history predicate, 0 means ANY and 7 means no such prior trial.
  function history_matches;
    input [2:0] predicate, value;
    begin
      history_matches = predicate == 0 || predicate == value ||
                        (predicate == 7 && value == 0);
    end
  endfunction
  wire [3:0] rule_hits;
  genvar r;
  generate for (r=0; r<4; r=r+1) begin : rule
    assign rule_hits[r] = condition[r][5] &&
        (condition[r][2:0] == 0 || condition[r][2:0] == verdict) &&
        (!match_source[r] || condition[r][4:3] == source_mask) &&
        history_matches(history[r][2:0], previous) &&
        history_matches(history[r][5:3], older);
  end endgenerate
  wire [1:0] winner = rule_hits[0] ? 0 : rule_hits[1] ? 1 : rule_hits[2] ? 2 : 3;
  wire [2:0] choice = action[winner];
  wire advance = |rule_hits && !choice[2] && count[1:0] != last_index;

  // Written once per completed trial. Count gates unread/uninitialized rows.
  // Snapshot parameter values so subsequent host edits cannot rewrite history.
  reg [57:0] records [0:3];
  always @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE;
      count <= 0;
      profile <= 0;
      previous <= 0;
      older <= 0;
    end else if (run) begin
      state <= START;
      count <= 0;
      profile <= initial_profile;
      previous <= 0;
      older <= 0;
    end else if (state == START) begin
      state <= WAIT_RESULT;
    end else if (state == WAIT_RESULT && verdict != 0) begin
      records[count[1:0]] <= {model_param, (|rule_hits && choice[2]), advance, |rule_hits, winner, profile,
          (|rule_hits ? choice[1:0] : profile), older, previous, modes[profile],
          issue_b, issue_a, stamp, source_mask, verdict};
      count <= count + 1'b1;
      older <= previous;
      previous <= verdict;
      if (advance) begin
        profile <= choice[1:0];
        state <= START;
      end else state <= IDLE;
    end
  end

  wire param_page = host_byte[7:2] == 6'h31; // C4..C7: applied model parameter
  wire [1:0] row = param_page ? host_byte[1:0] : host_byte[5:4];
  wire [3:0] logged_param;
  wire logged_stop, logged_advance, logged_hit;
  wire [1:0] logged_rule, logged_profile, logged_target, logged_mode, logged_source;
  wire [2:0] logged_older, logged_previous, logged_verdict;
  wire [7:0] logged_b, logged_a;
  wire [15:0] logged_tick;
  assign {logged_param, logged_stop, logged_advance, logged_hit, logged_rule, logged_profile,
          logged_target, logged_older, logged_previous, logged_mode, logged_b,
          logged_a, logged_tick, logged_source, logged_verdict} = records[row];
  always @* begin
    page = 0;
    if (host_byte == 8'hc0) page = {busy,count};
    else if (param_page && {1'b0,row} < count) page = logged_param;
    else if (host_byte[7:6] == 2'b10 && {1'b0,row} < count) begin
      case (host_byte[3:0])
        0: page = {1'b1,logged_verdict};
        1: page = {2'b0,logged_source};
        2: page = logged_tick[3:0];
        3: page = logged_tick[7:4];
        4: page = logged_tick[11:8];
        5: page = logged_tick[15:12];
        6: page = logged_a[3:0];
        7: page = logged_a[7:4];
        8: page = logged_b[3:0];
        9: page = logged_b[7:4];
        10: page = {2'b0,logged_mode};
        11: page = {1'b0,logged_previous};
        12: page = {1'b0,logged_older};
        13: page = {logged_profile,logged_target};
        14: page = {logged_advance,logged_hit,logged_rule};
        15: page = {3'b0,logged_stop};
      endcase
    end
  end
endmodule
