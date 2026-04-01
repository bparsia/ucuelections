"""
fuzzy_names.py — Find candidate name clusters via fuzzy matching and write a
                  CSV for manual review.

Usage:
    uv run python fuzzy_names.py                  # default threshold 0.85
    uv run python fuzzy_names.py --threshold 0.82
    uv run python fuzzy_names.py --out review/name_clusters.csv

Output CSV columns:
    cluster_id        — numeric cluster identifier
    proposed_canonical — most-frequent name in cluster (suggested winner)
    name_canonical    — this variant
    n_appearances     — how many candidate rows use this name
    years             — years in which this name appears (comma-separated)
    outcomes          — distinct outcomes seen (comma-separated)
    page_urls         — UCU election page URLs for those years (comma-sep)
    similarity        — similarity score vs proposed_canonical (1.0 = identical)

Only clusters with ≥ 2 distinct name_canonical values are written.
"""

import argparse
import csv
import difflib
from collections import defaultdict
from pathlib import Path

CANDIDATES_PATH = Path(__file__).parent / "data" / "processed" / "candidates.csv"
PAGES_PATH      = Path(__file__).parent / "sources" / "election_pages.csv"
DEFAULT_OUT     = Path(__file__).parent / "review" / "name_clusters.csv"

OUTPUT_FIELDS = [
    "cluster_id", "proposed_canonical",
    "name_canonical", "n_appearances", "years", "outcomes", "page_urls",
    "similarity",
]


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_year_urls() -> dict[str, str]:
    if not PAGES_PATH.exists():
        return {}
    with PAGES_PATH.open() as f:
        rows = list(csv.DictReader(f))
    urls: dict[str, str] = {}
    for r in rows:
        if r.get("include") == "yes":
            urls[r["year"]] = r["url"]
    return urls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="Minimum similarity ratio to link two names (default: 0.85)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="Output CSV path")
    args = parser.parse_args()

    # --- Load candidates ---
    with CANDIDATES_PATH.open() as f:
        candidates = list(csv.DictReader(f))

    year_urls = load_year_urls()

    # Build per-name metadata: appearances, years, outcomes
    meta: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "years": set(), "outcomes": set()
    })
    for row in candidates:
        nc = row["name_canonical"].strip()
        if not nc:
            continue
        meta[nc]["n"] += 1
        meta[nc]["years"].add(row["year"])
        if row["outcome"]:
            meta[nc]["outcomes"].add(row["outcome"])

    names = sorted(meta.keys())
    n = len(names)
    print(f"{n} distinct canonical names to cluster...")

    # --- Pairwise fuzzy similarity ---
    # O(n²) but n ≈ 500 so ~125k comparisons — fine
    uf = UnionFind(names)
    pair_sim: dict[tuple[str, str], float] = {}

    for i in range(n):
        for j in range(i + 1, n):
            a, b = names[i], names[j]
            ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
            if ratio >= args.threshold:
                uf.union(a, b)
                pair_sim[(a, b)] = ratio

    # --- Build clusters ---
    clusters: dict[str, list[str]] = defaultdict(list)
    for name in names:
        clusters[uf.find(name)].append(name)

    # Keep only multi-name clusters
    multi = {root: members for root, members in clusters.items() if len(members) > 1}
    print(f"{len(multi)} clusters with ≥ 2 names (covering "
          f"{sum(len(v) for v in multi.values())} name variants)")

    # --- Write output CSV ---
    args.out.parent.mkdir(parents=True, exist_ok=True)

    rows_out = []
    for cluster_id, (root, members) in enumerate(
        sorted(multi.items(), key=lambda kv: -max(meta[m]["n"] for m in kv[1])),
        start=1,
    ):
        # Proposed canonical = member with most appearances (alpha tie-break)
        proposed = max(members, key=lambda m: (meta[m]["n"], m))

        for name in sorted(members):
            m = meta[name]
            years_sorted = sorted(m["years"])
            urls = [year_urls[y] for y in years_sorted if y in year_urls]

            # Similarity to proposed_canonical
            if name == proposed:
                sim = 1.0
            else:
                key = (min(name, proposed), max(name, proposed))
                sim = pair_sim.get(key, difflib.SequenceMatcher(
                    None, name, proposed, autojunk=False).ratio())

            rows_out.append({
                "cluster_id":        cluster_id,
                "proposed_canonical": proposed,
                "name_canonical":    name,
                "n_appearances":     m["n"],
                "years":             ", ".join(years_sorted),
                "outcomes":          ", ".join(sorted(m["outcomes"])),
                "page_urls":         " | ".join(urls),
                "similarity":        f"{sim:.4f}",
            })

    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Written to {args.out}  ({len(rows_out)} rows)")


if __name__ == "__main__":
    main()
