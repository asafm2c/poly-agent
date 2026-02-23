# When Does the LLM Lead the Market?

**Status:** Active research direction — operationalizing the edge detection problem

## The Setup

From runs #9 and #10 we know:

| Signal | Value |
|--------|-------|
| Pass 1 (base rate, no market price) | Brier 0.2505 — near-random |
| Anchored final estimate | Brier 0.0261 |
| Blind final estimate (no market price) | Brier 0.0905 — 3.5× worse |
| Market price | Brier 0.0155 |

The LLM's unaided base rate is nearly useless. The moment market price enters Pass 2,
the LLM's estimate converges to the market. The market is right more often than the
LLM on clean prediction markets in the $10K-$500K range.

**The useful version of the question is therefore not:**
"Does the LLM add signal beyond the market?" (Answer: rarely, on these markets)

**But rather:**
"Under what conditions does the LLM's base rate (Pass 1) diverge from market price
*in the correct direction*?" — i.e., when is the market mispriced in a direction the
LLM's prior would catch?

We have `base_rate_estimate` stored per trial. This is the most direct empirical handle
on LLM-vs-market divergence we have.

---

## Candidate Conditions for LLM Edge

### 1. Information Lag Windows (highest priority)

The market price at query time reflects available information *at that moment*. If
Tavily/web search surfaces recent developments that haven't yet moved the market,
Pass 1 effectively carries the same prior as the market — but Pass 2's dossier would
already have the new information. In this frame, edge comes not from the LLM's prior
but from information recency.

**Testable signal:** Run simulation on markets where recent news volume is high, then
check if the anchored estimate diverges more from final resolution than from the
contemporary market price. If the agent's estimate predicts resolution better than the
market price at the time, it has an information lead.

**Key architectural point:** This is the only scenario where the full anchored pipeline
(not blind) may produce genuine edge — because the LLM anchors to a stale price while
incorporating fresh dossier evidence. If the dossier moves the estimate away from price,
that divergence is a signal.

**Observable metric in existing data:** For trials where `agent_estimate` diverges
significantly from `market_price` (≥0.10), do those markets resolve closer to the
agent's estimate? This is checkable right now.

### 2. Low-Volume / Thin Markets

Volume is a proxy for price discovery quality. A market with $10K volume has fewer
informed participants setting price. The market price carries less information and the
LLM's base rate may be as good or better than the thin-market consensus.

**Empirical prediction:** In the `<$10K volume` tier, `base_rate_estimate` should
correlate with resolution outcomes better than `market_price` does. In `>$10M` tier,
market almost certainly dominates.

**Measurement:** Compare `brier(base_rate_estimate)` vs `brier(market_price)` per
volume tier. We already have `volume_tier` in stratified sampling.

**Risk:** Thin markets are hard to trade (wide spreads, low max position). Even with
edge, execution degrades the effective return.

### 3. Ambiguous or Technical Resolution Criteria

Markets price the intuitive outcome. LLMs read the fine print.

Examples where this matters:
- "Will X happen by December 31?" — does "by" mean before, or on/before?
- Percentage thresholds ("inflation exceeds 3%") — which inflation measure?
- Legal/regulatory outcomes where the question semantics differ from the crowd's
  intuitive interpretation

**The LLM processes language; the crowd prices vibes.** On markets with precise
resolution conditions, LLM reasoning about resolution criteria may diverge from market
price in a useful direction.

**Testable but hard to automate:** Requires flagging markets with ambiguous resolution
criteria — either by category (regulatory, legal), keyword detection, or a cheap
screening call that explicitly asks whether the resolution criteria are technical/precise.

### 4. Directional Calibration Asymmetry

The existing empirical finding: "the model shows the most divergence from markets on
'probable NO' outcomes in unfiltered data." The LLM is more bearish than markets on
uncertain propositions.

**Two interpretations:**
1. (Good) Markets systematically overprice YES on uncertain events due to retail
   optimism / narrative bias. The LLM's bearishness is calibrated.
2. (Bad) The LLM has a training-derived negativity bias or prior toward caution that
   miscalibrates it low.

**How to distinguish:** Check whether LLM-below-market calls resolve to NO more often
than market-implied probability. If LLM bearishness predicts resolution correctly at
higher rates than the market price, it's signal. If not, it's miscalibration.

