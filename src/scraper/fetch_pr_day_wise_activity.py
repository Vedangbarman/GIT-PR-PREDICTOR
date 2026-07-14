import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

TOKEN = os.getenv("GITHUB_TOKEN")
API_URL = "https://api.github.com/graphql"
OUT_DIR = ROOT / "data" / "raw" / "JSON FILES"
DB_CANDIDATES = (ROOT / "data" / "raw" / "SQL FILES"/"pr_data.db",)
CHECKPOINTS = (1, 3, 7, 15, 30)
BATCH_SIZE = 10
CHECKPOINT_EVERY = 5
REQUEST_SLEEP = 0.25
MIN_RATE_REMAINING = 150


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def safe_name(value):
    return "".join("_" if c in '\\/:*?\"<>|' else c for c in value)


def source_db():
    for path in DB_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError("Missing data/raw/pr_comments_timeline.db; run build_pr_comments_timeline_db.py first")


def post(query, variables, tries=5):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for attempt in range(tries):
        try:
            response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers, timeout=90)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if response.status_code in (403, 429) or response.status_code >= 500:
            reset = response.headers.get("X-RateLimit-Reset")
            wait = max(int(reset) - int(time.time()) + 5, 10) if reset else 15 * (attempt + 1)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("GitHub request failed after retries")


def wait_for_rate(rate):
    if not rate or rate["remaining"] >= MIN_RATE_REMAINING:
        return
    reset = parse_time(rate["resetAt"])
    wait = (reset - datetime.now(timezone.utc)).total_seconds() + 5
    if wait > 0:
        time.sleep(wait)


def event_query(prs):
    definitions, fields, variables = [], [], {}
    for i, (_, _, number) in enumerate(prs):
        definitions.append(f"$number{i}: Int!")
        fields.append(f"""
          p{i}: pullRequest(number: $number{i}) {{
            comments(first: 100) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ createdAt }} }}
            reviews(first: 100) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ submittedAt }} }}
            commits(first: 100) {{
              pageInfo {{ hasNextPage endCursor }}
              nodes {{ commit {{ committedDate additions deletions changedFilesIfAvailable }} }}
            }}
          }}
        """)
        variables[f"number{i}"] = number
    query = f"""
      query({', '.join(definitions)}) {{
        repository(owner: \"{prs[0][0]}\", name: \"{prs[0][1]}\") {{ {' '.join(fields)} }}
        rateLimit {{ limit remaining resetAt }}
      }}
    """
    return query, variables


CONTINUE_QUERY = """
query($owner: String!, $repo: String!, $number: Int!,
      $commentsCursor: String, $reviewsCursor: String, $commitsCursor: String,
      $needComments: Boolean!, $needReviews: Boolean!, $needCommits: Boolean!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      comments(first: 100, after: $commentsCursor) @include(if: $needComments) {
        pageInfo { hasNextPage endCursor } nodes { createdAt }
      }
      reviews(first: 100, after: $reviewsCursor) @include(if: $needReviews) {
        pageInfo { hasNextPage endCursor } nodes { submittedAt }
      }
      commits(first: 100, after: $commitsCursor) @include(if: $needCommits) {
        pageInfo { hasNextPage endCursor }
        nodes { commit { committedDate additions deletions changedFilesIfAvailable } }
      }
    }
  }
  rateLimit { limit remaining resetAt }
}
"""


def extend(items, key, nodes):
    if key == "comments":
        items[key].extend(x["createdAt"] for x in nodes)
    elif key == "reviews":
        items[key].extend(x["submittedAt"] for x in nodes if x["submittedAt"])
    else:
        items[key].extend(x["commit"] for x in nodes if x["commit"] and x["commit"]["committedDate"])


def paginate(owner, repo, number, items, connections):
    active = {name: block["pageInfo"] for name, block in connections.items()}
    while any(info["hasNextPage"] for info in active.values()):
        variables = {
            "owner": owner, "repo": repo, "number": number,
            "commentsCursor": active["comments"]["endCursor"],
            "reviewsCursor": active["reviews"]["endCursor"],
            "commitsCursor": active["commits"]["endCursor"],
            "needComments": active["comments"]["hasNextPage"],
            "needReviews": active["reviews"]["hasNextPage"],
            "needCommits": active["commits"]["hasNextPage"],
        }
        body = post(CONTINUE_QUERY, variables)
        if body.get("errors"):
            raise RuntimeError(body["errors"][0]["message"])
        pr = body["data"]["repository"]["pullRequest"]
        for name in active:
            if active[name]["hasNextPage"]:
                extend(items, name, pr[name]["nodes"])
                active[name] = pr[name]["pageInfo"]
        wait_for_rate(body["data"].get("rateLimit"))
        time.sleep(REQUEST_SLEEP)
    return items


def eligible_prs():
    con = sqlite3.connect(source_db())
    rows = con.execute("""
        SELECT r.owner, r.name, p.number, p.created_at, p.closed_at, p.merged_at,
               p.state, p.author_login, p.additions, p.deletions, p.changed_files
        FROM pull_requests p
        JOIN repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL
          AND p.exclude_reason IS NULL
          AND COALESCE(p.is_draft, 0) = 0
          AND p.created_at IS NOT NULL
        ORDER BY r.owner, r.name, p.number
    """).fetchall()
    con.close()
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row[0], row[1])].append({
            "number": row[2], "created_at": row[3], "closed_at": row[4], "merged_at": row[5],
            "state": row[6], "author_login": row[7], "final_additions": row[8],
            "final_deletions": row[9], "final_changed_files": row[10],
        })
    return grouped


