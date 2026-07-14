import os
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PR_DB = ROOT / "data" / "raw" / "pr_data.db"
TIMELINE_DB = ROOT / "data" / "raw" / "pr_timelines.db"
OUTPUT_DB = ROOT / "data" / "raw" / "pr_comments_timeline.db"


def main():
    for path in (PR_DB, TIMELINE_DB):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT_DB.exists():
        os.remove(OUTPUT_DB)

    con = sqlite3.connect(OUTPUT_DB)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("ATTACH DATABASE ? AS raw", (str(PR_DB),))
    con.execute("ATTACH DATABASE ? AS timeline", (str(TIMELINE_DB),))
    con.executescript("""
        CREATE TEMP TABLE selected_pr_ids AS
        SELECT pr_id FROM timeline.fetch_audit
        UNION
        SELECT pr_id FROM timeline.comment_events
        UNION
        SELECT pr_id FROM timeline.review_events;
        CREATE UNIQUE INDEX temp.idx_selected_pr_ids ON selected_pr_ids(pr_id);

        CREATE TABLE repos AS
        SELECT r.*
        FROM raw.repos r
        WHERE EXISTS (
            SELECT 1
            FROM raw.pull_requests p
            JOIN selected_pr_ids s ON s.pr_id = p.id
            WHERE p.repo_id = r.id
        );

        CREATE TABLE pull_requests AS
        SELECT p.*
        FROM raw.pull_requests p
        JOIN selected_pr_ids s ON s.pr_id = p.id;

        CREATE TABLE comment_events AS
        SELECT e.*
        FROM timeline.comment_events e
        JOIN selected_pr_ids s ON s.pr_id = e.pr_id;

        CREATE TABLE review_events AS
        SELECT e.*
        FROM timeline.review_events e
        JOIN selected_pr_ids s ON s.pr_id = e.pr_id;

        CREATE TABLE fetch_audit AS
        SELECT a.*
        FROM timeline.fetch_audit a
        JOIN selected_pr_ids s ON s.pr_id = a.pr_id;

        CREATE INDEX idx_pr_repo ON pull_requests(repo_id);
        CREATE INDEX idx_comments_pr_time ON comment_events(pr_id, created_at);
        CREATE INDEX idx_reviews_pr_time ON review_events(pr_id, submitted_at);
        CREATE INDEX idx_audit_pr ON fetch_audit(pr_id);
        ANALYZE main;
    """)
    con.commit()
    prs = con.execute("SELECT COUNT(*) FROM pull_requests").fetchone()[0]
    comments = con.execute("SELECT COUNT(*) FROM comment_events").fetchone()[0]
    reviews = con.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
    con.close()
    print(f"prs={prs} comments={comments} reviews={reviews} output={OUTPUT_DB}")


if __name__ == "__main__":
    main()
