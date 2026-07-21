import os
import math
from datetime import datetime, timezone

import requests
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GRAPHQL_URL = "https://api.github.com/graphql"
CHECKPOINTS = [0, 1, 3, 7, 15, 30]


def gh_post(query, variables=None):
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if "errors" in body:
        raise RuntimeError(body["errors"][0]["message"])
    return body["data"]


def parse_repo_url(text):
    text = text.strip().rstrip("/")
    if text.startswith("http"):
        parts = text.split("/")
        return parts[-2], parts[-1]
    owner, name = text.split("/")
    return owner, name


def fetch_repo_prior_stats(owner, name):
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        merged: pullRequests(states: MERGED) { totalCount }
        closedNoMerge: pullRequests(states: CLOSED) { totalCount }
      }
    }
    """
    data = gh_post(query, {"owner": owner, "name": name})
    merged = data["repository"]["merged"]["totalCount"]
    closed = data["repository"]["closedNoMerge"]["totalCount"]
    resolved = merged + closed
    return merged + closed, (merged / resolved if resolved > 0 else None)


def fetch_recent_closed_sizes(owner, name, sample_size=75):
    query = """
    query($owner: String!, $name: String!, $n: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequests(states: [MERGED, CLOSED], first: $n, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes { additions deletions changedFiles }
        }
      }
    }
    """
    data = gh_post(query, {"owner": owner, "name": name, "n": sample_size})
    nodes = data["repository"]["pullRequests"]["nodes"]
    df = pd.DataFrame(nodes)
    if df.empty:
        return {"additions": 1, "deletions": 1, "changed_files": 1}
    return {
        "additions": max(df["additions"].median(), 1),
        "deletions": max(df["deletions"].median(), 1),
        "changed_files": max(df["changedFiles"].median(), 1),
    }


def fetch_author_prior_stats(owner, name, author_login):
    query = """
    query($q_all: String!, $q_merged: String!, $q_closed: String!) {
      all: search(query: $q_all, type: ISSUE, first: 1) { issueCount }
      merged: search(query: $q_merged, type: ISSUE, first: 1) { issueCount }
      closed: search(query: $q_closed, type: ISSUE, first: 1) { issueCount }
    }
    """
    base = f"repo:{owner}/{name} author:{author_login} is:pr"
    data = gh_post(query, {
        "q_all": base,
        "q_merged": f"{base} is:merged",
        "q_closed": f"{base} is:unmerged is:closed",
    })
    prior_count = data["all"]["issueCount"]
    merged = data["merged"]["issueCount"]
    closed = data["closed"]["issueCount"]
    resolved = merged + closed
    return prior_count, (merged / resolved if resolved > 0 else None)


def fetch_open_prs(owner, name, limit):
    query = """
    query($owner: String!, $name: String!, $n: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequests(states: OPEN, first: $n, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            number title createdAt additions deletions changedFiles
            author { login __typename }
            labels { totalCount }
            comments(first: 1) { totalCount nodes { createdAt } }
            reviews(first: 1) { totalCount nodes { submittedAt } }
          }
        }
      }
    }
    """
    data = gh_post(query, {"owner": owner, "name": name, "n": limit})
    return data["repository"]["pullRequests"]["nodes"]


def nearest_checkpoint(age_days):
    passed = [c for c in CHECKPOINTS if c <= age_days]
    return passed[-1] if passed else 0


def build_feature_row(pr, owner, name, size_medians, repo_prior_count, repo_prior_rate,
                       author_prior_count, author_prior_rate):
    created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age_days = (now - created).total_seconds() / 86400
    checkpoint_day = nearest_checkpoint(math.floor(age_days))

    comments_first = pr["comments"]["nodes"]
    reviews_first = pr["reviews"]["nodes"]
    response_times = []
    if comments_first:
        response_times.append(datetime.fromisoformat(comments_first[0]["createdAt"].replace("Z", "+00:00")))
    if reviews_first:
        response_times.append(datetime.fromisoformat(reviews_first[0]["submittedAt"].replace("Z", "+00:00")))
    first_response_hours = (min(response_times) - created).total_seconds() / 3600 if response_times else None

    author = pr["author"] or {}
    author_login = author.get("login", "unknown")
    author_type = "Bot" if author.get("__typename") == "Bot" else "User"

    return {
        "owner": owner, "name": name, "checkpoint_day": checkpoint_day, "days_elapsed": checkpoint_day,
        "additions": pr["additions"], "deletions": pr["deletions"], "changed_files": pr["changedFiles"],
        "title_length": len(pr["title"] or ""), "author_login": author_login, "author_type": author_type,
        "num_labels": pr["labels"]["totalCount"], "created_dow": created.weekday(), "created_hour": created.hour,
        "comments_so_far": pr["comments"]["totalCount"], "reviews_so_far": pr["reviews"]["totalCount"],
        "reviewer_assigned": int(pr["reviews"]["totalCount"] > 0),
        "first_response_hours": first_response_hours,
        "additions_norm": pr["additions"] / size_medians["additions"],
        "deletions_norm": pr["deletions"] / size_medians["deletions"],
        "changed_files_norm": pr["changedFiles"] / size_medians["changed_files"],
        "has_response_yet": int(first_response_hours is not None),
        "repo_key": f"{owner}/{name}",
        "author_prior_pr_count": author_prior_count, "author_prior_merge_rate": author_prior_rate,
        "is_first_time_contributor": int(author_prior_count == 0),
        "repo_prior_pr_count": repo_prior_count, "repo_prior_merge_rate": repo_prior_rate,
        "created_at_day": created.day, "created_at_month": created.month,
        "_pr_number": pr["number"], "_pr_title": pr["title"], "_age_days": round(age_days, 1),
    }


st.title("PR Bottleneck Risk")

repo_input = st.text_input("GitHub repo (owner/name or URL)", "")
limit = st.slider("Number of open PRs to check", 5, 15, 10)

if st.button("Scrape & predict") and repo_input:
    if not GITHUB_TOKEN:
        st.error("GITHUB_TOKEN environment variable is not set on the server.")
        st.stop()

    try:
        owner, name = parse_repo_url(repo_input)
        with st.spinner("Fetching repo history..."):
            repo_prior_count, repo_prior_rate = fetch_repo_prior_stats(owner, name)
            size_medians = fetch_recent_closed_sizes(owner, name)

        with st.spinner("Fetching open PRs..."):
            open_prs = fetch_open_prs(owner, name, limit)

        if not open_prs:
            st.warning("No open PRs found.")
            st.stop()

        author_cache = {}
        rows = []
        with st.spinner("Fetching contributor history..."):
            for pr in open_prs:
                author_login = (pr["author"] or {}).get("login", "unknown")
                if author_login not in author_cache:
                    author_cache[author_login] = fetch_author_prior_stats(owner, name, author_login)
                author_prior_count, author_prior_rate = author_cache[author_login]
                rows.append(build_feature_row(
                    pr, owner, name, size_medians, repo_prior_count, repo_prior_rate,
                    author_prior_count, author_prior_rate,
                ))

        api_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        with st.spinner("Predicting..."):
            resp = requests.post(f"{API_URL}/predict", json=api_rows, timeout=30)
            resp.raise_for_status()
            predictions = resp.json()

        chart_df = pd.DataFrame({
            "PR": [f"#{r['_pr_number']}" for r in rows],
            "Merge probability": [p["merge_probability"] for p in predictions],
        }).set_index("PR")
        st.bar_chart(chart_df)

        table_df = pd.DataFrame([
            {
                "PR": f"#{r['_pr_number']}", "Title": r["_pr_title"][:60], "Age (days)": r["_age_days"],
                "Checkpoint used": r["checkpoint_day"], "Merge probability": round(p["merge_probability"], 3),
            }
            for r, p in zip(rows, predictions)
        ])
        st.dataframe(table_df, use_container_width=True)

    except Exception as exc:
        st.error(f"Failed: {exc}")