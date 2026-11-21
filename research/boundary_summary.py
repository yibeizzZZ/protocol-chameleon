"""Plot recorded outcomes and wire timings from experiment C (simulation only)."""
import csv
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap


def main(directory):
    with (directory / "cases.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    overlap = [r for r in rows if r["family"] == "overlap"]
    costs = [r for r in rows if r["family"] == "complexity"]
    issues = sorted({int(r["issue_b"]) for r in overlap})
    deadlines = sorted({int(r["deadline_b"]) for r in overlap}, reverse=True)
    outcomes = {(int(r["issue_b"]), int(r["deadline_b"])):r["verdict"] for r in overlap}
    palette = {"PASS":0, "TIMEOUT":1, "ORDER":2}
    grid = [[palette[outcomes[i, d]] for i in issues] for d in deadlines]
    fig, (a, b) = plt.subplots(2, 1, figsize=(8.2, 7.9), layout="constrained")
    fig.suptitle("Operating boundaries on frozen RTL", fontsize=16, fontweight="bold")
    a.imshow(grid, cmap=ListedColormap(["#d2eade", "#f5d9bd", "#d6d7ec"]),
             aspect="auto", vmin=-0.5, vmax=2.5)
    for y, d in enumerate(deadlines):
        for x, i in enumerate(issues):
            a.text(x, y, outcomes[i,d], ha="center", va="center", fontsize=9)
    a.set(xticks=range(len(issues)), xticklabels=issues,
          yticks=range(len(deadlines)), yticklabels=deadlines,
          xlabel="B issue tick relative to A", ylabel="Inclusive B deadline (ticks)",
          title="A, A, B under continuous select at 5 MHz")
    sizes = sorted({int(r["rules"]) for r in costs})
    phases = sorted({int(r["phase_ps"]) for r in costs})
    grid = [[max(int(r["max_l1_ps"]) for r in costs if int(r["rules"]) == size
                 and int(r["phase_ps"]) == phase) / 1000 for phase in phases] for size in sizes]
    b.imshow(grid, cmap="Blues", aspect="auto", vmin=0, vmax=100)
    for y, values in enumerate(grid):
        for x, value in enumerate(values):
            b.text(x, y, f"{value:g}", ha="center", va="center", fontsize=11)
    b.set(xticks=range(len(phases)), xticklabels=[f"{n / 1000:g}" for n in phases],
          yticks=range(len(sizes)), yticklabels=sizes, xlabel="SPI phase offset (ns)",
          ylabel="Loaded two-byte rules",
          title="Worst changing-bit launch to valid MISO (ns, 100 ns available)")
    for axis in (a, b):
        axis.tick_params(length=0)
        axis.set_title(axis.get_title(), loc="left", fontsize=11, pad=12)
    fig.savefig(directory / "boundary.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
