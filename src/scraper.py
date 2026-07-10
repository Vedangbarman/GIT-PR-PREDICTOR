import os
import requests
from dotenv import load_dotenv

load_dotenv()  # reads .env in cwd

API_URL = "https://api.github.com/graphql"
TOKEN = os.environ.get("GITHUB_TOKEN")  # .env: GITHUB_TOKEN=ghp_xxx

GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        state
        createdAt
        mergedAt
        additions
        deletions
        changedFiles
        author { login }
        comments { totalCount }
        reviews { totalCount }
      }
    }
  }
  rateLimit { limit remaining resetAt }
}
"""


def fetch_pull_requests(owner, name, max_pages=None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    cursor = None
    all_prs = []
    page = 0

    while True:
        variables = {"owner": owner, "name": name, "cursor": cursor}
        resp = requests.post(
            API_URL,
            json={"query": GRAPHQL_QUERY, "variables": variables},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            raise RuntimeError(data["errors"])

        pr_block = data["data"]["repository"]["pullRequests"]
        all_prs.extend(pr_block["nodes"])

        rate = data["data"]["rateLimit"]
        page += 1
        print(f"page {page}: +{len(pr_block['nodes'])} PRs "
              f"(rate left {rate['remaining']}/{rate['limit']})")

        if not pr_block["pageInfo"]["hasNextPage"]:
            break
        if max_pages and page >= max_pages:
            break
        cursor = pr_block["pageInfo"]["endCursor"]

    return all_prs


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing GITHUB_TOKEN")

    prs = fetch_pull_requests("octocat", "Hello-World")
    print(f"total PRs fetched: {len(prs)}")