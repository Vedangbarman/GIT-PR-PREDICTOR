import pandas as pd

IN_CSV = "data/processed/pr_snapshots.csv"
OUT_CSV = "data/processed/pr_snapshots_clean.csv"

df = pd.read_csv(IN_CSV)
print(f"loaded {len(df)} rows")

df = df[df.timeline_data_available == 1].copy()
df = df[df.merged_before_next.notna()].copy()
df["merged_before_next"] = df["merged_before_next"].astype(int)
print(f"after filters: {len(df)} rows")

print("\nclass balance per checkpoint:")
print(df.groupby("checkpoint_day").merged_before_next.value_counts(normalize=True).unstack().round(3))

size_cols = ["additions", "deletions", "changed_files"]
for col in size_cols:
    repo_median = df.groupby(["owner", "name"])[col].transform("median").replace(0, 1)
    df[f"{col}_norm"] = df[col] / repo_median

df["has_response_yet"] = df["first_response_hours"].notna().astype(int)
df["repo_key"] = df["owner"] + "/" + df["name"]

print(f"\n{df.repo_key.nunique()} repos -> use each as held-out fold (leave-one-repo-out)")

df.to_csv(OUT_CSV, index=False)
print(f"-> {OUT_CSV}")