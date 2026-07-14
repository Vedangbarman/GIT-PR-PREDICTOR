import sqlite3 


DB_PATH = "data/raw/SQL FILES/pr_data.db"

EXCLUSION = {
    ("pytorch","pytorch"): "pytorchbot_label_based_merge"
}

def main():
    conn = sqlite3.connect(DB_PATH)
    
    for (owner,name), reason in EXCLUSION.items():
        conn.execute(
            "UPDATE repos SET exclude_reason = ? WHERE owner == ? AND name = ?",(reason,owner,name),
        )
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()