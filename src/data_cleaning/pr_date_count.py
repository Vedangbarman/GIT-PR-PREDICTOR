import sqlite3
import csv

DB_PATH = "data/raw/SQL FILES/pr_data.db"

QUERY = """
    WITH PR_Diffs AS (
        SELECT
            r.owner || '/' || r.name AS repo_name,
            (julianday(p.merged_at) - julianday(p.created_at)) AS diff_days
        FROM repos r
        JOIN pull_requests p ON r.id = p.repo_id
        WHERE p.merged_at IS NOT NULL
          AND p.created_at IS NOT NULL
          AND p.exclude_reason IS NULL
          AND r.exclude_reason IS NULL
          AND p.author_type IS NOT 'Bot'
    )
    SELECT
        repo_name,
        SUM(CASE WHEN diff_days <= 1 THEN 1 ELSE 0 END) AS within_1_day,
        SUM(CASE WHEN diff_days > 1 AND diff_days <= 3 THEN 1 ELSE 0 END) AS within_3_days,
        SUM(CASE WHEN diff_days > 3 AND diff_days <= 7 THEN 1 ELSE 0 END) AS within_7_days,
        SUM(CASE WHEN diff_days > 7 AND diff_days <= 15 THEN 1 ELSE 0 END) AS within_15_days,
        SUM(CASE WHEN diff_days > 15 AND diff_days <= 30 THEN 1 ELSE 0 END) AS within_30_days,
        SUM(CASE WHEN diff_days > 30 THEN 1 ELSE 0 END) AS over_30_days,
        COUNT(*) AS total_valid_prs
    FROM PR_Diffs
    GROUP BY repo_name
    ORDER BY repo_name;
"""


def main():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(QUERY).fetchall()  # fetch once, reuse for both print and CSV
    conn.close()

    print(f"{'Repository':<35} | {'<=1d':<5} | {'<=3d':<5} | {'<=7d':<5} | {'<=15d':<5} | {'<=30d':<5} | {'>30d':<5} | {'Total'}")
    print("-" * 100)
    for repo_name, d1, d3, d7, d15, d30, over_30, total in rows:
        print(f"{repo_name:<35} | {d1:<5} | {d3:<5} | {d7:<5} | {d15:<5} | {d30:<5} | {over_30:<5} | {total}")

    with open("data/raw/pr_time_distribution.csv", "w", newline="") as csvfile:
        w = csv.writer(csvfile)
        w.writerow(["Repository", "<=1 day", "<=3 days", "<=7 days", "<=15 days", "<=30 days", ">30 days", "Total"])
        w.writerows(rows)

    print(f"\nsaved data/raw/pr_time_distribution.csv ({len(rows)} repos)")


if __name__ == "__main__":
    main()