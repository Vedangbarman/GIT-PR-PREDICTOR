
import sqlite3
import pandas as pd

IN_CSV = "data/processed/pr_snapshots_clean.csv"
FEATURES_DB = "data/processed/pr_features.db"
OUT_CSV = "data/processed/pr_snapshots_clean_v2.csv"

df = pd.read_csv(IN_CSV)
conn = sqlite3.connect(FEATURES_DB)
features = pd.read_sql("SELECT * FROM pr_features", conn)
conn.close()

before = len(df)
df = df.merge(features, on="pr_id", how="left")
assert len(df) == before, "row count changed after merge -- check for duplicate pr_id in features table"

print(f"{len(df)} rows, {df.shape[1]} columns")
print(f"unmatched pr_id (no features row): {df['author_prior_pr_count'].isna().sum()}")

df.to_csv(OUT_CSV, index=False)
print(f"-> {OUT_CSV}")