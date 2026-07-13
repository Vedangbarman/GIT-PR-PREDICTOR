import os
import sqlite3
import json
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.github.com/graphql"
TOKEN = os.environ.get("GITHUB_TOKEN")
DB_PATH = "data/raw/pr_data.db"
OUT_DIR = "data/raw"

BATCH_SIZE = 20          # PRs per GraphQL request, via aliased sub-queries
REQUEST_SLEEP = 0.5      # pacing between batched requests
MIN_RATE_REMAINING = 200
CHECKPOINT_EVERY = 10    # batches, within a repo


def gh_post(query, variables, tries=5):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for attempt in range(tries):
        try:
            resp = requests.post(API_URL, json={"query": query, "variables": variables},
                                  headers=headers, timeout=60)
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  network error ({e}), retry in {wait}s")
            time.sleep(wait)
            continue

        if resp.status_code == 403:
            reset = resp.headers.get("X-RateLimit-Reset")
            wait = max(int(reset) - int(time.time()), 5) if reset else 30 * (attempt + 1)
            print(f"  403 rate limit, sleeping {wait:.0f}s")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = 10 * (attempt + 1)
            print(f"  server error ({resp.status_code}), retrying in {wait}s")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"request failed after {tries} retries")


def wait_for_rate_limit(rate):
    if rate["remaining"] < MIN_RATE_REMAINING:
        reset = datetime.fromisoformat(rate["resetAt"].replace("Z", "+00:00"))
        wait = (reset - datetime.now(timezone.utc)).total_seconds() + 5
        if wait > 0:
            print(f"  rate low ({rate['remaining']}), sleeping {wait:.0f}s")
            time.sleep(wait)


def build_batch_query(prs):
    """Packs multiple PRs into one GraphQL request using aliased root fields."""
    var_defs, fields = [], []
    variables = {}
    for i, (owner, name, number) in enumerate(prs):
        var_defs.append(f"$owner{i}: String!, $name{i}: String!, $number{i}: Int!")
        fields.append(
            f"p{i}: repository(owner: $owner{i}, name: $name{i}) {{ "
            f"pullRequest(number: $number{i}) {{ number "
            f"comments(first: 100) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ createdAt }} }} "
            f"reviews(first: 100) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ submittedAt }} }} }} }}"
        )
        variables[f"owner{i}"] = owner
        variables[f"name{i}"] = name
        variables[f"number{i}"] = number

    query = ("query(" + ", ".join(var_defs) + ") {\n" + "\n".join(fields) +
              "\n  rateLimit { remaining resetAt limit }\n}")
    return query, variables


CONTINUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!,
      $commentsCursor: String, $reviewsCursor: String,
      $needComments: Boolean!, $needReviews: Boolean!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      comments(first: 100, after: $commentsCursor) @include(if: $needComments) {
        pageInfo { hasNextPage endCursor }
        nodes { createdAt }
      }
      reviews(first: 100, after: $reviewsCursor) @include(if: $needReviews) {
        pageInfo { hasNextPage endCursor }
        nodes { submittedAt }
      }
    }
  }
  rateLimit { remaining resetAt limit }
}
"""


def paginate_remaining(owner, name, number, need_comments, need_reviews,
                        comments_cursor, reviews_cursor, comments_acc, reviews_acc):
    """Follow-up calls for the rare PR with >100 comments or >100 reviews."""
    while need_comments or need_reviews:
        variables = {
            "owner": owner, "name": name, "number": number,
            "commentsCursor": comments_cursor, "reviewsCursor": reviews_cursor,
            "needComments": need_comments, "needReviews": need_reviews,
        }
        data = gh_post(CONTINUE_QUERY, variables)
        pr = data["data"]["repository"]["pullRequest"]

        if need_comments:
            c = pr["comments"]
            comments_acc.extend([n["createdAt"] for n in c["nodes"]])
            need_comments = c["pageInfo"]["hasNextPage"]
            comments_cursor = c["pageInfo"]["endCursor"]
        if need_reviews:
            r = pr["reviews"]
            reviews_acc.extend([n["submittedAt"] for n in r["nodes"]])
            need_reviews = r["pageInfo"]["hasNextPage"]
            reviews_cursor = r["pageInfo"]["endCursor"]

        rate = data["data"]["rateLimit"]
        wait_for_rate_limit(rate)
        time.sleep(REQUEST_SLEEP)

    return comments_acc, reviews_acc


def fetch_eligible_prs():
    """Only repos and PRs that survived both exclusion layers -- ~130k, not ~230k."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT r.owner, r.name, p.number
        FROM pull_requests p JOIN repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL AND p.exclude_reason IS NULL
        ORDER BY r.owner, r.name, p.number
    """).fetchall()
    conn.close()

    repos = {}
    for owner, name, number in rows:
        repos.setdefault((owner, name), []).append(number)
    return repos


def out_path(owner, name):
    return os.path.join(OUT_DIR, owner, f"{name}_comments.json")


def checkpoint_path(owner, name):
    return os.path.join(OUT_DIR, owner, f"{name}_comments.partial.json")


def fetch_repo_timelines(owner, name, numbers, cp_path):
    results = {}
    if os.path.exists(cp_path):
        with open(cp_path, encoding="utf-8") as f:
            results = {int(k): v for k, v in json.load(f).items()}
        print(f"  resuming: {len(results)} PRs already fetched")

    remaining = [n for n in numbers if n not in results]
    batches = [remaining[i:i + BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]

    for bi, batch in enumerate(batches):
        prs = [(owner, name, n) for n in batch]
        query, variables = build_batch_query(prs)
        data = gh_post(query, variables)

        if data.get("errors"):
            print(f"  [warn] batch {bi} had errors: {[e.get('message', '') for e in data['errors']][:2]}")

        payload = data.get("data", {})
        for i, number in enumerate(batch):
            node = payload.get(f"p{i}")
            pr = node.get("pullRequest") if node else None
            if not pr:
                results[number] = {"comments": [], "reviews": []}
                continue

            comments_list = [c["createdAt"] for c in pr["comments"]["nodes"]]
            reviews_list = [r["submittedAt"] for r in pr["reviews"]["nodes"]]
            need_comments = pr["comments"]["pageInfo"]["hasNextPage"]
            need_reviews = pr["reviews"]["pageInfo"]["hasNextPage"]

            if need_comments or need_reviews:
                print(f"    PR #{number}: >100 comments/reviews, paginating further")
                comments_list, reviews_list = paginate_remaining(
                    owner, name, number, need_comments, need_reviews,
                    pr["comments"]["pageInfo"]["endCursor"] if need_comments else None,
                    pr["reviews"]["pageInfo"]["endCursor"] if need_reviews else None,
                    comments_list, reviews_list,
                )

            results[number] = {"comments": comments_list, "reviews": reviews_list}

        rate = payload.get("rateLimit")
        if rate:
            print(f"  batch {bi + 1}/{len(batches)}: +{len(batch)} PRs (rate {rate['remaining']}/{rate['limit']})")
            wait_for_rate_limit(rate)

        if (bi + 1) % CHECKPOINT_EVERY == 0:
            with open(cp_path, "w", encoding="utf-8") as f:
                json.dump(results, f)

        time.sleep(REQUEST_SLEEP)

    return results


def main():
    if not TOKEN:
        raise SystemExit("Missing GITHUB_TOKEN")

    repos = fetch_eligible_prs()
    total_prs = sum(len(v) for v in repos.values())
    print(f"{len(repos)} repos, {total_prs} eligible PRs queued")

    for (owner, name), numbers in repos.items():
        dest = out_path(owner, name)
        if os.path.exists(dest):
            print(f"[skip] {owner}/{name} already fetched")
            continue

        print(f"[fetch] {owner}/{name}: {len(numbers)} PRs")
        cp_path = checkpoint_path(owner, name)
        try:
            results = fetch_repo_timelines(owner, name, numbers, cp_path)
        except RuntimeError as e:
            print(f"  [error] {owner}/{name}: {e}")
            continue

        with open(dest, "w", encoding="utf-8") as f:
            json.dump({
                "owner": owner, "repo": name,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "pr_timelines": results,
            }, f, ensure_ascii=False)
        if os.path.exists(cp_path):
            os.remove(cp_path)
        print(f"  saved -> {dest}")


if __name__ == "__main__":
    main()