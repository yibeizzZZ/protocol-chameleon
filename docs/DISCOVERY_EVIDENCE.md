# Autonomous discovery and replay

**Status: local development verification.** The three public fault models contribute zero cases to the independent hidden-DUT evaluation.

The later internal study kept these cases in training, froze its policies, then compared them on a separately authored ten-model panel. It publishes the misses, paired-seed results and full cost of confirmation. [Research evaluation](../research/RESEARCH_RESULTS.md)

The frozen design at `6fd555b` found three response-dependent service errors in three public controller models. All three reproduced from reset and on the archived functional gate netlist. The models and the experiment were authored together. The independent ten-variant T5 panel is still open. [v0.7 acceptance target](PRODUCT_SPEC.md#e-hidden-evaluation) · [Recorded pin evidence](evidence/discovery-local.json) · [Gate netlist provenance](P5_PHYSICAL_ACCEPTANCE.md)

## Experiment and results

At tick zero both peripherals request service. The controller polls A, placing its own byte on MOSI, and normally acknowledges B with command `55`. Each request is a three-byte SPI frame. Both services are due by inclusive tick 800. The loaded P4 contract checks the two quotas, length and B command. After a passing trial the loaded P5 rule copies the byte observed on A into a reply operand. The next A poll returns it on MISO. The controller model chooses its subsequent bus operation using the reply it actually sampled. One RUN starts the two trials. Host data, mode and strobe are monitored throughout execution and result pages are read after DONE.

| Controller | Trial 1 | Trial 2 with feedback | P4 source / decision tick | Trial 2 with edit disabled |
| --- | --- | --- | --- | --- |
| Healthy | PASS | PASS | none / 801 | PASS |
| Omits B after the echoed byte | PASS | TIMEOUT | B / 801 | PASS |
| Repeats A after the echoed byte | PASS | DUPLICATE | A / 488 | PASS |
| Sends the wrong B command after the echoed byte | PASS | WRONG_CONTENT | B / 488 | PASS |

The control changes only the loaded edit byte, from `E0` (copy) to `00` (hold). The control and discovery have identical first-trial wire traffic. In each positive case discovery took two valid trials. Three fresh two-trial campaigns then reproduced the complete result. A further run replaced the controller with a timed playback of the recorded select and MOSI frames. Including the edit-disabled control and playback, each model used 12 trials. The healthy controller passed throughout.

The oracle decodes both data pins, checks which chip select was active and derives the expected verdict and source from observed services. The JSON includes frame times in 20 ns clocks, bytes in both directions, the recorded operand, rule, verdict, source and decision tick. A SHA-256 digest covers changes in the controller inputs, resolved pads, dedicated outputs and output enables sampled after each system clock. The digest compares runs at that sampling resolution. The stimulus is the frame list and fixed mode-0, 5 MHz driver in the harness. [Harness and wire oracle](../test/test_discovery.py)

## Reproduce

With the project's Cocotb dependencies active, run from the repository root. The second invocation reads the saved frames into a fresh simulation and checks both policies without instantiating any controller model.

```sh
DISCOVERY_EVIDENCE=/tmp/discovery.json make -C test COCOTB_TEST_MODULES=test_discovery FST=-none
DISCOVERY_REPLAY="$PWD/docs/evidence/discovery-local.json" make -C test COCOTB_TEST_MODULES=test_discovery FST=-none
```

The full RTL regression passed 67/67 and the assembler passed 11/11. The new discovery case also passed against the gate netlist inside the frozen submission. Its complete evidence JSON matched the RTL run byte-for-byte. For a gate rerun, use the documented Icarus 13 environment, copy the release netlist to `test/gate_level_netlist.v` and set `GATES=yes` on the first command. Area, extracted timing and GDS correspond to the same frozen RTL. [Gate simulation setup and physical results](P5_PHYSICAL_ACCEPTANCE.md)

## Independent panel handoff

An evaluator can supply ten undisclosed deterministic controller models within this experiment's two-trial, two-select envelope. Freeze the harness and policy before receiving the panel and record the panel digest before running. The evaluator retains the concealed fault conditions and confirms the classifications after the run. The public calibration and a synthetic scoring-threshold exercise are excluded from the hidden score.

Provide a Python module on `PYTHONPATH` exporting `case_ids()` (ten distinct opaque strings) and `new_peer(case_id)` (a fresh controller with the same initial state on each invocation). Its `poll()` returns the three MOSI bytes for A. Its `after_reply(miso_bytes)` returns an ordered sequence of `(slot, three_mosi_bytes)` services, with slot 0 for A and slot 1 for B. An empty sequence omits the remaining service. Each model receives only the sampled A reply and uses its own state. Keep the traffic inside the 800-clock window and the harness's supported verdict classes. Models that need different framing, DUT-controlled timing or a longer campaign require another preregistered experiment.

**Clock, reset and ownership.** The harness drives the ASIC system clock at 50 MHz (20 ns) and holds active-low reset across two rising edges before releasing it. It reloads the experiment for each campaign, including every confirmation. The peer factory must reset all simulated controller state for a new campaign and retain that state between the two trials. For a seeded model, use the same private seed on reset. The harness waits for both notification pins before invoking the peer. It owns the two active-low selects, MOSI and the 5 MHz mode-0 clock, and samples MISO at the rising edge. Peer callbacks return bytes synchronously and do not drive pins or advance simulator time. One three-byte service occupies 250 system clocks including deselect time.

For example, a healthy peer can return `[1, device_byte, 0]` from `poll()` and `[(1, [2, 0x55, 0])]` from `after_reply()` for every A reply. Choose a nonzero device byte to distinguish feedback from the reset reply. The evaluator may implement the callbacks independently and keep their code outside the project.

```sh
PYTHONPATH="/path/to/panel:${PYTHONPATH:-}" DISCOVERY_PEERS=panel_module \
  DISCOVERY_EVIDENCE=/tmp/panel.json make -C test COCOTB_TEST_MODULES=test_discovery FST=-none
```

Every supplied ID is evaluated. Credit requires an all-PASS control, matching first-trial frames, a changed second A reply, an independently corroborated second-trial failure, three identical fresh confirmations and exact wire playback. The runner writes the panel results before applying the 8/10 threshold. A simulator error or unsupported peer stimulus invalidates a run. A panel supplied by the experiment author cannot establish independent concealment.

### Result and replay interface

The JSON root identifies the suite and maps opaque case IDs under `cases`. Each case contains the following fields.

| Field | Meaning |
| --- | --- |
| `control`, `discovery` | Edit-disabled and feedback-enabled campaigns. Each contains ordered trial `records`, per-trial bus `frames`, `duration_clocks` and a sampled-pin digest. |
| `records[i]` | Chip verdict (1 PASS, 2 TIMEOUT, 3 DUPLICATE, 4 WRONG_CONTENT here), source mask (A=1, B=2), decision tick relative to trial tick zero, applied parameters, prior verdicts and winning rule. |
| `frames[i][j]` | Bus slot, decoded MOSI and MISO byte lists, and frame start/end offsets in system clocks from the campaign recorder origin immediately after the RUN helper returns. |
| `confirmations`, `differences` | Ordered pin digests of three fresh campaigns and the full results of any mismatching confirmations or playback. |
| `playback_sha256`, `confirmed_discovery` | Pin digest after replaying saved traffic and whether this case met all discovery and reproduction criteria. |

To reproduce an evaluator result, set `DISCOVERY_REPLAY` to its JSON path and use the second command in the reproduction section. Playback reloads each policy from reset, drives the recorded MOSI frames at their saved offsets, samples new MISO and rereads P4/P5 records. It needs the frozen harness and design. The private peer module is needed only to regenerate the original adaptive run or the fresh confirmations.
