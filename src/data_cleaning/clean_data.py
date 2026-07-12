import sqlite3

DB_PATH = "data/raw/pr_data.db"
WIP_KEYWORDS = ["wip", "work in progress", "work-in-progress", "do not merge", "do-not-merge"]


def ensure_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(pull_requests)")]
    if "exclude_reason" not in cols:
        conn.execute("ALTER TABLE pull_requests ADD COLUMN exclude_reason TEXT")


def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_column(conn)

    conn.execute("UPDATE pull_requests SET exclude_reason = NULL")  # reset for a clean rerun
    conn.execute("UPDATE pull_requests SET exclude_reason = 'bot_author' WHERE author_type = 'Bot'")
    conn.execute("UPDATE pull_requests SET exclude_reason = 'draft' "
                  "WHERE is_draft = 1 AND exclude_reason IS NULL")

    placeholders = " OR ".join(["LOWER(label) LIKE ?"] * len(WIP_KEYWORDS))
    wip_ids = [row[0] for row in conn.execute(
        f"SELECT DISTINCT pr_id FROM pr_labels WHERE {placeholders}",
        [f"%{k}%" for k in WIP_KEYWORDS],
    )]
    conn.executemany(
        "UPDATE pull_requests SET exclude_reason = 'wip_label' "
        "WHERE id = ? AND exclude_reason IS NULL",
        [(i,) for i in wip_ids],
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM pull_requests").fetchone()[0]
    print(f"{total} total PRs\n")
    for reason, count in conn.execute(
        "SELECT COALESCE(exclude_reason, 'eligible'), COUNT(*) "
        "FROM pull_requests GROUP BY 1 ORDER BY 2 DESC"
    ):
        print(f"  {reason:12s} {count:7d}  ({count / total * 100:.1f}%)")

    print("\nper-repo eligible-PR counts:")
    for repo, eligible, total_r in conn.execute(
        "SELECT r.owner || '/' || r.name, "
        "SUM(CASE WHEN exclude_reason IS NULL THEN 1 ELSE 0 END), COUNT(*) "
        "FROM pull_requests p JOIN repos r ON r.id = p.repo_id "
        "GROUP BY r.id ORDER BY 2 DESC"
    ):
        print(f"  {repo:35s} {eligible:6d} / {total_r:6d}")

    conn.close()


if __name__ == "__main__":
    main()