import os
import sys
import csv
import json
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.github.com/graphql"
TOKEN = os.environ.get("GITHUB_TOKEN")

REPOS_CSV = "data/raw/CSV FILES/repo_updated.csv"
OUT_DIR = "data/raw/JSON FILES"
MAX_PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else None 
MIN_RATE_REMAINING = 100
PAGE_SLEEP = 0.3
MAX_PRS_TO_FETCH = 5000 

GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        state
        isDraft
        createdAt
        mergedAt
        closedAt
        additions
        deletions
        changedFiles
        author { login __typename }
        comments { totalCount }
        reviews { totalCount }
        labels(first: 20) { nodes { name } }
      }
    }
  }
  rateLimit { limit remaining resetAt }
}
"""


def read_repo_list(csv_path):
    repos = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            owner, name = row.get("owner", "").strip(), row.get("repo", "").strip()
            if owner and name:
                repos.append((owner, name))
    return repos


def safe(s):
    bad = '\\/:*?"<>|'
    return "".join("_" if c in bad else c for c in s)


def out_path(owner, name):
    return os.path.join(OUT_DIR, safe(owner), f"{safe(name)}.json")


def post_graphql(payload, headers, tries=5):
    for attempt in range(tries):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  network error ({e}), retry in {wait}s")
            time.sleep(wait)
            continue
            
        if resp.status_code == 403 and "secondary" in resp.text.lower():
            wait = 30 * (attempt + 1)
            print(f"  secondary rate limit, sleeping {wait}s")
            time.sleep(wait)
            continue
            
        # Handle GitHub Server Errors (like 502 Bad Gateway)
        if resp.status_code >= 500:
            wait = 10 * (attempt + 1) # Wait 10s, 20s, 30s...
            print(f"  server error ({resp.status_code}), retrying in {wait}s")
            time.sleep(wait)
            continue
            
        resp.raise_for_status()
        return resp.json()
        
    raise RuntimeError(f"GraphQL request failed after {tries} retries")


def wait_for_rate_limit(rate):
    if rate["remaining"] < MIN_RATE_REMAINING:
        reset = datetime.fromisoformat(rate["resetAt"].replace("Z", "+00:00"))
        wait = (reset - datetime.now(timezone.utc)).total_seconds() + 5
        if wait > 0:
            print(f"  rate low ({rate['remaining']}), sleeping {wait:.0f}s")
            time.sleep(wait)


def fetch_pull_requests(owner, name, max_pages=None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    cursor, all_prs, page = None, [], 0
    
    while True:
        variables = {"owner": owner, "name": name, "cursor": cursor}
        
        # Catch the RuntimeError here so we don't lose our partial data
        try:
            data = post_graphql({"query": GRAPHQL_QUERY, "variables": variables}, headers)
        except RuntimeError as e:
            print(f"  [Warning] GitHub API gave up: {e}")
            print(f"  Keeping the {len(all_prs)} PRs we successfully fetched.")
            break 

        if data.get("errors"):
            raise ValueError(data["errors"][0].get("message", str(data["errors"])))

        repo_data = data["data"]["repository"]
        if repo_data is None:
            raise ValueError("repo not found, private, or renamed")

        pr_block = repo_data["pullRequests"]
        nodes = pr_block["nodes"]
        
        # Append the new PRs
        all_prs.extend(nodes)

        rate = data["data"]["rateLimit"]
        page += 1
        print(f"  page {page}: +{len(nodes)} PRs (Total: {len(all_prs)}) (rate {rate['remaining']}/{rate['limit']})")
        wait_for_rate_limit(rate)

        # Stop if we hit 5,000 PRs
        if len(all_prs) >= MAX_PRS_TO_FETCH:
            all_prs = all_prs[:MAX_PRS_TO_FETCH] # Slice off any extras beyond 5000
            print(f"  Reached limit of {MAX_PRS_TO_FETCH} PRs, stopping pagination.")
            break

        if not pr_block["pageInfo"]["hasNextPage"]:
            break
            
        if max_pages and page >= max_pages:
            break
            
        cursor = pr_block["pageInfo"]["endCursor"]
        time.sleep(PAGE_SLEEP)

    return all_prs


def main():
    if not TOKEN:
        raise SystemExit("Missing GITHUB_TOKEN")
    if not os.path.exists(REPOS_CSV):
        raise SystemExit(f"Missing {REPOS_CSV}, run repo_name_scraper.py first")

    repos = read_repo_list(REPOS_CSV)
    print(f"{len(repos)} repos queued")

    for owner, name in repos:
        dest = out_path(owner, name)
        if os.path.exists(dest):
            print(f"[skip] {owner}/{name} already fetched")
            continue

        print(f"[fetch] {owner}/{name}")
        try:
            prs = fetch_pull_requests(owner, name, MAX_PAGES)
        except (ValueError, RuntimeError) as e:
            print(f"  [error] {owner}/{name}: {e}")
            continue

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        payload = {
            "owner": owner,
            "repo": name,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "pr_count": len(prs),
            "pull_requests": prs,
        }
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f"  saved {len(prs)} PRs -> {dest}")


if __name__ == "__main__":
    main()