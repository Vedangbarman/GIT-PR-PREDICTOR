import os
import json
import math
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

DATA_DIR = "data/raw"
OUT_DIR = "output/images"

POINT_COLOR = "#4577d6"
TREND_COLOR = "#d64545"


def load_repo_metrics(path):
    d = json.load(open(path, encoding="utf-8"))
    prs = d.get("pull_requests", [])
    total = len(prs)
    if total == 0:
        return None
    bots = sum(1 for pr in prs if pr.get("author") and pr["author"].get("__typename") == "Bot")
    hrs = []
    for pr in prs:
        if not pr.get("mergedAt"):
            continue
        c = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
        m = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
        hrs.append((m - c).total_seconds() / 3600)
    if not hrs:
        return None
    hrs.sort()
    median_h = hrs[len(hrs) // 2]
    pct24 = sum(h < 24 for h in hrs) / len(hrs) * 100
    return {"bot_frac": bots / total * 100, "median_h": median_h, "pct24": pct24}


def rankdata_avg(a):
    """Tie-aware ranking (ties get the average rank) -- needed since many repos sit at 0% bot share."""
    a = np.asarray(a, dtype=float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a))
    sorted_a = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def interpret(rho, p):
    direction = "positive" if rho > 0 else "negative" if rho < 0 else "no"
    if abs(rho) < 0.1:
        strength = "No real relationship"
    elif abs(rho) < 0.3:
        strength = f"weak {direction}"
    elif abs(rho) < 0.5:
        strength = f"moderate {direction}"
    elif abs(rho) < 0.7:
        strength = f"strong {direction}"
    else:
        strength = f"very strong {direction}"
    sig = "significant" if p < 0.05 else "not significant"
    return f"{strength}, {sig}"


def normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def spearman(x, y):
    """Spearman rank correlation + an approximate two-sided p-value (Fisher z-transform, no scipy needed)."""
    rx, ry = rankdata_avg(x), rankdata_avg(y)
    rho = float(np.corrcoef(rx, ry)[0, 1])
    n = len(x)
    if n <= 3:
        return rho, float("nan")
    rho_c = max(min(rho, 0.999999), -0.999999)
    z = math.atanh(rho_c) * math.sqrt(n - 3)
    p = 2 * (1 - normal_cdf(abs(z)))
    return rho, p


def main():
    rows = []
    # Using dummy data loading logic for demonstration; ensure DATA_DIR exists
    if os.path.exists(DATA_DIR):
        for owner in sorted(os.listdir(DATA_DIR)):
            p = os.path.join(DATA_DIR, owner)
            if not os.path.isdir(p):
                continue
            for f in os.listdir(p):
                if not f.endswith(".json") or f.endswith(".partial.json"):
                    continue
                m = load_repo_metrics(os.path.join(p, f))
                if m:
                    m["name"] = f"{owner}/{f[:-5]}"
                    rows.append(m)
    
    # If no data is found, we'll avoid crashing for this example snippet
    if not rows:
        print("No data found to plot. Exiting.")
        return

    bot_frac = np.array([r["bot_frac"] for r in rows])
    median_h = np.array([r["median_h"] for r in rows])
    pct24 = np.array([r["pct24"] for r in rows])
    n = len(rows)

    rho1, p1 = spearman(bot_frac, median_h)
    rho2, p2 = spearman(bot_frac, pct24)

    os.makedirs(OUT_DIR, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax = axes[0]
    ax.scatter(bot_frac, median_h, color=POINT_COLOR, alpha=0.75, edgecolor="white", s=60, zorder=3, label="Repositories")
    ax.set_yscale("log")
    if n > 1 and np.ptp(bot_frac) > 0:
        coeffs = np.polyfit(bot_frac, np.log10(median_h), 1)
        xs = np.linspace(bot_frac.min(), bot_frac.max(), 100)
        ax.plot(xs, 10 ** (coeffs[0] * xs + coeffs[1]), "--", color=TREND_COLOR, linewidth=2, zorder=2, label="Trend")
    ax.set_xlabel("bot-authored PRs (%)")
    ax.set_ylabel("median hours to merge (log scale)")
    # Moved stats cleanly into the title
    ax.set_title(f"Bot share vs. merge time\n(Spearman ρ={rho1:.2f}, p={p1:.3f} - {interpret(rho1, p1)})", fontsize=11)

    ax2 = axes[1]
    ax2.scatter(bot_frac, pct24, color=POINT_COLOR, alpha=0.75, edgecolor="white", s=60, zorder=3, label="Repositories")
    if n > 1 and np.ptp(bot_frac) > 0:
        coeffs2 = np.polyfit(bot_frac, pct24, 1)
        xs2 = np.linspace(bot_frac.min(), bot_frac.max(), 100)
        ax2.plot(xs2, coeffs2[0] * xs2 + coeffs2[1], "--", color=TREND_COLOR, linewidth=2, zorder=2, label="Trend")
    ax2.set_xlabel("bot-authored PRs (%)")
    ax2.set_ylabel("% merged within 24h")
    ax2.set_ylim(0, 100)
    # Moved stats cleanly into the title
    ax2.set_title(f"Bot share vs. same-day merge rate\n(Spearman ρ={rho2:.2f}, p={p2:.3f} - {interpret(rho2, p2)})", fontsize=11)
             
    # Placing the legend strictly outside the second plot on the right
    ax2.legend(loc="center left", bbox_to_anchor=(1.04, 0.5), borderaxespad=0)

    fig.suptitle("Correlation: bot-authored PR share vs merge speed", fontsize=15, y=1.02)
    footer = ("ρ (rho): -1 to +1, how consistently one variable rises/falls with the other (0 = no pattern)   |   "
              "p: odds this pattern is due to chance if no real relationship exists (< 0.05 = probably real)")
    fig.text(0.5, -0.02, footer, ha="center", fontsize=9, color="#444")
    
    # Adjust layout to fit everything
    plt.tight_layout()

    out = os.path.join(OUT_DIR, "bot_vs_merge_speed_correlation.png")
    # bbox_inches="tight" ensures the external legend and footer are fully captured
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"saved {out}")
    print(f"bot% vs median-hours-to-merge: Spearman rho={rho1:.3f}, p={p1:.4f}, n={n}")
    print(f"bot% vs %merged<24h:          Spearman rho={rho2:.3f}, p={p2:.4f}, n={n}")


if __name__ == "__main__":
    main()