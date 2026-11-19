"""Synthetic through-the-door population for reject inference with bureau data.

All data is made up. Writes four CSVs shaped like a lender's sources:
  applications.csv        one row per application, champion decision, booked flag
  bureau_attributes.csv   bureau attributes at application
  booked_performance.csv  internal 12m bad flag, booked accounts only
  bureau_performance.csv  off-us bureau performance, not-booked applicants who
                          opened a similar trade elsewhere
Pure standard library so it runs anywhere.
"""
import csv
import math
import os
import random
from datetime import date, timedelta

N = 20000
SEED = 20261116
rng = random.Random(SEED)
OUT = os.path.dirname(os.path.abspath(__file__))


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def sig(x):
    return 1.0 / (1.0 + math.exp(-clip(x, -30, 30)))


def pois(lam):
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


STATES = ["TX", "CA", "FL", "NY", "IL", "GA", "OH", "NC", "PA", "AZ"]
CHANNELS = ["DIGITAL", "BRANCH", "PARTNER", "DIRECT_MAIL"]
PRODUCTS = ["PERSONAL_LOAN", "CREDIT_CARD"]

apps, attrs, booked_perf, bur_perf = [], [], [], []
start = date(2024, 1, 1)

for i in range(N):
    app_id = "A%06d" % (i + 1)
    z = rng.gauss(0, 1)  # latent risk, higher = riskier

    bureau_score = int(clip(685 - 62 * z + rng.gauss(0, 28), 350, 850))
    util = round(clip(36 + 17 * z + rng.gauss(0, 16), 0, 100), 1)
    dti = round(clip(31 + 6 * z + rng.gauss(0, 10), 2, 80), 1)
    inq = pois(math.exp(0.25 + 0.40 * z))
    delq = pois(math.exp(-1.5 + 0.85 * z))
    coll = pois(math.exp(-2.4 + 0.80 * z))
    bk = 1 if rng.random() < sig(-4.3 + 1.0 * z) else 0
    age = round(clip(9.5 - 1.8 * z + rng.gauss(0, 3.5), 0.3, 35), 1)
    trades = max(0, pois(clip(7.5 - 0.8 * z, 1, 14)))
    thin = 1 if trades <= 2 else 0
    bankcards = min(trades, pois(clip(3.2 - 0.3 * z, 0.5, 8)))
    mos_file = int(clip(age * 12 * (1.6 + rng.random() * 0.8), 6, 600))
    pct_never_dq = round(clip(96 - 9 * max(z, -1) - 6 * delq + rng.gauss(0, 4), 30, 100), 1)
    mos_recent_dq = "" if delq == 0 and rng.random() < 0.85 else int(clip(rng.expovariate(1 / 14.0), 1, 84))
    income = round(clip(math.exp(8.55 - 0.12 * z + rng.gauss(0, 0.42)), 1500, 30000), 0)
    rev_bal = round(max(0, income * (0.4 + util / 55.0) * (0.6 + rng.random())), 0)
    inst_bal = round(max(0, rng.gauss(14000, 9000) + 2500 * z), 0)
    max_limit = round(clip(income * (1.9 - 0.45 * z + rng.gauss(0, 0.5)), 500, 60000), 0)
    mortgage = 1 if rng.random() < sig(-0.4 - 0.6 * z) else 0
    util_trend = round(rng.gauss(1.5 * z, 7), 1)
    emp_mos = int(clip(rng.expovariate(1 / 55.0) - 8 * z, 0, 420))
    amount = round(clip(rng.gauss(12000, 6000), 1000, 40000), -2)
    pti = round(clip(amount * 0.032 / income * 100, 0.5, 40), 1)

    # True default propensity (identical on-us and off-us apart from a shift).
    logit = (-2.75
             - 0.0105 * (bureau_score - 685)
             + 0.014 * (util - 36)
             + 0.020 * (dti - 31)
             + 0.11 * inq
             + 0.38 * delq
             + 0.30 * coll
             + 0.85 * bk
             - 0.030 * (age - 9.5)
             - 0.0035 * (emp_mos - 55)
             + 0.012 * util_trend)
    # Planted pockets of creditworthy applicants the champion policy declines.
    pocket = ""
    if 610 <= bureau_score < 660 and util < 40 and delq == 0 and emp_mos >= 36:
        logit -= 1.35
        pocket = "NEAR_PRIME_STABLE"
    elif dti > 45 and income >= 7000 and util < 35 and bureau_score >= 680:
        logit -= 1.10
        pocket = "HIGH_DTI_AFFLUENT"
    p_bad = sig(logit)

    # Champion policy (first rule that fires).
    if bk == 1:
        reason = "R1_BANKRUPTCY"
    elif bureau_score < 660:
        reason = "R2_SCORE_LT_660"
    elif dti > 45:
        reason = "R3_DTI_GT_45"
    elif delq >= 2:
        reason = "R4_DELQ_24M_GE_2"
    elif inq >= 6:
        reason = "R5_INQ_6M_GE_6"
    else:
        reason = ""
    decision = "DECLINE" if reason else "APPROVE"
    if decision == "DECLINE" and reason != "R1_BANKRUPTCY" and rng.random() < 0.04:
        decision, reason = "APPROVE", "OVERRIDE"  # low-side overrides

    booked = 0
    if decision == "APPROVE":
        booked = 1 if rng.random() < sig(0.45 + 0.45 * z) else 0  # adverse selection

    d = start + timedelta(days=rng.randrange(366))
    apps.append([app_id, d.isoformat(), rng.choice(PRODUCTS), rng.choice(CHANNELS),
                 rng.choice(STATES), amount, income, emp_mos, pti, decision, reason, booked])
    attrs.append([app_id, bureau_score, util, dti, inq, delq, coll, bk, age, trades, bankcards,
                  thin, mos_file, pct_never_dq, mos_recent_dq, rev_bal, inst_bal,
                  max_limit, mortgage, util_trend])

    if booked:
        bad = 1 if rng.random() < p_bad else 0
        booked_perf.append([app_id, bad, [0, 30][rng.random() < 0.12] if not bad else rng.choice([60, 90, 120])])
    else:
        if decision == "APPROVE":
            p_open = 0.80
        else:
            p_open = clip(sig(0.55 - 0.85 * z) + (0.25 if pocket else 0), 0.05, 0.92)
        if rng.random() < p_open:
            bad = 1 if rng.random() < sig(logit + 0.20) else 0
            dpd = rng.choice([60, 90, 120]) if bad else (30 if rng.random() < 0.12 else 0)
            v12 = int(clip(bureau_score + rng.gauss(6, 22) - (75 if bad else 0), 300, 850))
            bur_perf.append([app_id, int(clip(rng.expovariate(1 / 25.0) + 3, 1, 90)),
                             rng.choice(["BANK", "FINTECH", "CREDIT_UNION", "FINANCE_CO"]),
                             dpd, bad, v12])


