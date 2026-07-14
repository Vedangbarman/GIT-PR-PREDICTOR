import os
import json
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from datetime import datetime

DATA_DIR = "data/raw/JSON FILES"
OUT_DIR = "output/images"
GROUP_SIZE = 15

RANGE_COLOR = "#8fb3e8"   # 25th-75th percentile bar
MEDIAN_COLOR = "#1f4e96"  # median dot
BAR_COLOR = "#4577d6"     # same-day % bar

TICK_CANDIDATES = [
    (1, "1h"), (3, "3h"), (6, "6h"), (12, "12h"), (24, "1d"),
    (72, "3d"), (168, "1w"), (720, "1mo"), (2160, "3mo"), (8760, "1yr"),
]


def load_hours(path):
    d = json.load(open(path, encoding="utf-8"))
    hrs = []
    for pr in d["pull_requests"]:
        if not pr["mergedAt"]:
            continue
        c = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
        m = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
        hrs.append((m - c).total_seconds() / 3600)
    return hrs


def human_ticks(all_vals):
    lo, hi = min(all_vals) * 0.6, max(all_vals) * 1.5
    ticks = [(v, lbl) for v, lbl in TICK_CANDIDATES if lo <= v <= hi]
    if not ticks:
        ticks = [(v, lbl) for v, lbl in TICK_CANDIDATES if v <= hi][-4:]
    return [t[0] for t in ticks], [t[1] for t in ticks]


def main():
    data = {}
    for owner in sorted(os.listdir(DATA_DIR)):
        p = os.path.join(DATA_DIR, owner)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if not f.endswith(".json") or f.endswith(".partial.json"):
                continue
            name = f"{owner}/{f[:-5]}"
            hrs = load_hours(os.path.join(p, f))
            if hrs:
                data[name] = hrs

    names_sorted = sorted(data, key=lambda n: sorted(data[n])[len(data[n]) // 2])
    all_items = [(n, data[n]) for n in names_sorted]

    os.makedirs(OUT_DIR, exist_ok=True)
    n_groups = math.ceil(len(all_items) / GROUP_SIZE)

    for g in range(n_groups):
        chunk = all_items[g * GROUP_SIZE:(g + 1) * GROUP_SIZE]
        names = [n for n, _ in chunk]
        hours = [h for _, h in chunk]
        n = len(names)

        fig, axes = plt.subplots(1, 2, figsize=(15, max(4.5, n * 0.5 + 2)))

        ax = axes[0]
        for i, h in enumerate(hours):
            p25, med, p75 = np.percentile(h, [25, 50, 75])
            ax.plot([p25, p75], [i, i], color=RANGE_COLOR, linewidth=6,
                    solid_capstyle="round", zorder=2)
            ax.plot(med, i, "o", color=MEDIAN_COLOR, markersize=8, zorder=3)

        ax.set_yticks(range(n))
        ax.set_yticklabels(names)
        ax.set_ylim(-1, n)
        ax.set_xscale("log")

        all_vals = [v for h in hours for v in h]
        tick_vals, tick_labels = human_ticks(all_vals)
        ax.set_xticks(tick_vals)
        ax.set_xticklabels(tick_labels)
        ax.axvline(24, color="gray", linestyle="--", linewidth=1)
        ax.set_xlabel("time to merge")
        ax.set_title("Typical merge time per repo")

        legend_handles = [
            mlines.Line2D([], [], color=MEDIAN_COLOR, marker="o", linestyle="None",
                          markersize=8, label="median merge time"),
            mlines.Line2D([], [], color=RANGE_COLOR, linewidth=6,
                          label="middle 50% of PRs (25th-75th pct)"),
            mlines.Line2D([], [], color="gray", linestyle="--", label="24h"),
        ]
        ax.legend(handles=legend_handles, loc="lower right", fontsize=8.5, framealpha=0.9)

        ax2 = axes[1]
        pct24 = [sum(x < 24 for x in h) / len(h) * 100 for h in hours]
        ax2.barh(range(n), pct24, color=BAR_COLOR)
        ax2.set_yticks(range(n))
        ax2.set_yticklabels(names)
        ax2.set_ylim(-1, n)
        ax2.set_xlabel("% merged within 24h")
        ax2.set_xlim(0, 100)
        ax2.set_title("Same-day merge rate")

        lo, hi = g * GROUP_SIZE + 1, g * GROUP_SIZE + n
        fig.suptitle(f"Merge-speed audit — repos {lo}-{hi} of {len(all_items)}", fontsize=13)
        plt.tight_layout(rect=[0, 0, 1, 0.96])

        out = os.path.join(OUT_DIR, f"merge_speed_audit_group{g + 1}.png")
        plt.savefig(out, dpi=150)
        plt.close(fig)
        print(f"saved {out} ({n} repos)")

    for n in names_sorted:
        h = sorted(data[n])
        med = h[len(h) // 2]
        p24 = sum(x < 24 for x in h) / len(h) * 100
        print(f"{n:30s} n={len(h):5d}  median={med:7.1f}h  <24h={p24:5.1f}%")


if __name__ == "__main__":
    main()