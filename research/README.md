# Reproduce the internal research evaluation

From the repository root under Linux, use Python 3.11, Cocotb 2.0.1 and Icarus for development and boundary measurements, and Verilator with a C++17 compiler for the paired pin-level experiment. A/B use the actual synthesized-design input RTL compiled by Verilator. The C++ wrapper drives external pins and samples MISO with output-enable checks. All generated service data are synthetic.

```sh
python3 research/check_inputs.py
lib=$(bash research/build_wire.sh)
python research/experiment.py train "$lib"
python research/experiment.py run "$lib" --workers 8
python research/experiment.py replay "$lib"
python research/run_boundary.py --help
python research/analyze.py
```

Training imports only the public development models. Formal runs check the SHA-256 seal of the evaluator module, then load its opaque cases. `development.json` freezes the selected scan. The published thresholds specify a search budget; confirmation and peer-free playback have separate costs. The three gzip JSON Lines streams under `results/` contain one paired-seed summary per method and variant, every completed search block, and the candidate blocks with three actual reset repeats plus a timed replay. Run the replay command in a fresh process to drive the saved MOSI and sample MISO without constructing any peer. The wire digest includes phase relative to the first poll of each window and the measured IRQ gap. Absolute time offsets from the start of each block, including the host's inter-window gap, are in the raw frames.

In the traces, each search block stores its index, settings, windows and measured resource counters. Settings are [first reply, scan reply, random reply, first B gap, second B gap]. Each frame is [start in system clocks, select, MOSI bytes, MISO bytes]. Each record is [P4 verdict, source mask, decision tick]. Strobe counts include RUNs. Read counts include six witness nibbles per completed window, plus the three binding pages needed by the host decision. Each page access advances the core by one clock. A reset count covers a fresh chip and peer per block. At the second single-window RUN the host keeps both intact. The timing includes data collection and configuration as implemented by this driver.
