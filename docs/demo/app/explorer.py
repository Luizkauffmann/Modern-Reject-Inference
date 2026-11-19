"""
Reject Inference Explorer: analytics and web API.

Inputs (CSV files in the data directory, see ``pipeline.py``)
  ri_scored.csv  one row per applicant: seg (BK booked / ANB approved-not-booked / DEC declined),
                 decision, decline_rule, the bureau attributes, bad_int (internal bad, booked only),
                 bad_bur (off-us bureau bad, not-booked who opened a trade elsewhere), has_bur,
                 p_kgb (booked-only model), bad_hc / bad_pcl / bad_fz (inferred flags) and the
                 final-model scores p_hc / p_pcl / p_fz.
  ri_map.csv     app_id, tx, ty: t-SNE coordinates of a stratified sample (built by build_map).

Everything that produces a rule works in the ORIGINAL attribute space; the map only displays.

Environment variables
  RI_DATA_DIR       folder holding ri_scored.csv and ri_map.csv   (default: ./data)
  RI_STRATEGY_DIR   folder where exported strategies are written   (default: ./strategies)
"""

import json
import os
import traceback

import numpy as np
import pandas as pd

FEATURES = ["bureau_score", "util_pct", "dti_pct", "inq_6m", "delq_24m", "coll_cnt", "credit_age_yrs",
            "open_trades", "bankcards", "thin_file", "mos_on_file", "pct_never_delq", "mos_since_delq",
            "rev_bal", "inst_bal", "max_limit", "mortgage_flag", "util_trend_6m", "req_amt",
            "income_mo", "emp_mos", "pti_pct"]
LABELS = {"bureau_score": "Bureau score", "util_pct": "Revolving utilization %", "dti_pct": "Debt-to-income %",
          "inq_6m": "Inquiries 6m", "delq_24m": "Delinquencies 24m", "coll_cnt": "Collections",
          "credit_age_yrs": "Avg credit age (yrs)", "open_trades": "Open trades", "bankcards": "Bankcards",
          "thin_file": "Thin file", "mos_on_file": "Months on file", "pct_never_delq": "% trades never delq",
          "mos_since_delq": "Months since delq", "rev_bal": "Revolving balance", "inst_bal": "Installment balance",
          "max_limit": "Max credit limit", "mortgage_flag": "Mortgage", "util_trend_6m": "Utilization trend 6m",
          "req_amt": "Requested amount", "income_mo": "Monthly income", "emp_mos": "Employment months",
          "pti_pct": "Payment-to-income %"}
# Champion policy, first rule that fires declines.  (id, column, operator, threshold, label)
POLICY = [("R1", "bk_flag", "==", 1, "Bankruptcy"),
          ("R2", "bureau_score", "<", 660, "Bureau score < 660"),
          ("R3", "dti_pct", ">", 45, "DTI > 45"),
          ("R4", "delq_24m", ">=", 2, "Delinquencies 24m >= 2"),
          ("R5", "inq_6m", ">=", 6, "Inquiries 6m >= 6")]
SWEEPS = {"R2": [650, 640, 630, 620, 610, 600, 590, 580],
          "R3": [47.5, 50, 52.5, 55, 57.5, 60],
          "R4": [3, 4, 5],
          "R5": [7, 8, 9, 10]}
MODELS = [("p_kgb", "KGB"), ("p_hc", "HC"), ("p_pcl", "PCL"), ("p_fz", "FZ")]
DATASET = "ri_scored"
MAP_DATASET = "ri_map"
TREE_FORMAT = "strategy_tree_v2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    return os.environ.get("RI_DATA_DIR") or os.path.join(ROOT, "data")


def strategy_dir():
    return os.environ.get("RI_STRATEGY_DIR") or os.path.join(ROOT, "strategies")
MAP_SAMPLE = {"BK": 2200, "ANB": 1500, "DEC": 2600}

_S = {}


# ───────────────────────────── helpers ─────────────────────────────
def _op(x, op, v):
    if op == "<":
        return x < v
    if op == "<=":
        return x <= v
    if op == ">":
        return x > v
    if op == ">=":
        return x >= v
    if op == "==":
        return x == v
    raise ValueError("Unknown operator %s" % op)


