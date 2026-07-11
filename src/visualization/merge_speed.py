import os
import json
import matplotlib.pyplot as plt
from datetime import datetime

FLAGGED = {"openclaw/openclaw", "NousResearch/hermes-agent", "tensorflow/tensorflow"}  # bot/automation-dominated, confirmed via author __typename + merge-speed audit


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


def main():
    data = {}
    for owner in sorted(os.listdir("data/raw")):
        p = os.path.join("data/raw", owner)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if not f.endswith(".json"):
                continue
            name = f"{owner}/{f[:-5]}"
            hrs = load_hours(os.path.join(p, f))
            if hrs:
                data[name] = hrs

    names = sorted(data, key=lambda n: sorted(data[n])[len(data[n]) // 2])
    colors = ["#d64545" if n in FLAGGED else "#4577d6" for n in names]

    fig, axes = plt.subplots(1, 2, figsize=(15, 7))

    box = axes[0].boxplot([data[n] for n in names], vert=False, patch_artist=True, showfliers=False)
    for patch, c in zip(box["boxes"], colors):
        patch.set_facecolor(c)
    axes[0].set_yticklabels(names)
    axes[0].set_xscale("log")
    axes[0].axvline(24, color="gray", linestyle="--", linewidth=1, label="24h")
    axes[0].set_xlabel("hours to merge (log scale)")
    axes[0].set_title("Merge-time distribution per repo")
    axes[0].legend()

    pct24 = [sum(h < 24 for h in data[n]) / len(data[n]) * 100 for n in names]
    axes[1].barh(names, pct24, color=colors)
    axes[1].set_xlabel("% merged within 24h")
    axes[1].set_title("Same-day merge rate")
    axes[1].set_xlim(0, 100)

    plt.tight_layout()
    out = "merge_speed_audit.png"
    plt.savefig(out, dpi=150)
    print(f"saved {out}")

    for n in names:
        h = sorted(data[n])
        med = h[len(h) // 2]
        p24 = sum(x < 24 for x in h) / len(h) * 100
        flag = "  <-- FLAGGED" if n in FLAGGED else ""
        print(f"{n:25s} n={len(h):5d}  median={med:7.1f}h  <24h={p24:5.1f}%{flag}")


if __name__ == "__main__":
    main()