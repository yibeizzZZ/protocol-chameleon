# Physical acceptance and verification evidence

The project-named macro `tt_um_forg_protocol_chameleon` at `59f32fd` passed all 58 pin-level tests on RTL and all 58 on the routed functional netlist. Nine assembler tests passed. The frozen P1 checkpoint at `d95090b` passed 53 gate-level tests. The shared-wire peer establishes its idle clock before RUN. The [held-out P1 protocol](P1_HELDOUT.md) and [five model tests](../test/test_models.py) describe the independent pin expectations.

| Measurement | Frozen P1 | Project-named release |
| --- | ---: | ---: |
| Official mapped area, µm² | 129,150.806 | 135,059.135 |
| Routed standard-cell utilization before filler | 13.1699% | 13.7604% |
| Worst extracted setup at 50 MHz | +3.710 ns | +2.795 ns |
| Worst extracted hold at 50 MHz | +0.119 ns | +0.116 ns |
| Detailed-route errors | 0 | 0 |

The implementation used the repository's Tiny Tapeout IHP CMOS5L workflow and 8×4 outline. Post-route STA covered slow, typical and fast cell corners with nominal extracted interconnect. The functional gate model used Icarus 13 without SDF. At 5 MHz the external master measured 40.1–60.0 ns launch-to-MISO across 22 phases in each of four modes. The minimum sampled setup margin was 40.0 ns. Pad, board and metastability effects remain unmeasured.

At this checkpoint the Magic DRC, Netgen LVS, independent Tiny Tapeout precheck and release archive are pending.
