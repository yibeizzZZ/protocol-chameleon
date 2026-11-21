# Synthetic SPI service panel

This panel models ten possible controller mistakes in a closed, two-slot SPI simulation. Its author received the public peer API and service contract and produced the models and their witnesses without inspecting campaign policies, development cases or comparative results. The opaque case IDs identify peers for scoring. The models, descriptions and witness code in this directory reveal their behavior and belong on the evaluator side of a blind run. This is internal role separation within a shared workspace. External authorship and access-control enforcement are outside the scope of the experiment.

Each peer instance handles two service windows. Each window starts with a three-byte A poll carrying a nonzero token. The third returned byte is the A reply. A nominal completion sends exactly one three-byte B service frame on slot 1. Tokens come from a deterministic hash of the seed, run index and window index. Every model receives the same token stream at those coordinates. Only the response byte and the advertised IRQ spacing are external test choices.

## Models and witnesses

Each pair in the witness column gives the IRQ gap in system ticks and the third MISO byte in decimal. A second pair uses the same peer instance. Token references use a token already visible in a poll. The witnesses use seed 0 and run index 0.

| Case | Abstract mistake | Witness | Observed consequence in the final window |
| --- | --- | --- | --- |
| c-4c | Change detector carries the previous response into the next window | (16, 53), (16, 53) | Equal samples suppress B |
| c-78 | Four-bit scheduler drops the carry when adding elapsed gap quanta and the low reply nibble | (128, 8) | Lost B service event |
| c-ad | B service uses the A chip-select line | (16, 0) | B frame on slot 0 |
| c-32 | Retry comparator reads the preceding poll's tag | (16, 0), (16, previous token) | A poll replayed in B's place |
| c-f1 | Simultaneous IRQ edges collapse into one pending request | (0, 0) | B omitted |
| c-6b | A response counter wrap is interpreted as a resynchronization cycle | (16, 255), (16, 0) | B omitted at wrap |
| c-95 | A level-sensitive enqueue duplicates the service request | (16, 0) | Two B frames |
| c-27 | High response bits alias a replay instruction | (16, 208) | B followed by a duplicate A poll |
| c-b3 | IRQ qualification time carries over into the next window | (128, 0), (64, 0) | Earlier B notification rejected |
| c-50 | Data equal to the live poll tag erroneously completes the request queue | (16, current token) | B omitted |

## Reproduction

From the repository root, run `python -B research/panel.py`. The audit uses the public peer methods for every case, checks valid poll and followup shapes, and requires the first failure at the indicated witness window. Its healthy check exercises every ordered pair of the 1,024 legal gap/reply combinations on a fresh peer. A recorded run completed with the following output.

```text
Healthy legal reply/gap histories checked: 1048576
Fault witnesses reproduced: 10
```

The healthy enumeration fixes the seed and run index. The token generator always returns an integer from 1 through 255, and the healthy transition unconditionally emits the same valid B frame, so changing the token cannot change healthy service. The first two MISO bytes do not enter dispatch. On the stated clock ratio, a three-byte transfer takes 240 system ticks. Starting at the later IRQ and issuing two frames back to back takes at most 608 ticks from the first IRQ. This calculation assumes the zero-wait transaction contract. Pin-level framing, inter-frame delays and the evaluation harness's tick accounting require separate checks.

The ten mechanisms deliberately cover unconditional, timing-dependent, response-dependent and history-dependent faults. Several share the same final symptom of a missing B service. Distinct mechanisms and distinct witnesses do not make the cases statistically independent. These transaction-level constructs support a comparison on this finite panel. They do not establish fault prevalence in hardware, fidelity to a particular controller implementation, or generalization to independently sampled designs.
