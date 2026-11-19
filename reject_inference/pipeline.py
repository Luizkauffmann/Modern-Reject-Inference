"""
Reject-inference pipeline: from the four source tables to the two tables the Explorer reads.

    python -m reject_inference.pipeline            # uses ./data
    python -m reject_inference.pipeline --hc-cut 0.25 --pcl-mult 1.3

Steps
  1. Join applications, bureau attributes, internal performance and bureau performance.
  2. KGB model: logistic regression on booked accounts, target bad_int  ->  p_kgb.
  3. Three inferred outcomes for not-booked applicants:
       bad_hc   hard cutoff     1 if p_kgb >= hc_cut
       bad_pcl  parceling       Bernoulli(min(1, pcl_mult * booked bad rate of the score band))
       bad_fz   fuzzy           p_kgb (used as a weight, not a label)
  4. One final logistic regression per method on everyone  ->  p_hc, p_pcl, p_fz.
  5. bad_obs: the best observed outcome (internal for booked, bureau otherwise).
  6. Similarity map (t-SNE) of a stratified sample.

Writes ri_scored.csv and ri_map.csv into the data directory.
The bureau outcome bad_bur is never used for training: it is held back to grade the methods.
"""

import argparse
import os

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import explorer

BAND_EDGES = [0.02, 0.04, 0.06, 0.09, 0.13, 0.20, 0.30, 0.45]
MODEL_FEATURES = explorer.FEATURES + ["bk_flag"]


def _model():
    # No class weighting: the output has to stay a calibrated probability.
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=1.0, max_iter=2000))


def _fit(X, y, weight=None):
    m = _model()
    m.fit(X, y, logisticregression__sample_weight=weight)
    return m


def load_sources(data_dir):
    def read(name):
        path = os.path.join(data_dir, name)
        if not os.path.exists(path):
            raise IOError("%s not found. Run: python data/generate_data.py" % path)
        return pd.read_csv(path)

    apps = read("applications.csv")
    attrs = read("bureau_attributes.csv")
    booked = read("booked_performance.csv").rename(columns={"worst_dpd_12m": "dpd_int"})
    bureau = read("bureau_performance.csv").rename(columns={"worst_dpd_12m_bur": "dpd_bur"})
    df = apps.merge(attrs, on="app_id", how="left").merge(booked, on="app_id", how="left") \
             .merge(bureau, on="app_id", how="left")
    df["seg"] = np.where(df["booked"] == 1, "BK", np.where(df["decision"] == "APPROVE", "ANB", "DEC"))
    df["has_bur"] = df["bad_bur"].notna().astype(int)
    df["mos_since_delq"] = df["mos_since_delq"].fillna(999)
    df["decline_rule"] = df["decline_rule"].fillna("")
    return df


def run(data_dir, hc_cut=0.20, pcl_mult=1.5, seed=20261116, with_map=True, log=print):
    df = load_sources(data_dir)
    X = df[MODEL_FEATURES].apply(pd.to_numeric, errors="coerce")
    bk = (df["seg"] == "BK").values
    nb = ~bk
    log("applications %d | booked %d | approved not booked %d | declined %d" % (
        len(df), bk.sum(), (df["seg"] == "ANB").sum(), (df["seg"] == "DEC").sum()))

    # 2. KGB model on booked accounts only
    kgb = _fit(X[bk], df.loc[bk, "bad_int"].astype(int))
    p = kgb.predict_proba(X)[:, 1]
    df["p_kgb"] = p
    df["band"] = np.searchsorted(BAND_EDGES, p, side="right") + 1

    # 3. inferred outcomes
    stats = df[bk].groupby("band")["bad_int"].agg(n_bk="count", br_bk="mean")
    n_bk = df["band"].map(stats["n_bk"]).fillna(0).values
    br_bk = df["band"].map(stats["br_bk"]).values
    p_parcel = np.minimum(1.0, pcl_mult * np.where(n_bk >= 30, br_bk, p))
    rng = np.random.RandomState(seed)
    bad_int = df["bad_int"].values
    df["bad_hc"] = np.where(bk, bad_int, (p >= hc_cut).astype(float))
    df["bad_pcl"] = np.where(bk, bad_int, (rng.rand(len(df)) < p_parcel).astype(float))
    df["bad_fz"] = np.where(bk, bad_int, p)

    # 4. final models on the whole through-the-door population
    df["p_hc"] = _fit(X, df["bad_hc"].astype(int)).predict_proba(X)[:, 1]
    df["p_pcl"] = _fit(X, df["bad_pcl"].astype(int)).predict_proba(X)[:, 1]
    # Fuzzy augmentation: each not-booked applicant enters twice, as bad (weight p) and good (1 - p).
    Xf = pd.concat([X[bk], X[nb], X[nb]])
    yf = np.concatenate([bad_int[bk], np.ones(nb.sum()), np.zeros(nb.sum())]).astype(int)
    wf = np.concatenate([np.ones(bk.sum()), p[nb], 1.0 - p[nb]])
    df["p_fz"] = _fit(Xf, yf, wf).predict_proba(X)[:, 1]

    # 5. best observed outcome
    df["bad_obs"] = np.where(bk, bad_int, np.where(df["has_bur"] == 1, df["bad_bur"], np.nan))

    out = os.path.join(data_dir, explorer.DATASET + ".csv")
    df.to_csv(out, index=False)
    log("wrote %s (%d rows, %d columns)" % (out, len(df), df.shape[1]))
    seen = df["has_bur"] == 1
    log("not-booked with a bureau outcome: actual bad %.1f%% | hard cutoff %.1f%% | parceling %.1f%% | fuzzy %.1f%%" % (
        100 * df.loc[seen, "bad_bur"].mean(), 100 * df.loc[seen, "bad_hc"].mean(),
        100 * df.loc[seen, "bad_pcl"].mean(), 100 * df.loc[seen, "bad_fz"].mean()))

    # 6. similarity map
    if with_map:
        log("building the similarity map (about a minute)...")
        mp = explorer.build_map(df)
        out = os.path.join(data_dir, explorer.MAP_DATASET + ".csv")
        mp.to_csv(out, index=False)
        log("wrote %s (%d rows)" % (out, len(mp)))
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default=explorer.data_dir())
    ap.add_argument("--hc-cut", type=float, default=0.20, help="hard-cutoff threshold on p_kgb")
    ap.add_argument("--pcl-mult", type=float, default=1.5, help="parceling multiplier on the booked bad rate")
    ap.add_argument("--no-map", action="store_true", help="skip the t-SNE map")
    a = ap.parse_args()
    run(a.data_dir, a.hc_cut, a.pcl_mult, with_map=not a.no_map)


if __name__ == "__main__":
    main()
