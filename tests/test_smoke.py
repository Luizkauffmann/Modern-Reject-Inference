"""End-to-end smoke test on a small synthetic sample: pipeline, analytics and web API."""

import csv
import json
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sources(folder, n=3000, seed=7):
    """A small population with the same columns as data/generate_data.py."""
    rng = random.Random(seed)
    sig = lambda x: 1.0 / (1.0 + math.exp(-x))
    apps, attrs, booked, bureau = [], [], [], []
    for i in range(n):
        a, z = "A%06d" % i, rng.gauss(0, 1)
        score = int(max(350, min(850, 685 - 62 * z + rng.gauss(0, 28))))
        dti = round(max(2, min(80, 31 + 6 * z + rng.gauss(0, 10))), 1)
        delq = 1 if rng.random() < sig(-2 + z) else 0
        inq = int(max(0, round(1.3 + z + rng.gauss(0, 1))))
        bk = 1 if rng.random() < 0.02 else 0
        rule = "R1_BANKRUPTCY" if bk else "R2_SCORE_LT_660" if score < 660 else "R3_DTI_GT_45" if dti > 45 else ""
        decision = "DECLINE" if rule else "APPROVE"
        is_booked = 1 if decision == "APPROVE" and rng.random() < 0.55 else 0
        p_bad = sig(-2.75 - 0.0105 * (score - 685) + 0.02 * (dti - 31) + 0.38 * delq)
        apps.append([a, "2024-01-01", "PERSONAL_LOAN", "DIGITAL", "TX", 12000, 5000, 60, 7.7, decision, rule, is_booked])
        attrs.append([a, score, round(max(0, min(100, 36 + 17 * z + rng.gauss(0, 16))), 1), dti, inq, delq, 0, bk,
                      round(max(0.3, 9.5 - 1.8 * z + rng.gauss(0, 3.5)), 1), 7, 3, 0, 200, 95.0, "", 3000, 14000,
                      9000, rng.randint(0, 1), round(rng.gauss(0, 7), 1)])
        if is_booked:
            booked.append([a, 1 if rng.random() < p_bad else 0, 0])
        elif rng.random() < 0.6:
            bad = 1 if rng.random() < p_bad else 0
            bureau.append([a, 20, "BANK", 0, bad, score])

    def write(name, header, rows):
        with open(os.path.join(folder, name), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    write("applications.csv", ["app_id", "app_date", "product", "channel", "state", "req_amt", "income_mo",
                               "emp_mos", "pti_pct", "decision", "decline_rule", "booked"], apps)
    write("bureau_attributes.csv", ["app_id", "bureau_score", "util_pct", "dti_pct", "inq_6m", "delq_24m", "coll_cnt",
                                    "bk_flag", "credit_age_yrs", "open_trades", "bankcards", "thin_file",
                                    "mos_on_file", "pct_never_delq", "mos_since_delq", "rev_bal", "inst_bal",
                                    "max_limit", "mortgage_flag", "util_trend_6m"], attrs)
    write("booked_performance.csv", ["app_id", "bad_int", "worst_dpd_12m"], booked)
    write("bureau_performance.csv", ["app_id", "days_to_open", "lender_type", "worst_dpd_12m_bur", "bad_bur",
                                     "score_12m"], bureau)


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["RI_DATA_DIR"] = cls.tmp.name
        os.environ["RI_STRATEGY_DIR"] = os.path.join(cls.tmp.name, "strategies")
        _sources(cls.tmp.name)
        from reject_inference import explorer, pipeline
        import pandas as pd
        cls.explorer = explorer
        cls.df = pipeline.run(cls.tmp.name, with_map=False, log=lambda *_: None)
        # A map is only a display: random coordinates are enough to exercise the API.
        rng = random.Random(1)
        sample = cls.df["app_id"].iloc[:600]
        pd.DataFrame({"app_id": sample, "tx": [rng.random() for _ in sample],
                      "ty": [rng.random() for _ in sample]}).to_csv(os.path.join(cls.tmp.name, "ri_map.csv"), index=False)
        from app import app
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def post(self, path, body=None):
        r = self.client.post(path, data=json.dumps(body or {}), content_type="application/json")
        d = r.get_json()
        self.assertTrue(d["ok"], d.get("error"))
        return d

    def test_pipeline_columns(self):
        for c in ("seg", "has_bur", "p_kgb", "band", "bad_hc", "bad_pcl", "bad_fz", "p_hc", "p_pcl", "p_fz", "bad_obs"):
            self.assertIn(c, self.df.columns)
        self.assertTrue(self.df["p_kgb"].between(0, 1).all())
        booked = self.df["seg"] == "BK"
        self.assertTrue((self.df.loc[booked, "bad_hc"] == self.df.loc[booked, "bad_int"]).all())

    def test_init_and_breakeven(self):
        d = self.post("/api/init")
        self.assertAlmostEqual(d["overview"]["breakeven"], 350 / 4550.0)
        self.assertEqual(sum(s["n"] for s in d["overview"]["segments"]), len(self.df))

    def test_twins_come_from_the_other_population(self):
        d = self.post("/api/init")
        t = self.post("/api/twins", {"row": d["points"]["row"][0]})
        me_booked = t["me"]["seg"] == "BK"
        for x in t["twins"]:
            self.assertNotEqual(x["seg"] == "BK", me_booked)

    def test_rule_search_and_export(self):
        self.post("/api/sweep")
        b = self.post("/api/bump")
        self.assertTrue(b["steps"])
        rule = b["steps"][-1]
        scored = self.post("/api/rule", {"conds": rule["conds"]})
        self.assertEqual(scored["n"], rule["n"])
        e = self.post("/api/export", {"name": "test rule", "conds": rule["conds"]})
        path = os.path.join(os.environ["RI_STRATEGY_DIR"], "trees", e["name"] + ".json")
        with open(path) as f:
            self.assertEqual(json.load(f)["meta"]["name"], "TEST_RULE")


if __name__ == "__main__":
    unittest.main()
