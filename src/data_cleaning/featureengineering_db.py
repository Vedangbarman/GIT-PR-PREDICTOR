import sqlite3
import numpy as np
import pandas as pd

PR_DB = "data/raw/SQL FILES/pr_data.db"
OUT_DB = "data/processed/pr_features.db"


def load_eligible(conn):
    df = pd.read_sql("""
        SELECT p.id AS pr_id, r.owner, r.name, p.author_login,
               p.created_at, p.merged_at, p.closed_at
        FROM pull_requests p JOIN repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL AND p.exclude_reason IS NULL
    """, conn)
    for c in ("created_at", "merged_at", "closed_at"):
        df[c] = pd.to_datetime(df[c])
    df["resolved_at"] = df["merged_at"].fillna(df["closed_at"])
    df["is_merge"] = df["merged_at"].notna()
    return df


def prior_stats(df, group_cols, prefix):
    df = df.sort_values("created_at").reset_index(drop=True)
    pr_count = np.zeros(len(df), dtype=int)
    resolved_count = np.zeros(len(df), dtype=int)
    merged_count = np.zeros(len(df), dtype=int)

    for _, idx in df.groupby(group_cols).groups.items():
        idx = sorted(idx, key=lambda i: df.at[i, "created_at"])
        created = df.loc[idx, "created_at"].values
        resolved = df.loc[idx, "resolved_at"].values
        is_merge = df.loc[idx, "is_merge"].values
        for pos, i in enumerate(idx):
            cutoff = created[pos]
            prior_resolved = resolved[:pos]
            mask = pd.notna(prior_resolved) & (prior_resolved < cutoff)
            pr_count[i] = pos
            resolved_count[i] = mask.sum()
            merged_count[i] = (mask & is_merge[:pos]).sum()

    rate = np.full(len(df), np.nan)
    nonzero = resolved_count > 0
    rate[nonzero] = merged_count[nonzero] / resolved_count[nonzero]

    df[f"{prefix}_pr_count"] = pr_count
    df[f"{prefix}_merge_rate"] = rate
    return df


def main():
    conn = sqlite3.connect(PR_DB)
    df = load_eligible(conn)
    conn.close()
    print(f"{len(df)} eligible PRs")

    df = prior_stats(df, ["owner", "name", "author_login"], "author_prior")
    df["is_first_time_contributor"] = (df["author_prior_pr_count"] == 0).astype(int)
    df = prior_stats(df, ["owner", "name"], "repo_prior")

    df["created_at_day"] = df["created_at"].dt.day
    df["created_at_month"] = df["created_at"].dt.month

    out = df[[
        "pr_id", "author_prior_pr_count", "author_prior_merge_rate", "is_first_time_contributor",
        "repo_prior_pr_count", "repo_prior_merge_rate", "created_at_day", "created_at_month",
    ]]

    out_conn = sqlite3.connect(OUT_DB)
    out.to_sql("pr_features", out_conn, if_exists="replace", index=False)
    out_conn.execute("CREATE INDEX idx_pr_features_pr_id ON pr_features(pr_id)")
    out_conn.commit()
    out_conn.close()

    print(f"-> {OUT_DB} (table: pr_features, {len(out)} rows)")


if __name__ == "__main__":
    main()