def _clean(o):
    """Make numpy / NaN values JSON-safe."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def _standardize(df):
    X = df[FEATURES].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median())
    lo, hi = X.quantile(0.01), X.quantile(0.99)
    X = X.clip(lo, hi, axis=1)
    sd = X.std().replace(0, 1.0)
    return ((X - X.mean()) / sd).values.astype(float)


def _auc(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    ok = ~np.isnan(p) & ~np.isnan(y)
    p, y = p[ok], y[ok]
    n1, n0 = y.sum(), (1 - y).sum()
    if n1 == 0 or n0 == 0:
        return None
    r = pd.Series(p).rank().values
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


# ───────────────────────────── map builder ─────────────────────────────
def build_map(df, seed=42):
    """t-SNE of a stratified sample on the standardised bureau attributes -> app_id, tx, ty."""
    from sklearn.manifold import TSNE
    df = df.sort_values("app_id", kind="mergesort").reset_index(drop=True)
    rng = np.random.RandomState(seed)
    keep = []
    for seg, n in MAP_SAMPLE.items():
        idx = np.where(df["seg"].values == seg)[0]
        keep.extend(rng.choice(idx, min(n, len(idx)), replace=False).tolist())
    keep = sorted(keep)
    X = _standardize(df)[keep]
    xy = TSNE(n_components=2, perplexity=40, init="pca", learning_rate="auto",
              random_state=seed).fit_transform(X)
    return pd.DataFrame({"app_id": df["app_id"].values[keep],
                         "tx": np.round(xy[:, 0], 3), "ty": np.round(xy[:, 1], 3)})


# ───────────────────────────── state ─────────────────────────────
def load(force=False):
    if _S.get("ok") and not force:
        return _S
    ds_name, map_name = DATASET, MAP_DATASET
    path = os.path.join(data_dir(), ds_name + ".csv")
    if not os.path.exists(path):
        raise IOError("%s not found. Run: python -m reject_inference.pipeline" % path)
    df = pd.read_csv(path, low_memory=False)
    # Sort so that the holdout split and the searches are repeatable whatever the file order.
    df = df.sort_values("app_id", kind="mergesort").reset_index(drop=True)
    ds_type = "CSV"
    for c in FEATURES + ["bk_flag", "bad_int", "bad_bur", "has_bur", "bad_hc", "bad_pcl", "bad_fz",
                         "p_kgb", "p_hc", "p_pcl", "p_fz", "score_12m"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["decline_rule"] = df["decline_rule"].fillna("").astype(str)
    N = len(df)
    seg = df["seg"].astype(str).values
    bk = seg == "BK"
    has_bur = (df["has_bur"].fillna(0).values == 1) & ~bk
    declined = df["decision"].astype(str).values == "DECLINE"
    approved = ~declined
    bad_int = df["bad_int"].values.astype(float)
    bad_bur = df["bad_bur"].values.astype(float)

    # Off-us -> on-us calibration: approved-not-booked passed the same policy as booked, so the ratio
    # of the booked internal bad rate to their bureau bad rate (same score-band mix) translates
    # "bad at a peer" into "bad with us".
    cal = 1.0
    if "band" in df.columns:
        num = den = 0.0
        for b, g in df.groupby("band"):
            gi = g.index.values
            a = gi[(seg[gi] == "ANB") & has_bur[gi]]
            k = gi[bk[gi]]
            if len(a) >= 30 and len(k) >= 30:
                num += len(a) * np.nanmean(bad_int[k])
                den += len(a) * np.nanmean(bad_bur[a])
        if den > 0:
            cal = float(np.clip(num / den, 0.5, 1.5))

    # 0 = good, 1 = bad, NaN = unknown; bureau outcomes scaled to on-us equivalents via cal.
    y_adj = np.where(bk, bad_int, np.where(has_bur, bad_bur * cal, np.nan))

    X = _standardize(df)
    rng = np.random.RandomState(7)
    holdout = rng.rand(N) < 0.30

    try:
        mp = pd.read_csv(os.path.join(data_dir(), map_name + ".csv"))
        pos = pd.Series(np.arange(N), index=df["app_id"].values)
        mp = mp[mp["app_id"].isin(pos.index)]
        map_idx = pos.loc[mp["app_id"].values].values.astype(int)
        map_xy = mp[["tx", "ty"]].values.astype(float)
    except Exception:
        map_idx, map_xy = np.zeros(0, dtype=int), np.zeros((0, 2))
    map_pos = -np.ones(N, dtype=int)
    map_pos[map_idx] = np.arange(len(map_idx))

    pools = {"BK": np.where(bk)[0], "NB_BUR": np.where(has_bur)[0], "NB": np.where(~bk)[0]}

    take_up = float(bk.sum()) / max(1, approved.sum())
    _S.update(dict(ok=True, dataset=ds_name, map_dataset=map_name, dataset_type=ds_type, df=df, N=N, seg=seg, bk=bk, has_bur=has_bur, declined=declined, approved=approved,
                   bad_int=bad_int, bad_bur=bad_bur, y_adj=y_adj, cal=cal, X=X, holdout=holdout,
                   map_idx=map_idx, map_xy=map_xy, map_pos=map_pos, pools=pools, take_up=take_up))
    return _S


# ───────────────────────────── metrics ─────────────────────────────
def swap_stats(mask, margin, loss, S=None):
    """Economics of approving the not-booked applicants in ``mask`` (a swap-in set)."""
    S = S or load()
    m = np.asarray(mask, bool)
    n = int(m.sum())
    mb = m & S["has_bur"]
    nb = int(mb.sum())
    br = float(np.nanmean(S["bad_bur"][mb])) if nb else None
    adj = br * S["cal"] if br is not None else None
    be = margin / float(margin + loss)
    profit = None
    if adj is not None:
        profit = n * S["take_up"] * ((1 - adj) * margin - adj * loss)
    return dict(n=n, n_bur=nb, bad_bur=br, bad_adj=adj, d_approval=n / float(S["N"]),
                profit=profit, good_bur=int(nb - np.nansum(S["bad_bur"][mb])) if nb else 0,
                beats_breakeven=(adj is not None and adj <= be))


def portfolio(approved_mask, S=None):
    """Approval rate and (on-us equivalent) bad rate of an approved population, on known outcomes."""
    S = S or load()
    a = np.asarray(approved_mask, bool)
    y = S["y_adj"][a]
    known = ~np.isnan(y)
    return dict(approval=float(a.mean()), bad=float(y[known].mean()) if known.any() else None,
                n=int(a.sum()), n_known=int(known.sum()))


def rule_mask(conds, S=None):
    S = S or load()
    df = S["df"]
    m = np.ones(S["N"], dtype=bool)
    for c in conds:
        if c["f"] not in df.columns:
            raise ValueError("Unknown column %s" % c["f"])
        m &= _op(df[c["f"]].values.astype(float), c["op"], float(c["v"]))
    return m


def eligible(S=None):
    """Declined applicants a challenger rule may swap in (bankruptcies stay declined)."""
    S = S or load()
    return S["declined"] & (S["df"]["bk_flag"].fillna(0).values != 1)


def rule_text(conds):
    return " and ".join("%s %s %s" % (c["f"], c["op"], _fmt(c["v"])) for c in conds) or "(all declined)"


def _fmt(v):
    v = float(v)
    return str(int(v)) if abs(v - round(v)) < 1e-9 else ("%.2f" % v).rstrip("0").rstrip(".")


def evaluate_rule(conds, margin, loss, S=None, with_members=True):
    S = S or load()
    m = rule_mask(conds, S) & eligible(S)
    out = swap_stats(m, margin, loss, S)
    out["holdout"] = swap_stats(m & S["holdout"], margin, loss, S)
    out["conds"] = conds
    out["text"] = rule_text(conds)
    out["champion"] = portfolio(S["approved"], S)
    out["challenger"] = portfolio(S["approved"] | m, S)
    by = []
    dr = S["df"]["decline_rule"].values
    for rid, _, _, _, lab in POLICY:
        mm = m & np.array([d.startswith(rid) for d in dr])
        if mm.any():
            s = swap_stats(mm, margin, loss, S)
            s.update(rule=rid, label=lab)
            by.append(s)
    out["by_rule"] = by
    if with_members:
        mp = S["map_pos"][np.where(m)[0]]
        out["members"] = mp[mp >= 0].tolist()
    return out


# ───────────────────────────── analytics ─────────────────────────────
def overview(margin, loss, S=None):
    S = S or load()
    df = S["df"]
    be = margin / float(margin + loss)
    segs = []
    for s, lab in (("BK", "Booked"), ("ANB", "Approved, not booked"), ("DEC", "Declined")):
        m = S["seg"] == s
        mb = m & S["has_bur"]
        segs.append(dict(seg=s, label=lab, n=int(m.sum()), n_bur=int(mb.sum()),
                         bad=float(np.nanmean(S["bad_int"][m])) if s == "BK" else (
                             float(np.nanmean(S["bad_bur"][mb])) if mb.any() else None)))
    rules = []
    dr = df["decline_rule"].values
    for rid, col, op, thr, lab in POLICY:
        m = S["declined"] & np.array([d.startswith(rid) for d in dr])
        s = swap_stats(m, margin, loss, S)
        s.update(rule=rid, label=lab)
        rules.append(s)
    return dict(segments=segs, rules=rules, breakeven=be, cal=S["cal"], take_up=S["take_up"],
                champion=portfolio(S["approved"], S), N=S["N"])


def methods(S=None):
    """How each inference method and each final model compares with observed bureau performance."""
    S = S or load()
    df = S["df"]
    nb = S["has_bur"]
    y = S["bad_bur"]
    out = dict(flags=[], models=[], actual_bad=float(np.nanmean(y[nb])), n=int(nb.sum()))
    for col, lab, name in (("bad_hc", "HC", "Hard cutoff"), ("bad_pcl", "PCL", "Parceling"), ("bad_fz", "FZ", "Fuzzy")):
        if col not in df.columns:
            continue
        v = df[col].values.astype(float)
        row = dict(key=lab, name=name, inferred_bad=float(np.nanmean(v[nb])),
                   inferred_bad_dec=float(np.nanmean(v[S["seg"] == "DEC"])),
                   inferred_bad_nobur=float(np.nanmean(v[~S["bk"] & ~S["has_bur"]])))
        if lab != "FZ":
            p = v[nb] >= 0.5
            t = y[nb] == 1
            row.update(tp=int((p & t).sum()), fp=int((p & ~t).sum()), fn=int((~p & t).sum()),
                       tn=int((~p & ~t).sum()), accuracy=float((p == t).mean()))
        out["flags"].append(row)
    for col, lab in MODELS:
        if col not in df.columns:
            continue
        p = df[col].values.astype(float)
        dec = (S["seg"] == "DEC") & nb
        out["models"].append(dict(key=lab, col=col,
                                  auc_booked=_auc(p[S["bk"]], S["bad_int"][S["bk"]]),
                                  auc_notbooked=_auc(p[nb], y[nb]),
                                  pred_dec=float(np.nanmean(p[dec])) if dec.any() else None,
                                  actual_dec=float(np.nanmean(y[dec])) if dec.any() else None))
    return out


def frontier(S=None):
    """Approval rate vs bad rate if each model alone ranked the whole through-the-door population."""
    S = S or load()
    df = S["df"]
    curves = []
    for col, lab in MODELS:
        if col not in df.columns:
            continue
        p = df[col].values.astype(float)
        order = np.argsort(np.where(np.isnan(p), 9.0, p), kind="stable")
        y = S["y_adj"][order]
        known = ~np.isnan(y)
        cb = np.cumsum(np.where(known, y, 0.0))
        ck = np.cumsum(known)
        pts = []
        for a in np.arange(0.30, 0.96, 0.025):
            k = int(a * S["N"]) - 1
            if ck[k] > 0:
                pts.append([round(float(a), 4), float(cb[k] / ck[k])])
        curves.append(dict(key=lab, points=pts))
    return dict(curves=curves, champion=portfolio(S["approved"], S))


def sweep(margin, loss, S=None):
    """Relax each champion threshold step by step; report who comes in and how they performed."""
    S = S or load()
    df = S["df"]
    fails = {rid: np.nan_to_num(_op(df[col].values.astype(float), op, thr), nan=0).astype(bool)
             for rid, col, op, thr, _ in POLICY}
    be = margin / float(margin + loss)
    out = []
    for rid, col, op, thr, lab in POLICY:
        if rid not in SWEEPS:
            continue
        others_pass = np.ones(S["N"], dtype=bool)
        for r2 in fails:
            if r2 != rid:
                others_pass &= ~fails[r2]
        base = others_pass & fails[rid] & S["declined"]
        x = df[col].values.astype(float)
        steps, prev, best, running = [], np.zeros(S["N"], dtype=bool), None, True
        for t in SWEEPS[rid]:
            now = base & ~_op(x, op, t)
            cum = swap_stats(now, margin, loss, S)
            mar = swap_stats(now & ~prev, margin, loss, S)
            steps.append(dict(cut=t, cum=cum, marginal=mar))
            # Suggest the furthest cut reached while every step so far cleared break-even on a
            # slice large enough to trust (30+ applicants with bureau performance).
            if running and mar["bad_adj"] is not None and mar["n_bur"] >= 30 and mar["bad_adj"] <= be:
                best = len(steps) - 1
            else:
                running = False
            prev = now
        out.append(dict(rule=rid, label=lab, column=col, op=op, current=thr, steps=steps,
                        recommended=SWEEPS[rid][best] if best is not None else None,
                        only_this_rule=int(base.sum())))
    return dict(rules=out, breakeven=be)


def _tidy(v):
    """Thresholds a policy writer would actually type: hundreds for balances, whole numbers above 100."""
    v = float(v)
    if abs(v) >= 1000:
        return float(round(v, -2))
    if abs(v) >= 100:
        return float(round(v))
    return float(round(v, 1))


def _box_conds(box, lo0, hi0):
    conds = []
    for f in FEATURES:
        lo, hi = box[f]
        if lo > lo0[f]:
            conds.append(dict(f=f, op=">=", v=_tidy(lo)))
        if hi < hi0[f]:
            conds.append(dict(f=f, op="<=", v=_tidy(hi)))
    return conds


def bump_hunt(margin, loss, alpha=0.08, min_support=0.03, S=None):
    """PRIM peeling on declined applicants with bureau performance: find boxes in attribute space
    with the highest share of good performers. Each peel is one point of a volume/purity frontier."""
    S = S or load()
    df = S["df"]
    pop = eligible(S) & S["has_bur"]
    tr = np.where(pop & ~S["holdout"])[0]
    Xr = df[FEATURES].apply(pd.to_numeric, errors="coerce")
    Xr = Xr.fillna(Xr.median())
    A = Xr.values[tr].astype(float)
    g = 1.0 - S["bad_bur"][tr]
    lo0 = {f: float(Xr[f].min()) for f in FEATURES}
    hi0 = {f: float(Xr[f].max()) for f in FEATURES}
    box = {f: [lo0[f], hi0[f]] for f in FEATURES}
    inside = np.ones(len(tr), dtype=bool)
    n_min = max(40, int(min_support * len(tr)))
    steps = []
    while inside.sum() > n_min:
        best = None
        n_in = inside.sum()
        for j, f in enumerate(FEATURES):
            x = A[inside, j]
            for side in (0, 1):
                if side == 0:
                    t = np.quantile(x, alpha)
                    keep_val = x >= t
                    if keep_val.all():
                        vals = np.unique(x)
                        if len(vals) < 2:
                            continue
                        t = vals[1]
                        keep_val = x >= t
                else:
                    t = np.quantile(x, 1 - alpha)
                    keep_val = x <= t
                    if keep_val.all():
                        vals = np.unique(x)
                        if len(vals) < 2:
                            continue
                        t = vals[-2]
                        keep_val = x <= t
                k = keep_val.sum()
                if k < n_min or k < 0.55 * n_in or k == n_in:
                    continue
                score = g[inside][keep_val].mean()
                if best is None or score > best[0] + 1e-12:
                    best = (score, j, side, float(t))
        if best is None:
            break
        _, j, side, t = best
        f = FEATURES[j]
        if side == 0:
            box[f][0] = t
            inside &= A[:, j] >= t
        else:
            box[f][1] = t
            inside &= A[:, j] <= t
        # Simplify: release every edge the box does not need (good rate within 1.2 pt of the peeled
        # box), widest release first, so the rule keeps only the conditions that do the work.
        slim = {f: list(v) for f, v in box.items()}
        g_ref = g[inside].mean()

        def _mask(bx):
            mm = np.ones(len(tr), dtype=bool)
            for jj, ff in enumerate(FEATURES):
                if bx[ff][0] > lo0[ff]:
                    mm &= A[:, jj] >= bx[ff][0]
                if bx[ff][1] < hi0[ff]:
                    mm &= A[:, jj] <= bx[ff][1]
            return mm

        while True:
            cand = None
            for ff in FEATURES:
                for sd, full in ((0, lo0[ff]), (1, hi0[ff])):
                    if slim[ff][sd] == full:
                        continue
                    trial = {k: list(v) for k, v in slim.items()}
                    trial[ff][sd] = full
                    mm = _mask(trial)
                    if g[mm].mean() >= g_ref - 0.012 and (cand is None or mm.sum() > cand[0]):
                        cand = (mm.sum(), ff, sd, full)
            if cand is None:
                break
            slim[cand[1]][cand[2]] = cand[3]
        conds = _box_conds(slim, lo0, hi0)
        if steps and rule_text(conds) == steps[-1]["text"]:
            continue
        ev = evaluate_rule(conds, margin, loss, S, with_members=False)
        steps.append(dict(conds=conds, text=ev["text"], n=ev["n"], n_bur=ev["n_bur"], bad_bur=ev["bad_bur"],
                          bad_adj=ev["bad_adj"], profit=ev["profit"], d_approval=ev["d_approval"],
                          holdout=ev["holdout"], challenger=ev["challenger"],
                          train_good=float(g[inside].mean()), train_n=int(inside.sum())))
    base = swap_stats(eligible(S), margin, loss, S)
    best_i = None
    for i, s in enumerate(steps):
        if s["profit"] is not None and (best_i is None or s["profit"] > steps[best_i]["profit"]):
            best_i = i
    return dict(steps=steps, base=base, best=best_i, breakeven=margin / float(margin + loss))


def lasso_rule(map_positions, margin, loss, S=None):
    """Describe a hand-drawn selection on the map with a shallow tree on the real attributes."""
    from sklearn.tree import DecisionTreeClassifier
    S = S or load()
    df = S["df"]
    sel = np.zeros(len(S["map_idx"]), dtype=bool)
    sel[np.asarray(map_positions, dtype=int)] = True
    if sel.sum() < 15:
        raise ValueError("Select at least 15 points.")
    rows = S["map_idx"]
    Xr = df[FEATURES].apply(pd.to_numeric, errors="coerce")
    Xr = Xr.fillna(Xr.median()).values[rows].astype(float)
    clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=max(10, int(sel.sum() * 0.08)),
                                 class_weight="balanced", random_state=0).fit(Xr, sel.astype(int))
    t = clf.tree_
    leaf_of = clf.apply(Xr)
    best, best_f1 = None, -1.0
    for leaf in np.unique(leaf_of):
        m = leaf_of == leaf
        tp = float((m & sel).sum())
        if tp == 0:
            continue
        pr, rc = tp / m.sum(), tp / sel.sum()
        f1 = 2 * pr * rc / (pr + rc)
        if f1 > best_f1:
            best, best_f1, stats = leaf, f1, (pr, rc)
    # path root -> leaf
    parent = {}
    for i in range(t.node_count):
        if t.children_left[i] != -1:
            parent[t.children_left[i]] = (i, "<=")
            parent[t.children_right[i]] = (i, ">")
    bounds = {}
    node = best
    while node in parent:
        p, side = parent[node]
        f, thr = FEATURES[t.feature[p]], float(t.threshold[p])
        lo, hi = bounds.get(f, [None, None])
        if side == "<=":
            hi = thr if hi is None else min(hi, thr)
        else:
            lo = thr if lo is None else max(lo, thr)
        bounds[f] = [lo, hi]
        node = p
    conds = []
    for f in FEATURES:
        if f in bounds:
            lo, hi = bounds[f]
            if lo is not None:
                conds.append(dict(f=f, op=">", v=round(lo, 2)))
            if hi is not None:
                conds.append(dict(f=f, op="<=", v=round(hi, 2)))
    out = evaluate_rule(conds, margin, loss, S)
    out.update(precision=stats[0], recall=stats[1], selected=int(sel.sum()))
    return out


def twins(row, k=10, pool="auto", S=None):
    """Counterfactual twins: nearest applicants on the standardised bureau attributes, taken from
    the opposite population (booked <-> not booked)."""
    S = S or load()
    df = S["df"]
    row = int(row)
    if pool == "auto":
        pool = "NB_BUR" if S["bk"][row] else "BK"
    idx = S["pools"][pool]
    # Exact nearest neighbours: Euclidean distance to every applicant of the pool.
    dist = np.sqrt(((S["X"][idx] - S["X"][row]) ** 2).sum(axis=1))
    near = np.argsort(dist, kind="stable")[:int(k) + 1]
    nb_rows = [int(idx[i]) for i in near if int(idx[i]) != row][:int(k)]
    d = {int(idx[i]): float(dist[i]) for i in near}

    def rec(r):
        y = S["bad_int"][r] if S["bk"][r] else (S["bad_bur"][r] if S["has_bur"][r] else None)
        return dict(row=r, app_id=str(df["app_id"].values[r]), seg=S["seg"][r],
                    decline_rule=df["decline_rule"].values[r], bad=y, map_pos=int(S["map_pos"][r]),
                    p_kgb=df["p_kgb"].values[r] if "p_kgb" in df.columns else None,
                    score_12m=df["score_12m"].values[r] if "score_12m" in df.columns else None,
                    values={f: df[f].values[r] for f in FEATURES})

    me = rec(row)
    tw = []
    for r in nb_rows:
        x = rec(r)
        x["dist"] = d.get(r)
        tw.append(x)
    zdiff = (S["X"][nb_rows].mean(axis=0) - S["X"][row]) if nb_rows else np.zeros(len(FEATURES))
    order = np.argsort(-np.abs(zdiff))
    diffs = [dict(f=FEATURES[j], label=LABELS[FEATURES[j]], z=float(zdiff[j]),
                  me=df[FEATURES[j]].values[row],
                  twins=float(np.nanmean(df[FEATURES[j]].values[nb_rows]))) for j in order[:8]]
    ys = [t["bad"] for t in tw if t["bad"] is not None and t["bad"] == t["bad"]]
    rules = {}
    for t in tw:
        if t["decline_rule"]:
            rules[t["decline_rule"]] = rules.get(t["decline_rule"], 0) + 1
    return dict(me=me, twins=tw, diffs=diffs, pool=pool, n_known=len(ys),
                n_good=int(sum(1 for v in ys if v == 0)), n_bad=int(sum(1 for v in ys if v == 1)),
                rules=rules)


# ───────────────────────────── strategy tree export ─────────────────────────────
def _leaf(nid, name, mode, reasons=None):
    return {"id": nid, "name": name, "calcs": [], "split": None, "children": [],
            "leaf": {"mode": mode, "score_expr": "", "approve_at": None, "refer_at": None,
                     "reason_codes": list(reasons or []), "pricing_tier": "", "limit_expr": "", "outputs": []}}


def policy_tree(conds=None):
    """Champion policy as a rule-split tree; with ``conds`` the challenger carve-out is inserted
    right after the bankruptcy knock-out, so those applicants are approved before the other rules."""
    rules, kids, i = [], [], 2
    for rid, col, op, thr, lab in POLICY:
        rules.append("%s %s %s" % (col, op, _fmt(thr)))
        kids.append(_leaf("n%d" % i, lab, "decline", [rid]))
        i += 1
        if rid == "R1" and conds:
            # Only applicants a later rule would decline land in this leaf, so the leaf's volume and
            # event rate are exactly the swap-in set the Explorer reported.
            fails = " or ".join("%s %s %s" % (p[1], p[2], _fmt(p[3])) for p in POLICY if p[0] != "R1")
            box = " and ".join("%s %s %s" % (c["f"], c["op"], _fmt(c["v"])) for c in conds)
            rules.append("(%s) and %s" % (fails, box))
            kids.append(_leaf("n%d" % i, "Swap-in carve-out", "approve", ["CHALLENGER_SWAP_IN"]))
            i += 1
    kids.append(_leaf("n%d" % i, "Passes policy", "approve"))
    return {"id": "n1", "name": "All applications", "calcs": [],
            "split": {"kind": "rule", "rules": rules, "source": "manual"}, "children": kids, "leaf": None}


def tree_doc(name, conds, margin, loss, status="draft"):
    import datetime
    return {"type": TREE_FORMAT,
            "meta": {"name": name, "version": 1, "status": status, "dataset": _S.get("dataset", DATASET),
                     "score_col": "p_kgb", "target": "bad_obs"},
            "tree": policy_tree(conds), "display": {}, "settings": {"margin": margin, "loss": loss},
            "saved_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "saved_by": "reject_inference_explorer"}


def export_tree(name, conds, margin, loss):
    """Write the champion policy plus the swap-in rule as a strategy tree: <strategy dir>/trees/NAME.json."""
    import re
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "")).strip("_.").upper() or "CHALLENGER"
    folder = os.path.join(strategy_dir(), "trees")
    os.makedirs(folder, exist_ok=True)
    doc = tree_doc(name, conds, margin, loss)
    with open(os.path.join(folder, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return dict(name=name, path="/trees/%s.json" % name, rules=doc["tree"]["split"]["rules"])


# ───────────────────────────── Flask routes ─────────────────────────────
def register(app):
    from flask import jsonify, request

    def wrap(fn):
        def inner(*a, **k):
            try:
                return jsonify(_clean(dict(ok=True, **fn(*a, **k))))
            except Exception as e:  # surfaced in the UI
                return jsonify(dict(ok=False, error=str(e), trace=traceback.format_exc())), 200
        inner.__name__ = fn.__name__
        return inner

    def body():
        return request.get_json(silent=True) or {}

    def ml(b):
        return float(b.get("margin", 350)), float(b.get("loss", 4200))

    @app.route("/api/init", methods=["POST"])
    @wrap
    def api_init():
        b = body()
        S = load(force=bool(b.get("reload")))
        margin, loss = ml(b)
        df = S["df"]
        r = S["map_idx"]
        y = np.where(S["bk"][r], S["bad_int"][r], np.where(S["has_bur"][r], S["bad_bur"][r], np.nan))
        pts = dict(row=r, x=S["map_xy"][:, 0], y=S["map_xy"][:, 1], seg=S["seg"][r].tolist(), bad=y,
                   rule=[d[:2] for d in df["decline_rule"].values[r]])
        for c in ("p_kgb", "p_hc", "p_pcl", "p_fz", "bad_hc", "bad_pcl", "bad_fz", "bureau_score", "dti_pct"):
            if c in df.columns:
                pts[c] = np.round(df[c].values[r].astype(float), 4)
        return dict(points=pts, dataset=S["dataset"], dataset_type=S["dataset_type"], overview=overview(margin, loss, S), methods=methods(S), frontier=frontier(S),
                    features=[dict(f=f, label=LABELS[f]) for f in FEATURES],
                    policy=[dict(rule=p[0], column=p[1], op=p[2], thr=p[3], label=p[4]) for p in POLICY])

    @app.route("/api/overview", methods=["POST"])
    @wrap
    def api_overview():
        return overview(*ml(body()))

    @app.route("/api/twins", methods=["POST"])
    @wrap
    def api_twins():
        b = body()
        return twins(b["row"], b.get("k", 10), b.get("pool", "auto"))

    @app.route("/api/sweep", methods=["POST"])
    @wrap
    def api_sweep():
        return sweep(*ml(body()))

    @app.route("/api/bump", methods=["POST"])
    @wrap
    def api_bump():
        b = body()
        m, l = ml(b)
        return bump_hunt(m, l, float(b.get("alpha", 0.08)), float(b.get("min_support", 0.03)))

    @app.route("/api/lasso", methods=["POST"])
    @wrap
    def api_lasso():
        b = body()
        m, l = ml(b)
        return lasso_rule(b["positions"], m, l)

    @app.route("/api/rule", methods=["POST"])
    @wrap
    def api_rule():
        b = body()
        m, l = ml(b)
        return evaluate_rule(b["conds"], m, l)

    @app.route("/api/export", methods=["POST"])
    @wrap
    def api_export():
        b = body()
        m, l = ml(b)
        return export_tree(b.get("name"), b.get("conds") or None, m, l)
