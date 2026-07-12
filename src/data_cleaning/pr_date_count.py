import sqlite3
import csv

DB_PATH = "data/raw/pr_data.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # Using a CTE (WITH clause) to calculate the difference first, 
    # then grouping it by repo and bucketing the days.
    query = """
        WITH PR_Diffs AS (
            SELECT 
                r.owner,
                r.name AS repo_name,
                (julianday(p.closed_at) - julianday(p.created_at)) AS diff_days
            FROM repos r
            JOIN pull_requests p ON r.id = p.repo_id
            WHERE p.closed_at IS NOT NULL 
              AND p.created_at IS NOT NULL 
              AND p.exclude_reason IS NULL 
              AND r.exclude_reason IS NULL
              AND p.author_type != 'Bot'
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
    
    cursor = conn.execute(query)
    
    # Let's print a header row so the terminal output makes sense
    print(f"{'Repository':<25} | {'<=1d':<5} | {'<=3d':<5} | {'<=7d':<5} | {'<=15d':<5} | {'<=30d':<5} | {'>30d':<5} | {'Total'}")
    print("-" * 85)
    
    for row in cursor:
        repo_name = row[0]
        # Unpack the rest of the row (the counts)
        d1, d3, d7, d15, d30, over_30, total = row[1:] 
        
        # Format the output nicely
        print(f"{repo_name:<25} | {d1:<5} | {d3:<5} | {d7:<5} | {d15:<5} | {d30:<5} | {over_30:<5} | {total}")

    with open("data/raw/pr_time_distribution.csv", "w", newline="") as csvfile:
        csv_writer = csv.writer(csvfile)
        # Write the header
        csv_writer.writerow(["Repository", "<=1 day", "<=3 days", "<=7 days", "<=15 days", "<=30 days", ">30 days", "Total"])
        
        # Reset the cursor to fetch the data again for CSV writing
        cursor = conn.execute(query)
        
        for row in cursor:
            csv_writer.writerow(row)
    
    conn.close()

    
if __name__ == "__main__":
    main()