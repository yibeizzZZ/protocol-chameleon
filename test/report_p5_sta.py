"""Report P5 paths with the routed netlist, SPEF and constraints used by LibreLane."""

import argparse
import csv
from pathlib import Path
import re
import subprocess


# Logical Q-net prefixes in the mapped SG13 CMOS5L design and expected widths.
GROUPS = {
    "verdict": ("trials.feedback.verdict", 3),
    "source": ("trials.feedback.source_mask", 2),
    "previous": ("trials.feedback.previous", 3),
    "older": ("trials.feedback.older", 3),
    "edit": ("trials.feedback.operand_edit", 32),
    "bound": ("trials.bound_value", 8),
    "valid": ("trials.bound_valid", 1),
    "live": ("trials.feedback.live_operands", 16),
    "log": ("trials.feedback.operand_log", 64),
    "frame": ("peripheral.frame_operands", 16),
    "branch": ("byte_state", 3),
    "shift": ("peripheral.tx_shift", 8),
    "miso": ("miso", 1),
}
PATHS = [
    ("verdict", "live"), ("source", "live"), ("previous", "live"), ("older", "live"),
    ("all_registers", "live"), ("edit", "live"), ("bound", "live"), ("valid", "live"), ("live", "live"),
    ("live", "log"), ("live", "frame"), ("frame", "branch"), ("frame", "shift"),
    ("shift", "miso"), ("miso", "port"),
]


def logical_cells(netlist):
    cells = {}
    for instance, ports in re.findall(r"\bsg13cmos5l_dfrbpq_1\s+(\w+)\s*\(([^;]+)\);", netlist):
        net = re.search(r"\.Q\(\s*([^)]*?)\s*\)", ports).group(1).lstrip("\\")
        cells.setdefault(net.split("[")[0], []).append(instance)
    groups = {}
    for name, (prefix, expected) in GROUPS.items():
        members = cells.get(prefix, [])
        if len(members) != expected:
            raise ValueError(f"{prefix}: expected {expected} mapped registers, found {len(members)}")
        groups[name] = members
    return groups


def quoted(path):
    path = str(path)
    if any(char in path for char in "{}\n"):
        raise ValueError(f"unsupported path {path!r}")
    return "{" + path + "}"


def corner_script(directory):
    log = (directory / "sta.log").read_text()

    def logged(kind):
        return re.findall(r"Reading " + kind + r"[^\n]*? at '([^']+)'", log)

    netlist, = logged("top-level netlist")
    spef, = logged("top-level design parasitics")
    sdc, = logged("design constraints file")
    env, = directory.glob("_env*.tcl")
    corner = directory.name
    groups = logical_cells(Path(netlist).read_text())
    libs = logged("cell library")
    if not libs:
        raise ValueError(f"missing libraries at {directory}")
    commands = ["set_cmd_units -time ns -capacitance pF -current mA -voltage V -resistance kOhm -distance um",
                "set sta_report_default_digits 6", f"define_corners {corner}"]
    commands += [f"read_liberty -corner {corner} {quoted(lib)}" for lib in libs]
    commands += [f"read_verilog {quoted(netlist)}", "link_design tt_um_forg_protocol_chameleon",
                 f"source {quoted(env)}", f"read_sdc {quoted(sdc)}", f"read_spef -corner {corner} {quoted(spef)}"]
    for name, members in groups.items():
        for pin in ("CLK", "D"):
            pins = " ".join(f"{m}/{pin}" for m in members)
            commands.append(f"set {name}_{pin} [get_pins {{{pins}}}]")
    commands.append("set all_registers_CLK [all_registers -clock_pins]")
    for src, dst in PATHS:
        endpoint = "[get_ports {uio_out[7]}]" if dst == "port" else f"${dst}_D"
        for kind in ("max", "min"):
            commands.extend([f'puts "BEGIN {src} {dst} {kind}"',
                             f"report_checks -from ${src}_CLK -to {endpoint} -path_delay {kind} "
                             f"-corner {corner} -format full_clock_expanded"])
    return "\n".join(commands) + "\n"


def measures(corner, report):
    sections = re.split(r"^BEGIN (\w+) (\w+) (max|min)\n", report, flags=re.M)[1:]
    if len(sections) != len(PATHS) * 8:
        raise ValueError(f"incomplete STA report for {corner}")
    for i in range(0, len(sections), 4):
        src, dst, kind, body = sections[i:i + 4]
        first = re.search(r"^Startpoint: (\S+)", body, re.M)
        if not first:
            raise ValueError(f"no {kind} path from {src} to {dst} in {corner}")
        start = first.group(1)
        end = re.search(r"^Endpoint: (\S+)", body, re.M).group(1)
        arrival = float(re.search(r"^\s*([-\d.]+)\s+data arrival time", body, re.M).group(1))
        clock = float(re.search(r"([-\d.]+) [\^v] " + re.escape(start) + r"/CLK ", body).group(1))
        slack = float(re.search(r"^\s*([-\d.]+)\s+slack \(", body, re.M).group(1))
        yield (corner, src, dst, kind, start, end, arrival, round(arrival-clock, 6), slack)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="LibreLane runs/wokwi directory")
    parser.add_argument("output", type=Path, help="directory visible at the same path to OpenSTA")
    parser.add_argument("--container", help="run sta in this container with the original PDK and build mounts")
    args = parser.parse_args()
    step, = args.run.resolve().glob("*-openroad-stapostpnr")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    corners = sorted(step.glob("nom_*"))
    if len(corners) != 3:
        raise ValueError(f"expected three nominal-RC corners under {step}")
    for corner in corners:
        script = output / f"{corner.name}.tcl"
        script.write_text(corner_script(corner))
        command = ["sta", "-no_splash", "-exit", str(script)]
        if args.container:
            command = ["docker", "exec", args.container] + command
        report = output / f"{corner.name}.rpt"
        with report.open("w") as handle:
            subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, check=True)
        rows.extend(measures(corner.name, report.read_text()))
    with (output / "paths.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("corner", "from_group", "to_group", "check", "startpoint", "endpoint",
                         "arrival_ns", "launch_clk_pin_to_endpoint_ns", "slack_ns"))
        writer.writerows(rows)


if __name__ == "__main__":
    main()
