import os
import csv
import time
from datetime import datetime
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else None,
    "Accept": "application/vnd.github.v3+json"
}

if not GITHUB_TOKEN:
    print("Warning: GITHUB_TOKEN not found in environment variables. Rate limits will be severely restricted.")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "../../data/raw"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "repo_updated.csv")

# Explicit target repositories to force-include
FORCED_REPOS = [
    "nodejs/node",
    "apache/spark",
    "kubernetes/kubernetes",
    "rust-lang/rust",
    "llvm/llvm-project",
    "pytorch/pytorch"
]

# Expanded blocklist to filter out curated lists, tutorials, leetcode, docs, and configurations
BLOCKLIST = [
    "awesome", "roadmap", "free-programming", "cheatsheet", "cheat-sheet",
    "tutorial", "interview", "-book", "bootcamp", "resources", "guide",
    "curriculum", "course", "list-of", "learning-", "-list", "leetcode",
    "leet-code", "interview-questions", "jstraining", "dism-multi-language",
    "profile-summary"
]

def should_block(repo_name):
    """Returns True if the repository name matches any blocklist keyword."""
    name_lower = repo_name.lower()
    return any(keyword in name_lower for keyword in BLOCKLIST)

def handle_rate_limit(response):
    """Handles GitHub API rate limits by sleeping if necessary."""
    if response.status_code == 403 and "X-RateLimit-Reset" in response.headers:
        reset_time = int(response.headers["X-RateLimit-Reset"])
        sleep_time = max(reset_time - int(time.time()), 0) + 1
        print(f"Rate limit exceeded. Sleeping for {sleep_time} seconds...")
        time.sleep(sleep_time)
        return True
    return False

def get_merged_prs_count(owner, repo):
    """Fetches the total count of merged Pull Requests for a repository."""
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
    """Fetches individual repository metadata."""
    url = f"https://api.github.com/repos/{repo_full_name}"
    while True:
        response = requests.get(url, headers=HEADERS)
        if handle_rate_limit(response):
            continue
        if response.status_code == 200:
            data = response.json()
            return {
                "owner": data["owner"]["login"],
                "repo": data["name"],
                "stars": data["stargazers_count"],
                "language": data["language"] or "Unknown",
                "pushed_at": data["pushed_at"],
                "merged_prs": get_merged_prs_count(data["owner"]["login"], data["name"])
            }
        else:
            print(f"Failed to fetch metadata for {repo_full_name}: {response.status_code}")
            return None

def scout_small_repos(target_count=8, forced_set=None):
    """Scouts for actual code repositories with 1k to 20k stars, respecting the blocklist."""
    if forced_set is None:
        forced_set = set()
        
    repos = []
    # Fetching fresh repositories within the star limit
    url = "https://api.github.com/search/repositories?q=stars:1000..20000&sort=updated&order=desc&per_page=50"
    
    while True:
        response = requests.get(url, headers=HEADERS)
        if handle_rate_limit(response):
            continue
        if response.status_code == 200:
            items = response.json().get("items", [])
            for item in items:
                # Stop immediately if we hit your requested size limit (5-10 small repos)
                if len(repos) >= target_count:
                    break
                    
                owner = item["owner"]["login"]
                repo_name = item["name"]
                full_identity = f"{owner}/{repo_name}".lower()
                
                # Filter out forced repos and blocklist matches
                if full_identity in forced_set or should_block(repo_name):
                    continue
                    
                print(f"Scouting discovered repo: {owner}/{repo_name}")
                repos.append({
                    "owner": owner,
                    "repo": repo_name,
                    "stars": item["stargazers_count"],
                    "language": item["language"] or "Unknown",
                    "pushed_at": item["pushed_at"],
                    "merged_prs": get_merged_prs_count(owner, repo_name)
                })
            break
        else:
            print(f"Failed to scout repositories: {response.status_code}")
            break
            
    return repos

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    all_repo_data = []
    seen_repos = set()

    # 1. Process forced inclusions
    print("Processing explicit target repositories...")
    for repo_name in FORCED_REPOS:
        full_name_lower = repo_name.lower()
        if full_name_lower not in seen_repos:
            print(f"Fetching: {repo_name}")
            details = fetch_repo_details(repo_name)
            if details:
                all_repo_data.append(details)
                seen_repos.add(full_name_lower)

    # 2. Scout 5-10 random small repos (setting target to 8)
    print("\nScouting general repositories between 1k and 20k stars...")
    scouted_data = scout_small_repos(target_count=8, forced_set=seen_repos)
    all_repo_data.extend(scouted_data)

    # 3. Write strictly required formats to CSV
    print(f"\nWriting dataset to {OUTPUT_FILE}...")
    fields = ["owner", "repo", "stars", "language", "pushed_at", "merged_prs"]
    
    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in all_repo_data:
            writer.writerow(row)
            
    print("Execution complete successfully.")

if __name__ == "__main__":
    main()