# Protocol Chameleon — Product Specification

**Status:** Target Specification  
**Priority:** Authoritative acceptance requirements for all development milestones

## 1. Product Definition

Protocol Chameleon is a post-fabrication reprogrammable ASIC for real-time protocol emulation and autonomous protocol testing.

A user must be able to load a complete experiment into the fabricated chip, run it against an external Device Under Test (DUT), and retrieve structured results.

The chip must support:

- Programmable protocol execution
- Programmable peripheral behavior
- Programmable test plans
- Programmable checking rules
- Programmable feedback policies

**All five capabilities must be reprogrammable after fabrication, within documented resource, pin, and timing limits.**

The chip must not require new RTL, synthesis, or fabrication when a user creates a new supported experiment.

## 2. The Five Programmable Capabilities

### P1 — Protocol Definition

The user defines how the chip communicates.

This includes pin roles, signal timing, framing, transaction boundaries, data direction, and legal protocol transitions.

The user must be able to express a previously unknown digital protocol within the declared I/O and timing envelope.

Changing between protocols must not require RTL modifications.

### P2 — Peripheral Behavior

The user defines how an emulated device responds.

Responses may depend on commands, addresses, payload contents, internal state, and previous transactions.

The user must be able to define new state-dependent behavior after fabrication, including relationships between different logical devices.

### P3 — Test Plan

The user defines what experiment to run.

This includes event generation, event ordering, absolute and relative timing, triggering conditions, trial boundaries, and configurable parameters.

Events must not be restricted to two hardcoded sensor notifications.

A new test scenario must be expressible through loaded configuration or programs rather than new RTL.

### P4 — Checking Rules

The user defines what constitutes correct or incorrect DUT behavior.

Rules may examine event identity, commands, addresses, payload data, sequence, multiplicity, and independent deadlines.

The checker must understand logical transactions defined by the loaded protocol.

**Physical SPI chip-select boundaries must not be the only possible logical transaction boundaries.**

P4 must be independently programmable from P2. A response being accepted by the peripheral model does not automatically make it correct under the testing contract.

### P5 — Feedback Policy

The user defines how subsequent tests change based on results.

Policies may depend on the current verdict, event identity, current parameters, and previous trials.

Actions must be able to modify user-defined test parameters and peripheral behavior, not only a fixed set of built-in timing values or state bits.

Multiple trials must execute without host decisions between trials.

## 3. End-to-End Product Contract

A complete experiment follows this user-visible workflow:

**LOAD P1–P5 → START → INTERACT WITH DUT → CHECK → ADAPT → REPEAT → REPORT**

The user can load and replace the complete experiment after fabrication.

The ASIC performs the time-critical protocol interaction, event tracking, checking, and feedback decisions locally.

The host is responsible for loading the experiment, starting or stopping execution, and retrieving results.

The host must not be required to decide individual protocol responses or feedback actions during an autonomous run.

## 4. Shared Programmable Semantics

All five layers must operate on a consistent interpretation of user-defined events and logical transactions.

For example, if a loaded protocol defines three logical transactions during one physical SPI CS assertion:

- P2 must execute all three transactions.
- P3 must be able to react to relevant logical events.
- P4 must be able to check and count each transaction independently.
- P5 must be able to respond to the resulting classifications.

The implementation must not require an application-specific RTL exception to achieve this behavior.

## 5. Required Acceptance Demonstrations

### A. Post-Fabrication Protocol Programmability

Freeze the RTL.

An independent evaluator then supplies a previously undisclosed digital protocol containing variable-length frames, a two-transaction dependency, and input-dependent responses.

The user must implement the specified behavior entirely through the public programming interface.

No RTL or physical-design modifications are permitted.

### B. Programmable Peripheral Behavior

Load two distinct peripheral models using unchanged hardware.

For the same incoming request, different valid histories must produce the responses specified by each model.

Cross-device state dependencies must be supported within the declared resource limits.

### C. Programmable Events and Checking

Load an experiment containing at least two outstanding events, independent deadlines, and checking conditions across at least four predicate categories.

Changing only the loaded checking contract must change the verdict on an identical recorded DUT trace when the contracts specify different outcomes.

### D. Autonomous Feedback

Demonstrate at least three feedback branches, control of two independent timing parameters and one non-timing behavior parameter, and decisions depending on at least two previous trials.

The same current verdict must be capable of producing different actions under different prior histories.

The host makes zero per-trial feedback decisions.

### E. Hidden Evaluation

Evaluate against concealed protocol specifications and DUT behavioral variants after RTL freeze.

The v0.7 acceptance target includes at least eight successful failure discoveries among ten hidden DUT variants, within 128 valid trials per variant, with three confirmation repeats and replayable evidence.

## 6. Physical and Timing Constraints

- IHP SG13 CMOS5L
- Maximum 8×4 Tiny Tapeout tiles
- Official Tiny Tapeout digital I/O interface
- Post-fabrication programmability
- Reproducible functional verification
- Passing physical implementation and required prechecks

Real-time behavior must be verified against external protocol deadlines.

Project acceptance targets include 5 MHz SPI target-mode response and 1 MHz SWD-style turnaround and ACK behavior.

A passing internal setup-time check alone is not sufficient evidence of external protocol timing correctness.

## 7. Implementation Freedom

This specification defines externally observable capabilities, not a mandatory architecture.

The implementation may use processors, programmable engines, hardware accelerators, dedicated datapaths, or combinations of these.

Fixed hardware mechanisms are permitted.

**Application-specific protocol semantics, test rules, and feedback decisions promised as programmable must be definable through the user programming interface.**

## 8. Development Acceptance Rule

Every milestone must identify:

1. Which Product Specification requirements it advances.
2. What new externally observable behavior is available.
3. What the user can now change without modifying RTL.
4. Which behaviors remain fixed in hardware.
5. What tests demonstrate the new programmability.
6. Whether previous supported behaviors still work.
7. How the change affects area, timing, and resource limits.

Passing existing regression tests is necessary but does not, by itself, demonstrate progress toward full programmability.

**A milestone is not complete merely because a new hardcoded application scenario works.**

The ultimate success criterion is the range of new experiments that users can define and execute after fabrication, while satisfying the physical and real-time constraints.

## Real-Time Latency Contract

Real-time performance is a core product requirement, not merely an optimization metric.

The ASIC must provide measurable and bounded worst-case latency for three operations:

**L1 — Protocol Response Latency**

The time from a relevant external protocol event to a valid output response.

Responses must meet the deadlines defined by the loaded protocol. The project acceptance target includes 5 MHz SPI target operation across modes 0–3, including history-dependent responses.

**L2 — Checking Latency**

The time from the point at which sufficient evidence is available to classify an observed DUT behavior to the availability of the corresponding P4 verdict.

Checking must execute locally, with a documented worst-case latency. It must not depend on host software scheduling or communication.

**L3 — Feedback Latency**

The time from a completed P4 verdict to the corresponding P5 action becoming effective.

The ASIC must apply programmable feedback and initiate subsequent trials within a documented worst-case latency, without host intervention.

**Acceptance Requirements**

- Measure worst-case latency, not only average latency.
- Test all supported timing-sensitive protocol modes and relevant event histories.
- Include concurrency, state-dependent responses, and active feedback in latency measurements.
- Specify exact measurement start and end points.
- Report latency in clock cycles and nanoseconds.
- Verify that increasing rule complexity does not silently violate protocol deadlines.
- Separate RTL timing results, post-route timing results, and physical hardware measurements.
- Characterize the tradeoff between programmable complexity, hardware area, and worst-case latency.

All latency guarantees must hold within the documented operating conditions and supported resource limits.