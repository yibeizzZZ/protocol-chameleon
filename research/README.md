# Reproduce the internal research evaluation

From the repository root under Linux, use Python 3.11, Cocotb 2.0.1 and Icarus for development and boundary measurements, and Verilator with a C++17 compiler for the paired pin-level experiment. A/B use the actual synthesized-design input RTL compiled by Verilator. The C++ wrapper drives external pins and samples MISO with output-enable checks. All generated service data are synthetic.

```sh
python3 research/check_inputs.py
lib=$(bash research/build_wire.sh)
python research/experiment.py train "$lib"
python research/experiment.py run "$lib" --workers 8
python research/experiment.py replay "$lib"
python research/check_panel_witnesses.py "$lib"
python -B research/panel.py
python research/run_boundary.py
python research/history_probe.py
python research/analyze.py
```

Training imports only the public development models. Formal runs check the SHA-256 seal of the evaluator module, then load its opaque cases. `development.json` freezes the selected scan. The published thresholds specify a search budget; confirmation and peer-free playback have separate costs. The three gzip JSON Lines streams under `results/` contain one paired-seed summary per method and variant, every completed search block, and the candidate blocks with three actual reset repeats plus a timed replay. Run the replay command in a fresh process to drive the saved MOSI and sample MISO without constructing any peer. The wire digest includes phase relative to the first poll of each window and the measured IRQ gap. Absolute time offsets from the start of each block, including the host's inter-window gap, are in the raw frames.

In the traces, each search block stores its index, settings, windows and measured resource counters. Settings are [first reply, scan reply, random reply, first B gap, second B gap]. Each frame is [start in system clocks, select, MOSI bytes, MISO bytes]. Each record is [P4 verdict, source mask, decision tick]. Strobe counts include RUNs. Read counts include six witness nibbles per completed window, plus the three binding pages needed by the host decision. Each page access advances the core by one clock. A reset count covers a fresh chip and peer per block. At the second single-window RUN the host keeps both intact. The timing includes data collection and configuration as implemented by this driver.

The main run used Verilator 5.032, GCC, Python 3.11, eight worker processes and system-clock cycle accounting. A clean Git export of framework commit `ddbbcbf` was rebuilt and trained independently. Its search, raw trace and witness JSON Lines streams matched the first run byte for byte after decompression. In a fresh process all 1,530 saved candidate blocks replayed without their peers. Gzip header creation times may differ between executions.

The [run manifest](results/provenance.json) records source revisions, tool versions, the seed list, the release and panel digests, and hashes of the uncompressed result streams.

A/B load the same four-rule SPI image (8 of 16 instruction bytes and four annotation writes), two service slots and one wire-field binding. The on-chip method uses one feedback rule and two timing profiles; the one-window methods program the reply seed and the first profile between RUNs. These are allocations in the frozen 155,696.310 µm² mapped design. [Release timing and area](../docs/P5_PHYSICAL_ACCEPTANCE.md)

After the comparison was complete, the evaluator's ten directed witnesses and ten matched healthy controls were also driven through the pin interface. All ten defects have reachable legal witnesses, including the response wrap from 255 to 0 that all three search methods missed. These directed cases have no effect on the discovery score. [Directed pin records](results/directed-audit.json) · [Evaluator's model-level audit](PANEL_AUDIT.md)
