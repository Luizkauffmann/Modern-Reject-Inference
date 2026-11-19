"""Copies the two tables the Explorer reads into the demo folder, with shorter numbers (smaller download)."""
import sys

import pandas as pd

src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src + "/ri_scored.csv", low_memory=False)
for c in ("p_kgb", "p_hc", "p_pcl", "p_fz", "bad_fz"):
    df[c] = df[c].round(5)
df.to_csv(dst + "/ri_scored.csv", index=False)
pd.read_csv(src + "/ri_map.csv").to_csv(dst + "/ri_map.csv", index=False)
print("ri_scored.csv", len(df), "rows")
