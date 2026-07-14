import argparse
import os
import sqlite3
from pathlib import Path

PR_DB = Path(r"C:\Users\VEDANG BARMAN\Desktop\Git_Pr_prediction\data\raw\SQL FILES\pr_data.db")
TIMELINE_DB = Path(r"C:\Users\VEDANG BARMAN\Desktop\Git_Pr_prediction\data\raw\SQL FILES\pr_timelines.db")
OUTPUT_DB = Path(r"C:\Users\VEDANG BARMAN\Desktop\Git_Pr_prediction\data\processed\pr_snapshots.db")


def sql_list(value):
    values = sorted({int(x.strip()) for x in value.split(",") if x.strip()})
    if not values or values[0] < 0:
        raise argparse.ArgumentTypeError("checkpoints must be non-negative integers")
    return values


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoints", type=sql_list, default=[0, 1, 3, 7, 15, 30])
    p.add_argument("--last-window-days", type=int, default=30)
    args = p.parse_args()

    if args.last_window_days < 1:
        p.error("--last-window-days must be positive")
    for path in (PR_DB, TIMELINE_DB):
        if not Path(path).is_file():
            p.error(f"missing database: {path}")

    out = OUTPUT_DB
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    horizons = []
    for i, day in enumerate(args.checkpoints):
        horizons.append(args.checkpoints[i + 1] - day if i + 1 < len(args.checkpoints) else args.last_window_days)
    checkpoint_rows = ",".join(f"({day},{horizon})" for day, horizon in zip(args.checkpoints, horizons))

    con = sqlite3.connect(out)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA cache_size = -200000")
    con.execute("ATTACH DATABASE ? AS raw", (str(PR_DB.resolve()),))
    con.execute("ATTACH DATABASE ? AS timeline", (str(TIMELINE_DB.resolve()),))

    con.executescript("""
        CREATE TEMP TABLE checkpoints(day INTEGER PRIMARY KEY, horizon INTEGER NOT NULL);
        CREATE TEMP TABLE eligible_prs AS
        SELECT
            p.id AS pr_id, r.owner, r.name AS repo, p.number, p.state, p.created_at,
            p.merged_at, p.closed_at, r.fetched_at, p.additions, p.deletions,
            p.changed_files, length(COALESCE(p.title, '')) AS title_length,
            p.author_login
        FROM raw.pull_requests p
        JOIN raw.repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL
          AND p.exclude_reason IS NULL
          AND COALESCE(p.is_draft, 0) = 0
          AND p.created_at IS NOT NULL;

        CREATE INDEX temp.idx_eligible_pr ON eligible_prs(pr_id);
        CREATE INDEX temp.idx_eligible_dates ON eligible_prs(created_at, merged_at, closed_at);

        CREATE TEMP TABLE comment_events AS
        SELECT e.pr_id, e.created_at
        FROM timeline.comment_events e
        JOIN eligible_prs p ON p.pr_id = e.pr_id;
        CREATE TEMP TABLE review_events AS
        SELECT e.pr_id, e.submitted_at
        FROM timeline.review_events e
        JOIN eligible_prs p ON p.pr_id = e.pr_id;
        CREATE TEMP TABLE fetch_audit AS
        SELECT a.pr_id, a.status
        FROM timeline.fetch_audit a
        JOIN eligible_prs p ON p.pr_id = a.pr_id;
        CREATE INDEX temp.idx_comment_events_pr_time ON comment_events(pr_id, created_at);
        CREATE INDEX temp.idx_review_events_pr_time ON review_events(pr_id, submitted_at);
        CREATE INDEX temp.idx_fetch_audit_pr ON fetch_audit(pr_id);

        CREATE TABLE snapshots (
            pr_id INTEGER NOT NULL,
            owner TEXT NOT NULL,
            repo TEXT NOT NULL,
            number INTEGER NOT NULL,
            checkpoint_day INTEGER NOT NULL,
            days_elapsed INTEGER NOT NULL,
            additions INTEGER,
            deletions INTEGER,
            changed_files INTEGER,
            title_length INTEGER NOT NULL,
            author_login TEXT,
            created_dow INTEGER NOT NULL,
            created_hour INTEGER NOT NULL,
            comments_so_far INTEGER,
            reviews_so_far INTEGER,
            reviewer_assigned INTEGER,
            first_response_latency_days REAL,
            timeline_data_available INTEGER NOT NULL,
            merged_before_next INTEGER,
            censored INTEGER NOT NULL
        );
    """)
    con.executemany("INSERT INTO checkpoints(day, horizon) VALUES (?, ?)", zip(args.checkpoints, horizons))

    con.executescript("""
        INSERT INTO snapshots (
            pr_id, owner, repo, number, checkpoint_day, days_elapsed, additions,
            deletions, changed_files, title_length, author_login, created_dow,
            created_hour, comments_so_far, reviews_so_far, reviewer_assigned,
            first_response_latency_days, timeline_data_available,
            merged_before_next, censored
        )
        SELECT
            p.pr_id, p.owner, p.repo, p.number, c.day, c.day,
            p.additions, p.deletions, p.changed_files, p.title_length, p.author_login,
            CAST(strftime('%w', p.created_at) AS INTEGER),
            CAST(strftime('%H', p.created_at) AS INTEGER),
            NULL, NULL, NULL, NULL,
            CASE WHEN EXISTS (
                SELECT 1 FROM fetch_audit a
                WHERE a.pr_id = p.pr_id AND lower(a.status) IN ('complete', 'completed', 'success', 'ok')
            ) OR EXISTS (SELECT 1 FROM comment_events e WHERE e.pr_id = p.pr_id)
              OR EXISTS (SELECT 1 FROM review_events e WHERE e.pr_id = p.pr_id)
              THEN 1 ELSE 0 END,
            CASE
                WHEN upper(COALESCE(p.state, '')) = 'OPEN'
                 AND (p.fetched_at IS NULL OR julianday(p.created_at, '+' || (c.day + c.horizon) || ' days') > julianday(p.fetched_at))
                    THEN NULL
                WHEN p.merged_at IS NOT NULL
                 AND julianday(p.merged_at) <= julianday(p.created_at, '+' || (c.day + c.horizon) || ' days')
                    THEN 1
                ELSE 0
            END,
            CASE
                WHEN upper(COALESCE(p.state, '')) = 'OPEN'
                 AND (p.fetched_at IS NULL OR julianday(p.created_at, '+' || (c.day + c.horizon) || ' days') > julianday(p.fetched_at))
                    THEN 1
                ELSE 0
            END
        FROM eligible_prs p
        CROSS JOIN checkpoints c
        WHERE
            (p.merged_at IS NULL OR julianday(p.merged_at) > julianday(p.created_at, '+' || c.day || ' days'))
            AND (p.closed_at IS NULL OR julianday(p.closed_at) > julianday(p.created_at, '+' || c.day || ' days'))
            AND (p.fetched_at IS NULL OR julianday(p.created_at, '+' || c.day || ' days') <= julianday(p.fetched_at));

        CREATE INDEX idx_snapshots_pr_checkpoint ON snapshots(pr_id, checkpoint_day);
        CREATE INDEX idx_snapshots_repo_checkpoint ON snapshots(owner, repo, checkpoint_day);

        UPDATE snapshots
        SET comments_so_far = (
            SELECT COUNT(*) FROM comment_events e
            JOIN eligible_prs p ON p.pr_id = snapshots.pr_id
            WHERE e.pr_id = snapshots.pr_id
              AND julianday(e.created_at) >= julianday(p.created_at)
              AND julianday(e.created_at) <= julianday(p.created_at, '+' || snapshots.checkpoint_day || ' days')
        ),
        reviews_so_far = (
            SELECT COUNT(*) FROM review_events e
            JOIN eligible_prs p ON p.pr_id = snapshots.pr_id
            WHERE e.pr_id = snapshots.pr_id
              AND julianday(e.submitted_at) >= julianday(p.created_at)
              AND julianday(e.submitted_at) <= julianday(p.created_at, '+' || snapshots.checkpoint_day || ' days')
        );

        UPDATE snapshots
        SET reviewer_assigned = CASE WHEN reviews_so_far > 0 THEN 1 ELSE 0 END,
            first_response_latency_days = (
                SELECT MAX(0.0, julianday(MIN(event_at)) - julianday(p.created_at))
                FROM eligible_prs p
                JOIN (
                    SELECT created_at AS event_at FROM comment_events WHERE pr_id = snapshots.pr_id
                    UNION ALL
                    SELECT submitted_at FROM review_events WHERE pr_id = snapshots.pr_id
                ) e
                WHERE p.pr_id = snapshots.pr_id
                  AND julianday(e.event_at) >= julianday(p.created_at)
                  AND julianday(e.event_at) <= julianday(p.created_at, '+' || snapshots.checkpoint_day || ' days')
            );

        CREATE INDEX idx_snapshots_checkpoint ON snapshots(checkpoint_day);
        ANALYZE main;
    """)
    con.commit()
    rows = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    labelled = con.execute("SELECT COUNT(*) FROM snapshots WHERE merged_before_next IS NOT NULL").fetchone()[0]
    con.close()
    print(f"snapshots={rows} labelled={labelled} output={out}")


if __name__ == "__main__":
    main()
