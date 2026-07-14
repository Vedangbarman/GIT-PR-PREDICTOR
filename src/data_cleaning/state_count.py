import sqlite3
import csv 

DB_PATH = "data/raw/SQL FILES/pr_data.db"

QUERY = """
SELECT
    r.owner || '/' || r.name AS repo_name,
    SUM(CASE WHEN p.state = 'MERGED' THEN 1 ELSE 0 END) AS merged_count,
    SUM(CASE WHEN p.state = 'CLOSED' THEN 1 ELSE 0 END) AS closed_without_merge,
    SUM(CASE WHEN p.state = 'OPEN' THEN 1 ELSE 0 END) AS still_open,
    COUNT(*) AS total
FROM repos r
JOIN pull_requests p ON r.id = p.repo_id
WHERE p.exclude_reason IS NULL
  AND r.exclude_reason IS NULL
  AND p.author_type IS NOT 'Bot'
GROUP BY repo_name
ORDER BY repo_name;
"""


def main():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(QUERY).fetchall()
       
    for repo_name, merged_count, closed_without_merge, still_open, total in rows:
        print(repo_name,":", merged_count,":", closed_without_merge,":", still_open,":", total)
          
    with open("data/raw/state.csv","w",newline="") as file:
        w = csv.writer(file)
        w.writerow(["Repositery","Merged Count", "Closed Without Merged","Still Open","Total"])
        w.writerows(rows)
    print(f"\nsaved data/raw/state.csv ({len(rows)} repos)")   

if __name__ == "__main__":
    main()
    