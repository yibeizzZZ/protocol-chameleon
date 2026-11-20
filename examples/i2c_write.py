"""Build a timed-GPIO program for one seven-bit I2C controller write."""

import argparse


def build_write(address, data, rate_khz):
    """Return program bytes and (control selector, data value) settings at 50 MHz."""
    if not 0 <= address <= 0x7F or not 0 <= data <= 0xFF:
        raise ValueError("expected a seven-bit address and an eight-bit data byte")
    if rate_khz not in (100, 400):
        raise ValueError("rate must be 100 or 400 kHz")
    low_step, high_step = (125, 250) if rate_khz == 100 else (33, 59)

    # A set bit pulls the corresponding pin low. P0 is SCL and P1 is SDA.
    slots = [0, 0, 2]  # Bus free, then START while SCL is high.
    previous_data = 2
    checkpoints = []
    for byte in (address << 1, data):
        bits = [(byte >> n) & 1 for n in reversed(range(8))]
        for bit in [*bits, 1]:  # Release SDA for the target's ninth clock.
            data_mask = 0 if bit else 2
            slots.extend((1 | previous_data, 1 | data_mask, data_mask))
            previous_data = data_mask
        checkpoints.append(len(slots) - 1)
    stop = len(slots)
    slots.extend((1, 3, 2, 0))  # Lower SCL, pull SDA low, raise SCL, then STOP.
    slots.extend([0] * (-len(slots) % 4))
    image = bytes(sum(mask << (2 * j) for j, mask in enumerate(slots[i:i+4]))
                  for i in range(0, len(slots), 4))
    settings = [(0x20, low_step - 1), (0x21, high_step - 1),
                (0x22, 0x40 | checkpoints[0]), (0x23, 0x40 | checkpoints[1]),
                (0x24, stop)]
    return image, settings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", type=lambda value: int(value, 0))
    parser.add_argument("data", type=lambda value: int(value, 0))
    parser.add_argument("rate_khz", type=int, choices=(100, 400))
    args = parser.parse_args()
    program, settings = build_write(args.address, args.data, args.rate_khz)
    print("Image:", program.hex(" "))
    print("Selector/data:", " ".join(f"{k:02x}={v:02x}" for k, v in settings))
