# LLM-Market Correlation: An Open Question

**Status:** Pinned — important open question with deep implications for strategy

## Observation

Simulation results show that LLM probability estimates closely track market prices even
on post-training-cutoff markets (Run #8: Brier scores ~0.06 for both agent and market,
near-identical). The correlation is surprisingly tight. This raises a fundamental
question: **why does the LLM agree with the market so consistently, and what does that
imply about whether any independent signal exists?**

## The Four Competing Explanations

### 1. Shared Information Substrate (Benign)
Both LLM and market participants draw on the same public information. Markets aggregate
public knowledge efficiently; LLMs are trained on that same corpus. Convergence is
expected — the LLM and the market are solving the same problem from the same inputs.

*Implication:* No anchoring problem, but also no edge. The LLM is not adding information
beyond what markets already know. Edge can only come from proprietary or real-time data.

### 2. Price Anchoring in Prompts (Methodological concern)
If the estimator pipeline receives the current market price as part of its context, the
LLM may be anchoring on that price even when nominally doing independent estimation. This
would create artificial correlation and understate the LLM's independent signal.

*Implication:* Our measurements of "agent Brier score" may be biased. The true
independent signal could be higher (or lower) than observed. **This must be tested.**
See: `src/polymarket_agent/analyst/estimator.py`.

### 3. Selection Bias from Decisive Markets (Methodological concern)
Run #8 filtered for clean prediction markets in the $10K-$500K range. These tend to
resolve near 0 or 1 rather than at intermediate probabilities. Both market and LLM
naturally score well on decisive outcomes — the test isn't discriminating where it
matters (the 0.3-0.7 range where genuine uncertainty lives).

*Implication:* The low Brier scores may say more about market selection than about model
quality. We need to evaluate on the full probability spectrum.

### 4. Fuzzy Training Cutoff (Partial explanation)
"Post-Claude4" doesn't mean zero relevant training. The LLM carries forward base rates,
historical patterns, and domain priors that transfer to new markets. It doesn't need to
have seen the specific event to reason well about it.

*Implication:* Partially explains convergence on stable-domain questions (politics,
economics), but shouldn't explain convergence on fast-moving or niche markets.

## Why This Matters

If explanations #1 or #4 dominate, the LLM adds real signal but markets are already
incorporating it. Strategy implication: find markets where that shared signal hasn't
reached the market yet (niche, low-volume, short-duration).

