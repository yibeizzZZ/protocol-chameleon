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
  reg [2:0] policy;
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
      for (i=0; i<16; i=i+1) cfg[i] <= 0;
    end else if (!selected) begin
      selected <= spi_selected && control && strobe && host_byte == 8'h30;
      write_pending <= 0;
    end else if (!running && !campaign_busy && strobe) begin
      if (control) begin
        selected <= host_byte != 8'h31;
        write_pending <= host_byte[7:4] == 4'h4 || host_byte == 8'h50;
        selector <= host_byte[4:0];
      end else if (write_pending) begin
        if (selector[4]) policy <= host_byte[2:0];
        else cfg[selector[3:0]] <= host_byte;
        write_pending <= 0;
      end
    end
  end

  reg [15:0] elapsed, stamp;
  reg [1:0] issued;
  reg [2:0] serviced [0:1];
  wire [1:0] enabled, satisfied, expired, due, invalid_window, past_end;
  genvar s;
  generate for (s=0; s<2; s=s+1) begin : slot
    wire [7:0] flags = cfg[8*s];
    wire [15:0] issue = campaign_busy ? {8'd0,(s==0 ? issue_a : issue_b)} :
                                       {cfg[8*s+4],cfg[8*s+3]};
    wire [15:0] deadline = {cfg[8*s+6],cfg[8*s+5]};
    assign enabled[s] = flags[0];
    assign satisfied[s] = serviced[s] >= ({1'b0,flags[2:1]} + 3'd1);
    assign invalid_window[s] = enabled[s] && (deadline < issue || deadline == 16'hffff);
    assign due[s] = enabled[s] && elapsed == issue;
    assign past_end[s] = !enabled[s] || elapsed > deadline;
    assign expired[s] = enabled[s] && past_end[s] && !satisfied[s];
  end endgenerate
  wire invalid_plan = enabled == 0 || |invalid_window || policy[1:0] == 3 ||
                      (policy[1:0] != 0 && enabled != 3);

  reg frame_open, early;
  reg [1:0] owner;
  reg [3:0] bytes_seen; // saturates at ten; the longest rule permits nine
  reg [7:0] cmd_byte, addr_byte;
  wire src = owner[1];
  wire [7:0] flags = src ? cfg[8] : cfg[0];
  wire bad_content = bytes_seen != ({1'b0,flags[7:5]} + 4'd2) ||
                     (flags[3] && cmd_byte != (src ? cfg[9] : cfg[1])) ||
                     (flags[4] && addr_byte != (src ? cfg[10] : cfg[2]));
  wire predecessor_missing = (policy[1:0] == 1 && src && !satisfied[0]) ||
                             (policy[1:0] == 2 && !src && !satisfied[1]);

  reg [2:0] outcome, decision;
  reg [1:0] implicated, subject;
  reg [7:0] evidence_cmd, evidence_addr;
  feedback_policy feedback (
    .clk(clk), .rst_n(rst_n), .selected(selected), .trial_running(running),
    .strobe(strobe), .control(control), .host_byte(host_byte),
    .verdict(outcome), .source_mask(implicated), .stamp(stamp),
    .busy(campaign_busy), .start_trial(auto_start), .issue_a(issue_a),
    .issue_b(issue_b), .status_mode(status_mode), .page(campaign_page)
  );
  always @* begin
    decision = 0;
    subject = owner;
    if ((command && host_byte == 8'h33) || cs_active == 3 ||
        (frame_open && cs_active != 0 && cs_active != owner)) begin
      decision = UNKNOWN;
      subject = (frame_open ? owner : 2'b00) | cs_active;
    end else if (frame_end && (!frame_open || partial_byte || bytes_seen < 2)) begin
      decision = UNKNOWN;
    end else if (|expired) begin
      decision = TIMEOUT;
      subject = expired;
    end else if (&past_end) begin
      decision = PASS;
      subject = 0;
    end else if (frame_end) begin
      if (!enabled[src] || early) decision = ORDER_ERROR;
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
      early <= 0;
      owner <= 0;
      bytes_seen <= 0;
      cmd_byte <= 0;
      addr_byte <= 0;
      evidence_cmd <= 0;
      evidence_addr <= 0;
    end else if (running) begin
      elapsed <= elapsed + 1'b1;
      issued <= issued | due;
      if (frame_start) begin
        owner <= cs_active;
        early <= (((issued | due) & cs_active) == 0);
        frame_open <= 1;
        bytes_seen <= 0;
        cmd_byte <= 0;
        addr_byte <= 0;
      end
      if (byte_valid) begin
        if (bytes_seen == 0) cmd_byte <= observed_byte;
        if (bytes_seen == 1) addr_byte <= observed_byte;
        if (bytes_seen < 10) bytes_seen <= bytes_seen + 1'b1;
      end
      if (frame_end) begin
        frame_open <= 0;
        if (decision == 0) serviced[src] <= serviced[src] + 1'b1;
      end
      if (decision != 0) begin
        running <= 0;
        outcome <= decision;
        implicated <= subject;
        stamp <= elapsed;
        if (frame_open && |(owner & subject)) begin
          evidence_cmd <= cmd_byte;
          evidence_addr <= addr_byte;
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
      default: page = 0;
    endcase
  end
  wire feedback_read = host_byte[7:6] == 2'b10 || host_byte == 8'hc0;
  assign outputs = {feedback_read ? campaign_page : page, !campaign_busy && outcome != 0,
                    campaign_busy || running, issued & ~satisfied & {2{running}}};
endmodule
