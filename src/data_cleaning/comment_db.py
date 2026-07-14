import os
import json
import glob
import sqlite3

RAW_DIR = "data/raw"
PR_DB = "data/raw/pr_data.db"
OUT_DB = "data/raw/pr_timelines.db"


def load_pr_lookup(conn):
    rows = conn.execute("""
        SELECT r.owner, r.name, p.number, p.id, p.comments_count, p.reviews_count
        FROM pull_requests p JOIN repos r ON r.id = p.repo_id
    """).fetchall()
    lookup = {}
    for owner, name, number, pr_id, c_count, r_count in rows:
        lookup.setdefault((owner, name), {})[number] = (pr_id, c_count or 0, r_count or 0)
    return lookup


def find_timeline_files():
    found = []
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*", "*_comments.json"))):
        owner = os.path.basename(os.path.dirname(path))
        name = os.path.basename(path)[: -len("_comments.json")]
        found.append((owner, name, path))
    return found


def init_out_db(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE comment_events (pr_id INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE review_events (pr_id INTEGER NOT NULL, submitted_at TEXT NOT NULL);
        CREATE TABLE fetch_audit (
            pr_id INTEGER, owner TEXT NOT NULL, name TEXT NOT NULL, number INTEGER NOT NULL,
            meta_comments_count INTEGER, meta_reviews_count INTEGER,
            timeline_comments_count INTEGER, timeline_reviews_count INTEGER,
            status TEXT NOT NULL
        );
        CREATE INDEX idx_comment_events_pr ON comment_events(pr_id);
        CREATE INDEX idx_review_events_pr ON review_events(pr_id);
        CREATE INDEX idx_fetch_audit_pr ON fetch_audit(pr_id);
    """)
    return conn


def main():
    src_conn = sqlite3.connect(PR_DB)
    pr_lookup = load_pr_lookup(src_conn)
    src_conn.close()

    timeline_files = find_timeline_files()
    print(f"{len(timeline_files)} repos have a _comments.json")

    out_conn = init_out_db(OUT_DB)
    n_prs = n_comments = n_reviews = n_unresolved = n_suspect = n_no_match = 0

    for owner, name, path in timeline_files:
        repo_prs = pr_lookup.get((owner, name))
        if repo_prs is None:
            print(f"  [skip] {owner}/{name}: not in pr_data.db repos table")
            continue

        with open(path, encoding="utf-8") as f:
            payload = json.load(f)

        pr_timelines = payload.get("pr_timelines", {})
        unresolved = payload.get("unresolved_pr_numbers", [])

        for number_str, timeline in pr_timelines.items():
            number = int(number_str)
            match = repo_prs.get(number)
            if match is None:
                n_no_match += 1
                continue
            pr_id, meta_c, meta_r = match
            comments, reviews = timeline["comments"], timeline["reviews"]

            if (meta_c > 0 and len(comments) == 0) or (meta_r > 0 and len(reviews) == 0):
                status = "suspect_mismatch"
                n_suspect += 1
            else:
                status = "ok"

            out_conn.executemany("INSERT INTO comment_events (pr_id, created_at) VALUES (?, ?)",
                                  [(pr_id, ts) for ts in comments])
            out_conn.executemany("INSERT INTO review_events (pr_id, submitted_at) VALUES (?, ?)",
                                  [(pr_id, ts) for ts in reviews])
            out_conn.execute(
                """INSERT INTO fetch_audit (pr_id, owner, name, number, meta_comments_count,
                   meta_reviews_count, timeline_comments_count, timeline_reviews_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pr_id, owner, name, number, meta_c, meta_r, len(comments), len(reviews), status))
            n_prs += 1
            n_comments += len(comments)
            n_reviews += len(reviews)

        for number in unresolved:
            match = repo_prs.get(number)
            out_conn.execute(
                """INSERT INTO fetch_audit (pr_id, owner, name, number, meta_comments_count,
                   meta_reviews_count, timeline_comments_count, timeline_reviews_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (match[0] if match else None, owner, name, number,
                 match[1] if match else None, match[2] if match else None,
                 0, 0, "unresolved"))
            n_unresolved += 1

    out_conn.commit()
    out_conn.close()

    print(f"PRs with timelines:  {n_prs}")
    print(f"comment events:      {n_comments}")
    print(f"review events:       {n_reviews}")
    print(f"unresolved:          {n_unresolved}")
    print(f"suspect mismatches:  {n_suspect}")
    print(f"no repo/pr match:    {n_no_match}")
    print(f"-> {OUT_DB}")


if __name__ == "__main__":
    main()