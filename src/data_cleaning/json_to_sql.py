import os
import json
import sqlite3

DATA_DIR = "data/raw/JSON FILES"
DB_PATH = "data/raw/SQL FILES/pr_data.db"

SCHEMA = """
DROP TABLE IF EXISTS pr_labels;
DROP TABLE IF EXISTS pull_requests;
DROP TABLE IF EXISTS repos;

CREATE TABLE repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    fetched_at TEXT,
    pr_count INTEGER,
    UNIQUE(owner, name)
);

CREATE TABLE pull_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repos(id),
    number INTEGER NOT NULL,
    title TEXT,
    state TEXT,
    is_draft INTEGER,
    created_at TEXT,
    merged_at TEXT,
    closed_at TEXT,
    additions INTEGER,
    deletions INTEGER,
    changed_files INTEGER,
    author_login TEXT,
    author_type TEXT,
    comments_count INTEGER,
    reviews_count INTEGER,
    UNIQUE(repo_id, number)
);

CREATE TABLE pr_labels (
    pr_id INTEGER NOT NULL REFERENCES pull_requests(id),
    label TEXT NOT NULL
);

CREATE INDEX idx_pr_repo ON pull_requests(repo_id);
CREATE INDEX idx_pr_state ON pull_requests(state);
CREATE INDEX idx_pr_author_type ON pull_requests(author_type);
"""


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    total_prs = 0
    for owner in sorted(os.listdir(DATA_DIR)):
        p = os.path.join(DATA_DIR, owner)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if not f.endswith(".json") or f.endswith(".partial.json"):
                continue
            d = json.load(open(os.path.join(p, f), encoding="utf-8"))
            repo_name = d.get("repo", f[:-5])
            prs = d.get("pull_requests", [])

            conn.execute(
                "INSERT INTO repos (owner, name, fetched_at, pr_count) VALUES (?,?,?,?)",
                (owner, repo_name, d.get("fetched_at"), len(prs)),
            )
            repo_id = conn.execute(
                "SELECT id FROM repos WHERE owner=? AND name=?", (owner, repo_name)
            ).fetchone()[0]

            for pr in prs:
                author = pr.get("author") or {}
                conn.execute(
                    """INSERT INTO pull_requests
                       (repo_id, number, title, state, is_draft, created_at, merged_at,
                        closed_at, additions, deletions, changed_files, author_login,
                        author_type, comments_count, reviews_count)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        repo_id, pr.get("number"), pr.get("title"), pr.get("state"),
                        int(bool(pr.get("isDraft"))), pr.get("createdAt"), pr.get("mergedAt"),
                        pr.get("closedAt"), pr.get("additions"), pr.get("deletions"),
                        pr.get("changedFiles"), author.get("login"), author.get("__typename"),
                        (pr.get("comments") or {}).get("totalCount"),
                        (pr.get("reviews") or {}).get("totalCount"),
                    ),
                )
                pr_id = conn.execute(
                    "SELECT id FROM pull_requests WHERE repo_id=? AND number=?",
                    (repo_id, pr.get("number")),
                ).fetchone()[0]
                for label in (pr.get("labels") or {}).get("nodes", []):
                    conn.execute("INSERT INTO pr_labels (pr_id, label) VALUES (?,?)", (pr_id, label["name"]))

            total_prs += len(prs)
            print(f"loaded {owner}/{repo_name}: {len(prs)} PRs")

    conn.commit()
    conn.close()
    print(f"\ndone: {total_prs} PRs -> {DB_PATH}")


if __name__ == "__main__":
    main()