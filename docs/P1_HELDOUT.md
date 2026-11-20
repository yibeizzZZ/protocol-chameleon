# P1 held-out protocol evaluation

The hardware baseline is `190eb49`. A fresh-context AI reviewer who did not implement the RTL designed the following wire protocol and wrote an external-pin oracle. The reviewer received the public programming limits and was instructed to withhold the oracle cases from the candidate author until the candidate was committed. The candidate author received only the wire contract. An external human evaluation remains open.

## Two-vote interlock contract

The controller drives a 1 MHz clock on P0 (idle low, 500 ns half-periods), COMMIT on P1 and VOTE on P2. The chip exclusively drives GRANT on P3 while running. Allow 500 ns after RUN for startup. GRANT and the previous completed vote start at zero.

A frame contains zero or more wait cells and a final commit cell. Each cell has a rising and a falling P0 edge. Sample COMMIT on the rise. If zero, leave both history and GRANT unchanged for the whole cell. If one, sample VOTE on the following fall. The new GRANT is the logical AND of this vote and the previous completed vote. Retain the current vote for the next frame. Repeated commits and arbitrarily many waits are legal.

Inputs have 100 ns setup and hold around their designated sampling edges. Either may change elsewhere. GRANT must remain stable through waits and rising edges. A commit may change GRANT starting on its falling edge and must establish the result within 200 ns. The chip releases P0 through P2 at all times.

## Seal

The evaluator supplied the digest before the candidate was written. Commit `75ec853` preserves the [oracle](../test/test_p1_heldout.py). The supplied working copy had a CRLF on its final line and LF on the other lines. Its SHA-256 was `22e6cd14162fb7769c6f0cefc9009b19f40a1a2c086cc5ff86f37b184f3941b6`. Git normalized the final newline on commit. To verify the committed bytes on Linux, run `git show 75ec853:test/test_p1_heldout.py | sha256sum`. The expected digest is `e79ab40a77f177daa4715ebf2ce58f86ce7dab98924e01f0513efa85c5c6b358`.

## Results

The [candidate](../examples/heldout.p1) was committed in `8ac4636` before the first simulation. It passed on the first run and uses all 16 GPIO instructions. The external controller delivered 57 frames at each of two phase offsets (3 and 13 ns), with up to 23 wait cells before a commit. The monitor checked pin ownership, state retention and the 200 ns deadline across all 114 frames. It sampled the digital pins every 20 ns.

A fresh checkout of `fa1ce36` passed all eight compiler tests and all 53 RTL tests. In a disposable copy, replacing `JUMP_ONE grant` with `JUMP grant` made the monitor report GRANT high when it expected low at phase 3 ns, frame index 3, cell 0. The two commits containing the oracle and the candidate precede this negative control.

With the [simulation prerequisites](../test/README.md#reproduce-the-functional-tests) installed and active, run `make -C test p1` from the root to compile the programs, load them through the pins and reproduce the five P1 pin tests.

## First-time author replication

A second fresh-context AI participant received the wire requirements and access to the public programming guide and loader reference. They had no prior involvement in the project and did not inspect examples, implementation, candidate or tests. They submitted their program before any compiler or simulator feedback. A separate clean checkout compiled their submission and passed the sealed pin test on the first attempt.

Both authors independently encoded the previous vote in the instruction address. Both programs assembled to `28 81 64 71 92 67 71 81 6a 77 92 6e 10 71 18 77`. The independent source used different labels. Its SHA-256 with LF line endings was `733ed68330d6d1d83538a3c9ba5c568ff06eb593ead71cf38ea135ca7be9a0fc`.

## Scope and handoff

The frozen design met this protocol's timing and state requirements in digital RTL simulation. This protocol fills the GPIO instruction store. Faster wire rates, other clock phases and post-route pin delays require separate measurements. This milestone changed host tooling, examples and verification. The RTL and Tiny Tapeout configuration match the hardware baseline, so the milestone adds no hardware cells or timing paths. The product's next acceptance demonstration covers loading two peripheral models with different state-dependent behavior. [Product specification, section 5](PRODUCT_SPEC.md#5-required-acceptance-demonstrations)
