# Milestones 1–5 verification

The Tiny Tapeout RTL regression passed **16 tests, 0 failed, 0 skipped**. The twelve Milestone 1–4 cases still pass alongside four SPI peripheral cases. All oracles use external inputs, outputs, enables, or resolved pads.

## Reproduce the functional tests

The run used an Ubuntu 24.04 container, Python 3.11, Icarus Verilog 12.0 (`12.0-2build2`), GNU Make 4.3 and Cocotb 2.0.1. From the repository root on Linux with Python 3.11 and its venv support installed, use the same Makefile, simulator and result check as the [repository's Tiny Tapeout workflow](../.github/workflows/test.yaml).

```sh
sudo apt-get install -y make iverilog
python3.11 -m venv /tmp/chameleon-verify
. /tmp/chameleon-verify/bin/activate
python -m pip install -r test/requirements.txt
cd test
make clean && make && python -m cocotb_tools.check_results results.xml
```

`results.xml` records each case and `tb.fst` contains the waveform. The [testbench](tb.v) resolves external and DUT drivers on the same digital pads. The [host driver](pins.py) also checks for simultaneous enables every sampled clock, so even two drivers producing the same value are detectable in the driven scenarios.

| Suite | Passed | Externally observed behavior |
| --- | ---: | --- |
| [UART and runtime configuration](test_uart.py) | 7 | Independent TX and RX messages in full duplex, bit-cell lengths and order, busy/done timing, held and busy strobes, valid/error pulses, both bad stop positions, false start, break recovery, consecutive frames and reset mid-frame. Covers 8N1, 7N2, 8N2, 7N1, 8–4096 clocks/bit endpoints, incomplete and invalid descriptor writes, reconfiguration during TX/RX, and UART operation across an engine handoff. An independently timed peer sends at 315 and 325 ns/bit with RX configured for 320 ns/bit. |
| [Programmable sequencer](test_engine.py) | 5 | Exact two-pulse waveform and replay, both conditional reply paths, rising/falling edge samples, sample history, GPIO value and direction, held-level versus edge detection, and a missed edge during delay. Covers empty RUN, 16th and excess bytes, stale addresses after CLEAR, reserved opcode, writes while running, STOP during delay/wait, EXIT and reset. A deliberate opposing drive produces an X on the resolved pad and clears when the peer releases it. |
| [SPI peripheral](test_spi.py) | 4 | Modes 0–3 with independently clocked transactions and pad-level setup/hold checks, address-local history, aborted and extra clocks, invalid headers, live reprogramming, ignored busy writes, CS release, UART handoff and reset. |

## SPI measurements

The independent SPI master ran 5 MHz SCLK against the 50 MHz system clock. Each mode was exercised at 22 launch offsets across one 20 ns system period, including offsets 0.1 ns before and after a system rising edge. Each offset included a first read and a repeat read. The monitor recorded resolved MISO transitions and checked the expected bit throughout a 20 ns setup / 10 ns hold window, including header bits and adjacent equal bits.

| SPI mode | Measured payload transitions | Launch edge to valid MISO | Minimum setup before sample | CS assertion to first MISO drive |
| --- | ---: | ---: | ---: | ---: |
| 0 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| 1 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| 2 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| 3 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |

Launch-to-valid spans 2.005–3.000 system periods depending on phase. The target selects the byte on the last address sample, one half-period before the first response launch. Timing above starts at the launch edge and uses only bits whose value changes. CS deassertion released the resolved MISO pad by the check 1 ps later in zero-delay RTL.

## Synthesis and basic timing

The commands below reproduce the estimate from the repository root. They run Yosys/ABC and standalone OpenSTA. The image supplies the binaries; no LibreLane or OpenROAD flow is invoked.

```sh
out=$(mktemp -d)
pdk_rev=2bbec755dc67ca3db0261c3d6163e15735d66710
lib=ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib
curl -fLsS "https://raw.githubusercontent.com/IHP-GmbH/IHP-Open-PDK/$pdk_rev/$lib" -o "$out/cells.lib"
echo "34163f3e7de9f854afac57332ba06f1739b78e7ac35660a8a5ddd39c570124ad  $out/cells.lib" | sha256sum -c -
docker run --rm --entrypoint bash -v "$PWD:/work:ro" -v "$out:/out" -w /work \
  -e LIBERTY=/out/cells.lib -e ESTIMATE_DIR=/out \
  ghcr.io/librelane/librelane@sha256:d109140b8f17fc54f4fca998beb8124f4949404ec52e339eebd2250854a18b5a \
  test/synth_estimate.sh
```

The [synthesis script](synth_estimate.sh) writes the mapped netlist, `yosys.log` and `sta.log` in the output directory. Yosys 0.66 completed the structural check and mapped the flattened top to the IHP SG13 CMOS5L typical library (1.20 V, 25 °C). [OpenSTA 2.7.0 constraints](prelayout_sta.tcl) use an ideal 20 ns system clock. Separate reports measure paths from any register to the shared bit-7 data and enable ports with zero external load and zero output delay.

| Quantity | M4 baseline | M5 |
| --- | ---: | ---: |
| Mapped standard cells (excluding Yosys metadata) | 1,209 | 1,761 |
| Flip-flops | 286 | 390 |
| Sum of library cell areas | 24,464.727 µm² | 33,109.322 µm² |
| Sequential cell area | 14,010.797 µm² | 19,105.632 µm² |
| Worst reported register-to-register setup slack | +16.978 ns | +17.144 ns |
| Register to bit-7 data / enable block-port arrival | — | 0.807 ns / 0.761 ns |

## External timing and remaining risks

For the documented clocked reply program, both request values enabled P2 on the **sixth system rising edge** after P0 rose in the exercised phase. At 50 MHz, with the peer changing P0 halfway between system rising edges, that sixth edge occurs 110 ns later. A 5 MHz peer sampling on the next falling edge gives only 100 ns. This particular program and phase already miss that deadline before pad delays or peer setup time. The positive internal setup slack does not resolve this protocol latency.

The sequencer has no edge queue. An external transition during another instruction can be lost, and the suite does not exhaust program images or input phases. Reset and EXIT restore UART output enables, so the peer must release shared pins beforehand. Digital X resolution can flag ownership errors; it cannot measure pad skew, electrical contention, or metastability.

The SPI accelerator uses a fixed 24-bit register-read transaction; the generic sequencer still has the latency described above. The measurements cover a digital controller using a 50% duty cycle and changing MOSI on launch edges. They do not characterize the minimum MOSI setup/hold aperture, synchronizer metastability, noisy clocks, or arbitrary duty cycles.

The area estimate excludes routing, clock distribution, filler and pad overhead. The timing estimate excludes extracted interconnect, actual pad/board loading, hold analysis and other process/voltage/temperature corners. Physical fit in 8×4 tiles and silicon-level SPI timing remain unverified. No placement, routing, GDS, DRC or LVS was run.
