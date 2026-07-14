import sqlite3

DB_PATH = "data/raw/SQL FILES/pr_data.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    
    schema_repos = conn.execute("pragma table_info(repos);")
    schema_pull_requests = conn.execute("pragma table_info(pull_requests);")
    schema_pr_labels = conn.execute("pragma table_info(pr_labels);")
    
    print("Schema for 'repos' table:")
    for rows_repos in schema_repos:
        print(rows_repos)
    
    print("Schema for 'pull_requests' table:")
    for rows_pull_requests in schema_pull_requests:
        print(rows_pull_requests)
    
    print("Schema for 'pr_labels' table:")
    for rows_pr_labels in schema_pr_labels:
        print(rows_pr_labels)

    conn.close()
    

if __name__ == "__main__":
    main()