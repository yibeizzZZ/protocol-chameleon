"""Aggregate the released paired A/B experiment. Run from any directory."""
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RAW = RESULTS / "search.jsonl.gz"
METHODS = ("chip", "scan", "random", "host0", "host1", "host10", "host100")
A = METHODS[:3]
B = (METHODS[0], *METHODS[3:])
LABEL = dict(zip(METHODS, ("On-chip", "Fixed scan", "Random", "Host 0 µs", "Host 1 µs",
                           "Host 10 µs", "Host 100 µs")))
BUDGETS = (2, 4, 8, 16, 32, 64, 128)
COSTS = ("windows", "clocks", "frames", "strobes", "reads", "runs", "resets", "reset_clocks")
STAGES = ("search", "confirmation", "replay")
HZ = 50_000_000
STATUSES = {"confirmed", "miss", "false_alarm", "inconclusive", "unconfirmed"}


def load_rows():
    with gzip.open(RAW, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    cases = sorted({r["case"] for r in rows} - {"healthy"})
    expected = {(c, m, s) for c in [*cases, "healthy"] for m in METHODS for s in range(30)}
    actual = {(r["case"], r["method"], r["seed"]) for r in rows}
    if len(cases) != 10 or actual != expected or len(rows) != len(expected):
        raise ValueError("Expected 10 defective variants plus healthy × 7 methods × 30 unique seeds")
    for r in rows:
        status = r["status"]
        n = r["search"]["windows"]
        if status not in STATUSES or not 0 <= n <= 128:
            raise ValueError(f"Invalid outcome or window count: {r}")
        if status == "miss" and (n != 128 or r["first"] is not None):
            raise ValueError(f"Unexhausted miss: {r}")
        if status == "confirmed" and (r["case"] == "healthy" or r["confirms"] != 3 or r["replay_ok"] is not True):
            raise ValueError(f"Invalid confirmed hit: {r}")
        if status in {"confirmed", "false_alarm", "unconfirmed"} and not (r["first"] == n and n > 0):
            raise ValueError(f"Invalid candidate index: {r}")
        if status == "false_alarm" and r["case"] != "healthy":
            raise ValueError(f"False alarm on a defective case: {r}")
    return cases, {(r["case"], r["method"], r["seed"]): r for r in rows}


def write_csv(name, rows):
    with (RESULTS / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def hit(r, budget):
    return r["status"] == "confirmed" and r["first"] <= budget


def groups(cases, data, method):
    return [[data[c, method, s] for s in range(30)] for c in cases]


def discovery(cases, data):
    coverage, by_case, comparisons, first_hits = [], [], [], []
    # Resample whole variants. A selected variant carries all its fixed paired seeds.
    draws = np.random.default_rng(20261121).integers(len(cases), size=(20_000, len(cases)))
    for m in METHODS:
        for c in cases:
            rows = [data[c, m, s] for s in range(30)]
            counts = Counter(r["first"] for r in rows if hit(r, 128))
            misses = sum(r["status"] == "miss" for r in rows)
            failed = len(rows) - sum(counts.values()) - misses
            for n in range(1, 129):
                first_hits.append(dict(case=c, method=m, window=n, new_confirmed=counts[n],
                                       censored_at_128=misses if n == 128 else 0,
                                       other_no_credit_stops=sum(r["status"] in {"inconclusive", "unconfirmed"}
                                                                 and r["search"]["windows"] == n for r in rows)))
            for b in BUDGETS:
                nhit = sum(hit(r, b) for r in rows)
                by_case.append(dict(case=c, method=m, budget=b, seeds=30, confirmed=nhit,
                                    percent=round(100*nhit/30, 6),
                                    first_run_confirmed=sum(hit(r, b) and r["first_run_hit"] for r in rows),
                                    eventual_censored_at_128=misses, eventual_other_no_credit_stops=failed))
        for b in BUDGETS:
            flags = np.array([[hit(r, b) for r in g] for g in groups(cases, data, m)])
            means = flags.mean(axis=1)
            coverage.append(dict(method=m, budget=b, pairs=flags.size, confirmed=int(flags.sum()),
                                 macro_percent=round(float(means.mean()*100), 6),
                                 distinct_duts=int(np.count_nonzero(means)), total_duts=len(cases),
                                 min_dut_percent=100*means.min(), max_dut_percent=100*means.max()))
            if m == "chip":
                continue
            local = np.array([[hit(r, b) for r in g] for g in groups(cases, data, "chip")])
            delta = (local.astype(int) - flags.astype(int)).mean(axis=1)*100
            low, high = np.percentile(delta[draws].mean(axis=1), [2.5, 97.5])
            comparisons.append(dict(comparator=m, budget=b, pairs=int(flags.size),
                                    both=int((local & flags).sum()), neither=int((~local & ~flags).sum()),
                                    chip_only=int((local & ~flags).sum()), comparator_only=int((~local & flags).sum()),
                                    chip_minus_comparator_pp=round(delta.mean(), 6),
                                    resample_p2_5_pp=round(low, 6), resample_p97_5_pp=round(high, 6)))
    write_csv("coverage.csv", coverage)
    write_csv("coverage_by_dut.csv", by_case)
    write_csv("paired_comparisons.csv", comparisons)
    write_csv("first_hit_distribution.csv", first_hits)
    return coverage, by_case, comparisons


def accounting(cases, data):
    costs, outcomes, equivalence = [], [], []
    for m in METHODS:
        for population, ids in (("defective", cases), ("healthy", ["healthy"]), ("all", [*cases, "healthy"])):
            rows = [r for group in groups(ids, data, m) for r in group]
            stats = Counter(r["status"] for r in rows)
            candidates = [r for r in rows if r["first"] is not None]
            outcomes.append(dict(method=m, population=population, sequences=len(rows),
                                 **{k: stats[k] for k in sorted(STATUSES)},
                                 first_run_confirmed=sum(hit(r, 128) and r["first_run_hit"] for r in rows),
                                 confirmed_later_run=sum(hit(r, 128) and not r["first_run_hit"] for r in rows),
                                 confirmation_successes=sum(r["confirms"] for r in candidates),
                                 confirmation_attempts=3*len(candidates),
                                 replay_successes=sum(r["replay_ok"] is True for r in candidates),
                                 replay_attempts=sum(r["replay_ok"] is not None for r in candidates),
                                 expired_windows=sum(r["deadlines_missed"] for r in rows)))
            for stage in (*STAGES, "inclusive"):
                parts = STAGES if stage == "inclusive" else (stage,)
                amounts = {k: sum(r[p][k] for r in rows for p in parts) for k in COSTS}
                seconds = amounts["clocks"]/HZ
                costs.append(dict(method=m, population=population, stage=stage, sequences=len(rows),
                                  **amounts, simulated_seconds=seconds,
                                  windows_per_second=amounts["windows"]/seconds if seconds else None))
        if m not in B[1:]:
            continue
        for c in [*cases, "healthy"]:
            for s in range(30):
                local, host = data[c, "chip", s], data[c, m, s]
                equivalence.append(dict(case=c, seed=s, method=m, same_status=local["status"] == host["status"],
                                        same_first=local["first"] == host["first"],
                                        same_windows=local["search"]["windows"] == host["search"]["windows"],
                                        same_wire_digest=local["wire_digest"] == host["wire_digest"],
                                        chip_expired=local["deadlines_missed"], host_expired=host["deadlines_missed"]))
    write_csv("costs.csv", costs)
    write_csv("outcomes.csv", outcomes)
    write_csv("host_equivalence.csv", equivalence)
    return costs, outcomes, equivalence


def detail(cases, data):
    per_dut, inclusive = [], []
    for m in METHODS:
        for c in [*cases, "healthy"]:
            rows = [data[c, m, s] for s in range(30)]
            counts = Counter(r["status"] for r in rows)
            candidates = [r for r in rows if r["first"] is not None]
            per_dut.append(dict(case=c, method=m, seeds=len(rows),
                                **{k: counts[k] for k in sorted(STATUSES)},
                                confirms=sum(r["confirms"] for r in candidates), confirmation_attempts=3*len(candidates),
                                replay_matches=sum(r["replay_ok"] is True for r in candidates),
                                replay_attempts=sum(r["replay_ok"] is not None for r in candidates),
                                **{f"{p}_{k}":sum(r[p][k] for r in rows) for p in STAGES for k in COSTS}))
        defective = [r for group in groups(cases, data, m) for r in group]
        for b in BUDGETS:
            paid = [r for r in defective if hit(r, b) and sum(r[p]["windows"] for p in STAGES) <= b]
            inclusive.append(dict(method=m, budget=b, denominator=len(defective),
                                  search_confirmed=sum(hit(r, b) for r in defective), inclusive_confirmed=len(paid),
                                  inclusive_percent=100*len(paid)/len(defective), inclusive_duts=len({r["case"] for r in paid})))
    write_csv("outcomes_by_dut.csv", per_dut)
    write_csv("inclusive_coverage.csv", inclusive)
    return inclusive


def reaction():
    intervals = {m: [] for m in B}
    with gzip.open(RESULTS / "traces.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            _, m, _, blocks = json.loads(line)
            if m in intervals:
                for _, _, windows, _ in blocks:
                    if len(windows) == 2:
                        first, second = windows
                        decision = first["frames"][0][0] - first["gap"] + first["record"][2]
                        next_a = second["frames"][0][0] - second["gap"]
                        intervals[m].append(next_a - decision)
    stats = [dict(method=m, advances=len(ns), min_clocks=min(ns), median_clocks=float(np.median(ns)),
                  max_clocks=max(ns)) for m, ns in intervals.items()]
    write_csv("reaction.csv", stats)
    return stats


def figures(coverage, costs):
    colors = ("#005d78", "#c05216", "#6651a6")
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for m, color, marker in zip(A, colors, ("o", "s", "^")):
        series = [r for r in coverage if r["method"] == m]
        for axis, field in ((left, "macro_percent"), (right, "distinct_duts")):
            axis.plot(BUDGETS, [r[field] for r in series], marker=marker, label=LABEL[m], color=color,
                      linestyle={"chip": "-", "scan": "--", "random": ":"}[m])
            axis.set_xscale("log", base=2)
            axis.set_xticks(BUDGETS, labels=BUDGETS)
            axis.set_xlabel("Search budget (valid windows)")
            axis.grid(axis="y", alpha=.25)
    left.set(ylabel="Confirmed defective-variant seeds (%)", ylim=(-3, 103))
    right.set(ylabel="Distinct defective variants reached", ylim=(-.3, 10.3), yticks=range(0, 11, 2))
    left.legend(frameon=False)
    fig.savefig(RESULTS / "discovery.png", dpi=170)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 3.8), layout="constrained")
    for pos, population, color in ((-.2, "all", colors[0]), (.2, "healthy", colors[1])):
        rates = [next(r["windows_per_second"] for r in costs if
                      (r["method"], r["population"], r["stage"]) == (m, population, "search")) for m in B]
        ax.bar(np.arange(len(B))+pos, rates, .4, color=color,
               label="All searches, including misses" if population == "all" else "Healthy control")
    ax.set_xticks(range(len(B)), labels=[LABEL[m] for m in B])
    ax.set_ylabel("Valid search windows / simulated second")
    ax.set_ylim(bottom=0)
    ax.ticklabel_format(axis="y", style="plain")
    ax.legend(frameon=False)
    fig.savefig(RESULTS / "host_throughput.png", dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5), layout="constrained")
    delays = [0, 1, 10, 100]
    for ax, field, lookup, ylabel in [
        (axes[0], "macro_percent", {r["method"]:r for r in coverage if r["budget"] == 128}, "Confirmed defective seeds (%)"),
        (axes[1], "simulated_seconds", {r["method"]:r for r in costs if r["population"] == "all" and r["stage"] == "search"},
         "Total search time for 330 sequences (s)"),
    ]:
        ax.axhline(lookup["chip"][field], color=colors[0], linestyle="--", linewidth=3, label="On-chip reference")
        ax.plot(delays, [lookup[m][field] for m in B[1:]], color=colors[1], marker="o", label="Host feedback")
        ax.set_xscale("symlog", linthresh=1, base=10)
        ax.set_xticks(delays, labels=delays)
        ax.set_xlabel("Additional host delay (µs)")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=.25)
    axes[0].set_ylim(0, 100)
    axes[1].set_ylim(bottom=0)
    axes[0].legend(frameon=False, loc="lower left")
    fig.savefig(RESULTS / "host_delay.png", dpi=170)
    plt.close(fig)


