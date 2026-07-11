import os
import json

DATA_DIR = "data/raw"


def main():
    total_prs = 0
    total_bytes = 0
    rows = []

    for owner in sorted(os.listdir(DATA_DIR)):
        p = os.path.join(DATA_DIR, owner)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if not f.endswith(".json") or f.endswith(".partial.json"):
                continue
            full = os.path.join(p, f)
            size = os.path.getsize(full)
            d = json.load(open(full, encoding="utf-8"))
            n = len(d.get("pull_requests", []))
            total_prs += n
            total_bytes += size
            rows.append((f"{owner}/{f[:-5]}", n, size / 1e6))

    name_w = max(len(r[0]) for r in rows) + 2
    print(f"{'repo':<{name_w}}{'prs':>8}{'size_mb':>10}")
    for name, n, mb in sorted(rows, key=lambda r: -r[1]):
        print(f"{name:<{name_w}}{n:>8}{mb:>10.2f}")

    print("-" * (name_w + 18))
    print(f"{len(rows)} repos  |  total PRs: {total_prs}  |  total size: {total_bytes / 1e6:.2f} MB")


if __name__ == "__main__":
    main()