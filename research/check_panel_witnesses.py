"""Post-score calibration: drive each evaluator-supplied witness through the frozen chip."""
import argparse
import json
from pathlib import Path

from experiment import Chip, DEST, run_block
import panel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    args = parser.parse_args()
    chip = Chip(args.library.resolve())
    observations = {}
    for case, steps in panel._witnesses().items():
        # Resolve the evaluator's symbolic tokens ahead of a directed reset run.
        # The resulting choices are deliberately excluded from the search scores.
        preview = panel.new_peer(case, 0, 0)
        gaps, replies = [], []
        previous = None
        for gap, value in steps:
            token = preview.poll()[1]
            reply = {"previous": previous, "current": token}.get(value, value)
            preview.after_reply([0, 0, reply], gap)
            gaps.append(gap)
            replies.append(reply)
            previous = token
        if len(steps) == 1:
            gaps.append(0)
            replies.append(0)
        params = (replies[0], replies[1], replies[1], *gaps)
        observations[case] = {}
        for variant in (case, "healthy"):
            windows, costs = run_block(chip, panel.new_peer(variant, 0, 0), "scan", params)
            records = [w["record"] for w in windows]
            if variant == "healthy":
                assert [r[0] for r in records] == [1, 1]
            else:
                assert len(records) == len(steps) and records[-1][0] in (2, 3, 4)
            observations[case][variant] = dict(windows=windows, costs=costs)
    chip.close()
    (DEST / "directed-audit.json").write_text(json.dumps(observations, indent=2) + "\n")
    print(f"{len(observations)} directed pin witnesses and matched healthy controls passed")


if __name__ == "__main__":
    main()