def table(headers, rows):
    lines = [headers, ["---"]*len(headers), *rows]
    return "\n".join("| " + " | ".join(map(str, line)) + " |" for line in lines)


def report(cases, data, coverage, by_case, comparisons, costs, outcomes, equivalence, inclusive, reaction_stats):
    cov = {(r["method"], r["budget"]):r for r in coverage}
    dut = {(r["case"], r["method"], r["budget"]):r["confirmed"] for r in by_case}
    totals = {(r["method"], r["population"], r["stage"]):r for r in costs}
    outs = {(r["method"], r["population"]):r for r in outcomes}
    text = ["# Discovery and feedback placement on the frozen internal controller panel",
            "Experiments A and B use ten defective controller models and one healthy control, each with 30 paired seeds. "
            "Each method receives up to 128 valid search windows per seed and variant. Credit requires a matching wire violation and P4 record, "
            "three fresh-block confirmations, and peer-free timed replay. These are synthetic digital simulations at a 50 MHz system clock. "
            "[Preregistered design](../docs/RESEARCH_EVALUATION_PLAN.md) · [Panel audit](PANEL_AUDIT.md) · "
            "[Experiment C, operating boundaries and capacity](BOUNDARY.md)",
            "## A. Confirmed discovery by search budget",
            "Each entry gives confirmed seeds out of 300, the mean per-variant confirmation percentage, and distinct variants reached out of ten. "
            "Each variant receives equal weight. The 30 healthy searches per method are scored separately. Reusing the same sequence prefixes "
            "at each budget preserves pairing. Confirmation and playback work is additional to the search budget.",
            table(["Windows", *[LABEL[m] for m in A]], [
                [b, *[f"{r['confirmed']}/300 ({r['macro_percent']:.1f}%), {r['distinct_duts']}/10"
                      for r in [cov[m, b] for m in A]]] for b in BUDGETS]),
            "![Confirmed discovery curves by method and budget](results/discovery.png)",
            "The fixed scan was selected on the public development set. At 2, 4 and 8 windows the linear scan confirmed 0, 0 and 0 of 90 defective seeds, "
            "the modular scan confirmed 0, 0 and 30, and the selected scan confirmed 30, 60 and 90. Its second-window sequence starts with "
            "0xA3, 0x59 and 0xCE, then the remaining byte values in increasing order. [Development scores](development.json) · [Frozen strategies](experiment.py)",
            "### Paired effects and uncertainty",
            "Positive differences favor on-chip feedback. Each paired comparison uses the same variant and seed. The interval gives the 2.5th and 97.5th percentiles "
            "from 20,000 paired bootstrap resamples of ten whole variants, retaining all 30 seeds of each sampled variant. It describes sensitivity to panel composition. "
            "The internally authored variants do not constitute a probability sample of production controllers.",
            table(["Windows", "Comparator", "Chip only", "Comparator only", "Difference (percentage points)", "Variant bootstrap interval (pp)"],
                  [[r["budget"], LABEL[r["comparator"]], r["chip_only"], r["comparator_only"], f"{r['chip_minus_comparator_pp']:+.1f}",
                    f"[{r['resample_p2_5_pp']:+.1f}, {r['resample_p97_5_pp']:+.1f}]"]
                   for r in sorted(comparisons, key=lambda r:r["budget"]) if r["comparator"] in A]),
            "### Which variants the methods reached",
            "Confirmed seeds out of 30 at 128 windows. The downloadable table includes every method, variant and budget.",
            table(["Variant", *[LABEL[m] for m in A]], [[c, *[dut[c, m, 128] for m in A]] for c in cases]),
            "[All per-variant budget estimates](results/coverage_by_dut.csv) · [Outcome and resource costs by variant and method, including healthy](results/outcomes_by_dut.csv) · [All paired comparisons](results/paired_comparisons.csv)"]
    for m in A[1:]:
        ahead = [c for c in cases if dut[c, m, 128] > dut[c, "chip", 128]]
        same = [c for c in cases if dut[c, m, 128] == dut[c, "chip", 128]]
        text.append(f"At 128 windows {LABEL[m].lower()} confirmed more seeds than on-chip feedback for {len(ahead)} of ten variants"
                    + (" (" + ", ".join(ahead) + ")" if ahead else "") + f" and tied on {len(same)}.")
    timing = []
    for m in METHODS:
        o = outs[m, "defective"]
        hits = sorted(r["first"] for g in groups(cases, data, m) for r in g if hit(r, 128))
        quantiles = ", ".join(str(int(q)) for q in np.quantile(hits, [.25,.5,.75], method="inverted_cdf")) if hits else "—"
        timing.append([LABEL[m], o["first_run_confirmed"], o["confirmed_later_run"], o["confirmed"], quantiles, o["miss"],
                       o["inconclusive"] + o["unconfirmed"]])
    text.extend(["In a post hoc breakdown, the previous-tag comparator (c-32) accounts for 25 of the 28 net additional seed hits over scan, "
                 "and 22 of the 24 over random. Using the observed tag directly matches this mechanism. The repeat-value case (c-4c) favors scan, "
                 "8 seeds to 5. None of the policies discovered the 255-to-0 wrap case (c-6b) in the search. A separate, post-scoring directed "
                 "pin check reproduced each of the ten specified faults, including the wrap, alongside its healthy control. [Directed witness audit](results/directed-audit.json)",
                 "### First RUN, cumulative search and censoring",
                 "A chip RUN can contain two windows. Fixed, random and host experiments issue a separate RUN for each window. "
                 "The quartiles are observed first-hit window indices among confirmed sequences only (empirical inverse CDF). An exhausted miss is "
                 "right-censored after window 128. The remaining no-credit stops are listed separately. [Exact first-hit distribution by variant](results/first_hit_distribution.csv)",
                 table(["Method", "First RUN", "Later RUN", "Total confirmed / 300", "Hit-only Q1, median, Q3", "Censored at 128", "Other no-credit stops"], timing),
                 "### Search, confirmation and replay cost",
                 "Totals cover all 330 sequences per method, including healthy controls and exhausted searches. Repetitions start from the candidate block. "
                 "Confirmation and replay can therefore cost fewer windows than repeating the full search. Clock totals include reset, configuration, "
                 "host waits, RUN strobes and witness-page capture. Each completed record costs six measurement reads. A host copy adds three operand reads when needed.",
                 table(["Method", "Search windows / clocks", "Confirmation windows / clocks", "Replay windows / clocks", "Inclusive windows / clocks"],
                       [[LABEL[m], *[f"{r['windows']:,} / {r['clocks']:,}" for r in [totals[m, "all", p] for p in (*STAGES, "inclusive")]]]
                        for m in METHODS]),
                 table(["Method", "Confirmation matches / attempts", "Replay matches / attempts", "Healthy false alarms / 30", "Inconclusive / 330", "Unconfirmed / 330"],
                       [[LABEL[m], f"{o['confirmation_successes']}/{o['confirmation_attempts']}", f"{o['replay_successes']}/{o['replay_attempts']}",
                         outs[m, "healthy"]["false_alarm"], o["inconclusive"], o["unconfirmed"]] for m in METHODS for o in [outs[m, "all"]]]),
                 "The cost ledger also gives bus frames, setup/control strobes (including RUN), page reads, RUNs, resets, and reset clocks by stage and population. "
                 "[Cost ledger](results/costs.csv) · [Outcome counts](results/outcomes.csv)",
                 "If the **entire campaign** must fit within 128 windows, including three confirmations and playback, the credited counts become "
                 + ", ".join(f"{r['inclusive_confirmed']}/300 for {LABEL[r['method']].lower()} ({r['search_confirmed']-r['inclusive_confirmed']} beyond the inclusive limit)"
                             for r in inclusive if r["budget"] == 128 and r["method"] in A)
                 + ". [Inclusive versus search-only coverage at every budget](results/inclusive_coverage.csv)",
                 "## B. Feedback placement",
                 "Throughput is the sum of valid search windows divided by the sum of simulated search seconds, including misses. The healthy control supplies "
                 "a common fixed-work comparison with 30 full searches when every seed exhausts its 128 windows. Host waits of 0, 50, 500 and 5,000 clocks "
                 "model delays between the two single-window RUNs. The driver charges one clock per page read and two per configuration strobe.",
                 table(["Placement", "All search windows", "All search time (s)", "All windows/s", "Healthy windows", "Healthy search time (s)", "Healthy windows/s", "µs/healthy window"],
                       [[LABEL[m], f"{a['windows']:,}", f"{a['simulated_seconds']:.6f}", f"{a['windows_per_second']:,.1f}",
                         f"{h['windows']:,}", f"{h['simulated_seconds']:.6f}", f"{h['windows_per_second']:,.1f}", f"{1e6/h['windows_per_second']:.2f}"]
                        for m in B for a, h in [(totals[m, "all", "search"], totals[m, "healthy", "search"])]]),
                 "![Measured search throughput by feedback placement](results/host_throughput.png)",
                 "![Host delay against confirmed discovery and total simulated search time](results/host_delay.png)",
                 "The first poll starts once both notifications have arrived. Subtracting its measured B gap gives the A notification time "
                 "for each window. Adding the first record's decision tick to its A notification gives the registered verdict time. "
                 "Their difference across each advancing pair is the interval from verdict to next A notification (20 ns per clock). "
                 "Across the full search the zero-wait host and on-chip policy have nearly equal throughput because each block also pays "
                 "configuration, wire and measurement costs. Their local reaction intervals still differ.",
                 table(["Placement", "Advances", "Minimum (clocks)", "Median (clocks)", "Maximum (clocks)"],
                       [[LABEL[r["method"]], f"{r['advances']:,}", r["min_clocks"], f"{r['median_clocks']:g}", r["max_clocks"]]
                        for r in reaction_stats]),
                 "[Intervals reconstructed from search traces](results/reaction.csv)",
                 "Each host row below compares 330 matched variant–seed pairs against the on-chip policy. The wire digest includes relative frame offsets inside "
                 "each window, chip select, MOSI/MISO bytes, measured interrupt spacing, and recorded verdict, source and decision tick. "
                 "Absolute inter-window delays vary by placement. An expired window records a TIMEOUT on a missing service. Deadlines are relative to trial start. "
                 "The contract defines no deadline between RUNs.",
                 table(["Host wait", "Same outcome", "Same first index", "Same search windows", "Same wire digest", "Expired windows (host / chip)"],
                       [[LABEL[m], *[sum(r[k] for r in eq) for k in ("same_status", "same_first", "same_windows", "same_wire_digest")],
                         f"{sum(r['host_expired'] for r in eq)} / {sum(r['chip_expired'] for r in eq)}"]
                        for m in B[1:] for eq in [[r for r in equivalence if r["method"] == m]]]),
                 "[Seed-level host comparisons](results/host_equivalence.csv) · [Aggregate coverage including host policies](results/coverage.csv)"])
    chip = cov["chip",128]
    text.extend(["## Interpretation",
                 f"At the full search budget the on-chip policy confirmed {chip['confirmed']}/300 paired defective seeds "
                 f"and reached {chip['distinct_duts']}/10 distinct variants. Fixed scan reached {cov['scan',128]['distinct_duts']}/10 "
                 f"and random reached {cov['random',128]['distinct_duts']}/10. "
                 f"On the healthy fixed workload the on-chip search processed {totals['chip','healthy','search']['windows_per_second']/totals['host0','healthy','search']['windows_per_second']:.2f}× "
                 f"the windows per second of the zero-wait host and {totals['chip','healthy','search']['windows_per_second']/totals['host100','healthy','search']['windows_per_second']:.2f}× "
                 "the rate of the 100 µs host. These ratios measure simulated interface and idle cost under the common witness-readout protocol.",
                 "Development and panel authorship are internal. Findings apply to these controller models, reply and gap distributions, and frozen image. "
                 "Estimating a population-wide discovery rate or physical host performance would require independent controllers and measured hardware.",
                 "## C. Operating boundary",
                 "Across all four sampled clock phases and four SPI modes at 5 MHz, 896 changing MISO bits reached their correct level 40.1–59.9 ns "
                 "after launch. The ninth rule exceeded program capacity. Extending the encodable fall-through path from two to eight rules moved "
                 "the reply from byte 3 to byte 9, adding 9.6 µs on the wire. [Operating boundaries, capacity and timing](BOUNDARY.md) · "
                 "[Case-level data](results/boundary/cases.csv) · [Boundary figure](results/boundary/boundary.png)",
                 "## Reproduction and data",
                 "Run from the repository root with Python 3, NumPy (1.22 or newer) and Matplotlib (3.6 or newer).",
                 "```sh\npython3 research/analyze.py\n```",
                 f"The input contains {len(data):,} unique sequences. Compressed search file SHA-256: `{hashlib.sha256(RAW.read_bytes()).hexdigest()}`. "
                 "[Raw outcomes](results/search.jsonl.gz) · [All search traces](results/traces.jsonl.gz) · [Candidate witnesses and replay](results/witnesses.jsonl.gz) · "
                 "[Reproduction commands and trace format](README.md)"])
    (HERE / "RESEARCH_RESULTS.md").write_text("\n\n".join(text)+"\n", encoding="utf-8")


def main():
    cases, data = load_rows()
    coverage, by_case, comparisons = discovery(cases, data)
    costs, outcomes, equivalence = accounting(cases, data)
    inclusive = detail(cases, data)
    reaction_stats = reaction()
    figures(coverage, costs)
    report(cases, data, coverage, by_case, comparisons, costs, outcomes, equivalence, inclusive, reaction_stats)


if __name__ == "__main__":
    main()
