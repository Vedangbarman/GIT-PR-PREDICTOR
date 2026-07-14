import sqlite3

DB_PATH = "data/raw/pr_timelines.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    query = "SELECT name FROM sqlite_master WHERE type='table'"
    table_name = conn.execute(query).fetchall()
    for rows in table_name:
        print(rows)
       
           
    schema_comment_events = conn.execute("pragma table_info(comment_events);").fetchall()
    schema_review_events = conn.execute("pragma table_info(review_events);").fetchall()
    schema_fetch_audits = conn.execute("pragma table_info(fetch_audit);").fetchall()
    
    
    print("\n")
    print("Comments")
    for rows1 in schema_comment_events:
        print(rows1)
    
    print("\n")
    print("Reviews")
    for rows2 in schema_review_events:
        print(rows2)
    
    print("\n")
    print("fetch_audit")
    for rows3 in schema_fetch_audits:
        print(rows3)
    
    
    
    conn.close()
    
    
    

if __name__ == "__main__":
    main()