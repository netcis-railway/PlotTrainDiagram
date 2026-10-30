"""
plot_gurobi_progress.py
-----------------------
Reads a Gurobi solver log file, extracts the branch-and-bound progress table,
and plots incumbent objective value and best bound vs. computation time.

Usage:
    python plot_gurobi_progress.py <logfile>
    python plot_gurobi_progress.py  (uses hardcoded filename .\\Results\\logFile_latest.txt )
"""

import re
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ── regex patterns ────────────────────────────────────────────────────────────

RE_HEADER = re.compile(r"Expl\s+Unexpl\s+\|")
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
RE_ROOT = re.compile(r"Root relaxation:\s+objective\s+(" + NUMBER + ")")
RE_FINAL = re.compile(r"Best objective\s+(" + NUMBER + r"|-),\s+best bound\s+(" + NUMBER + r"|-)")
RE_TIMED = re.compile(r"\s(" + NUMBER + r")s\s*$")

# Trailing 5 fields: Incumbent  BestBd  Gap%  It/Node  Time
RE_TAIL = re.compile(
    r"(?<!\S)(" + NUMBER + r"|-)\s+"
    r"(" + NUMBER + r"|-)\s+"
    r"(" + NUMBER + r"%|-)\s+"
    r"(" + NUMBER + r"|-)\s+"
    r"(" + NUMBER + r")s\s*$"
)

# Flag at the very start of the line: H = heuristic, * = B&B node, else ' '
RE_FLAG = re.compile(r"^([H\*])")


# ── parser ────────────────────────────────────────────────────────────────────


