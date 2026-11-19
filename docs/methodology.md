# Methodology

All figures quoted here come from the synthetic sample (`data/generate_data.py`, default seed). They illustrate the method. They are not findings about a real portfolio.

## 1. The question

A lender observes repayment only on the accounts it booked. Two questions follow.

1. **Modelling.** How do we build a score for everyone who applies when the bad flag exists only for booked accounts?
2. **Strategy.** Which applicants did the policy turn away who would have been good customers, and what rule lets them in without raising the bad rate?

For not-booked applicants who opened a similar trade with another lender, a credit bureau shows how that trade performed. That turns the second question from a guess into a measurement.

## 2. Populations and outcomes

| Code | Population | Outcome available |
|---|---|---|
| `BK` | Booked | Internal 12-month bad flag `bad_int` |
| `ANB` | Approved, not booked | Bureau flag `bad_bur`, when a trade was opened elsewhere |
| `DEC` | Declined | Bureau flag `bad_bur`, when a trade was opened elsewhere |

`has_bur = 1` marks a not-booked applicant with a bureau outcome. `bad_obs` is the best observed outcome: `bad_int` for booked, `bad_bur` when `has_bur = 1`, empty otherwise.

The sample policy declines on the first rule that fires: bankruptcy on file, bureau score < 660, debt-to-income > 45%, two or more delinquencies in 24 months, six or more inquiries in 6 months.

## 3. Reject inference

**Booked-only (KGB) model.** A logistic regression on booked accounts with target `bad_int`:

```
z = b0 + b1*x1 + ... + bk*xk
p_kgb = 1 / (1 + exp(-z))
```

No class weighting is used, so `p_kgb` stays a calibrated probability. The model has never seen a declined applicant: below the policy cuts it extrapolates.

**Three ways to give a not-booked applicant an outcome.** Booked accounts always keep their real outcome.

