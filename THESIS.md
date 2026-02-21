# Strategy Thesis

**Last updated:** 2026-02-21
**Status:** Living document — update as evidence accumulates

---

## Core Question

> Does this agent have a durable information advantage over prediction market prices,
> and if so, where and for how long?

---

## Foundational Beliefs

### 1. LLM alpha is not private

Every agent using similar models shares the same alpha. As model capability increases
and costs decrease, LLM-derived alpha gets arbitraged away — the market becomes more
efficient precisely because of agents like this one.

**Implication:** "Use a better model" is not a strategy. The edge is in *where* you
deploy it, not *which* one you use.

### 2. Markets price LLM consensus quickly

Our simulation data (n=104 across 6 runs) shows the agent agrees with the market price
within 5% on **96% of trials**. Only 4 of 104 trials showed >5% divergence — and in
all 4 cases the agent estimated *lower* than the market (the "probable NO" pattern).
On high-volume (>$1M) markets in the post-Claude4 era, agent Brier ≈ market Brier.
The crowd has already absorbed what the LLM knows.

**Direction bias:** The agent systematically estimates slightly below market prices
(avg agent: 0.398 vs avg market: 0.404), while actual outcomes resolve at 0.442.
Both undershoot the true outcome rate, but market is marginally better calibrated.

**Implication:** Estimating the right probability on an efficient market generates no
edge. The question is not "what is the probability?" but "do I know something the
market doesn't?"

### 3. Category and volume tier dominate everything else

The backtest DB is dominated by sports markets (Match Winner, Spread, O/U). These are
the worst possible targets: sportsbooks have 50 years of data, full-time quants, and
real-time feeds. An LLM brings nothing to that fight.

**Implication:** Market selection is the highest-leverage decision in the system. A
mediocre estimate on the right market beats a perfect estimate on the wrong one.

**Critical gap:** All 104 simulation trials to date were drawn from an *unfiltered*
market pool — which in the post-June 2025 period is dominated by sports markets.
We have zero Brier data on the actual target zone ($10K–$500K, non-sports).
The entire thesis rests on a claim we haven't tested yet.

---

## The Alpha Map

```
                    LLM KNOWLEDGE DEPTH
                    HIGH              LOW
                 ┌─────────────────┬──────────────┐
          LOW    │  ★ TARGET ZONE  │   Avoid      │
  MARKET         │                 │              │
  COMPETITION    │  Niche politics │  Hyperlocal  │
  (thin/         │  Macro events   │  Sports props│
   illiquid)     │  Science/tech   │  Local weather│
                 ├─────────────────┼──────────────┤
          HIGH   │  Neutral/       │  ✗ WORST     │
  MARKET         │  declining      │              │
  COMPETITION    │                 │  Sports spreads│
  (thick/        │  Major elections│  O/U lines   │
   liquid)       │  Crypto price   │  Match winners│
                 └─────────────────┴──────────────┘
```