def write(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(name, len(rows))


write("applications.csv",
      ["app_id", "app_date", "product", "channel", "state", "req_amt", "income_mo",
       "emp_mos", "pti_pct", "decision", "decline_rule", "booked"], apps)
write("bureau_attributes.csv",
      ["app_id", "bureau_score", "util_pct", "dti_pct", "inq_6m", "delq_24m", "coll_cnt",
       "bk_flag", "credit_age_yrs", "open_trades", "bankcards", "thin_file", "mos_on_file",
       "pct_never_delq", "mos_since_delq", "rev_bal", "inst_bal", "max_limit",
       "mortgage_flag", "util_trend_6m"], attrs)
write("booked_performance.csv", ["app_id", "bad_int", "worst_dpd_12m"], booked_perf)
write("bureau_performance.csv",
      ["app_id", "days_to_open", "lender_type", "worst_dpd_12m_bur", "bad_bur", "score_12m"],
      bur_perf)

# quick sanity summary
ap = {a[0]: a for a in apps}
bp = {b[0]: b[1] for b in booked_perf}
up = {b[0]: b[4] for b in bur_perf}
n_app = sum(1 for a in apps if a[9] == "APPROVE")
n_bk = sum(a[11] for a in apps)
print("approve rate %.3f  booked %d  booked bad rate %.3f" % (n_app / N, n_bk, sum(bp.values()) / len(bp)))
anb = [k for k in up if ap[k][9] == "APPROVE"]
dec = [k for k in up if ap[k][9] == "DECLINE"]
print("ANB w/ trade %d bad %.3f | declined w/ trade %d bad %.3f | declined total %d" % (
    len(anb), sum(up[k] for k in anb) / len(anb), len(dec), sum(up[k] for k in dec) / len(dec), N - n_app))
at = {a[0]: a for a in attrs}
pk = [k for k in dec if 610 <= at[k][1] < 660 and at[k][2] < 40 and at[k][5] == 0 and ap[k][7] >= 36]
print("pocket declined w/ trade %d bad %.3f" % (len(pk), sum(up[k] for k in pk) / max(1, len(pk))))
