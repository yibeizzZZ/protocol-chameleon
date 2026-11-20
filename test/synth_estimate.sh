#!/usr/bin/env bash
# Run from the repository root. Write all netlists and logs outside the checkout.
set -euo pipefail
: "${LIBERTY:?Set LIBERTY to the absolute path of an IHP standard-cell Liberty file}"
: "${ESTIMATE_DIR:?Set ESTIMATE_DIR to an output directory}"
export LIBERTY ESTIMATE_DIR
mkdir -p "$ESTIMATE_DIR"
yosys -Q -l "$ESTIMATE_DIR/yosys.log" -p "
  read_verilog src/project.v src/serial_config.v src/protocol_engine.v src/spi_target.v src/trial_checker.v src/transaction_observer.v src/feedback_policy.v src/uart_tx.v src/uart_rx.v
  hierarchy -check -top tt_um_example
  synth -flatten -noabc -top tt_um_example
  check -assert
  dfflibmap -liberty \"$LIBERTY\"
  abc -liberty \"$LIBERTY\"
  clean
  stat -liberty \"$LIBERTY\"
  write_verilog -noattr -noexpr -nohex -nodec \"$ESTIMATE_DIR/mapped.v\"
"
if [[ ${SYNTH_ONLY:-0} != 1 ]]; then
  sta -exit test/prelayout_sta.tcl | tee "$ESTIMATE_DIR/sta.log"
fi