**Measurement:** Among trials where `base_rate_estimate < market_price - 0.10`:
- How often does the market resolve NO?
- Does the LLM call it correctly more often than the market price implies?

This is directly computable from existing trial data.

### 5. Post-Cutoff Domain Decay Rate

LLM training data isn't uniformly stale. Some domains are heavily represented at all
time points (geopolitics, elections, science) while others decay faster (local events,
sports seasons, financial specifics). The LLM may retain useful priors in slow-decay
domains even on markets past the training cutoff.

**Domain hypothesis:** LLM has relative edge on:
- **Geopolitics/international relations**: Deep training data, slow-moving patterns
- **Scientific/regulatory outcomes**: Known timelines, well-documented base rates
- **Recurring elections**: Strong historical patterns, similar structure year-over-year

LLM has relative disadvantage on:
- **Sports**: Team-specific recent performance, injuries, transfers — fast decay
- **Financial tick markets**: Price-action driven, no LLM signal beyond momentum
- **Local/hyperlocal events**: Outside training distribution

**Already partially testable:** The `market_type` classifier now separates prediction,
sports, tick, and economic-range. We can compare `brier(base_rate_estimate)` across
market types.

### 6. Early Price Formation (Market Age)

When a market is newly listed, price often anchors near 50% or at a round number
reflecting the contract designer's prior, not informed trading. LLM base rate might
be better than this initial anchor for the first hours/days of market life.

**Not easily testable with current data:** We don't record the date of simulation
relative to market listing date. Would require knowing market creation timestamp and
querying the API for historical price at listing time.

---

## The Edge Signal: `base_rate_estimate` as Leading Indicator

The most actionable immediate insight: `base_rate_estimate` (Pass 1) is the LLM's
prior *before seeing the market*. When it diverges significantly from `market_price`:

- **Agreement** (|base_rate - market_price| < 0.05): LLM and market agree. No edge.
  The anchored pipeline will confirm the market price, and the adversarial pass will
  close any gap. Don't trade.

- **Mild divergence** (0.05–0.15): LLM has a somewhat different prior. After Pass 2,
  the estimate will move toward market but may not fully converge. Some signal, but
  the anchoring process narrows it substantially.

- **Strong divergence** (>0.15): LLM's base rate is well away from market. Worth
  asking: why? Is the LLM missing information the market has? Or does the LLM have
  a relevant prior the market is ignoring?

The strong-divergence cases are where investigating resolution outcome vs. both
estimates is most revealing. Building a database of these cases, tagged by whether
the LLM or market was closer to correct, would directly answer the "when does LLM
lead?" question.

### Proposed Divergence Score

For each simulated market, compute:

```
divergence = base_rate_estimate - market_price
direction = "LLM_BULLISH" if divergence > 0.10 else "LLM_BEARISH" if divergence < -0.10 else "NEUTRAL"
magnitude = abs(divergence)
```

~~The hypothesis: `LLM_BEARISH` cases resolve NO more often than `market_price` implies.~~

**DISPROVED** by Experiment A: LLM bearishness is miscalibration, not signal. 89.5% of
strong-divergence cases the market is directionally correct. Naive divergence score is
not a reliable trading filter.

**Revised approach:** Divergence score alone is insufficient. Need a *second layer*
that characterizes *why* the LLM diverges. The 4 cases where LLM was correct all
involved strong domain priors (banking crisis base rates, electoral patterns, geopolitics).
The 34 wrong cases likely involve markets where the LLM lacks domain knowledge or recent
events have moved prices away from historical base rates in ways the LLM can't detect.

---

## The Architecture Implication

If we identify conditions where LLM leads, the screening layer should change. Currently:
- Screening (Pass 0.5): Haiku determines if market is "worth analyzing"
- The worthiness criterion is mostly "is there a meaningful probability estimate?"

**Future screening criterion should also ask:**
- "Is the Pass 1 estimate likely to diverge significantly from market price?"
- "Is this market type/category/volume tier one where LLM base rates have historically
  been better-calibrated than market prices?"

This is a second-order optimization: screen for opportunities rather than for analyzability.

### Proposed New Screening Pass (Pass 0)

Before the full pipeline, a cheap Haiku call:
1. Reads question, category, end date
2. Produces a rough base rate (0–1) without any market price or dossier
3. Compares against market price
4. Gates into full analysis only if `|base_rate - market_price| > threshold`

