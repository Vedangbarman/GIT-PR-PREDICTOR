import json, os, math
from datetime import datetime
import matplotlib.pyplot as plt

OUT_DIR = "output/images"
OUT_FILE = os.path.join(OUT_DIR, "bot_composition.png")

results = []
for owner in sorted(os.listdir("data/raw")):
    p = os.path.join("data/raw", owner)
    if not os.path.isdir(p):
        continue
    for f in os.listdir(p):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(p, f), encoding="utf-8"))
        prs = d["pull_requests"]
        merged = [pr for pr in prs if pr["mergedAt"]]
        if not merged:
            continue
        bot_frac = sum(1 for pr in prs if pr["author"] and pr["author"]["__typename"] == "Bot") / len(prs)
        hrs = sorted((datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")) -
                      datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))).total_seconds() / 3600
                     for pr in merged)
        median_h = hrs[len(hrs) // 2]
        same_day = sum(h < 24 for h in hrs) / len(hrs)
        results.append({"name": f"{owner}/{d['repo']}", "bot_frac": bot_frac,
                         "median_h": median_h, "same_day": same_day})

results.sort(key=lambda r: r["bot_frac"], reverse=True)

n = len(results)
cols = 4
rows = math.ceil(n / cols)
fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.4, rows * 4.6))
axes = axes.flatten()

for ax, r in zip(axes, results):
    bot_pct, human_pct = r["bot_frac"], 1 - r["bot_frac"]
    ax.pie([bot_pct, human_pct], colors=["#d64545", "#4577d6"],
           autopct=lambda p: f"{p:.0f}%" if p > 3 else "",
           startangle=90, wedgeprops={"edgecolor": "white", "linewidth": 1})
    ax.set_title(r["name"], fontsize=9, pad=14)
    ax.text(0, -1.3, f"median merge: {r['median_h']:.1f}h\n<24h: {r['same_day']:.0%}",
            ha="center", va="top", fontsize=7.5, color="#444")

for ax in axes[n:]:
    ax.axis("off")

fig.legend(["Bot-authored", "Human-authored"], loc="lower center", ncol=2,
           bbox_to_anchor=(0.5, -0.01), frameon=False, fontsize=10)
fig.suptitle("PR author composition by repo (sorted by bot share)", fontsize=13, y=0.995)
plt.subplots_adjust(hspace=0.65, wspace=0.3, top=0.90, bottom=0.05)

os.makedirs(OUT_DIR, exist_ok=True)
plt.savefig(OUT_FILE, dpi=150, bbox_inches="tight")
print(f"saved {OUT_FILE}")