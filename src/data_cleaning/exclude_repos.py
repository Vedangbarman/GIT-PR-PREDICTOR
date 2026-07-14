import sqlite3

DB_PATH = "data/raw/SQL FILES/pr_data.db"

# confirmed exclusions so far
EXCLUSIONS = {
    ("openclaw", "openclaw"): "bot_dominated_merge_speed",
    ("tensorflow", "tensorflow"): "copybara_bot_96pct",
    ("NousResearch", "hermes-agent"): "implausible_merge_rate",
    ("freeCodeCamp", "freeCodeCamp"): "not_a_software_library",
    ("EbookFoundation", "free-programming-books"): "not_a_software_library",
    ("golang", "go"): "gerrit_not_github_merges",
    ("curl", "curl"): "mailing_list_not_github_prs",
    ("public-apis", "public-apis"): "not_a_software_library",
    ("vinta", "awesome-python"): "not_a_software_library",
    ("nilbuild", "developer-roadmap"): "not_a_software_library",
    ("affaan-m", "ECC"): "not_a_software_library",
    ("enzymejs", "enzyme"): "legacy_inactive",
    ("ReactiveCocoa", "ReactiveCocoa"): "legacy_inactive",
    ("pytorch","pytorch"): "pytorchbot_label_based_merge"
}


def ensure_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(repos)")]
    if "exclude_reason" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN exclude_reason TEXT")


def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_column(conn)
    conn.execute("UPDATE repos SET exclude_reason = NULL")  # reset for a clean rerun

    for (owner, name), reason in EXCLUSIONS.items():
        conn.execute(
            "UPDATE repos SET exclude_reason = ? WHERE owner = ? AND name = ?",
            (reason, owner, name),
        )
    conn.commit()

    print("repo-level exclusions:")
    for owner, name, reason, pr_count in conn.execute(
        "SELECT owner, name, exclude_reason, pr_count FROM repos "
        "WHERE exclude_reason IS NOT NULL ORDER BY owner"
    ):
        print(f"  {owner}/{name:30s} {reason:28s} ({pr_count} PRs)")

    total_repos = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    excluded_repos = conn.execute(
        "SELECT COUNT(*) FROM repos WHERE exclude_reason IS NOT NULL").fetchone()[0]
    total_prs = conn.execute("SELECT COUNT(*) FROM pull_requests").fetchone()[0]
    excluded_prs = conn.execute(
        "SELECT COUNT(*) FROM pull_requests p JOIN repos r ON r.id = p.repo_id "
        "WHERE r.exclude_reason IS NOT NULL"
    ).fetchone()[0]

    print(f"\n{excluded_repos}/{total_repos} repos excluded")
    print(f"{excluded_prs}/{total_prs} PRs excluded as a result ({excluded_prs / max(total_prs, 1) * 100:.1f}%)")

    missing = [k for k in EXCLUSIONS if not conn.execute(
        "SELECT 1 FROM repos WHERE owner=? AND name=?", k).fetchone()]
    if missing:
        print(f"\nnote: not found in DB (never fetched, or already gone from data/raw): {missing}")

    conn.close()


if __name__ == "__main__":
    main()