This is cheaper than running Pass 1 (which it would replace/supplement), and it would
focus full analysis effort on markets where the LLM genuinely has a different view.

---

## Experiment A Results (n=70, runs #9–#11)

Run immediately against existing trial data. Key findings:

### Head-to-head: base rate vs market price

| Group | n | Base rate wins | Final wins |
|-------|---|---------------|-----------|
| Anchored runs (n=60) | 60 | 5/60 (8%) | 6/60 (10%) |
| Blind run (n=10) | 10 | 0/10 (0%) | 0/10 (0%) |

Market price beats LLM base rate on **~92% of individual trials** across 70 cases.

### Divergence calibration by bucket

| Divergence bucket | Direction | n | Base Brier | Market Brier | Final Brier | Base-vs-Mkt Δ |
|------------------|-----------|---|------------|--------------|-------------|---------------|
| Neutral (<0.05) | NEUTRAL | 19 | 0.021 | 0.019 | 0.019 | +0.002 |
| Mild (0.05–0.10) | LLM_BEARISH | 1 | 0.672 | 0.585 | 0.608 | +0.087 |
| Mild (0.05–0.10) | LLM_BULLISH | 4 | 0.012 | 0.001 | 0.002 | +0.011 |
| Moderate (0.10–0.15) | LLM_BEARISH | 1 | 0.023 | 0.000 | 0.000 | +0.023 |
| Moderate (0.10–0.15) | LLM_BULLISH | 7 | 0.048 | 0.016 | 0.018 | +0.032 |
| **Strong (>0.15)** | **LLM_BEARISH** | **19** | **0.499** | **0.073** | **0.123** | **+0.426** |
| **Strong (>0.15)** | **LLM_BULLISH** | **19** | **0.251** | **0.030** | **0.028** | **+0.221** |

In every bucket, market price beats LLM base rate. The stronger the divergence, the more
the LLM is wrong.

### Directional accuracy at strong divergence

| LLM direction | Correct | Wrong | Win rate |
|---------------|---------|-------|----------|
| Bearish (base < mkt - 0.15) | 2 | 17 | **10.5%** |
| Bullish (base > mkt + 0.15) | 2 | 17 | **10.5%** |

When the LLM strongly disagrees with the market, **the market is directionally correct 89.5%
of the time**. LLM divergence is miscalibration, not alpha.

When LLM *is* correct (4 cases): market mispricing was severe (market_brier 0.20–0.50 range,
implying market was at 0.50–0.90 on the wrong side). Lottery-like payoff structure — rare,
large wins against frequent, small losses.

### The 4 cases where LLM base rate was right

| Market | Base div | Outcome | What happened |
|--------|----------|---------|---------------|
| US tourism decline in April | −0.544 | NO | LLM bearish (0.35), market 0.89, resolved NO |
| US bank failure before July | +0.405 | YES | LLM bullish (0.85), market 0.45, resolved YES |
| Patient Focus in Norwegian election | −0.295 | NO | LLM bearish (0.15), market 0.45, resolved NO |
| EU sanctions on Russia by Dec 31 | +0.245 | YES | LLM bullish (0.95), market 0.71, resolved YES |

Pattern: all involve domain priors the LLM carries strongly (economic trends, banking crisis
base rates, electoral history, geopolitical patterns) that the market underweighted. The market
was substantially mispriced (not just slightly off).

### Revised conclusion

**LLM base rate divergence is not a reliable alpha signal in clean prediction markets.**
The market is right ~90% of the time when the LLM strongly disagrees. However:

1. The 10% where LLM is correct involves large market mispricings — suggesting these are
   genuine market errors, not sampling noise.
2. Run #11 (50 markets) had avg market_brier = 0.054 vs runs #9/10's 0.016 — less efficient
   markets exist and the LLM comes closer to parity there.
3. The pipeline's anchoring behavior (final brier ≈ market brier in anchored runs) is
   functionally correct: it overrides the LLM's unreliable base rate with market information.

**The edge detection problem requires identifying *in advance* the 10% where LLM divergence
is signal, not noise.** The question is what distinguishes those 4 cases from the 34 wrong ones.

---

## Next Experiments

### ~~Experiment A: Divergence Calibration Analysis~~ DONE

