"""Run experiment C from a clean, selective export of the specified RTL freeze."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FREEZE = "6fd555b7e008227d7bcdaa2b921525284ff5e062"
HELPERS = (
    "Makefile", "tb.v", "pins.py", "test_spi.py", "test_byte_program.py",
    "test_trials.py", "test_feedback.py", "test_transactions.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results" / "boundary")
    parser.add_argument("--smoke", action="store_true", help="Development subset; use a separate --out")
    args = parser.parse_args()
    destination = args.out.resolve()
    if args.smoke and destination == (HERE / "results" / "boundary").resolve():
        parser.error("--smoke requires a non-formal output directory")
    with tempfile.TemporaryDirectory(prefix="forg-boundary-") as tmp:
        temp = Path(tmp)
        sources = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", FREEZE, "src"], cwd=ROOT, text=True
        ).splitlines()
        for name in sources + ["test/" + x for x in HELPERS]:
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(["git", "show", f"{FREEZE}:{name}"], cwd=ROOT))
        # Keep all simulator products and waveforms off the shared checkout.
        (temp / "test" / "boundary_cocotb.py").write_bytes((HERE / "boundary_cocotb.py").read_bytes())
        env = dict(os.environ, BOUNDARY_OUTPUT=str(temp), BOUNDARY_SMOKE=str(int(args.smoke)),
                   COCOTB_RANDOM_SEED="451")
        subprocess.run(["make", "sim", "SIM=icarus", "COCOTB_TEST_MODULES=boundary_cocotb"],
                       cwd=temp / "test", env=env, check=True)
        subprocess.run([sys.executable, "-m", "cocotb_tools.check_results", "results.xml"],
                       cwd=temp / "test", check=True)
        destination.mkdir(parents=True, exist_ok=True)
        rows = destination / "cases.csv"
        rows.write_bytes((temp / "cases.csv").read_bytes())
        subprocess.run([sys.executable, str(HERE / "boundary_summary.py"), str(destination)],
                       check=True)


if __name__ == "__main__":
    main()