**Target zone characteristics:**
- Volume: $10K–$500K (thin enough that LLM analysis isn't priced in)
- Category: Politics (niche races), economics (indicators), science/tech milestones,
  crypto governance, international events
- Time horizon: < 60 days (information decay is manageable)
- Question type: Requires synthesis of text-heavy information, not quantitative data

**Avoid:**
- Sports spreads, O/U, match winners — efficient, quantitative, non-LLM-tractable
- Markets > $1M volume in LLM-tractable categories — already efficiently priced
- Markets where resolution criteria are ambiguous (resolution risk, not alpha)

---

## The Regime Hypothesis

Market efficiency correlates with model generation. As LLMs proliferate:

```
Pre-GPT4 era  → Human-priced markets → LLM has structural advantage
GPT4 era      → LLMs entering market → Alpha window opens
Claude3/GPT4o → More agents, more pricing → Alpha narrows
o1/Claude4    → Agents commoditized  → Alpha near zero on thick markets
Post-Claude4+ → Next wave: proprietary data, real-time feeds → Alpha migrates
```

**What this means now (Feb 2026):** We are in the post-Claude4 era. The window of
pure LLM alpha on mainstream markets is closing. The remaining alpha is in:
- Markets that LLM agents haven't found yet (niche, low-volume)
- Markets where LLM consensus is systematically wrong (requires knowing when to
  *not* trust the model)
- Markets where non-LLM signals provide the edge (real-time data, domain expertise)

---

## The Self-Awareness Requirement

The agent must estimate not just the probability of resolution, but its own
**information advantage** relative to the market.

Three questions the agent should answer before trading:

1. **"Is this a market that other LLM agents are likely analyzing?"**
   If yes, the market price probably already reflects LLM-quality reasoning.

2. **"Does my estimate diverge meaningfully from the market price?"**
   If no (< 5% difference), the adversarial pass has correctly identified no edge.
   If yes, ask: *why do I disagree?* If the reason is traceable to specific
   information the market may not have priced, that's a signal. If it's just
   model noise, pass.

3. **"Is this market getting more or less efficient over time?"**
   Rising efficiency = rising agent competition. Exit before alpha fully
   disappears.

---

## The Adversarial Pass Problem

The current 4-pass pipeline (base rate → Bayesian update → adversarial →
calibration) may be systematically suppressing genuine divergence. The adversarial
pass asks "what would a sophisticated trader think?" — which may collapse the
estimate toward market consensus, defeating the purpose of having an independent view.

**Open question:** Is the adversarial pass reducing noise (good) or eliminating
real signal (bad)? Worth testing by comparing pre- vs post-adversarial Brier
scores on divergent markets.

**Observed behavior:** In all 4 high-divergence trials, the agent ended up below
the market price. The adversarial pass asks "what would a sophisticated trader
think?" — if that consistently collapses estimates toward a consensus that is
itself LLM-derived, the pass is circular. A 15–20% divergence compressed to 5%
is not noise reduction; it is signal destruction. The `reasoning` field in
`bt_simulation_trials` contains intermediate estimates and can be used to measure
this compression directly.

---

## The Contamination Caveat

LLM training data likely includes Polymarket outcomes for pre-cutoff markets.
Backtests on markets resolving before April 2025 (Claude's cutoff) may show
artificially good results due to the model "remembering" the outcome.

**Protocol:**
- Backtest validation: use only markets resolving after model training cutoff
- Simulation runs: our post-Claude4 regime (June 2025+) is clean
- Any impressive pre-cutoff results should be treated as suspect

---

## Strategic Roadmap

### Near-term (now) — Evidence first

**#1 priority: Run the target-zone simulation.** This is the test the thesis depends on.
```
uv run polymarket backtest simulate \
  --min-volume 10000 --max-volume 500000 \
  --regime post-claude4 -n 50
```
Use null/unset category to catch misc prediction markets; exclude sports explicitly
in market selection. Compare agent vs market Brier on this slice. If agent Brier <
market Brier here, the thesis holds. If not, reconsider the fundamental premise before
adding more infrastructure.

**#2: Investigate the adversarial pass.** Read the `reasoning` field from existing
trials to see if it contains pre/post adversarial estimates. Measure compression.
Specifically: on the 4 divergent trials, how large was the pre-adversarial divergence?

**#3: Diagnose the negative PnL mechanics.** Run #4 showed -$91.59 on n=50 with
near-neutral Brier (+0.0009 agent worse). This is the expected outcome when Kelly
sizing bets on a slightly-worse model — the math is correct, not broken. But it
confirms: even tiny Brier disadvantage compounds negatively. Requires positive Brier
edge *before* trading, not neutral.

### Medium-term
- Build category filter: exclude sports spread/O/U markets from live target universe
- Implement market efficiency index: track agent-market agreement rate over time
  as a proxy for competition density
- Test adversarial pass ablation: does removing it improve Brier on divergent cases?
- Formally test the 4 seed hypotheses once target-zone data exists

### Long-term
- Identify non-LLM information edges: real-time data, domain APIs, proprietary feeds
- Monitor for regime shifts: track Brier score degradation as a competition signal
- The endgame is not "better LLM" — it's "unique signal the LLM can reason about"

---

## Open Questions

1. Does the $10K–$500K volume tier show meaningful agent alpha on non-sports markets? (**untested — #1 priority**)
2. Is the adversarial pass net-positive or net-negative for edge preservation? (**suspected net-negative — measurable from existing trial data**)
3. What is the pre-adversarial divergence on the 4 known high-divergence trials? Does the pass suppress 10–20% down to 5%?
4. Can we measure market efficiency change over time using our 90K-market DB?
5. What non-LLM data sources are realistically accessible and legally usable?
6. Is there a "question complexity" signal that predicts when LLMs outperform markets?
7. Does the direction bias (agent estimates lower than market) persist on target-zone markets, or is it an artifact of the sports-heavy pool?

---

## Evidence Log

| Date | Finding | Implication |
|------|---------|-------------|
| 2026-02-20 | n=79 trials: 95% agent-market agreement within 5% | Agent echoing market on >$1M markets |
| 2026-02-20 | post-Claude4 regime: agent Brier +0.0016 vs market (slightly worse) | No edge on thick modern markets |
| 2026-02-20 | o1-era: agent Brier -0.0048 vs market (slightly better) | Edge may have existed in 2024 |
| 2026-02-20 | Backtest DB dominated by sports categories | Systematic category bias in evaluation |
| 2026-02-20 | Run #4 (n=50, Sonnet): simulated PnL = -$91.59 | Negative PnL despite neutral Brier |
| 2026-02-21 | n=104 total: 4/104 trials diverged >5%; all 4 agent estimates were LOWER than market | Agent has "probable NO" bias; rarely finds upside bets |
| 2026-02-21 | Solana ETF trial: agent 82%, market 99.95%, resolved NO — agent massively correct | Largest divergence was the clearest call; adversarial pass may not have killed it fully |
| 2026-02-21 | Avg agent: 0.398 vs avg market: 0.404 vs avg outcome: 0.442 | Both agent and market undershoot actual resolution rate; market is marginally better calibrated |
| 2026-02-21 | Run #6 (n=25, Sonnet, most recent): agent Brier 0.1174 vs market 0.1159 (+0.0015 worse) | No improvement trend; most recent run still agent-worse |
| 2026-02-21 | $10K–$500K null-category pool (post-April 2025): 34,890 markets available | Target zone exists and is large enough to test; never been simulated |
| 2026-02-21 | Negative PnL mechanics: even +0.0009 Brier disadvantage produces -$91 on n=50 × $50 positions | Kelly sizing requires positive Brier edge before any live trading; neutral is not enough |
