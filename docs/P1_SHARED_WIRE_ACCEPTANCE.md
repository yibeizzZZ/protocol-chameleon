# P1 acceptance test for a two-wire register

**Goal.** With the M10 RTL at `5b99677`, load a program through the public pins that lets an external controller write one bit and read it back on the same data wire. The controller supplies the clock. Frame length depends on the command, and the answer to a READ depends on the preceding WRITE. Use the GPIO sequencer's 16-byte instruction store and give the target 100 ns to take or release the bus.

## Wire contract

The controller drives P0 (`uio[4]`) as a 1 MHz clock, idle low, with 500 ns half-periods. P1 (`uio[5]`) is a shared push-pull data wire. P2 and P3 stay released. After RUN, the stored bit is zero. Each rising edge samples one bit.

| Operation | First rising edge | Second rising edge | Third rising edge |
| --- | --- | --- | --- |
| READ | Controller sends 0 | Controller samples the target's stored bit | Frame complete |
| WRITE | Controller sends 1 | Controller sends the new bit | Controller samples the target's echo of that bit |

The controller releases P1 on the falling edge after its last outgoing bit. The target has 100 ns from that edge to drive a valid reply and must hold it through the falling edge after the reply sample. It then has 100 ns to release P1. The controller leaves that interval free before driving the next command. Both devices must release P1 in idle. Simultaneous output enables are a failure even when both drive the same level.

## Acceptance and evidence

| Criterion | How the test decides | Recorded result |
| --- | --- | --- |
| Same hardware | Compare the RTL and Tiny Tapeout configuration to `5b99677`. Load the GPIO image through the top-level host pins once. Use STOP/RUN between phase sweeps and leave the host idle during each sequence. | Same RTL and configuration. The image uses 13 of 16 bytes. |
| Framing and history | At each phase run READ, WRITE(1), READ, READ, WRITE(0), READ, WRITE(0), WRITE(1), READ. A controller-side variable predicts each sampled reply. A fresh RUN must restore the initial zero after the preceding sequence ended with a one. | All 110 reads and 88 write echoes matched, including repeated reads and consecutive writes. |
| Timing and ownership | Run a 50 MHz system clock against 22 external phases spanning its 20 ns period. Observe every DUT output-enable transition and every change on the resolved data pad. Require exactly one drive and one release per reply, valid stable data from the 100 ns deadline through the reply cell, and released GPIOs between replies. | Drive enable and release each took **60.1–80.0 ns** from their respective falling edges. All 198 replies met the 100 ns validity and release deadlines. |
| Negative control | Temporarily replace the store-one instruction at address `0xB` with `0x10` (store zero). Run the same controller and restore the original image. | The first WRITE(1) failed at phase 0, with a resolved zero where the controller expected one. Restoring `0x12` passed. |

The program retains its bit in the output latch while P1 is released. A READ enables the latch on P1. A WRITE updates the latch before entering the same reply path. The controller and its expected values are defined from the wire contract and do not read DUT registers. [Program and instruction annotations](../examples/shared_wire_register.hex) · [Pin-level test](../test/test_shared_wire_register.py)

## Reproduce

From the repository root, use the Linux or WSL simulation environment described in the [test setup](../test/README.md#reproduce-the-functional-tests). The recorded run used Icarus Verilog 12.0 and cocotb 2.0.1.

```sh
git diff --exit-code 5b99677 9abe5c0 -- src/ info.yaml
cd test
make COCOTB_TEST_MODULES=test_shared_wire_register
python -m cocotb_tools.check_results results.xml
```

The first command checks the historical acceptance commit against the frozen hardware baseline. Run the simulation at `9abe5c0` to reproduce that exact version, or at a later revision to check compatibility. A passing simulation prints the program size, phase and reply counts, and the minimum and maximum drive and release delays. To replay the negative control, edit the example byte described above and rerun the same test.

For a manual load, enter the GPIO loader with control bytes `00 83`, clear with `01`, write the 13 program bytes as data, then issue control `02` to run. Keep external drivers released until the loader owns the GPIOs. [Pin mapping and loader strobes](info.md#enter-load-run-stop)

This is a team-defined protocol on zero-delay RTL. The measured bounds apply to the stated pin timing and sampled phases. A subsequent AI-administered evaluation used a protocol disclosed after RTL freeze and an independently written peer. [Two-vote interlock results](P1_HELDOUT.md)
