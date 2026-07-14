
import os
import csv
import sqlite3
from datetime import datetime, timedelta

CHECKPOINTS = [0, 1, 3, 7, 15, 30]

PR_DB = "data/raw/SQL FILES/pr_data.db"
TIMELINE_DB = "data/raw/SQL FILES/pr_timelines.db"
OUT_DB = "data/processed/pr_snapshots.db"
OUT_CSV = "data/processed/pr_snapshots.csv"

COLUMNS = [
    "pr_id", "owner", "name", "number", "checkpoint_day", "days_elapsed",
    "additions", "deletions", "changed_files", "title_length",
    "author_login", "author_type", "num_labels", "created_dow", "created_hour",
    "comments_so_far", "reviews_so_far", "reviewer_assigned",
    "first_response_hours", "timeline_data_available", "merged_before_next",
]


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def load_eligible_prs(conn):
    return conn.execute("""
        SELECT p.id, r.owner, r.name, r.fetched_at, p.number, p.title,
               p.created_at, p.merged_at, p.closed_at,
               p.additions, p.deletions, p.changed_files,
               p.author_login, p.author_type
        FROM pull_requests p JOIN repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL AND p.exclude_reason IS NULL
    """).fetchall()


def load_label_counts(conn):
    return dict(conn.execute("SELECT pr_id, COUNT(*) FROM pr_labels GROUP BY pr_id"))


def load_events(conn, table, ts_col):
    events = {}
    for pr_id, ts in conn.execute(f"SELECT pr_id, {ts_col} FROM {table}"):
        events.setdefault(pr_id, []).append(parse_ts(ts))
    for pr_id in events:
        events[pr_id].sort()
    return events


def load_fetched_repos(conn):
    """(owner, name) pairs that actually went through the timeline fetch."""
    return {(o, n) for o, n in conn.execute("SELECT DISTINCT owner, name FROM fetch_audit")}


def init_out_db(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    cols_sql = ",\n".join(f"{c} " + ("TEXT" if c in ("owner", "name", "author_login", "author_type") else
                                      "REAL" if c == "first_response_hours" else "INTEGER")
                           for c in COLUMNS)
    conn.execute(f"CREATE TABLE snapshots (\n{cols_sql}\n)")
    return conn


def build_rows(pr, label_counts, comment_events, review_events, timeline_available):
    (pr_id, owner, name, fetched_at, number, title,
     created_at, merged_at, closed_at,
     additions, deletions, changed_files, author_login, author_type) = pr

    created = parse_ts(created_at)
    cutoff = parse_ts(fetched_at)
    if created is None or cutoff is None:
        return []

    merged = parse_ts(merged_at)
    closed = parse_ts(closed_at)
    resolution = merged or closed
    resolved_as_merge = merged is not None

    comments = comment_events.get(pr_id, [])
    reviews = review_events.get(pr_id, [])
    n_labels = label_counts.get(pr_id, 0)
    title_length = len(title) if title else 0
    dow = int(created.strftime("%w"))
    hour = created.hour

    rows = []
    for i, day in enumerate(CHECKPOINTS):
        cp_date = created + timedelta(days=day)

        if resolution is not None and resolution <= cp_date:
            break
        if cp_date > cutoff:
            break

        if timeline_available:
            comments_so_far = sum(1 for t in comments if t <= cp_date)
            reviews_so_far = sum(1 for t in reviews if t <= cp_date)
            first_events = [t for t in (comments + reviews) if t <= cp_date]
            first_response_hours = ((min(first_events) - created).total_seconds() / 3600
                                     if first_events else None)
        else:
            comments_so_far = reviews_so_far = first_response_hours = None

        if i + 1 < len(CHECKPOINTS):
            next_date = created + timedelta(days=CHECKPOINTS[i + 1])
            if resolution is not None and resolution <= next_date:
                label, stop = (1 if resolved_as_merge else 0), True
            elif next_date > cutoff:
                label, stop = None, True
            else:
                label, stop = 0, False
        else:
            label = (1 if resolved_as_merge else 0) if resolution is not None else None
            stop = True

        rows.append((
            pr_id, owner, name, number, day, day,
            additions, deletions, changed_files, title_length,
            author_login, author_type, n_labels, dow, hour,
            comments_so_far, reviews_so_far,
            (int(reviews_so_far > 0) if reviews_so_far is not None else None),
            first_response_hours, int(timeline_available), label,
        ))

        if stop:
            break

    return rows


def export_csv(db_path, csv_path):
    conn = sqlite3.connect(db_path)
    cur = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM snapshots ORDER BY pr_id, checkpoint_day")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(cur)
    conn.close()


def main():
    pr_conn = sqlite3.connect(PR_DB)
    tl_conn = sqlite3.connect(TIMELINE_DB)

    prs = load_eligible_prs(pr_conn)
    label_counts = load_label_counts(pr_conn)
    comment_events = load_events(tl_conn, "comment_events", "created_at")
    review_events = load_events(tl_conn, "review_events", "submitted_at")
    fetched_repos = load_fetched_repos(tl_conn)
    pr_conn.close()
    tl_conn.close()

    print(f"{len(prs)} eligible PRs, {len(fetched_repos)} repos w/ timeline data")

    out_conn = init_out_db(OUT_DB)
    placeholders = ",".join("?" * len(COLUMNS))
    total_rows = n_skipped = n_no_timeline = 0

    for pr in prs:
        timeline_available = (pr[1], pr[2]) in fetched_repos
        if not timeline_available:
            n_no_timeline += 1
        rows = build_rows(pr, label_counts, comment_events, review_events, timeline_available)
        if not rows:
            n_skipped += 1
            continue
        out_conn.executemany(f"INSERT INTO snapshots VALUES ({placeholders})", rows)
        total_rows += len(rows)

    out_conn.commit()
    out_conn.close()

    export_csv(OUT_DB, OUT_CSV)

    print(f"snapshot rows: {total_rows}")
    print(f"PRs w/ 0 rows: {n_skipped}")
    print(f"PRs missing timeline data (repo not yet fetched): {n_no_timeline}")
    print(f"-> {OUT_DB}")
    print(f"-> {OUT_CSV}")


if __name__ == "__main__":
    main()