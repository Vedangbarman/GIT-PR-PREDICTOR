import os
import json
from collections import defaultdict

import matplotlib.pyplot as plt

DATA_DIR = "data/raw"
OUT_DIR = "output/images"
OUT_FILE = os.path.join(OUT_DIR, "ai_pr_distribution.png")

AI_KEYWORDS = [
    "claude", "gpt", "gemini", "codex", "sweep", "coderabbit",
    "copilot", "cursor", "cody", "qodo", "bito", "mutableai", "kessler"
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    repo_counts = {}

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

                counts = defaultdict(int)

                for pr in prs:
                    author = pr.get("author")
                    if not author:
                        continue

                    login = author.get("login", "").lower()

                    for keyword in AI_KEYWORDS:
                        if keyword in login:
                            counts[keyword] += 1
                            break

                repo = f"{owner}/{file[:-5]}"
                repo_counts[repo] = counts

            except Exception:
                continue

    # Sort repositories by total AI PRs
    repos = sorted(
        repo_counts,
        key=lambda r: sum(repo_counts[r].values()),
        reverse=True,
    )

    fig, ax = plt.subplots(figsize=(14, max(8, len(repos) * 0.35)))

    left = [0] * len(repos)

    for agent in AI_KEYWORDS:
        values = [repo_counts[r].get(agent, 0) for r in repos]

        if sum(values) == 0:
            continue

        ax.barh(repos, values, left=left, label=agent)

        left = [l + v for l, v in zip(left, values)]

    ax.set_title("AI-authored Pull Requests by Repository")
    ax.set_xlabel("Number of AI-authored PRs")
    ax.set_ylabel("Repository")

    ax.legend(title="AI Agent", fontsize=8)
    ax.invert_yaxis()

    plt.tight_layout()
    plt.savefig(OUT_FILE, dpi=300)
    plt.close()

    print(f"Saved plot to {OUT_FILE}")


if __name__ == "__main__":
    main()