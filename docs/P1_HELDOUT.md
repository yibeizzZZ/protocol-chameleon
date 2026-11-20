# P1 held-out protocol evaluation

The hardware baseline is `190eb49`. A fresh-context AI reviewer who did not implement the RTL designed the following wire protocol and wrote an external-pin oracle. The reviewer received the public programming limits and was instructed to withhold the oracle cases from the candidate author until the candidate was committed. The candidate author received only the wire contract. This is an AI-administered evaluation; external human evaluation remains open.

## Two-vote interlock contract

The controller drives a 1 MHz clock on P0 (idle low, 500 ns half-periods), COMMIT on P1 and VOTE on P2. The chip exclusively drives GRANT on P3 while running. Allow 500 ns after RUN for startup. GRANT and the previous completed vote start at zero.

A frame contains zero or more wait cells and a final commit cell. Each cell has a rising and a falling P0 edge. Sample COMMIT on the rise. If zero, leave both history and GRANT unchanged for the whole cell. If one, sample VOTE on the following fall. The new GRANT is the logical AND of this vote and the previous completed vote. Retain the current vote for the next frame. Repeated commits and arbitrarily many waits are legal.

Inputs have 100 ns setup and hold around their designated sampling edges. Either may change elsewhere. GRANT must remain stable through waits and rising edges. A commit may change GRANT starting on its falling edge and must establish the result within 200 ns. The chip releases P0 through P2 at all times.

## Seal

The evaluator supplied the SHA-256 digest `22e6cd14162fb7769c6f0cefc9009b19f40a1a2c086cc5ff86f37b184f3941b6` for the LF-encoded [oracle](../test/test_p1_heldout.py) before candidate disclosure. Compare the Git blob when the local checkout uses CRLF. The frozen RTL, independent input schedule and observed output pins are the basis for the verdict.
