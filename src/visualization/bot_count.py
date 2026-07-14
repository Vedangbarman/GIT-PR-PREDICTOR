import os
import json
import math
import matplotlib.pyplot as plt

DATA_DIR = "data/raw/JSON FILES"
OUT_DIR = "output/images"
GROUP_SIZE = 15


def load_repo_stats(path):
    d = json.load(open(path, encoding="utf-8"))
    prs = d.get("pull_requests", [])
    total = len(prs)
    bots = sum(1 for pr in prs if pr.get("author") and pr["author"].get("__typename") == "Bot")
    return total, bots


def main():
    results = []
    for owner in sorted(os.listdir(DATA_DIR)):
        p = os.path.join(DATA_DIR, owner)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if not f.endswith(".json") or f.endswith(".partial.json"):
                continue
            total, bots = load_repo_stats(os.path.join(p, f))
            if total == 0:
                continue
            results.append({"name": f"{owner}/{f[:-5]}", "total": total, "bots": bots})

    results.sort(key=lambda r: r["bots"] / r["total"], reverse=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    n_groups = math.ceil(len(results) / GROUP_SIZE)

    for g in range(n_groups):
        chunk = results[g * GROUP_SIZE: (g + 1) * GROUP_SIZE]
        rows, cols = 3, 5
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.4, rows * 4.8))
        axes = axes.flatten()

        for ax, r in zip(axes, chunk):
            bot_n, human_n = r["bots"], r["total"] - r["bots"]
            explode = (0.12, 0) if bot_n > 0 else (0, 0)
            ax.pie(
                [bot_n, human_n],
                colors=["#d64545", "#4577d6"],
                explode=explode,
                autopct=lambda p: f"{p:.0f}%" if p > 3 else "",
                startangle=90,
                wedgeprops={"edgecolor": "white", "linewidth": 1.2},
                textprops={"fontsize": 8.5},
            )
            ax.set_title(r["name"], fontsize=9, pad=14)
            ax.text(0, -1.4, f"{r['bots']}/{r['total']} bot PRs",
                    ha="center", va="top", fontsize=7.5, color="#444")

        for ax in axes[len(chunk):]:
            ax.axis("off")

        fig.legend(["Bot-authored", "Human-authored"], loc="lower center", ncol=2,
                    bbox_to_anchor=(0.5, -0.01), frameon=False, fontsize=11)
        lo, hi = g * GROUP_SIZE + 1, g * GROUP_SIZE + len(chunk)
        fig.suptitle(f"Bot vs human PR share — repos {lo}-{hi} of {len(results)} (sorted by bot share)",
                     fontsize=13, y=0.995)
        plt.subplots_adjust(hspace=0.7, wspace=0.3, top=0.90, bottom=0.07)

        out_file = os.path.join(OUT_DIR, f"bot_composition_group{g + 1}.png")
        plt.savefig(out_file, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"saved {out_file} ({len(chunk)} repos)")


if __name__ == "__main__":
    main()