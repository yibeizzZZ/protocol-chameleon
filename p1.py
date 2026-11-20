"""Assemble Protocol Chameleon programs for the public pin loader."""

import argparse
import json
from pathlib import Path
import re

from examples.i2c_write import build_write


OPCODES = {
    "HALT": 0x00, "DRIVE": 0x10, "DIR": 0x20, "SAMPLE": 0x30,
    "DELAY": 0x50, "JUMP_ONE": 0x60, "JUMP": 0x70,
    "RISE_SAMPLE": 0x80, "FALL_SAMPLE": 0x90,
}
LABEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def number(token, maximum):
    try:
        base = 10 if token.lstrip("+-").isdigit() else 0
        n = int(token, base)
    except ValueError:
        raise ValueError(f"expected an integer, got {token!r}") from None
    if not 0 <= n <= maximum:
        raise ValueError(f"{token} is outside 0..{maximum}")
    return n


def pin(token):
    if token.upper() not in ("P0", "P1", "P2", "P3"):
        raise ValueError(f"expected P0..P3, got {token!r}")
    return int(token[1])


def destination(token, labels, size):
    if LABEL.fullmatch(token):
        if token not in labels:
            raise ValueError(f"unknown label {token!r}")
        address = labels[token]
    else:
        address = number(token, size - 1)
    if address >= size:
        raise ValueError(f"branch {token!r} falls outside the loaded image")
    return address


def encode(op, args, labels, size):
    if op not in OPCODES:
        raise ValueError(f"unknown instruction {op!r}")
    count = 0 if op == "HALT" else 2 if op in ("RISE_SAMPLE", "FALL_SAMPLE") else 1
    if len(args) != count:
        raise ValueError(f"{op} expects {count} operand(s)")
    if op == "HALT":
        return 0
    if op in ("RISE_SAMPLE", "FALL_SAMPLE"):
        operand = (pin(args[0]) << 2) | pin(args[1])
    elif op == "SAMPLE":
        operand = pin(args[0])
    elif op in ("JUMP", "JUMP_ONE"):
        operand = destination(args[0], labels, size)
    else:
        operand = number(args[0], 15)
    return OPCODES[op] | operand


# Byte rule opcode, literal/register argument maximum. Only QUIET has no destination.
SPI_RULES = {"QUIET": (0, None), "IF_BYTE": (1, 255), "STATUS_ADDR": (2, None),
             "STATUS_REG": (3, 3), "COMMIT": (4, None), "REPLY": (5, 255),
             "IF_SEEN": (6, 3), "NEXT": (7, None)}
FIELDS = {"TAG": 16, "CMD": 8, "ADDR": 4, "MOSI_DATA": 2, "MISO_DATA": 3, "END": 32}


def encode_spi(op, args, labels, size):
    fields = None
    if "|" in args:
        split = args.index("|")
        flags = [flag.upper() for flag in args[split+1:]]
        args = args[:split]
        if flags == ["NONE"]:
            fields = 0
        elif (not flags or len(set(flags)) != len(flags) or not set(flags) <= FIELDS.keys()
              or {"MISO_DATA", "MOSI_DATA"} <= set(flags)):
            raise ValueError("invalid or conflicting transaction fields")
        else:
            fields = 0
            for flag in flags:
                fields |= FIELDS[flag]
    if op not in SPI_RULES:
        raise ValueError(f"unknown SPI rule {op!r}")
    opcode, maximum = SPI_RULES[op]
    count = int(op != "QUIET") + int(maximum is not None)
    if len(args) != count:
        raise ValueError(f"{op} expects {count} operand(s)")
    target = destination(args[-1], labels, size) if op != "QUIET" else 0
    argument = number(args[0], maximum) if maximum is not None else 0
    return opcode << 4 | target, argument, fields


def compile_source(source):
    """Return JSON-compatible image bytes, selector/value pairs and RUN command."""
    labels, rows = {}, []
    mode, header = "GPIO", []
    header_line = None
    for line_no, raw in enumerate(source.removeprefix("\ufeff").splitlines(), 1):
        line = raw.partition("#")[0].strip()
        if ":" in line:
            name, line = line.split(":", 1)
            name = name.strip()
            if not LABEL.fullmatch(name) or name in labels:
                raise ValueError(f"line {line_no}: invalid or duplicate label {name!r}")
            labels[name] = len(rows)
        words = line.split()
        if not words:
            continue
        op, args = words[0].upper(), words[1:]
        if op in ("TIMED", "SPI", "I2C_WRITE") and header_line is None and not rows and not labels:
            mode, header, header_line = op, args, line_no
        else:
            rows.append((line_no, op, args))

    line_no = header_line or 1
    try:
        if mode == "I2C_WRITE":
            if rows or labels or len(header) != 3:
                raise ValueError("use I2C_WRITE address data rate_khz as the only statement")
            image, settings = build_write(number(header[0], 127), number(header[1], 255),
                                          number(header[2], 400))
            return {"image": list(image), "settings": [list(pair) for pair in settings], "run": 5}
        if not rows:
            raise ValueError("empty program")
        limit = {"GPIO": 16, "SPI": 8, "TIMED": 64}[mode]
        if len(rows) > limit:
            line_no = rows[limit][0]
            raise ValueError(f"{mode} program exceeds {limit} entries")

        image, settings = [], []
        if mode == "TIMED":
            if len(header) != 2:
                raise ValueError("TIMED needs the low and released P0 dwell in clocks")
            for selector, token in zip((0x20, 0x21), header):
                dwell = number(token, 256)
                if dwell < 2:
                    raise ValueError("dwell must be 2..256 clocks")
                settings.append([selector, dwell - 1])
        elif header:
            raise ValueError("SPI takes no header operands")

        branch = None
        checkpoints = []
        for index, (line_no, op, args) in enumerate(rows):
            if mode == "TIMED":
                if (op, len(args)) not in (("SLOT", 1), ("CHECK", 2)):
                    raise ValueError("expected SLOT mask or CHECK mask destination")
                if index % 4 == 0:
                    image.append(0)
                image[-1] |= number(args[0], 3) << (2 * (index % 4))
                if op == "CHECK":
                    target = destination(args[1], labels, 64)
                    if len(checkpoints) == 2 or (branch is not None and target != branch):
                        raise ValueError("at most two checkpoints can share one branch destination")
                    branch = target
                    checkpoints.append(index)
            elif mode == "SPI":
                state, argument, fields = encode_spi(op, args, labels, len(rows))
                image.extend((state, argument))
                if fields is not None:
                    settings.append([0x10 + index, fields])
            else:
                image.append(encode(op, args, labels, len(rows)))
        if checkpoints:
            settings.extend([0x22 + i, 0x40 | slot] for i, slot in enumerate(checkpoints))
            settings.append([0x24, branch])
        return {"image": image, "settings": settings, "run": {"GPIO": 2, "SPI": 4, "TIMED": 5}[mode]}
    except ValueError as error:
        raise ValueError(f"line {line_no}: {error}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="English .p1 source file")
    args = parser.parse_args()
    try:
        artifact = compile_source(args.source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{args.source}: {error}\n")
    print(json.dumps(artifact))


if __name__ == "__main__":
    main()
