import os
import csv
import time
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else None,
    "Accept": "application/vnd.github.v3+json"
}

if not GITHUB_TOKEN:
    print("Warning: GITHUB_TOKEN not found in environment variables. Rate limits will be severely restricted.")

SEARCH_SLEEP = 2.1 if GITHUB_TOKEN else 6.5  # 30/min auth, ~10/min unauth
MIN_MERGED_PRS = 500
CUTOFF = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "../../data/raw"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "repo_updated.csv")

# Explicit target repositories to force-include (Apache Spark removed - see note below)
FORCED_REPOS = [
    "nodejs/node",
    "kubernetes/kubernetes",
    "rust-lang/rust",
    "llvm/llvm-project",
    "pytorch/pytorch",
    "microsoft/vscode",
    "flutter/flutter",
    "python/cpython",
    "moby/moby",
    "denoland/deno",
    "oven-sh/bun",
    "django/django",
    "homebrew/brew",
    "hashicorp/terraform",
    "prometheus/prometheus",
    "alacritty/alacritty",
    "tauri-apps/tauri",
    "hoppscotch/hoppscotch",
    "golang/go",
    "helm/helm",
    "cli/cli",
    "fastapi/fastapi",
    "pallets/flask",
    "vitejs/vite",
    "vuejs/core",
    "tailwindlabs/tailwindcss",
    "supabase/supabase",
    "redis/redis",
    "curl/curl",
    "neovim/neovim",
    "opencv/opencv",
    "godotengine/godot",
    "electron/electron",
    "home-assistant/core",
    "ansible/ansible",
]

BLOCKLIST = [
    "awesome", "roadmap", "free-programming", "cheatsheet", "cheat-sheet",
    "tutorial", "interview", "-book", "bootcamp", "resources", "guide",
    "curriculum", "course", "list-of", "learning-", "-list", "leetcode",
    "leet-code", "interview-questions", "jstraining", "dism-multi-language",
    "profile-summary"
]


def should_block(repo_name):
    name_lower = repo_name.lower()
    return any(keyword in name_lower for keyword in BLOCKLIST)


def handle_rate_limit(response):
    if response.status_code == 403 and "X-RateLimit-Reset" in response.headers:
        reset_time = int(response.headers["X-RateLimit-Reset"])
        sleep_time = max(reset_time - int(time.time()), 0) + 1
        print(f"Rate limit exceeded. Sleeping for {sleep_time} seconds...")
        time.sleep(sleep_time)
        return True
    return False


def get_merged_prs_count(owner, repo):
    query = f"repo:{owner}/{repo} type:pr is:merged"
    url = f"https://api.github.com/search/issues?q={query}&per_page=1"

    while True:
        response = requests.get(url, headers=HEADERS)
        if handle_rate_limit(response):
            continue
        if response.status_code == 200:
            return response.json().get("total_count", 0)
        else:
            print(f"Failed to fetch PRs for {owner}/{repo}: {response.status_code}")
            return 0


def fetch_repo_details(repo_full_name):
    url = f"https://api.github.com/repos/{repo_full_name}"
    while True:
        response = requests.get(url, headers=HEADERS)
        if handle_rate_limit(response):
            continue
        if response.status_code == 200:
            data = response.json()
            merged = get_merged_prs_count(data["owner"]["login"], data["name"])
            if merged < MIN_MERGED_PRS:
                print(f"  [warn] {repo_full_name} only has {merged} merged PRs (forced-include, keeping anyway)")
            return {
                "owner": data["owner"]["login"],
                "repo": data["name"],
                "stars": data["stargazers_count"],
                "language": data["language"] or "Unknown",
                "pushed_at": data["pushed_at"],
                "merged_prs": merged
            }
        else:
            print(f"Failed to fetch metadata for {repo_full_name}: {response.status_code}")
            return None


def scout_small_repos(target_count=8, forced_set=None, max_pages=10):
    """Scouts repos with 1k-20k stars AND > MIN_MERGED_PRS merged PRs, not fork, pushed within 1yr."""
    if forced_set is None:
        forced_set = set()

    repos = []
    page = 1
    while len(repos) < target_count and page <= max_pages:
        q = f"stars:1000..20000 fork:false archived:false pushed:>{CUTOFF}"
        url = (f"https://api.github.com/search/repositories?q={q}"
               f"&sort=stars&order=desc&per_page=50&page={page}")
        response = requests.get(url, headers=HEADERS)
        if handle_rate_limit(response):
            continue
        if response.status_code != 200:
            print(f"Failed to scout repositories (page {page}): {response.status_code}")
            break

        items = response.json().get("items", [])
        if not items:
            break

        for item in items:
            if len(repos) >= target_count:
                break

            owner = item["owner"]["login"]
            repo_name = item["name"]
            full_identity = f"{owner}/{repo_name}".lower()

            if full_identity in forced_set or should_block(repo_name):
                continue

            time.sleep(SEARCH_SLEEP)
            merged_count = get_merged_prs_count(owner, repo_name)
            if merged_count <= MIN_MERGED_PRS:
                continue

            print(f"Scouting discovered repo: {owner}/{repo_name} ({merged_count} merged PRs)")
            repos.append({
                "owner": owner,
                "repo": repo_name,
                "stars": item["stargazers_count"],
                "language": item["language"] or "Unknown",
                "pushed_at": item["pushed_at"],
                "merged_prs": merged_count
            })

        page += 1
        time.sleep(SEARCH_SLEEP)

    return repos


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_repo_data = []
    seen_repos = set()

    print("Processing explicit target repositories...")
    for repo_name in FORCED_REPOS:
        full_name_lower = repo_name.lower()
        if full_name_lower not in seen_repos:
            print(f"Fetching: {repo_name}")
            details = fetch_repo_details(repo_name)
            if details:
                all_repo_data.append(details)
                seen_repos.add(full_name_lower)
            time.sleep(SEARCH_SLEEP)

    print("\nScouting general repositories between 1k and 20k stars, >500 merged PRs...")
    scouted_data = scout_small_repos(target_count=8, forced_set=seen_repos)
    all_repo_data.extend(scouted_data)

    print(f"\nWriting dataset to {OUTPUT_FILE}...")
    fields = ["owner", "repo", "stars", "language", "pushed_at", "merged_prs"]

    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in all_repo_data:
            writer.writerow(row)

    print(f"Execution complete. {len(all_repo_data)} repos written.")


if __name__ == "__main__":
    main()