If explanation #2 dominates, our evaluation methodology is broken. We're measuring
anchoring, not estimation quality. Fix: run the pipeline with and without market price
in context, compare divergence. **Done (runs #9/#10): blind mode is 3.5× worse on
Brier. The anchoring is real but the market price is also genuinely informative.
Methodology is not broken — it's incorporating signal, not just noise.**

If explanation #3 dominates, we're looking in the wrong place. Fix: evaluate on
ambiguous-outcome markets (final price 0.2-0.8), not clean binary resolvers.

## The Asymmetry Signal

Across all runs, the model shows the most divergence from markets on "probable NO"
outcomes in unfiltered data. This is the pattern most worth understanding — it suggests
the LLM may be systematically more bearish than markets on uncertain propositions, which
could be a real signal or a calibration artifact.

## Code-Level Finding: Market Price Flows Through 3 of 4 Passes

Inspected `src/polymarket_agent/analyst/estimator.py` and all prompt templates.

| Pass | Market price visible? | How framed |
|------|----------------------|------------|
| Screening (Haiku) | Yes | "Current YES price: X (implies Y%)" — asks if price "seems reasonable" |
| Pass 1 — Base rate | **No** | Question, category, end date only. Fully independent. |
| Pass 2 — Bayesian update | Yes | Listed as `**Current market price (YES)**` alongside dossier evidence |
| Pass 2.5 — Adversarial | Yes, explicitly | "Your estimate is X, market says Y — argue why market might be right, revise toward it if compelling" |
| Pass 3 — Calibration | No | Just the current estimate + calibration history |

**Pass 2 is the main anchoring mechanism — not the adversarial pass.** The moment
market price appears in the Pass 2 prompt alongside the dossier, the LLM anchors to
it. The adversarial pass then narrows the gap further, but the heavy lifting is done
in Pass 2.

**Pass 1 (base rate) is the only fully independent signal.** It receives only the
question, category, and end date — no market price.

## Empirical Findings (Runs #9 and #10, n=10 paired, prediction markets $10K-$500K)

### Pass-level decomposition (Run #9, anchored)

| Stage | Avg Brier | Avg |estimate − market| |
|-------|-----------|----------------------------|
| Pass 1 — base rate (no market price) | **0.2505** | **0.307** |
| Pass 2 — after evidence + market price | 0.0355 | 0.034 |
| Final — after adversarial pass | 0.0261 | 0.017 |
| Market price | **0.0155** | — |

Pass 1 is nearly useless standalone — Brier 0.25, barely better than guessing 0.5 on
everything (naive Brier = 0.25). The moment Pass 2 introduces the market price,
divergence collapses 9× (0.307 → 0.034). The adversarial pass halves it again to 0.017.

### Anchored vs. blind paired comparison (Runs #9 vs #10, same 10 markets)

| Mode | Avg Brier | Avg |estimate − market| |
|------|-----------|----------------------------|
| Anchored (market price in Pass 2 + adversarial) | 0.0261 | 0.017 |
| **Blind (market price withheld entirely)** | **0.0905** | **0.109** |
| Market price | 0.0155 | — |

Removing market price causes **3.5× Brier degradation**. Worst failures in blind mode
were on high-confidence markets where LLM had no independent conviction:

| Market | Outcome | Market price | Anchored | Blind | Blind Brier |
|--------|---------|-------------|---------|-------|-------------|
| 515500 | YES | 0.639 | 0.52 | 0.15 | 0.7225 |
| 573699 | YES | 0.991 | 0.98 | 0.72 | 0.0784 |
| 507484 | YES | 0.895 | 0.88 | 0.72 | 0.0784 |

### Refined interpretation

**The pipeline anchors on market price — and the market price is genuinely informative.**
These are not in conflict. The market price is providing real signal the LLM cannot
replicate from question text and price history alone, particularly on high-consensus
markets (>80% or <20%). The correlation is partly structural (pipeline design) and
partly real (market knows things the LLM doesn't).

The hypothesis #5 framing ("anchoring, not independent reasoning") was partially right
and partially misleading. The blind run proves the convergence mechanism is architectural,
but the blind run also shows removing that mechanism makes the agent genuinely worse —
not just differently calibrated. **The market price anchor is load-bearing.**

**Revised question:** Not "is anchoring bad?" but "when does the LLM have information
the market hasn't yet priced?" That's where real edge lives: markets where current price
lags the LLM's evidence, not markets where both are processing the same public signals.

Evidence in hypothesis tracker: run #9 (brier_diff +0.0106) and run #10 (brier_diff
+0.0750), both supports_hypothesis=1, confidence 0.28 (inconclusive, needs n≥30).

## Open Questions

- ~~How much does Pass 1 diverge from market?~~ **Answered: 0.307 avg, Brier 0.2505.**
- ~~Is blind mode better?~~ **Answered: No. 3.5× worse. Market price is informative.**
- ~~When does the LLM have information not yet in the market price?~~ **See `when-llm-leads.md`
  for full strategic breakdown and proposed experiments.**
- Is the LLM-market correlation stronger or weaker on low-volume markets?
  (Low-volume = less price discovery = more room for LLM divergence to be correct)
  → **Experiment B** in `when-llm-leads.md`
- What happens to anchored vs. blind comparison on markets resolving 0.2-0.8?
  (Ambiguous markets — where the market's signal is weaker — may be where blind does better)
- Can we identify in advance which markets are "high-consensus" (LLM should defer to
  market) vs. "uncertain" (LLM may have an edge)?
  → **The `base_rate_estimate` divergence score** is the proposed operationalization.
  See `when-llm-leads.md`.

## Relationship to Existing Thesis

Connects directly to `regime-awareness.md`: if markets already price in LLM-quality
reasoning, then correlation is evidence of market efficiency, not LLM quality. The
self-aware agent should treat high correlation as a "no edge here" signal rather than
as validation.

Also connects to `pseudo-llm-backtest.md`: any pseudo-backtest must carefully control
for price anchoring, or results will be spuriously good.
