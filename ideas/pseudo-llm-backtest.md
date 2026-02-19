# Pseudo-LLM Backtesting

**Status:** Pinned for future exploration

## Concept

For resolved markets, run the LLM estimation pipeline using only the market
question, description, and category (no web search). Compare the LLM's
"training data knowledge" estimate against the market price at various points
before resolution.

## Why It's Interesting

- Tests whether the LLM's base reasoning adds value beyond market consensus
- Tests whether the adversarial pass helps or hurts calibration
- Tests whether the 3-pass pipeline produces well-calibrated outputs
- Cost: ~$0.10-0.20 per market. 500 markets = $50-100 for a meaningful sample.

## Key Concern: Contamination

LLM training data likely includes Polymarket outcomes (especially high-profile
markets). This biases pseudo-backtests toward artificially good results.

**Mitigation:** Focus on markets that resolved AFTER the LLM's training cutoff.
For Claude, that's May 2025. Any market resolving after that date is clean.

## Relationship to Self-Aware Agent

If LLMs genuinely have alpha from training data, that alpha is shared by every
agent using similar models. The pseudo-backtest would measure the *ceiling* of
LLM-derived alpha before competition erodes it. See: `regime-awareness.md`.

## Open Questions

- How to construct the information context without web search? Use only market
  metadata + price history?
- Should we strip temporal hints from market descriptions to reduce leakage?
- Could we use older models (GPT-3.5 era) as a control group?
- What's the minimum sample size for statistical significance?
