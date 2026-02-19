# Regime Awareness: The Self-Aware Agent

**Status:** Pinned for future exploration — deep implications for system design

## Core Insight

If LLMs have alpha in prediction markets, that alpha is not private. Every
agent using similar models shares it. As model capability increases and costs
decrease, this alpha gets arbitraged away — the market becomes more efficient
precisely because of agents like us.

This means the **competitive landscape is a function of model generation.**
The market we're entering today is fundamentally different from the market of
6 months ago, and will be different again in 6 months.

## Observable Implications

### 1. Efficiency Should Correlate with Model Releases

If LLM alpha is real, we should observe:
- Market spreads narrowing after major model releases (GPT-4, Claude 3, etc.)
- Faster price convergence to resolution outcomes over time
- Volume patterns shifting (more algorithmic flow)
- Category-specific efficiency gains (categories LLMs are better at should
  become efficient faster)

**This is testable with historical data.** We can look for structural breaks in
market efficiency metrics around known model release dates.

### 2. The Diminishing Alpha Hypothesis

If N agents are running similar LLM estimation pipelines:
- Markets where LLMs agree with each other will be efficiently priced
- Alpha exists only where LLMs *disagree* or where LLMs systematically fail
- The highest-alpha markets are those where LLM consensus is wrong — which
  requires a non-LLM information edge

This suggests our long-term strategy should be:
- **Short-term:** LLM estimation on under-analyzed markets (niche, low-volume)
- **Medium-term:** Identify where LLM consensus breaks down
- **Long-term:** Proprietary data sources that LLMs don't have access to

### 3. Self-Awareness as a Feature

Our agent should not just estimate probabilities — it should estimate its own
information advantage relative to the market.

Questions the agent should be asking:
- "Is this a market that other LLM agents are likely analyzing?"
- "Is the current market price consistent with what an LLM would estimate?"
  (If yes, we probably have no edge. If no, why not?)
- "Has this market's efficiency changed recently?" (Possible new agent
  entering)
- "Am I the marginal price-setter here, or am I trading against someone with
  better information?"

### 4. Behavioral Implications

**Don't be the last LLM to the party.** If a market price already reflects
LLM-quality reasoning, our estimate will converge to the market price and the
adversarial pass will correctly tell us we have no edge.

**Seek markets where LLMs are structurally disadvantaged:**
- Real-time events (LLMs have stale training data)
- Local/niche knowledge (outside training distribution)
- Markets requiring proprietary data (weather sensors, satellite imagery)
- Markets where the question is ambiguous (LLMs may misparse resolution criteria)

**Monitor for regime shifts:**
- Track our own Brier score over time. Declining performance may indicate
  increasing competition from other agents.
- Track market efficiency metrics (spread, time-to-convergence) as a proxy
  for agent density.
- If efficiency improves faster in categories LLMs excel at (politics, crypto)
  vs categories they don't (hyperlocal, technical), that's evidence of LLM
  impact.

## Concrete Signals to Build

1. **Market efficiency index** per category over time (spread, volume, Brier
   of market price itself)
2. **Agent-competition proxy**: How often does our estimate agree with market
   price within 5%? Rising agreement = rising competition.
3. **Alpha decay tracking**: Our edge per category over rolling windows.
   Decaying edge = category becoming efficient.
4. **Structural break detection**: Changepoint analysis on efficiency metrics
   around model release dates.

## Philosophical Note

This framing rejects the "smarter model = more alpha" assumption. Instead:
smarter models = more efficient markets = alpha migrates elsewhere. Our job is
not to be the best estimator — it's to be the best at **finding markets where
estimation quality matters and competition is thin.**

The self-aware agent doesn't ask "what is the right probability?" It asks
"do I know something the market doesn't, and can I be confident that I do?"
