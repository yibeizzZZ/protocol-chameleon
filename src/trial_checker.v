// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Two independently scheduled notification sources; all times in clk cycles.
// Observe the shifter's byte/end strobes without adding a stage to SPI launch.
module trial_checker (
    input wire clk, rst_n, spi_selected, strobe, control,
    input wire [7:0] host_byte,
    input wire [1:0] cs_n,
    input wire frame_start, frame_end, byte_valid, partial_byte,
    input wire [7:0] observed_byte,
    input wire logical_transactions, logical_end, byte_start,
    input wire [4:0] fields,
    input wire [7:0] observed_reply,
    output reg selected,
    output wire bank_enable, bank_id,
    output wire [1:0] status_mode,
    output wire [7:0] outputs
);
  localparam [2:0] PASS=1, TIMEOUT=2, DUPLICATE=3, WRONG_CONTENT=4,
                   ORDER_ERROR=5, UNKNOWN=6;
  (* async_reg = "true" *) reg [1:0] cs_meta, cs_active;
  always @(posedge clk) begin
    if (!rst_n) begin
      cs_meta <= 0;
      cs_active <= 0;
    end else begin
      cs_meta <= ~cs_n;
      cs_active <= cs_meta;
    end
  end

  reg [7:0] cfg [0:15]; // two eight-byte descriptors, layout in docs/info.md
  reg [7:0] policy;
  reg [7:0] expected_data [0:1];
  reg reactive, accepted_only, target_slot, relative_deadline;
  reg [1:0] ordinal_minus_one;
  reg [7:0] trigger_tag, trigger_delay, service_window;
  reg [4:0] selector;
  reg write_pending, running;
  wire command = selected && strobe && control;
  wire campaign_busy, auto_start;
  wire [7:0] issue_a, issue_b;
  wire [3:0] campaign_page;
  wire start = auto_start || (command && host_byte == 8'h32 && !running && !campaign_busy);
  assign bank_enable = selected && policy[2];
  assign bank_id = cs_active[1];

  integer i;
  always @(posedge clk) begin
    if (!rst_n) begin
      selected <= 0;
      write_pending <= 0;
      selector <= 0;
      policy <= 0;
      expected_data[0] <= 0;
      expected_data[1] <= 0;
      {reactive, accepted_only, target_slot, relative_deadline, ordinal_minus_one} <= 0;
      trigger_tag <= 0;
      trigger_delay <= 0;
      service_window <= 0;
      for (i=0; i<16; i=i+1) cfg[i] <= 0;
    end else if (!selected) begin
      selected <= spi_selected && control && strobe && host_byte == 8'h30;
      write_pending <= 0;
    end else if (!running && !campaign_busy && strobe) begin
      if (control) begin
        selected <= host_byte != 8'h31;
        write_pending <= host_byte[7:4] == 4'h4 || host_byte == 8'h50 ||
                         host_byte[7:1] == 7'h29 || host_byte[7:2] == 6'h15;
        selector <= host_byte[4:0];
      end else if (write_pending) begin
        if (!selector[4]) cfg[selector[3:0]] <= host_byte;
        else case (selector)
          5'h10: policy <= host_byte;
          5'h12, 5'h13: expected_data[selector[0]] <= host_byte;
          5'h14: {reactive, accepted_only, target_slot, relative_deadline, ordinal_minus_one}
                     <= {host_byte[7:4], host_byte[1:0]};
          5'h15: trigger_tag <= host_byte;
          5'h16: trigger_delay <= host_byte;
          5'h17: service_window <= host_byte;
          default: ;
        endcase
        write_pending <= 0;
      end
    end
  end

  reg [15:0] elapsed, stamp;
  reg [1:0] issued;
  reg [2:0] serviced [0:1];
  reg trigger_fired, trigger_issued;
  reg [2:0] occurrences;
  reg [7:0] remaining;
  wire reactive_due;
  wire relative_overdue = relative_deadline && trigger_issued && remaining == 0;
  wire [1:0] enabled, satisfied, expired, due, invalid_window, past_end;
  genvar s;
  generate for (s=0; s<2; s=s+1) begin : slot
    wire [7:0] flags = cfg[8*s];
    wire [15:0] issue = campaign_busy ? {8'd0,(s==0 ? issue_a : issue_b)} :
                                       {cfg[8*s+4],cfg[8*s+3]};
    wire [15:0] deadline = {cfg[8*s+6],cfg[8*s+5]};
    wire waits_for_record = reactive && target_slot == s;
    assign enabled[s] = flags[0];
    assign satisfied[s] = serviced[s] >= ({1'b0,flags[2:1]} + 3'd1);
    assign invalid_window[s] = enabled[s] && ((!waits_for_record && deadline < issue) ||
                                              deadline == 16'hffff);
    assign due[s] = enabled[s] && (waits_for_record ? reactive_due : elapsed == issue);
    assign past_end[s] = !enabled[s] || elapsed > deadline;
    assign expired[s] = enabled[s] && !satisfied[s] &&
                        (past_end[s] || (waits_for_record && relative_overdue));
  end endgenerate
  wire use_tag = logical_transactions && policy[3];
  wire invalid_plan = enabled == 0 || |invalid_window || policy[1:0] == 3 ||
                      (reactive && (!logical_transactions || !enabled[target_slot])) ||
                      (use_tag && cfg[7] == cfg[15]) ||
                      (policy[1:0] != 0 && enabled != 3);

  reg frame_open;
  reg [1:0] owner, eligible_at_start;
  wire txn_start, txn_end, truncated;
  wire [3:0] length, present;
  wire [7:0] tag, cmd_byte, addr_byte, data_byte;
  transaction_observer observer (
    .clk(clk), .rst_n(rst_n), .running(running), .logical_transactions(logical_transactions),
    .logical_end(logical_end),
    .frame_start(frame_start), .frame_end(frame_end), .byte_start(byte_start),
    .byte_valid(byte_valid), .partial_byte(partial_byte), .fields(fields),
    .mosi_byte(observed_byte), .miso_byte(observed_reply),
    .txn_start(txn_start), .txn_end(txn_end), .truncated(truncated),
    .length(length), .present(present), .tag(tag), .cmd(cmd_byte), .addr(addr_byte), .data(data_byte)
  );
  wire [1:0] tag_match = {2{present[3]}} & {tag == cfg[15], tag == cfg[7]};
  wire [1:0] identity = use_tag ? tag_match : owner;
  wire src = identity[1];
  wire [7:0] flags = src ? cfg[8] : cfg[0];
  wire single_byte = logical_transactions && (src ? policy[7] : policy[6]);
  wire [3:0] expected_length = single_byte ? 4'd1 : {1'b0,flags[7:5]} + 4'd2;
  wire check_data = logical_transactions && (src ? policy[5] : policy[4]);
  wire bad_content = length != expected_length ||
                     (flags[3] && (!present[2] || cmd_byte != (src ? cfg[9] : cfg[1]))) ||
                     (flags[4] && (!present[1] || addr_byte != (src ? cfg[10] : cfg[2]))) ||
                     (check_data && (!present[0] || data_byte != expected_data[src]));
  wire predecessor_missing = (policy[1:0] == 1 && src && !satisfied[0]) ||
                             (policy[1:0] == 2 && !src && !satisfied[1]);

  reg [2:0] outcome, decision;
  // A raw record may match even on a failing check. The witness records that
  // fact, while a terminal decision always wins over issuing a notification.
  wire match_record = reactive && !trigger_fired && txn_end && frame_open &&
                      cs_active == owner && (owner == 1 || owner == 2) &&
                      present[3] && tag == trigger_tag && (!accepted_only || decision == 0);
  wire fire_now = match_record && occurrences[1:0] == ordinal_minus_one;
  wire [7:0] delay_ticks = campaign_busy ? (target_slot ? issue_b : issue_a) : trigger_delay;
  assign reactive_due = !trigger_issued && decision == 0 &&
                        ((fire_now && delay_ticks == 0) || (trigger_fired && remaining == 0));
  always @(posedge clk) begin
    if (!rst_n || start) begin
      trigger_fired <= 0;
      trigger_issued <= 0;
      occurrences <= 0;
      remaining <= 0;
    end else if (running && reactive) begin
      if (match_record) occurrences <= occurrences + 1'b1;
      if (fire_now) trigger_fired <= 1;
      if (reactive_due) begin
        trigger_issued <= 1;
        remaining <= service_window;
      end else if (fire_now && delay_ticks != 0) remaining <= delay_ticks - 1'b1;
      else if (remaining != 0) remaining <= remaining - 1'b1;
    end
  end
  reg [1:0] implicated, subject;
  reg [7:0] evidence_cmd, evidence_addr, evidence_data, evidence_tag;
  feedback_policy feedback (
    .clk(clk), .rst_n(rst_n), .selected(selected), .trial_running(running),
    .strobe(strobe), .control(control), .host_byte(host_byte),
    .verdict(outcome), .source_mask(implicated), .stamp(stamp),
    .busy(campaign_busy), .start_trial(auto_start), .issue_a(issue_a),
    .issue_b(issue_b), .status_mode(status_mode), .page(campaign_page)
  );
  always @* begin
    decision = 0;
    subject = identity;
    if ((command && host_byte == 8'h33) || cs_active == 3 ||
        (frame_open && cs_active != 0 && cs_active != owner)) begin
      decision = UNKNOWN;
      subject = (frame_open ? owner : 2'b00) | cs_active;
    end else if ((frame_end && (!frame_open || truncated)) ||
                 (txn_end && use_tag && !present[3])) begin
      decision = UNKNOWN;
    end else if (|expired) begin
      decision = TIMEOUT;
      subject = expired;
    end else if (&past_end) begin
      decision = PASS;
      subject = 0;
    end else if (txn_end) begin
      if (use_tag && identity == 0) decision = WRONG_CONTENT;
      else if (!enabled[src] || !eligible_at_start[src]) decision = ORDER_ERROR;
      else if (satisfied[src]) decision = DUPLICATE;
      else if (bad_content) decision = WRONG_CONTENT;
      else if (predecessor_missing) decision = ORDER_ERROR;
    end
  end

  always @(posedge clk) begin
    if (!rst_n || start) begin
      running <= rst_n && !invalid_plan && cs_active == 0;
      outcome <= (rst_n && (invalid_plan || cs_active != 0)) ? UNKNOWN : 0;
      implicated <= rst_n ? cs_active : 2'b0;
      elapsed <= 0;
      stamp <= 0;
      issued <= 0;
      serviced[0] <= 0;
      serviced[1] <= 0;
      frame_open <= 0;
      eligible_at_start <= 0;
      owner <= 0;
      evidence_cmd <= 0;
      evidence_addr <= 0;
      evidence_data <= 0;
      evidence_tag <= 0;
    end else if (running) begin
      elapsed <= elapsed + 1'b1;
      issued <= issued | due;
      if (txn_start) eligible_at_start <= issued | due;
      if (frame_start) begin
        owner <= cs_active;
        frame_open <= 1;
      end
      if (frame_end) frame_open <= 0;
      if (txn_end && decision == 0) serviced[src] <= serviced[src] + 1'b1;
      if (decision != 0) begin
        running <= 0;
        outcome <= decision;
        implicated <= subject;
        stamp <= elapsed;
        if (frame_open && (|(identity & subject) || (txn_end && decision == WRONG_CONTENT))) begin
          evidence_cmd <= cmd_byte;
          evidence_addr <= addr_byte;
          evidence_data <= data_byte;
          evidence_tag <= tag;
        end
      end
    end
  end

  reg [3:0] page;
  always @* begin
    case (host_byte[3:0])
      0: page = {1'b0,outcome};
      1: page = {2'b0,implicated};
      2: page = stamp[3:0];
      3: page = stamp[7:4];
      4: page = stamp[11:8];
      5: page = stamp[15:12];
      6: page = evidence_cmd[3:0];
      7: page = evidence_cmd[7:4];
      8: page = evidence_addr[3:0];
      9: page = evidence_addr[7:4];
      10: page = {1'b0,serviced[0]};
      11: page = {1'b0,serviced[1]};
      12: page = evidence_data[3:0];
      13: page = evidence_data[7:4];
      14: page = evidence_tag[3:0];
      15: page = evidence_tag[7:4];
    endcase
  end
  wire feedback_read = host_byte[7:6] == 2'b10 || host_byte == 8'hc0;
  wire [3:0] readback = feedback_read ? campaign_page :
                        host_byte == 8'hd0 ? {2'b0,trigger_issued,trigger_fired} :
                        host_byte == 8'hd1 ? {1'b0,occurrences} : page;
  assign outputs = {readback, !campaign_busy && outcome != 0,
                    campaign_busy || running, issued & ~satisfied & {2{running}}};
endmodule