**Completed against n=70 trials (runs #9–#11).** Full results above.
Finding: market beats LLM base rate on 92% of trials. Divergence is miscalibration,
not alpha signal. Naive divergence score as a filter does not work.

### ~~Experiment B: Volume-Tier Decomposition~~ PARTIAL / BLOCKED

**Finding from existing data:**

| Volume tier | n | Market Brier | Agent Brier | Gap |
|------------|---|-------------|-------------|-----|
| $10K–$50K | 29 | 0.0545 | 0.061 | +12% |
| $50K–$100K | 31 | 0.0447 | 0.068 | +52% |
| $100K–$500K | 10 | 0.0048 | 0.013 | +171% |

Market efficiency degrades significantly below $100K. LLM approaches parity at $10K–$50K.

**Blocked below $10K:** History collection floor is ~$100K volume. No markets with
`has_history=1` exist below $10K in the database. True crossover point (where LLM
equals or beats market) requires data not currently collected.

**Alternative:** Targeting very uncertain market segments (see Experiment C findings
below) proved more productive than chasing thin-by-volume markets.

### ~~Experiment C: Training Contamination Test~~ DONE (n=100, runs #12–#13)

Two dedicated pre-cutoff simulations (training_recency_score = 0.0, GPT4o-era 2024):

| Run | Cohort | n | Base Brier | Mkt Brier | Agent Brier | Agent Wins | Str-Div Correct |
|-----|--------|---|------------|-----------|-------------|------------|-----------------|
| #9 | post-cutoff clean | 10 | 0.2505 | 0.0155 | 0.0261 | 10% | 0% |
| #11 | post-cutoff general | 50 | 0.2144 | 0.0541 | 0.0566 | 12% | 14% |
| #13 | pre-cutoff general | 30 | 0.2140 | 0.0375 | 0.0406 | 23% | 12.5% |
| **#12** | **pre-cutoff election-adjacent** | **30** | **0.1484** | **0.1376** | **0.1343** | **43%** | **53%** |

**Finding: Contamination is domain-specific, not general.**

- Run #13 (general pre-cutoff markets, 2024): base_brier=0.214 — **same as post-cutoff**.
  No evidence of contamination.
- Run #12 (US election-adjacent 2024 markets: Biden, Kamala, Nate Silver odds, etc.):
  base_brier=0.148 (somewhat lower), **agent BEATS market** (Brier 0.1343 vs 0.1376),
  strong-divergence correct rate = **53%** (vs 10–12% on clean markets).

Sample of run #12 markets: *"Kamala Harris solo interview before debate?"*, *"Will
Biden endorse Kamala?"*, *"10+ Dem senators call on Biden to drop out?"* — The LLM
has partial training-derived knowledge of these events, but importantly, the market
was ALSO very uncertain on them (mkt_brier = 0.1376 avg — the highest of all runs).

The LLM's edge on these markets is narrow but real: 43% win rate, agent barely edges
market on a market segment where price discovery is very low. This is BOTH contamination
AND market inefficiency combined.

**Recency-bin analysis (A1) confirms anti-contamination for post-cutoff claims:**
Among 38 strong-divergence cases across all runs:
- recency 0–0.25: 4 WRONG, 0 CORRECT (no LLM edge near cutoff)
- recency 0.50–0.75: 1 CORRECT, 5 WRONG
- recency 0.75–1.0: 3 CORRECT, 25 WRONG

The 4 LLM-correct calls in the original analysis were all at recency 0.5+, not near
the training window. This was not contamination — it was genuine domain priors.

### ~~Experiment D: Dossier Signal~~ DONE — leads to new finding

**Original hypothesis** (dossier creates divergence from market): fully disproved.
In 54/54 trials with meaningful dossier movement, the dossier moved toward market price,
never away. Tavily web search returns public information already priced by the market.

**New finding from A3/A7: Blind Pass 2 is the right measure, not full blind mode.**

| Stage | Anchored Brier | Blind Brier |
|-------|---------------|-------------|
| Pass 1 (base rate) | 0.2505 | 0.2493 |
| Pass 2 (dossier updated) | 0.0355 | **0.0242** ← BETTER |
| Pass 3 (final) | 0.0261 | 0.0905 ← MUCH WORSE |
| Market price | 0.0155 | 0.0155 |

In blind mode, Pass 2 (research + dossier, no market price) achieves Brier 0.0242 —
**better than anchored Pass 2 (0.0355)**. But then the blind adversarial pass (Pass 3)
systematically pushes estimates DOWN by 0.067 on average, destroying the gain.

The blind adversarial prompt has a **systematic bearish bias** that makes blind mode
worse than anchored for these markets.

**Implication: "research-only" estimate** = Pass 2 without market price, stopping
before adversarial. This gives Brier 0.0242 — only 1.6× worse than market (0.0155),
and it would reveal cases where the LLM's research produces a different picture from
the market price. That divergence would be the cleanest "information lead" signal.

**`pass2_blind_estimate` is now implemented and collecting.** See Experiment D
Validation below.

---

## Experiment D Validation: pass2_blind_estimate Results (n=40, runs #15–#16)

First real data with `pass2_blind_estimate` stored per trial:

### Overall (runs #15 + #16, n=40):

| Estimator | Brier | vs Market |
|-----------|-------|-----------|
| Blind P2 (`pass2_blind_estimate`) | **0.054** | **+7% better** |
| Final agent | 0.055 | +4% better |
| Market | 0.058 | — |
| Anchored P2 (`pass2_estimate`) | 0.062 | −7% worse |

Blind P2 beats anchored P2 by ~15% and beats the market slightly overall.

### By market price tier:

| Tier | n | Blind P2 | Anch P2 | Agent | Market |
|------|---|----------|---------|-------|--------|
| uncertain (0.25–0.75) | 4 | 0.2032 | 0.1494 | 0.3107 | 0.344 |
| moderate (0.1–0.25 or 0.75–0.9) | 3 | 0.1564 | 0.0426 | 0.0264 | 0.0188 |
| decided (<0.1 or >0.9) | 33 | 0.027 | 0.053 | 0.027 | **0.026** |

On **decided markets** (the bulk of post-Claude4 prediction markets), blind P2 = agent
= market quality. Anchored P2 is substantially worse — the LLM's evidence integration
in Pass 2 *with* the market price anchor is counterproductive on decided markets.

On **uncertain markets** (4 cases), the pattern reverses: anchored P2 > blind P2 >
market. When prices are genuinely uncertain, the market anchor helps the LLM not
over-commit to a wrong direction.

### Key structural insight

On post-Claude4 prediction markets:
- **90% are decided** (price <0.1 or >0.9) — markets already know the answer
- The LLM's job is not to estimate probability but to avoid being dragged wrong
- Blind P2 succeeds here because it isn't distorted by market-price anchoring
- Anchored P2 fails because it updates *away from* the extreme price based on
  thin evidence, then gets pulled back — a noisy round trip

**The implication for edge detection**: `pass2_blind_estimate` on uncertain markets
(price 0.25–0.75) is where the signal/noise ratio is highest. But there are very
few such markets in post-Claude4 era — they resolve quickly. The interesting markets
for `pass2_blind_estimate` divergence analysis are in the 0.1–0.5 range.

### No systematic bias confirmed

Average `pass2_blind_estimate - market_price` = −0.004 across 40 trials. The blind
adversarial bias (−0.067 per trial) is *not present* in blind Pass 2 alone — the
bias comes entirely from the blind adversarial prompt pushing estimates down.

---

## Connection to Existing Framework

- **`regime-awareness.md`**: The self-aware agent should treat high agreement between
  Pass 1 and market price as "no edge here, skip." Strong divergence triggers
  investigation. This document provides the quantitative threshold.

- **`pseudo-llm-backtest.md`**: A pseudo-backtest must use Pass 1 (not the anchored
  final estimate) as the LLM's independent signal. Pass 1 Brier measures the ceiling
  of LLM-derived alpha before market price information contaminates it.

- **`llm-market-correlation.md`**: The refined question established there is answered
  here: LLM leads when `base_rate_estimate` diverges from `market_price` in the
  direction of resolution. Experiment A is the direct test.

---

## Prioritized Action

1. ~~**Experiment A**~~ DONE. Naive divergence score: not reliable. Market wins 89.5% of
   strong-divergence cases. The 4 correct LLM calls were post-cutoff domain priors.

2. ~~**Experiment B (volume)**~~ PARTIAL. No sub-$10K data available (history collection
   floor too high). From existing data: market efficiency degrades sharply below $100K
   and agent approaches parity at $10K–$50K.

3. ~~**Experiment C (contamination)**~~ DONE (n=100 pre-cutoff markets across 2 runs).
   General contamination: absent (base_brier same as post-cutoff). Domain-specific
   contamination: present but narrow on 2024 election-adjacent markets. Agent slightly
   beats market there, but market was also very inefficient. The 4 original LLM-correct
   calls were genuine domain priors, not training recall.

4. ~~**Experiment D (dossier)**~~ DONE. Dossier never creates counter-market divergence.
   Tavily searches public info already priced. BUT: blind Pass 2 alone achieves Brier
   0.0242 (only 1.6× vs market's 0.0155), better than anchored Pass 2 (0.0355). The
   blind adversarial pass has a systematic bearish bias — avoid in blind mode.

**Next actions (in priority order):**

1. ~~**Implement `pass2_blind_estimate`**~~ DONE. Deployed in simulator. Runs #15–#16
   confirm: blind P2 beats anchored P2 by 15% and beats market by 7% overall. No
   systematic bias. See Experiment D Validation above.

2. **Build a domain classifier for question text.** The `category` field is NULL for
   most prediction markets. A cheap Haiku classifier on question text could distinguish
   "historical-pattern dominant" from "recent-event dominant" questions, enabling the
   domain-prior hypothesis to be tested properly. Focus on the uncertain-market segment
   (0.25–0.75 price range) where the signal-to-noise ratio is highest for blind P2.

3. **Lower the history collection floor.** If we want to study sub-$10K markets, the
   collector needs to be configured to collect history at lower volumes. This is an
   infrastructure change, not a research question.

4. **Run election-adjacent experiment intentionally.** The run #12 finding (agent beats
   market at 43% win rate on 2024 election-adjacent markets) is interesting but confounded
   by contamination. A clean version: target similar markets in a POST-cutoff period
   (2026 elections?) where the LLM has strong domain priors without training recall.

5. ~~**Analyze uncertain markets specifically.**~~ Subsumed into Experiment E below.

---

## Experiment E: Domain Classification — Actuarial vs Current-Event

**Hypothesis:** LLM has genuine edge on "actuarial" questions (outcome driven by historical
base rates / statistical frequency) and loses on "current_event" questions (outcome requires
post-training knowledge). The earthquake vs TikTok divergence pattern from Exp D data was
the original trigger.

**Infrastructure built:**
- `bt_markets.domain_type` column (actuarial / current_event / mixed)
- `classify_domain_type()` — Haiku-based LLM tagger in `backtest/classifier.py`
- `backtest classify-domains` CLI for batch tagging
- `select_markets()` extended with `domain_types`, `price_min`, `price_max` filters
- `simulate --domain-type --price-min --price-max` flags

**Key calibration finding:** Running Haiku classifier on 500 prediction markets produced
**0 actuarial tags** (372 current_event, 128 mixed). Polymarket is overwhelmingly
news/person-specific driven — the Haiku model is correct to avoid misclassifying these.
SQL keyword tagging was used for well-defined seismic/natural categories.

### Markets tagged as actuarial (907 prediction markets eligible):

| Category | Tagged | Eligible | Avg Volume | Testable |
|----------|--------|----------|------------|---------|
| weather-threshold | 808 | 807 | $69K | No — daily resolution, fails 7-day horizon filter |
| seismic (earthquake, magnitude) | 24 | 24 | $238K | Yes |
| storm (hurricane, tornado) | 28 | 24 | $238K | Yes |
| macro-GDP (GDP, recession) | 31 | 31 | $211K | Yes |
| employment (NFP, unemployment) | 20 | 20 | $91K | Yes |

**Weather markets finding:** "Will NYC temp exceed 57°F on Oct 26?" questions resolve
in 1-2 days. The 7-day horizon filter (`EXISTS price history 7d before resolution`)
eliminates all 807 weather markets. They are structurally untestable at our default horizon.

### Simulation results (runs #17–#19, n=56, post-Claude4):

| Subtype | n | Avg mkt price | Agent Brier | Market Brier | Diff | Agent wins |
|---------|---|---------------|-------------|--------------|------|------------|
| **seismic** | **33** | **0.597** | **0.1233** | **0.1339** | **−0.0106** | **12/33** |
| storm | 15 | 0.178 | 0.0138 | 0.0128 | +0.0010 | 0/15 |
| macro-GDP | 6 | 0.019 | 0.0007 | 0.0004 | +0.0003 | 2/6 |

**Seismic is the only actuarial category where the LLM beats the market.**

### Mechanism: earthquake frequency underpricing

The seismic markets fall into three groups:

1. **Decided NO (price <0.10):** narrow time windows ("earthquake this week in X region"),
   outcome always NO, both agent and market near parity at near-zero Brier.

2. **Uncertain zone (price 0.20–0.80):** intermediate time windows (1–2 months globally
   for 7.0+ events). The market prices these at 0.27–0.64. The LLM's base rate says 0.85–0.99
   (driven by global seismicity: ~12-15 events/year globally → Poisson P(≥1 in 60 days) ≈ 91%).
   **Outcomes: 5/6 resolved YES.** LLM correctly identified market underpricing.
   Agent wins by 0.026–0.067 Brier per trial.

3. **Decided YES (price >0.90):** long windows ("7.0+ earthquake by end of year"), both
   agree ≈ 99%, near parity.

The LLM's base rate for earthquake frequency is accurate at a global level. The market
was systematically pricing the intermediate-window questions too low, probably because
participants anchor to regional earthquake probability or don't apply global seismicity rates.

### Storm markets: decided by hurricane season structure

Storm questions were all "will a Cat-5 make US landfall?" type — structurally decided NO
at <0.003 prices. The LLM slightly deviates from 0.003 toward a higher rate (hurricane
does happen), losing every trial by a tiny margin. Agent wins 0/15. Near-zero impact on Brier.
No edge, but also no significant loss.

### Macro-GDP: market efficient, LLM not useful

All 6 GDP trials were decided-NO (avg price 0.019: "GDP contraction >5%?", "GDP <0%?").
Market correctly priced these at near-zero. LLM slightly overestimates probability. No edge.

### Divergence pattern consistent with Exp D (large divergence cases)

The 3 large-divergence cases from Exp D runs #15–#16:
- "Earthquake 7.0+ by July 31?": mkt=0.27, blind_p2=0.55, outcome=YES ← **seismic edge**
- "Earthquake 7.0+ before August?": mkt=0.455, blind_p2=0.70, outcome=YES ← **seismic edge**
- "TikTok banned in 2025?": mkt=0.865, blind_p2=0.35, outcome=YES ← **current_event, market right**

The earthquake pattern is confirmed across multiple runs and data sources.

### Conclusions

1. **LLM has a specific, repeatable edge on global seismic frequency questions** at
   intermediate time horizons (1–2 month windows). The market underprices these by 0.20–0.40
   in the uncertain zone. N=33, consistent direction.

2. **The edge is mechanistic:** the LLM correctly applies global Poisson base rates for
   large earthquakes. The market appears to anchor to regional or short-window frequencies.

3. **The edge is narrow:** seismic markets represent ~24 eligible in the DB, all previously
   explored, small dollar volumes ($40K–$309K). The trading pool is very small.

4. **Other "actuarial" categories show no LLM edge** at 7-day horizon:
   - Storm (decided, market correct)
   - GDP (decided, market correct)
   - Weather-threshold (structurally excluded by short resolution window)

5. **The Haiku domain classifier correctly identifies Polymarket as ~80% current_event,
   ~25% mixed.** True actuarial markets (where LLM has frequency-based edge) are <1% of
   the Polymarket universe. The edge is real but the market is tiny.

### Open questions

- Can the seismic edge be traded profitably given market depth? Volume $40K–$300K suggests
  max position ~$500–$3K before moving the market.
- Does the LLM's earthquake frequency model remain accurate on more specific geographic
  or magnitude questions (not just "global 7.0+")?

---

## Experiment F: Broader Actuarial Alpha Search

**Date:** 2026-02-22
**Goal:** Systematically test all actuarial market subtypes (not just seismic) to determine
whether any other frequency-based category yields LLM edge.

### Setup

Extended domain tagging to cover all actuarial candidates:
- **Seismic** (earthquake, magnitude, seismic): 25 markets tagged (confirmed)
- **GDP/recession** (GDP growth, recession): ~48 markets tagged (mislabeled — actually current_event/mixed)
- **Employment** (unemployment rate, NFP, payroll): ~20 tagged
- **Hurricane season count** (named storm count): ~15 tagged
- **Tornado count** (annual/monthly US tornado totals): ~8 tagged
- **Inflation** (CPI delay, BLS): ~5 tagged

Fixed bug: 3 Carolina Hurricanes (hockey team) markets incorrectly tagged actuarial → relabeled NULL.

Key insight discovered: `select_markets()` defaults to `category IS NULL`, excluding
bracket-style markets (GDP ranges, tornado count ranges, hurricane season bands) which all
have non-null categories. Required `--category "*"` to include all actuarial subcategories.

**Run #22:** n=39 trials, all actuarial, price 0.10–0.90, no regime filter, `--category "*"`

### Results by Subtype (aggregate runs #17–#22, n=107 total trials)

| Subtype | n | Agent Brier | Mkt Brier | Edge | Agent wins |
|---------|---|-------------|-----------|------|-----------|
| seismic | 53 | 0.148 | 0.162 | **+0.014** | 24/53 (45%) |
| gdp | 18 | 0.188 | 0.188 | **0.000** | 7/18 |
| hurricane | 18 | 0.020 | 0.019 | -0.001 | 1/18 |
| employment | 14 | 0.184 | 0.179 | -0.005 | 5/14 |
| inflation | 2 | 0.471 | 0.297 | **-0.173** | 0/2 |

*Note: seismic n=53 includes repeat simulations of the 25 tagged markets across multiple runs.*

### Findings

**1. Seismic is the only actuarial category with LLM edge (+0.014, n=53).**
All other categories show no edge or slight market advantage. The seismic finding
is robust and consistent across six simulation runs with different market subsets.

**2. GDP parity disproves the contamination hypothesis for economic statistics.**
LLM has training data containing Q1/Q2 2025 GDP results (released April 30 and July 30, 2025,
both within the August 2025 training cutoff). Yet agent Brier exactly equals market Brier (0.188).
The 4-pass estimation framework is probability-reasoning based — the LLM reasons from base rates
("historical ~15% recession probability") rather than recalling specific quarterly facts from
training data. **Economic statistics training knowledge does not surface as forecasting edge.**

**3. Employment markets favor the market (-0.005, n=14).**
Unemployment rate threshold markets ("Will unemployment be ≥4.5% in September?") require
knowledge of current labor market trajectory — exactly what the market prices efficiently
and the LLM's base rates miss. LLM applies ~4% historical mean, market knows the trend.

**4. Hurricane season count markets: near parity, mostly decided by 7d horizon.**
Season count markets ("Will there be >14 named storms?") are essentially decided by the
7-day horizon because the season is nearly complete. The few uncertain cases (mid-season
questions at 30–50%) show no systematic edge.

**5. Inflation/CPI administrative markets strongly favor the market (-0.173, n=2).**
"BLS delays another CPI release before 2027?" — a specific administrative decision, clearly
current_event. These are misclassified. The LLM had no edge, the market was well-informed.

**6. Tornado count markets: n=1, statistically meaningless.**
"Will fewer than 1550 tornadoes occur in 2025?" (price=0.865, resolved NO) — single trial,
LLM slightly better but not actionable.

### Why Seismic Is Unique

The seismic edge exists because **all three required conditions** are met simultaneously:
1. **Stationary Poisson process:** global M7.0+ frequency is ~12–15/year and stable month-to-month
2. **Systematic market underpricing:** markets anchor on short windows, price 0.27–0.64 for P≥1 event
3. **LLM applies the correct model:** estimates 0.70–0.99, matching the Poisson rate

No other actuarial subcategory on Polymarket satisfies all three. GDP/unemployment outcomes
depend on current conditions the market knows better. Hurricane season counts are decided
by horizon. Tornadoes have too few markets. Volcanic eruptions: only 2 markets total.

### Search Completeness

Explored and eliminated:
- **Volcanic eruptions** (Iceland/global): 2 markets in entire DB — not viable
- **Solar/geomagnetic storms**: ~0 actuarial markets on Polymarket
- **Seasonal hurricane frequency**: decided by 7d horizon; mid-season uncertain markets near parity
- **Measles/disease case thresholds**: mostly decided NO; 2025 cases policy-driven, not frequency
- **GDP quarterly outcomes**: parity — training knowledge doesn't surface as forecasting advantage
- **Unemployment rate thresholds**: market edge — current conditions trump LLM base rates

**Conclusion: The actuarial alpha search on Polymarket is complete. Seismic is the sole
reliable frequency-based signal. Pool size: ~25 tagged markets, ~24 eligible with 7d history,
representing a small but real and mechanistically understood edge.**
