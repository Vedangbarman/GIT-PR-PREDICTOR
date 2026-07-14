import os
import json

import matplotlib.pyplot as plt

DATA_DIR = "data/raw/JSON FILES"
OUT_DIR = "output/images"
OUT_FILE = os.path.join(OUT_DIR, "open_prs_by_repo.png")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    repos = []
    total_prs = []
    open_prs = []

    for owner in sorted(os.listdir(DATA_DIR)):
        owner_path = os.path.join(DATA_DIR, owner)
        if not os.path.isdir(owner_path):
            continue

        for file in os.listdir(owner_path):
            if not file.endswith(".json") or file.endswith(".partial.json"):
                continue

            path = os.path.join(owner_path, file)

            try:
                with open(path, encoding="utf-8") as f:
                    prs = json.load(f).get("pull_requests", [])

                repos.append(f"{owner}/{file[:-5]}")
                total_prs.append(len(prs))
                open_prs.append(sum(pr["state"] == "OPEN" for pr in prs))

            except Exception:
                continue

    # Sort by open percentage
    data = []

    for repo, total, open_ in zip(repos, total_prs, open_prs):
        pct = (open_ / total * 100) if total else 0
        data.append((repo, pct, open_, total))

    data.sort(key=lambda x: x[1], reverse=True)

    repos = [d[0] for d in data]
    percent = [d[1] for d in data]

    plt.figure(figsize=(12, max(8, len(repos) * 0.3)))

    plt.barh(repos, percent)

    plt.xlabel("Open Pull Requests (%)")
    plt.title("Percentage of Open Pull Requests by Repository")

    plt.xlim(0, max(percent) * 1.1)
    plt.gca().invert_yaxis()

    plt.tight_layout()
    plt.savefig(OUT_FILE, dpi=300)
    plt.close()


if __name__ == "__main__":
    main()