| Method | Rule | Assumption |
|---|---|---|
| Hard cutoff | bad if `p_kgb >= hc_cut` (0.20) | A probability can be treated as a certainty. |
| Parceling | Score bands with upper edges 2, 4, 6, 9, 13, 20, 30, 45%. Bad with probability `min(1, pcl_mult x r_band)`, where `r_band` is the booked bad rate of the band (the applicant's own `p_kgb` if the band has fewer than 30 booked accounts) and `pcl_mult` is 1.5. | Rejects are worse than booked accounts with the same score, by that multiplier. |
| Fuzzy augmentation | Two training rows: bad with weight `p_kgb`, good with weight `1 - p_kgb`. | `p_kgb` is right on average for rejects. |

A final logistic regression is trained on the whole population for each method. For fuzzy augmentation it maximises a weighted log-likelihood:

```
L(b) = sum_i  w_i * [ y_i * log(p_i) + (1 - y_i) * log(1 - p_i) ]
```

**Grading.** The bureau outcome is never used for training, so each method can be compared with what happened. In the sample, among not-booked applicants with a bureau trade, 14.2% went bad; hard cutoff labels 23.7%, parceling 20.9%, and the fuzzy weights sum to 14.3%. All models rank about equally well; they differ in the level of risk they assign to rejects, which is what drives cutoffs and pricing.

## 4. From bureau performance to "what would have happened with us"

**Off-us to on-us factor.** Approved-not-booked applicants passed the same policy as booked customers. Over score bands `b` with at least 30 of each:

```
f = sum_b n_b * BR_internal(b)  /  sum_b n_b * BR_bureau(b)
```

where `n_b` is the number of approved-not-booked applicants with a bureau outcome in the band. The result is limited to the range 0.5 to 1.5. The on-us equivalent of a bureau bad rate is `f x bureau bad rate`.

**Take-up** is booked divided by approved. It scales the profit of extra approvals.

**Economics.**

```
break-even = margin / (margin + loss)
profit     = n * take_up * ((1 - b) * margin - b * loss)
```

`n` is the number of extra approvals and `b` their on-us equivalent bad rate. With a margin of 350 and a loss of 4,200, break-even is 7.7%.

## 5. The similarity map

1. Take 22 numeric attributes (18 bureau attributes, requested amount, income, employment months, payment-to-income).
2. Fill missing values with the median, clip at the 1st and 99th percentile, standardise: `z = (x - mean) / sd`.
3. Draw a stratified sample (2,200 booked, 1,500 approved-not-booked, 2,600 declined).
4. Project to two dimensions with t-SNE (perplexity 40, PCA initialisation, fixed seed).

t-SNE converts distances in the 22-dimensional space into neighbour probabilities,

```
p(j|i) = exp(-d_ij^2 / 2 s_i^2) / sum_k exp(-d_ik^2 / 2 s_i^2)
```

with `s_i` tuned per applicant to a common effective number of neighbours (the perplexity). It then places points on the plane with similarities `q_ij` proportional to `1 / (1 + |y_i - y_j|^2)` and minimises `KL(P || Q) = sum p_ij * log(p_ij / q_ij)`.

The map keeps neighbours together. Its axes have no meaning, and distances between far-apart groups are not reliable. Nothing is computed from map coordinates: every rule, twin and statistic uses the original attributes.

## 6. Counterfactual twins

For one applicant, the twins are the 10 nearest applicants in the opposite population:

```
d(a, b) = sqrt( sum_j (z_a,j - z_b,j)^2 )     over the 22 attributes
```

- For a booked customer, the pool is not-booked applicants with a bureau outcome.
- For a not-booked applicant, the pool is booked customers.

The search covers the whole table, not only the map sample. The panel reports how many twins were good or bad, which recorded decline rule removed each twin, and the eight attributes where the twins' mean z differs most from the selected applicant.

## 7. Scoring a candidate rule

Every search produces candidate rules, and all of them go through one scorer.

1. **Members**: declined applicants, not bankrupt, who meet every condition.
2. **Bureau bad rate**: bads over members with a bureau outcome.
3. **On-us equivalent**: `f x bureau bad rate`.
4. **Profit**: the formula of section 4, with `n` equal to all members.
5. **New portfolio**: currently approved plus members. Its bad rate uses every known outcome, internal for booked and `f x bureau` for the rest.
6. **Holdout**: the same figures on a random 30% of applicants that the search never saw.

A rule clears break-even when its on-us equivalent is at or below `margin / (margin + loss)`.

## 8. Three searches

**Threshold sweep.** For one policy rule, keep only applicants declined by that rule alone. Relax the cut in steps. At each step score the marginal slice and the cumulative group. Recommend the furthest step for which every marginal slice so far is at or below break-even, each with at least 30 bureau outcomes.

**Bump hunting (PRIM).**

1. Start with a box holding every eligible declined applicant with a bureau outcome, outside the holdout.
2. For each attribute, try removing the lowest 8% or the highest 8% of what is still inside.
3. Keep the peel that leaves the highest share of good performers. A peel must leave at least 55% of the box and at least 3% of the starting population (minimum 40 applicants).
4. After each peel, release any edge the box does not need: if dropping a condition costs less than 1.2 points of good rate, drop it, widest release first.
5. Round thresholds to readable values and score the rule.

The result is a sequence of rules from large and risky to small and clean. The most profitable is preselected.

**Lasso to rule.** The analyst circles at least 15 points on the map. A decision tree (depth 3, balanced classes, leaves of at least 8% of the selection) separates circled from not-circled points on the original attributes. The leaf with the highest F1 is read as an if/else rule and scored.

## 9. The frontier

For each model, sort applicants by score, approve the safest 30% up to 95% in steps of 2.5 points, and compute the bad rate on known outcomes among those approved. The current policy and the policy plus the selected rule are plotted as single points on the same chart.

## 10. From a rule to a strategy

"Send to Strategy Tree" writes `strategies/trees/NAME.json`: the current policy as a rule-split tree, with one approve branch inserted after the bankruptcy rule for applicants who fail a later rule and fall inside the box.

## 11. Limits

- **Selection in bureau outcomes.** Bureau performance exists only for applicants who obtained a trade elsewhere. They are likely better than declined applicants who obtained nothing.
- **The factor comes from approved applicants** and is applied to declined ones.
- **Product and terms.** A similar trade elsewhere may differ in amount, price and term.
- **Rule search can overfit.** The holdout guards against it, but the same data chooses among candidates. Validate on a later period, then run a controlled champion/challenger test.
- **First rule only.** `decline_rule` records the first rule that fired, not every rule an applicant fails.
- **Fair lending.** Any new rule needs a compliance review of the attributes it uses.
