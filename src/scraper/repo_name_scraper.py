
import os, sys, time, csv
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests


load_dotenv()  # reads .env in cwd


TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"

API = "https://api.github.com"
SEARCH_SLEEP = 2.1 if TOKEN else 6.5  # 30/min auth, ~10/min unauth
MIN_STARS = 150
MIN_MERGED_PRS = 500
TARGET_N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
MAX_CHECKS = 80
CUTOFF = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
LANGS = ["python", "javascript", "typescript", "go", "rust", "java", "c++", "ruby"]

sess = requests.Session()
sess.headers.update(HEADERS)


def gh_get(url, params):
    while True:
        r = sess.get(url, params=params)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 30))
            time.sleep(max(reset - time.time(), 5))
            continue
        r.raise_for_status()
        return r.json()


def candidates():
    seen = {}
    for lang in LANGS:
        q = f"stars:>{MIN_STARS} language:{lang} pushed:>{CUTOFF} fork:false archived:false"
        data = gh_get(f"{API}/search/repositories",
                       {"q": q, "sort": "stars", "order": "desc", "per_page": 25})
        for item in data.get("items", []):
            seen[item["full_name"]] = item
        time.sleep(SEARCH_SLEEP)
    return sorted(seen.values(), key=lambda x: x["stargazers_count"], reverse=True)


def merged_pr_count(full_name):
    data = gh_get(f"{API}/search/issues",
                   {"q": f"repo:{full_name} is:pr is:merged", "per_page": 1})
    return data.get("total_count", 0)


def main():
    cands = candidates()
    print(f"{len(cands)} candidates")
    w = csv.writer(sys.stdout)
    w.writerow(["owner", "repo", "stars", "language", "pushed_at", "merged_prs"])
    found, checked = 0, 0
    for c in cands:
        if found >= TARGET_N or checked >= MAX_CHECKS:
            break
        checked += 1
        mp = merged_pr_count(c["full_name"])
        time.sleep(SEARCH_SLEEP)
        if mp > MIN_MERGED_PRS:
            found += 1
            w.writerow([c["owner"]["login"], c["name"], c["stargazers_count"],
                        c["language"], c["pushed_at"], mp])
            sys.stdout.flush()
    print(f"# selected {found}/{TARGET_N}, checked {checked}", file=sys.stderr)


if __name__ == "__main__":
    if not TOKEN:
        print("# no GITHUB_TOKEN set, running unauthenticated (slow, low rate limit)", file=sys.stderr)
    main()