import sqlite3

DB_PATH = "data/raw/SQL FILES/pr_data.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    total_repos, total_prs = conn.execute(
        "SELECT (SELECT COUNT(*) FROM repos), (SELECT COUNT(*) FROM pull_requests)"
    ).fetchone()

    excluded_repos = conn.execute(
        "SELECT COUNT(*) FROM repos WHERE exclude_reason IS NOT NULL"
    ).fetchone()[0]

    print(f"{excluded_repos}/{total_repos} repos fully excluded\n")

    print("PR breakdown across ALL repos (repo-level + PR-level combined):")
    for reason, count in conn.execute("""
        SELECT
            CASE
                WHEN r.exclude_reason IS NOT NULL THEN 'repo_excluded: ' || r.exclude_reason
                WHEN p.exclude_reason IS NOT NULL THEN 'pr_excluded: ' || p.exclude_reason
                ELSE 'eligible'
            END AS status,
            COUNT(*)
        FROM pull_requests p JOIN repos r ON r.id = p.repo_id
        GROUP BY 1 ORDER BY 2 DESC
    """):
        print(f"  {reason:35s} {count:7d}  ({count / total_prs * 100:.1f}%)")

    eligible_total = conn.execute("""
        SELECT COUNT(*) FROM pull_requests p JOIN repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL AND p.exclude_reason IS NULL
    """).fetchone()[0]

    print(f"\nFINAL training-eligible PRs: {eligible_total} / {total_prs} "
          f"({eligible_total / total_prs * 100:.1f}%)")

    print("\nper-repo eligible counts (excluded repos omitted):")
    for repo, eligible, total_r in conn.execute("""
        SELECT r.owner || '/' || r.name,
               SUM(CASE WHEN p.exclude_reason IS NULL THEN 1 ELSE 0 END),
               COUNT(*)
        FROM pull_requests p JOIN repos r ON r.id = p.repo_id
        WHERE r.exclude_reason IS NULL
        GROUP BY r.id ORDER BY 2 DESC
    """):
        print(f"  {repo:35s} {eligible:6d} / {total_r:6d}")

    conn.close()


if __name__ == "__main__":
    main()