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
        n = int(token, 0)
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


def compile_source(source):
    """Return JSON-compatible image bytes, selector/value pairs and RUN command."""
    labels = {}
    rows = []
    for line_no, raw in enumerate(source.splitlines(), 1):
        line = raw.partition("#")[0].strip()
        if ":" in line:
            name, line = line.split(":", 1)
            name = name.strip()
            if not LABEL.fullmatch(name) or name in labels:
                raise ValueError(f"line {line_no}: invalid or duplicate label {name!r}")
            labels[name] = len(rows)
        words = line.split()
        if words:
            rows.append((line_no, words[0].upper(), words[1:]))
    if not rows:
        raise ValueError("empty program")
    line_no, op, args = rows[0]
    try:
        if op == "I2C_WRITE":
            if len(rows) != 1 or labels or len(args) != 3:
                raise ValueError("use I2C_WRITE address data rate_khz as the only statement")
            image, settings = build_write(number(args[0], 127), number(args[1], 255),
                                          number(args[2], 400))
            return {"image": list(image), "settings": [list(pair) for pair in settings], "run": 5}
        if len(rows) > 16:
            line_no = rows[16][0]
            raise ValueError("GPIO instruction store holds 16 bytes")
        image = []
        for line_no, op, args in rows:
            image.append(encode(op, args, labels, len(rows)))
        return {"image": image, "settings": [], "run": 2}
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