def totals(comments, reviews, commits, created, end):
    comment_times = [parse_time(x) for x in comments]
    review_times = [parse_time(x) for x in reviews]
    commit_times = [(parse_time(x["committedDate"]), x) for x in commits]
    comment_count = sum(created <= x <= end for x in comment_times)
    review_count = sum(created <= x <= end for x in review_times)
    selected_commits = [x for t, x in commit_times if t <= end]
    activity = [x for x in comment_times + review_times if created <= x <= end]
    first_activity = min(activity).isoformat().replace("+00:00", "Z") if activity else None
    return {
        "comments": comment_count,
        "reviews": review_count,
        "commits": len(selected_commits),
        "commit_additions": sum(x["additions"] or 0 for x in selected_commits),
        "commit_deletions": sum(x["deletions"] or 0 for x in selected_commits),
        "commit_changed_files_sum": sum(x["changedFilesIfAvailable"] or 0 for x in selected_commits),
        "first_activity_at": first_activity,
        "first_activity_latency_days": round((min(activity) - created).total_seconds() / 86400, 6) if activity else None,
    }


def build_day_wise(pr, items, fetched_at):
    created = parse_time(pr["created_at"])
    terminal = parse_time(pr["merged_at"] or pr["closed_at"]) or fetched_at
    windows = {}
    previous = created
    for day in CHECKPOINTS:
        end = min(created + timedelta(days=day), terminal)
        cumulative = totals(items["comments"], items["reviews"], items["commits"], created, end)
        earlier = totals(items["comments"], items["reviews"], items["commits"], created, previous)
        new = {key: cumulative[key] - earlier[key] for key in (
            "comments", "reviews", "commits", "commit_additions", "commit_deletions", "commit_changed_files_sum"
        )}
        windows[f"day_{day}"] = {"cumulative": cumulative, "new_since_previous": new}
        previous = end
    after_30_start = created + timedelta(days=30)
    final_totals = totals(items["comments"], items["reviews"], items["commits"], created, terminal)
    at_30 = totals(items["comments"], items["reviews"], items["commits"], created, min(after_30_start, terminal))
    windows["day_30_plus"] = {
        "note": "Activity after day 30 through close/merge/data-fetch; do not use as a day-30 prediction feature.",
        "new_after_day_30": {key: final_totals[key] - at_30[key] for key in (
            "comments", "reviews", "commits", "commit_additions", "commit_deletions", "commit_changed_files_sum"
        )},
    }
    return windows


def load_partial(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)["pull_requests"]


def save_partial(path, owner, repo, results):
    with path.open("w", encoding="utf-8") as f:
        json.dump({"owner": owner, "repo": repo, "pull_requests": results}, f, ensure_ascii=False)


def fetch_repo(owner, repo, prs, partial):
    results = load_partial(partial)
    pending = [pr for pr in prs if str(pr["number"]) not in results]
    fetched_at = datetime.now(timezone.utc)
    for batch_index in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_index:batch_index + BATCH_SIZE]
        query, variables = event_query([(owner, repo, pr["number"]) for pr in batch])
        body = post(query, variables)
        data = body.get("data", {})
        if body.get("errors"):
            print(f"{owner}/{repo}: GraphQL warning: {body['errors'][0]['message']}")
        repository = data.get("repository") or {}
        for i, pr in enumerate(batch):
            node = repository.get(f"p{i}")
            if not node:
                results[str(pr["number"])] = {"metadata": pr, "fetch_status": "unavailable"}
                continue
            items = {"comments": [], "reviews": [], "commits": []}
            connections = node
            for name in items:
                extend(items, name, connections[name]["nodes"])
            try:
                items = paginate(owner, repo, pr["number"], items, connections)
                results[str(pr["number"])] = {
                    "metadata": pr,
                    "fetch_status": "complete",
                    "day_wise": build_day_wise(pr, items, fetched_at),
                }
            except RuntimeError as exc:
                results[str(pr["number"])] = {"metadata": pr, "fetch_status": f"partial: {exc}"}
        done = batch_index // BATCH_SIZE + 1
        total = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"{owner}/{repo}: {done}/{total}")
        wait_for_rate(data.get("rateLimit"))
        if done % CHECKPOINT_EVERY == 0:
            save_partial(partial, owner, repo, results)
        time.sleep(REQUEST_SLEEP)
    return results, fetched_at


def main():
    if not TOKEN:
        raise SystemExit("Missing GITHUB_TOKEN in .env")
    repos = eligible_prs()
    print(f"repos={len(repos)} prs={sum(map(len, repos.values()))}")
    for (owner, repo), prs in repos.items():
        folder = OUT_DIR / safe_name(owner)
        output = folder / f"{safe_name(repo)}_comment_day_wise.json"
        partial = folder / f"{safe_name(repo)}_comment_day_wise.partial.json"
        if output.exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        results, fetched_at = fetch_repo(owner, repo, prs, partial)
        with output.open("w", encoding="utf-8") as f:
            json.dump({
                "owner": owner, "repo": repo,
                "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
                "checkpoints": list(CHECKPOINTS),
                "pull_requests": results,
            }, f, ensure_ascii=False)
        if partial.exists():
            partial.unlink()
        print(f"saved {owner}/{repo}")


if __name__ == "__main__":
    main()
