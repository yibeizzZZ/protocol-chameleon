# Jane Street Protocol Emulator ASIC Competition

Entries close on **January 18, 2027**. The announcement does not specify a cutoff time or time zone. Jane Street published the rules on September 10, 2026. Its latest dated update, **November 9, 2026**, confirmed the 8×4 tile allocation and added the FAQ. Both official pages were checked on November 20, 2026. [Jane Street announcement and FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) · [Tiny Tapeout competition page](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/)

## Entry requirements

> Your chip should be reprogrammable enough to support new protocols after fabrication, within its timing and I/O constraints.

The entry must be an open-source, general-purpose protocol emulator ASIC. An entrant can use an instruction engine, an embedded FPGA or another architecture that lets users implement new protocols on the same silicon. [Jane Street design FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/)

| Item | What to provide |
| --- | --- |
| Process and area | Use the Tiny Tapeout IHP 130 nm CMOS5L flow. The Verilog template targets CMOS5L on its `main` branch. Set `tiles` in `info.yaml` to `"8x4"`, the maximum allocation per design. [Official template](https://github.com/TinyTapeout/ttihp-verilog-template) · [Competition rules](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#the-rules) |
| Physical implementation | Provide the GDS and passing Tiny Tapeout precheck for the submitted RTL. If the flow exceeds the six-hour GitHub Actions limit, entrants can run the Tiny Tapeout flow locally and submit through its custom GDS action. [Submission instructions](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#what-to-submit) |
| Source and software | Submit a public repository with RTL, tests, architecture and instruction-set documentation, an assembler or other programming toolchain (including a bitstream flow where applicable), and example programs for the supported protocols. Document the host and how it loads programs. [Jane Street submission and design FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) |
| Verification | Explain the verification methods and tools. If the team used AI, describe how it was used. Entrants choose their own verification tools. The judges give substantial weight to the clarity of the write-up. [Jane Street judging FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) |
| Board interface | The design has eight digital inputs, eight outputs and eight bidirectional pins, plus clock and reset. Use `rst_n` to reach a known state. Deselection powers the design down, so the host must be able to reload it after selection. Document any external pull-ups, transceivers or level shifters. Choose a clock frequency that closes timing after routing and meets the demonstrated protocols' timing requirements. [Tiny Tapeout board constraints](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#pins-speed-and-the-board) |
| Entry and submission | Individuals and teams of any size can enter. Each team submits one entry and makes its repository public by submission. As of November 20, the sign-up form is for updates. Jane Street plans to post the final submission form on the announcement page. The shuttle is planned for March 2027, subject to the foundry schedule. [Jane Street announcement and forms](https://blog.janestreet.com/protocol-emulator-asic-competition/) |

## Judging priorities

The judges give flexibility the most attention. They also consider the demonstrated protocols, distinctive architectural capabilities, design and verification methods, and the quality of the write-up. They publish no fixed scoring weights or protocol speeds. UART, SPI and I²C are suggested starting points. Suggested settings include common UART baud rates, SPI modes 0–3 and I²C at 100 and 400 kHz. Low-speed USB and 10 Mbit Ethernet are stretch goals. Concurrent protocols and support for both controller and target roles can strengthen an entry. Gate-level simulation is strongly recommended. FPGA prototyping and a demo video are optional. [Jane Street design and judging FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) · [Tiny Tapeout judging criteria](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#how-entries-are-judged)

## Priorities for Protocol Chameleon

A reviewer can write and load a new GPIO program on frozen hardware. The held-out two-vote interlock was specified after the GPIO design freeze and reproduced by a second author using the public programming guide. Independent pin checks cover GPIO exchanges, UART, SPI and 100/400 kHz I2C writes. [Held-out evidence and its scope](P1_HELDOUT.md) · [Source examples and assembler](P1_PROGRAMMING.md) · [Test coverage](../test/README.md)

The shared-state revision adds two editable peripheral models, observed-reply scheduling, independent checking and feedback across trials. The successor release also covers writable device bytes and feedback edits to reply operands. Each release identifies the GDS, source revision and checks. Publishing the selected commit and artifacts and entering the competition are separate owner actions. [Shared-state release](PHYSICAL_ACCEPTANCE.md) · [Feedback operand release](P5_PHYSICAL_ACCEPTANCE.md)

Codex assisted with RTL, assembly, documentation, test authoring and running the implementation tools. The sealed P1 evaluator and independent replication author were separate AI sessions. Verification used independent wire expectations, a negative control, simulation and extracted timing. External human replication, silicon measurements and the product proposal's concealed-device benchmark remain open. [Evaluation provenance](P1_HELDOUT.md) · [Product targets](PRODUCT_SPEC.md)