def parse_gurobi_log(filename: str):
    """
    Returns a dict:
        times       – list[float]
        incumbents  – list[float|None]  (carries forward last known value)
        best_bounds – list[float|None]
        flags       – list[str]  ('H', '*', or ' ' for each row)
        root_obj    – float|None
        final_obj   – float|None
        final_bound – float|None
        total_time  – float|None
    """
    times, incumbents, best_bounds, flags = [], [], [], []
    root_obj = final_obj = final_bound = total_time = None

    in_table = False
    current_incumbent = None

    with open(filename, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = RE_ROOT.search(line)
            if m:
                root_obj = float(m.group(1))
                continue

            if RE_HEADER.search(line):
                in_table = True
                continue

            m = RE_FINAL.search(line)
            if m:
                final_obj = float(m.group(1)) if m.group(1) != "-" else None
                final_bound = float(m.group(2)) if m.group(2) != "-" else None
                in_table = False
                continue

            m = re.search(r"Explored.*in\s+([\d\.]+)\s+seconds", line)
            if m:
                total_time = float(m.group(1))
                continue

            if not in_table:
                continue
            if not RE_TIMED.search(line):
                continue

            m = RE_TAIL.search(line)
            if not m:
                continue

            inc_str, bd_str, _, _, time_str = m.groups()

            # Row flag
            fm = RE_FLAG.match(line.lstrip())
            flag = fm.group(1) if fm else " "

            t = float(time_str)
            bd = float(bd_str) if bd_str != "-" else None
            if inc_str != "-":
                current_incumbent = float(inc_str)

            times.append(t)
            incumbents.append(current_incumbent)
            best_bounds.append(bd)
            flags.append(flag)

    return dict(
        times=times,
        incumbents=incumbents,
        best_bounds=best_bounds,
        flags=flags,
        root_obj=root_obj,
        final_obj=final_obj,
        final_bound=final_bound,
        total_time=total_time,
    )


# ── plotter ───────────────────────────────────────────────────────────────────


def plot_progress(data: dict, filename: str, *, output_path=None, show=True):
    times = data["times"]
    incumbents = data["incumbents"]
    best_bounds = data["best_bounds"]
    flags = data["flags"]

    # ── collect series ────────────────────────────────────────────────────
    t_all, v_all = [], []  # every row with a known incumbent
    t_new, v_new, f_new = [], [], []  # improvement rows + their flag
    t_bd, v_bd = [], []
    prev_inc = None

    for t, inc, bd, flag in zip(times, incumbents, best_bounds, flags):
        if inc is not None:
            t_all.append(t)
            v_all.append(inc)
            if prev_inc is None or inc != prev_inc:
                t_new.append(t)
                v_new.append(inc)
                f_new.append(flag)
                prev_inc = inc
        if bd is not None:
            t_bd.append(t)
            v_bd.append(bd)

    # Split improvement rows by flag type
    t_H = [t for t, f in zip(t_new, f_new) if f == "H"]
    v_H = [v for v, f in zip(v_new, f_new) if f == "H"]
    t_BB = [t for t, f in zip(t_new, f_new) if f == "*"]
    v_BB = [v for v, f in zip(v_new, f_new) if f == "*"]
    t_other = [t for t, f in zip(t_new, f_new) if f not in ("H", "*")]
    v_other = [v for v, f in zip(v_new, f_new) if f not in ("H", "*")]

    # ── figure ────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(11, 5))

    # Best bound (dashed blue)
    if t_bd:
        ax.plot(t_bd, v_bd, color="steelblue", linewidth=1.2, linestyle="--", label="Best bound")

    if not t_bd and data["final_bound"] is not None:
        ax.axhline(data["final_bound"], color="steelblue", linestyle="--", label="Final best bound")

    # Root LP relaxation
    if data["root_obj"] is not None:
        ax.axhline(
            data["root_obj"],
            color="steelblue",
            linewidth=0.8,
            linestyle=":",
            alpha=0.6,
            label=f"Root LP relaxation ({data['root_obj']:.0f})",
        )

    # All incumbent rows — small translucent dots
    if t_all:
        ax.scatter(
            t_all,
            v_all,
            color="crimson",
            s=8,
            alpha=0.35,
            zorder=3,
            label="Incumbent (all logged rows)",
        )

    # Step line through improvement points
    if t_new:
        ax.step(
            t_new,
            v_new,
            where="post",
            color="crimson",
            linewidth=1.8,
            zorder=4,
            label="Incumbent (improvements)",
        )

    # H-found improvements: small red dot + blue hollow ring
    if t_H:
        ax.scatter(t_H, v_H, s=28, color="crimson", zorder=6)
        ax.scatter(
            t_H,
            v_H,
            s=120,
            facecolors="none",
            edgecolors="royalblue",
            linewidths=1.8,
            zorder=7,
            label="Found by MIP heuristic (H)",
        )

    # B&B-found improvements: small red dot + green hollow diamond
    if t_BB:
        ax.scatter(t_BB, v_BB, s=28, color="crimson", zorder=6)
        ax.scatter(
            t_BB,
            v_BB,
            s=120,
            facecolors="none",
            edgecolors="forestgreen",
            linewidths=1.8,
            marker="D",
            zorder=7,
            label="Found by B&B node (*)",
        )

    # Other (unlabelled rows that carry an improvement)
    if t_other:
        ax.scatter(t_other, v_other, s=28, color="crimson", zorder=6)

    # Final annotation
    if data["final_obj"] is not None:
        objective, bound = data["final_obj"], data["final_bound"]
        gap_pct = (
            abs(objective - bound) / abs(objective) * 100
            if bound is not None and objective != 0
            else 0
            if bound == objective
            else None
        )
        gap_text = f"{gap_pct:.1f}%" if gap_pct is not None else "undefined"
        ax.axhline(data["final_obj"], color="crimson", linewidth=0.7, linestyle=":", alpha=0.5)
        annotation = f"Final: {data['final_obj']:.1f}  (gap {gap_text})"
        if data["total_time"] is not None:
            ax.annotate(
                annotation,
                xy=(data["total_time"], data["final_obj"]),
                xytext=(-10, 12),
                textcoords="offset points",
                fontsize=9,
                color="crimson",
                ha="right",
            )
        else:
            ax.text(
                0.98,
                0.95,
                annotation,
                transform=ax.transAxes,
                fontsize=9,
                color="crimson",
                ha="right",
                va="top",
            )

    # ── formatting ────────────────────────────────────────────────────────
    if data["total_time"] is not None:
        ax.set_xlim(0, max(1, data["total_time"], *times) * 1.03)
    ax.set_xlabel("Computation time (s)", fontsize=12)
    ax.set_ylabel("Objective value", fontsize=12)
    ax.set_title(
        f"Gurobi B&B Progress: Objective vs. Computation Time\n(log file: {filename})", fontsize=13
    )
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda y, _: f"{y:,.0f}"))
    plt.tight_layout()

    out_png = output_path or filename.rsplit(".", 1)[0] + "_progress.png"
    fig.savefig(out_png, dpi=150)
    print(f"Figure saved to: {out_png}")
    if show:
        plt.show()
    return fig


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log_file = sys.argv[1] if len(sys.argv) > 1 else ".\\Results\\logFile_latest.txt"

    print(f"Parsing: {log_file}")
    data = parse_gurobi_log(log_file)

    n_H = sum(1 for f in data["flags"] if f == "H")
    n_BB = sum(1 for f in data["flags"] if f == "*")
    print(f"  Rows parsed        : {len(data['times'])}")
    print(f"  H-heuristic rows   : {n_H}")
    print(f"  B&B-node rows (*)  : {n_BB}")
    print(f"  Root relaxation    : {data['root_obj']}")
    print(f"  Final objective    : {data['final_obj']}")
    print(f"  Final best bound   : {data['final_bound']}")
    print(f"  Total solve time   : {data['total_time']} s")

    plot_progress(data, log_file)
